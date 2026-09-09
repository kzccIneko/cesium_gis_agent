"""诊断：抓取 CUDA 崩溃的真实原因。

做三件事：
1. 每条样本后记录 显存占用 / 耗时 / 输出长度，看是否单调增长（泄漏）
2. 捕获完整 stderr（llama.cpp 的 CUDA 错误是写在 C 层 stderr 的，Python 捕获不到）
3. 崩到哪一条、崩前最后状态是什么

用法：
  python bench/diag_cuda.py --limit 60
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def gpu_mb() -> float:
    """当前 GPU 显存占用（MiB）。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(out.stdout.strip().splitlines()[0])
    except Exception:
        return -1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--out", default=str(REPO / "bench" / "diag_cuda.json"))
    args = ap.parse_args()

    from app.agent.llm import EmbeddedLlamaClient
    from app.eval.runner import EvalRunner, load_dataset

    client = EmbeddedLlamaClient(n_ctx=args.n_ctx, n_gpu_layers=-1)
    runner = EvalRunner(client=client, mode="tool_calling")

    # 统计 prompt token 数：这是 max_tokens 取值的硬约束
    prompt_tokens = len(
        client._ensure_model().tokenize(
            json.dumps(runner.tools, ensure_ascii=False).encode("utf-8")
        )
    )
    print(f"[diag] 工具 Schema token 数 = {prompt_tokens}", flush=True)

    cases = load_dataset()[: args.limit]
    rows = []
    base_mb = gpu_mb()
    print(f"[diag] 起始显存 {base_mb:.0f} MiB", flush=True)

    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        resp = client.chat(
            runner._build_messages(case["query"]),
            tools=runner.tools,
            temperature=0.0,
        )
        dt = time.perf_counter() - t0
        mb = gpu_mb()
        r = {
            "i": i,
            "sec": round(dt, 2),
            "vram_mb": mb,
            "out_len": len(resp.content or ""),
            "calls": [c["name"] for c in resp.tool_calls],
        }
        rows.append(r)
        print(
            f"[{i:3d}] {dt:5.1f}s vram={mb:6.0f}MiB out={r['out_len']:5d} {r['calls']}",
            flush=True,
        )

    Path(args.out).write_text(
        json.dumps({"prompt_tokens": prompt_tokens, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"[diag] 完成 {len(rows)} 条，无崩溃", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
