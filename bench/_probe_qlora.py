"""QLoRA 可行性探测：在这台 6 GB 的 RTX 2060 上到底能不能训 Qwen3.5-4B。

## 为什么需要它

调研给出的估算区间是 4–5 GB（4-bit 权重 2.3GB + LoRA 参数与优化器数百 MB
+ 梯度检查点后的激活 1–1.5GB），而硬件只有 6 GB —— **理论可行但没有任何余量**。
而且 Qwen3.5 是 Gated DeltaNet + Gated Attention 的混合架构，
PEFT 能否正确识别全部线性层也需要实测（不是看文档就能确定的）。

所以先做**最小验证**：能加载、能包装、能跑一个 batch 的前向+反向、峰值显存多少。
这一步通过 = 后训练路线可行；不通过 = 直接放弃，不浪费时间下载 8.5 GB 权重。

## 用法

    # 先用小模型验证流程（权重仅 ~1.6 GB，快）
    python bench/_probe_qlora.py --model Qwen/Qwen3.5-0.8B

    # 流程通了再上真正的目标模型
    python bench/_probe_qlora.py --model Qwen/Qwen3.5-4B-Instruct

⚠️ 跑之前先停掉后端服务 —— 6 GB 显存装不下 llama.cpp 和训练框架两份模型。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, "backend")
os.environ.setdefault("TMP", "D:/llama_build/tmp")
os.environ.setdefault("TEMP", "D:/llama_build/tmp")
# 权重一律下到 D 盘（C 盘红线）
os.environ.setdefault("HF_HOME", "D:/llama_build/hf")
os.environ.setdefault("MODELSCOPE_CACHE", "D:/llama_build/ms")


def human(n: int) -> str:
    return f"{n / 1024 ** 3:.2f} GB"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B",
                    help="HF/ModelScope 模型 id（先用小模型验证流程）")
    ap.add_argument("--seq", type=int, default=512, help="训练序列长度上限")
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--max-steps", type=int, default=1, help="只跑几步，验证能训即可")
    args = ap.parse_args()

    import torch  # noqa: PLC0415

    print("=" * 66)
    print(f"torch      : {torch.__version__}")
    print(f"CUDA 可用   : {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("❌ CUDA 不可用 —— 先确认装的是 CUDA 版 torch，而不是 +cpu 版")
        return
    cap = torch.cuda.get_device_capability()
    print(f"GPU        : {torch.cuda.get_device_name(0)}  (sm_{cap[0]}{cap[1]})")
    print(f"显存       : {human(torch.cuda.get_device_properties(0).total_memory)}")
    print("=" * 66)

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    t0 = time.perf_counter()
    print(f"\n[1/5] 加载 tokenizer / 模型（4-bit）：{args.model}")
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb,
        device_map={"": 0},           # 单卡，全部塞进 0 号设备
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    print(f"      加载完成，用时 {time.perf_counter() - t0:.1f}s，"
          f"显存 {human(torch.cuda.memory_allocated())}")

    print("\n[2/5] 统计可被 LoRA 命中的线性层（混合架构的关键检查）")
    linear_names = set()
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.Linear):
            linear_names.add(name.split(".")[-1])
    print(f"      线性层种类（{len(linear_names)}）：{sorted(linear_names)}")
    gdn = [n for n in linear_names if "in_proj" in n or n == "out_proj"]
    print(f"      Gated DeltaNet 相关：{sorted(gdn) if gdn else '（未检出，可能是小模型结构不同）'}")

    print(f"\n[3/5] 包装 LoRA（target_modules='all-linear', r={args.lora_r}）")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    lcfg = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_r * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        # PEFT 官方推荐的架构无关写法：命中全部线性层，不用手写 GDN 的层名。
        # （Axolotl 文档给的显式列表是 linear_attn.in_proj_qkv / in_proj_z / out_proj，
        #  all-linear 等价于把它们一并覆盖。）
        target_modules="all-linear",
    )
    model = get_peft_model(model, lcfg)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"      可训练 {trainable:,} / 总参数 {total:,}  ({trainable / total:.3%})")
    if trainable == 0:
        print("❌ 没有任何可训练参数 —— LoRA 没命中，检查 target_modules")
        return

    print("\n[4/5] 构造一个 batch 并跑前向 + 反向")
    text = (
        "你是地理分析助手。判断意图。\n用户：统计珠峰坡度在15度以下的比例\n"
        "助手：{\"intent\": \"analysis\", \"understanding\": \"要算坡度分级占比\", \"reply\": \"\"}"
    )
    enc = tok(text, return_tensors="pt", truncation=True, max_length=args.seq).to("cuda")
    enc["labels"] = enc["input_ids"].clone()
    try:
        out = model(**enc)
        loss = out.loss
        loss.backward()
        print(f"      ✅ 前向+反向成功，loss = {loss.item():.4f}")
    except RuntimeError as exc:
        msg = str(exc)
        print(f"      ❌ 失败：{type(exc).__name__}: {msg[:400]}")
        if "out of memory" in msg.lower():
            print("      → 显存不足。降级路径：减 --seq、降到 r=8、或换更小底座")
        return

    print("\n[5/5] 显存与时间")
    peak = torch.cuda.max_memory_allocated()
    reserved = torch.cuda.max_memory_reserved()
    print(f"      训练峰值（allocated）: {human(peak)}")
    print(f"      训练峰值（reserved） : {human(reserved)}")
    print(f"      总参数占用上限 6.00 GB，余量 {6.0 - reserved / 1024 ** 3:.2f} GB")

    # 反向已经跑过，再走一步优化器更新，确认优化器状态也能装下
    try:
        opt = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad], lr=1e-4
        )
        opt.step()
        torch.cuda.synchronize()
        peak2 = torch.cuda.max_memory_allocated()
        print(f"      含优化器状态峰值: {human(peak2)}")
    except RuntimeError as exc:
        print(f"      ⚠ 优化器一步失败：{str(exc)[:200]}")

    print("\n结论：上述数字就是这台机器训 Qwen3.5-4B 的真实上限依据。")
    print("      峰值若明显超过 5.5 GB，完整训练基本不可行，应考虑更小底座或租云。")


if __name__ == "__main__":
    main()
