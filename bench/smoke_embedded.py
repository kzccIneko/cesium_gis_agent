"""Smoke test: does the embedded llama.cpp actually load our GGUF and generate?

This is the go/no-go gate for dropping Ollama. If this passes, the embedded
route is viable and we can proceed to the real benchmark.
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GGUF = REPO / "models" / "llm" / "qwen3.5-4b-q4km.gguf"

def main() -> int:
    print(f"[1/4] GGUF: {GGUF}")
    if not GGUF.exists():
        print(f"[FATAL] missing, size would be needed: {GGUF}")
        return 1
    print(f"      size: {GGUF.stat().st_size / 1024**3:.2f} GB")

    print("[2/4] import llama_cpp ...")
    t0 = time.perf_counter()
    from llama_cpp import Llama
    print(f"      ok in {time.perf_counter() - t0:.2f}s")

    # CPU build for now (no CUDA Toolkit on this machine yet)
    n_gpu_layers = 0
    print(f"[3/4] loading model (n_gpu_layers={n_gpu_layers}, CPU) ...")
    t0 = time.perf_counter()
    llm = Llama(model_path=str(GGUF), n_ctx=2048, n_gpu_layers=n_gpu_layers, verbose=False)
    load_s = time.perf_counter() - t0
    print(f"      loaded in {load_s:.2f}s")

    print("[4/4] generating ...")
    t0 = time.perf_counter()
    out = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": "You are a geospatial analysis assistant. Answer in Chinese, briefly."},
            {"role": "user", "content": "坡度分析是什么？用一句话回答。"},
        ],
        max_tokens=64,
        temperature=0.0,
    )
    gen_s = time.perf_counter() - t0
    text = out["choices"][0]["message"]["content"]
    usage = out.get("usage", {})
    n_out = usage.get("completion_tokens", 0)

    print("\n" + "=" * 60)
    print("OUTPUT:", text.strip())
    print("=" * 60)
    print(f"load_s          : {load_s:.2f}")
    print(f"gen_s           : {gen_s:.2f}")
    print(f"completion_toks : {n_out}")
    if n_out and gen_s > 0:
        print(f"gen_tps         : {n_out / gen_s:.2f} tok/s  (CPU backend)")
    print("\n[PASS] embedded llama.cpp works with our GGUF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
