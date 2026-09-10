"""把 bge-small-zh-v1.5 转成 GGUF —— convert_hf_to_gguf.py 的一层薄包装。

为什么需要包装
--------------
llama.cpp 的 `get_vocab_base_pre()` 用「把一段多语言探针文本编码后取 SHA256」
来反查使用的是哪个 BPE pre-tokenizer，**维护方式是一张硬编码的哈希白名单**。
bge-small-zh-v1.5 的哈希不在名单里，转换会抛

    NotImplementedError: BPE pre-tokenizer was not recognized

但 bge 用的是 **WordPiece + BertPreTokenizer**，而 llama.cpp 本身是支持它的
（`MODEL_ARCH.BERT = "bert"`，`llama-vocab.cpp` 有 `tokenizer_model == "bert"` 分支）。
也就是说：**缺的不是运行时能力，只是转换脚本不认识这把锁的钥匙**。

这里不改第三方源码（改了下次 git pull 就冲突），而是在调用前 monkey-patch 掉
这一个函数、直接返回 `"bert"`。改一处、影响面可控，并在末尾做端到端校验。

用法：
    python tools/convert_bge_gguf.py --src D:/tmp/bge_dl --outdir models/embedding
    python tools/convert_bge_gguf.py --src D:/tmp/bge_dl --quantize q8_0
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LLAMA_CPP = Path(os.environ.get("LLAMA_CPP_DIR", "D:/llama_build/llama.cpp"))


def patch(llama_cpp: Path) -> None:
    """把 llama.cpp 的转换模块挂进 sys.path 并打补丁。"""
    sys.path.insert(0, str(llama_cpp))
    # 注意：目标方法是挂在 TextModel 上的（base.py），不在 ModelBase
    from conversion.base import TextModel

    # 只对 BERT 架构生效，避免影响其它模型的转换行为
    orig = TextModel.get_vocab_base_pre

    def patched(self, tokenizer):
        arch = str(getattr(self, "model_arch", "")).lower()
        cfg_name = ""
        try:
            cfg_name = str(type(tokenizer).__name__).lower()
        except Exception:
            pass
        if "bert" in arch or "bert" in cfg_name:
            return "bert"
        return orig(self, tokenizer)

    TextModel.get_vocab_base_pre = patched


def run_convert(src: Path, outfile: Path, outtype: str) -> None:
    """直接执行转换脚本的 main —— 补丁已在 sys.modules 生效。"""
    import runpy

    script = LLAMA_CPP / "convert_hf_to_gguf.py"
    sys.argv = [
        str(script),
        str(src),
        "--outfile",
        str(outfile),
        "--outtype",
        outtype,
    ]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            raise


def quantize(src_gguf: Path, dst_gguf: Path, qtype: str) -> Path:
    exe = LLAMA_CPP / "build" / "bin" / "Release" / "llama-quantize.exe"
    if not exe.exists():
        # 源码构建时二进制可能在别处，尝试常见位置
        cands = list(LLAMA_CPP.rglob("llama-quantize.exe"))
        if not cands:
            raise FileNotFoundError("找不到 llama-quantize.exe")
        exe = cands[0]

    cmd = [str(exe), str(src_gguf), str(dst_gguf), qtype]
    subprocess.run(cmd, check=True)
    return dst_gguf


def verify(model_path: Path) -> bool:
    """端到端校验：语义相近的句子，余弦相似度应显著高于不相干的。"""
    import numpy as np
    from llama_cpp import Llama

    llm = Llama(model_path=str(model_path), embedding=True, n_ctx=512, verbose=False)

    def emb(t: str) -> np.ndarray:
        return np.asarray(llm.embed(t, normalize=True), dtype=np.float32)

    a = emb("坡度是地表倾斜程度的度量")
    b = emb("地形坡度反映了地面的陡缓程度")
    c = emb("今天股市大涨，银行股领涨")
    sim_ab = float(a @ b)
    sim_ac = float(a @ c)
    dim = len(a)

    print(f"[校验] 维度 {dim}")
    print(f"[校验] 语义相近句 ({sim_ab:.4f}) vs 无关句 ({sim_ac:.4f})")
    ok = sim_ab > sim_ac + 0.15 and sim_ab > 0.6
    print(f"[校验] {'通过' if ok else '未通过 —— 检查是否用错 pooling'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="bge → GGUF 转换（含 llama.cpp 打补丁）")
    ap.add_argument("--src", required=True, help="HF 格式模型目录")
    ap.add_argument("--outdir", default=str(REPO_ROOT / "models" / "embedding"))
    ap.add_argument("--name", default="bge-small-zh-v1.5")
    ap.add_argument("--quantize", default="q8_0", help="留空则不量化")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    if not LLAMA_CPP.exists():
        print(f"[错误] llama.cpp 目录不存在：{LLAMA_CPP}", file=sys.stderr)
        return 1

    patch(LLAMA_CPP)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    f16 = outdir / f"{args.name}-f16.gguf"

    print(f"[转换] {args.src} -> {f16}")
    run_convert(Path(args.src), f16, "f16")
    print(f"[完成] {f16}  {f16.stat().st_size / 1e6:.1f} MB")

    final = f16
    if args.quantize:
        qpath = outdir / f"{args.name}-{args.quantize}.gguf"
        print(f"[量化] -> {qpath} ({args.quantize})")
        quantize(f16, qpath, args.quantize)
        print(f"[完成] {qpath}  {qpath.stat().st_size / 1e6:.1f} MB")
        final = qpath

    if args.skip_verify:
        return 0
    print(f"[校验] 用 llama.cpp 加载 {final.name}")
    return 0 if verify(final) else 1


if __name__ == "__main__":
    raise SystemExit(main())
