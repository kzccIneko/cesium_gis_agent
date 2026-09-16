"""意图路由 LoRA 微调：让模型自己判对，从而拆掉正则安全网。

## 背景（为什么要做这件事）

实测数据（bench/_test_grammar.py，24 条）：
    模型自己判意图 91.7%  <  主集得分 98.75%
差额来自 `planner._force_analysis` —— 一条正则安全网在替模型兜底。
用户明确反对这种硬编码（"太笨太死板、泛化能力差"），但删掉它准确率就掉。

三条路只有一条走得通：**微调让模型自己判对**。

## 脚本设计

- **只对 assistant 段算 loss**（prompt 段 mask 成 -100），
  否则模型会学着去生成 system/user 文本，既浪费容量也污染输出。
- **支持 CPU**：CUDA 版 torch 在这个网络环境下要下 2.6 GB（实测 ~90 KB/s），
  先用 CPU 把"数据 → 训练 → 评测"整条流水线跑通，确认方法有效，
  再决定是否为一个零余量的 GPU 训练投入下载时间。
- **训练后立刻在留出集上评测**：产出"训练前 vs 训练后"的准确率对比，
  没有这个对比，训练就是没有证据的动作。

用法：
    # 先跑通流程（CPU + 0.8B）
    python bench/train_intent_lora.py --model Qwen/Qwen3.5-0.8B --device cpu \
        --limit 300 --epochs 1

    # 云端 24 GB 卡（bf16 加载 4B，最稳）
    python bench/train_intent_lora.py --model Qwen/Qwen3.5-4B --device cuda \
        --epochs 2 --save lora_out/intent_4b

    # 8–12 GB 卡（4-bit 加载 + 梯度检查点）
    python bench/train_intent_lora.py --model Qwen/Qwen3.5-4B --device cuda \
        --load-4bit --batch 1 --accum 16 --epochs 2 --save lora_out/intent_4b

    注：ModelScope 上的 id 是 Qwen/Qwen3.5-4B；Qwen/Qwen3.5-4B-Instruct 不存在
    （HuggingFace 的命名不能照搬到 ModelScope）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "backend")
# 这些只在 Windows 本机需要（把临时/缓存目录从余量极小的 C 盘挪到 D 盘）。
# Linux（云端实例）上绝不能设 —— 否则会造出名为 "D:/llama_build/..." 的怪目录，
# 且 MODELSCOPE_CACHE 会被顶掉，模型重复下载 8.8 GB。
if os.name == "nt":
    os.environ.setdefault("TMP", "D:/llama_build/tmp")
    os.environ.setdefault("TEMP", "D:/llama_build/tmp")
    os.environ.setdefault("HF_HOME", "D:/llama_build/hf")
    os.environ.setdefault("MODELSCOPE_CACHE", "D:/llama_build/ms")
    # CPU 训练时把线程数用满（本机 8 核）
    os.environ.setdefault("OMP_NUM_THREADS", "8")

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "sft_data"
OUT_DIR = HERE / "lora_out"


def load_split(name: str, limit: int | None = None):
    rows = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    return rows[:limit] if limit else rows


def intent_of(sample: dict) -> str:
    return json.loads(sample["messages"][2]["content"])["intent"]


def _ids(enc) -> list:
    """把 apply_chat_template 的返回值统一成 list[int]。

    transformers 5.x 起 `tokenize=True` 返回的是 `Encoding` / `BatchEncoding`
    对象而不是裸 list（旧版是 list），直接丢给 torch.tensor 会报
    "Could not infer dtype of tokenizers.Encoding"。这里统一收口。
    """
    if isinstance(enc, list):
        return list(enc)
    if hasattr(enc, "input_ids"):
        v = enc.input_ids
        return list(v[0]) if v and isinstance(v[0], (list, tuple)) else list(v)
    if isinstance(enc, dict):
        v = enc["input_ids"]
        return list(v[0]) if v and isinstance(v[0], (list, tuple)) else list(v)
    return list(enc)


def build_batch(tok, sample: dict, max_len: int):
    """把一条样本编码成 (input_ids, labels)，只对 assistant 段算 loss。

    prompt 段的 label 置 -100 是刻意的：我们只想教会模型"输出什么"，
    不想让它把容量花在复现 system/user 的措辞上。
    """
    msgs = sample["messages"]
    # enable_thinking=False 是这次的关键修复。Qwen3.5 的 chat template 在思考开启时
    # 会注入 "<think>\n"，模型随即开始长篇推理（"首先，我需要判断……"），而我们只要 JSON。
    # 训练数据渲染出的是 "<think>\n\n</think>\n\n{JSON}"（空思考），所以评测侧必须用
    # **同一个开关**，否则模板前缀不一致，模型会走进推理分支。
    prompt_ids = _ids(
        tok.apply_chat_template(msgs[:2], tokenize=True, add_generation_prompt=True,
                                enable_thinking=False)
    )
    full_ids = _ids(
        tok.apply_chat_template(msgs, tokenize=True, enable_thinking=False)
    )
    if len(full_ids) > max_len:
        full_ids = full_ids[:max_len]
    labels = [-100] * min(len(prompt_ids), len(full_ids))
    labels += full_ids[len(labels):]
    return full_ids, labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B")
    ap.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="只用前 N 条训练样本（0=全部）")
    ap.add_argument("--eval-limit", type=int, default=60)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=320)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--load-4bit", action="store_true",
                    help="以 4-bit（NF4）加载底座。显存约为 bf16 的 1/4，"
                         "8–12 GB 显卡跑 4B 时用这个；24 GB 卡可直接用 bf16")
    ap.add_argument("--save", default="")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    dev = "cuda" if (args.device == "cuda" and torch.cuda.is_available()) else "cpu"
    print(f"设备: {dev}   模型: {args.model}   4bit: {args.load_4bit}")
    if args.device == "cuda" and dev == "cpu":
        print("  ⚠ 指定了 cuda 但不可用（装的是 +cpu 版 torch？），已回退 CPU")

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    load_kw = {"trust_remote_code": True, "low_cpu_mem_usage": True}
    quantized = bool(args.load_4bit and dev == "cuda")
    if quantized:
        # 4-bit 分支：权重按 NF4 存、按 bf16 算。双重量化再省约 0.4 bit/参数。
        # 注意 quantized 模型必须用 device_map 指定设备，之后**不能**再调 .to()。
        from transformers import BitsAndBytesConfig

        load_kw.update(
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            ),
            device_map={"": 0},
        )
    elif dev == "cuda":
        load_kw.update(torch_dtype=torch.bfloat16, device_map={"": 0})
    else:
        load_kw.update(torch_dtype=torch.float32)   # CPU 用 fp32，bf16 在 CPU 上很慢
    model = AutoModelForCausalLM.from_pretrained(args.model, **load_kw)

    if quantized:
        # 把 LayerNorm 等非量化层转回 fp32 并开梯度检查点，否则 4-bit 下训练不稳
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    n_lin = sum(1 for _, m in model.named_modules() if isinstance(m, torch.nn.Linear))
    print(f"线性层数: {n_lin}")

    lcfg = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_r * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules="all-linear",   # PEFT 官方架构无关写法，覆盖 GDN 层
    )
    model = get_peft_model(model, lcfg)
    model.print_trainable_parameters()
    if not quantized:
        model.to(dev)
    if dev == "cuda":
        print(f"  显存占用: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

    train_rows = load_split("train.json", args.limit or None)
    eval_rows = load_split("eval.json", args.eval_limit)
    print(f"训练 {len(train_rows)} 条 / 评测 {len(eval_rows)} 条")

    # ---------------- 训练前基线 ----------------
    print("\n[基线] 训练前的意图准确率…")
    base_acc, base_detail = evaluate(model, tok, eval_rows, dev, args.max_len)
    print(f"  训练前: {base_acc:.1%}  ({base_detail['ok']}/{base_detail['n']})")

    # ---------------- 训练 ----------------
    print(f"\n[训练] {args.epochs} epoch, lr={args.lr}, r={args.lora_r}, "
          f"batch={args.batch}×accum={args.accum}")
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr
    )
    model.train()
    t0 = time.perf_counter()
    step = 0
    losses = []
    for ep in range(args.epochs):
        for i, sample in enumerate(train_rows):
            ids, labels = build_batch(tok, sample, args.max_len)
            input_ids = torch.tensor([ids], device=dev)
            label_t = torch.tensor([labels], device=dev)
            out = model(input_ids=input_ids, labels=label_t)
            (out.loss / args.accum).backward()
            losses.append(out.loss.item())
            if (i + 1) % args.accum == 0:
                opt.step()
                opt.zero_grad()
                step += 1
                if step % 10 == 0:
                    avg = sum(losses[-args.accum * 10:]) / max(len(losses[-args.accum * 10:]), 1)
                    done = i + 1
                    el = time.perf_counter() - t0
                    eta = el / done * (len(train_rows) - done)
                    print(f"    ep{ep + 1} {done}/{len(train_rows)}  "
                          f"loss={avg:.4f}  已用 {el / 60:.1f}min  预计还需 {eta / 60:.1f}min")
    opt.step()
    opt.zero_grad()
    print(f"  训练完成，用时 {(time.perf_counter() - t0) / 60:.1f} min，"
          f"末段 loss ≈ {sum(losses[-20:]) / max(len(losses[-20:]), 1):.4f}")

    # ---------------- 训练后 ----------------
    print("\n[评测] 训练后的意图准确率…")
    model.eval()
    new_acc, new_detail = evaluate(model, tok, eval_rows, dev, args.max_len)
    print(f"  训练后: {new_acc:.1%}  ({new_detail['ok']}/{new_detail['n']})")

    print("\n" + "=" * 60)
    print(f"{'意图准确率':<14}{'训练前':>12}{'训练后':>12}{'变化':>12}")
    print(f"{'留出集':<14}{base_acc:>11.1%}{new_acc:>12.1%}"
          f"{(new_acc - base_acc) * 100:>+11.1f}pp")
    print("=" * 60)

    save = args.save or str(OUT_DIR / "intent_lora")
    model.save_pretrained(save)
    tok.save_pretrained(save)
    print(f"adapter 已保存到 {save}")
    (Path(save) / "eval_result.json").write_text(
        json.dumps(
            {
                "model": args.model, "device": dev, "epochs": args.epochs,
                "train_n": len(train_rows), "eval_n": len(eval_rows),
                "acc_before": base_acc, "acc_after": new_acc,
                "eval_detail_after": new_detail["rows"][:40],
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


def evaluate(model, tok, rows, dev, max_len):
    """在留出集上评测意图判定。"""
    import torch

    ok = 0
    detail = []
    was_training = model.training
    model.eval()
    for sample in rows:
        msgs = sample["messages"]
        prompt_ids = _ids(
            tok.apply_chat_template(msgs[:2], tokenize=True, add_generation_prompt=True,
                                    enable_thinking=False)
        )[:max_len]
        input_ids = torch.tensor([prompt_ids], device=dev)
        with torch.no_grad():
            # 256 是护栏：正常直出 JSON 只要 30–50 token，留足余量以便万一又走推理分支时
            # 能在日志里看到完整思考文本，好定位问题。
            gen = model.generate(
                input_ids=input_ids, max_new_tokens=256, do_sample=False,
                pad_token_id=tok.pad_token_id or tok.eos_token_id,
            )
        text = tok.decode(gen[0][len(prompt_ids):], skip_special_tokens=True)
        want = intent_of(sample)
        got = extract_intent(text)
        hit = got == want
        ok += hit
        if not hit and len(detail) < 20:
            detail.append({
                "query": msgs[1]["content"], "want": want, "got": got,
                "raw": text[:300],
            })
    if was_training:
        model.train()
    return ok / max(len(rows), 1), {"ok": ok, "n": len(rows), "rows": detail}


def extract_intent(text: str):
    """从模型输出里抠出 intent 字段。

    先认 JSON。**兜底规则必须收紧** —— 曾经的写法是"文本里出现 analysis 就返回 analysis"，
    结果模型一旦进入推理分支、开始复述规则（"intent 的选项有 analysis、knowledge、action……"），
    每个失败样本都被误判成 analysis，训练前基线直接变成 0.0%，把整轮评测毁了。
    改为要求取值出现在 `intent` 一词附近，宁可返回 None 也不要瞎猜。
    """
    import re

    m = re.search(r'"intent"\s*:\s*"([a-z_]+)"', text or "")
    if m:
        return m.group(1)
    m = re.search(
        r'\bintent\b\s*(?:是|为|:|＝|=)?\s*"?(analysis|knowledge|action|chat|refuse)\b',
        text or "",
    )
    if m:
        return m.group(1)
    return None


if __name__ == "__main__":
    main()
