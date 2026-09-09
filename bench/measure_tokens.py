"""测量：Agent 输出到底需要多少 token —— max_tokens 取值的依据。

max_tokens 不能拍脑袋，它由三个约束共同决定（见 IMPROVEMENT_PLAN）：
  A. 下界 = 实际输出的 p99（太小会截断正常回答）
  B. 上界1 = n_ctx - prompt_tokens - 安全余量（超出则上下文溢出）
  C. 上界2 = 可接受延迟 / 单 token 耗时（交互体验）

本脚本把 A 测出来：跑 N 条样本，统计输出 token 数的分布。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def pct(sorted_vals, p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--out", default=str(REPO / "bench" / "token_dist.json"))
    args = ap.parse_args()

    from app.agent.llm import EmbeddedLlamaClient
    from app.eval.runner import EvalRunner, load_dataset

    client = EmbeddedLlamaClient(n_ctx=args.n_ctx, n_gpu_layers=-1)
    llm = client._ensure_model()
    runner = EvalRunner(client=client, mode="tool_calling")

    # prompt token 数（工具 Schema 是大头）
    prompt_tokens = len(
        llm.tokenize(json.dumps(runner.tools, ensure_ascii=False).encode("utf-8"))
    )

    cases = load_dataset()[args.offset : args.offset + args.limit]
    rows = []
    t_all = time.perf_counter()
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        resp = client.chat(
            runner._build_messages(case["query"]),
            tools=runner.tools,
            temperature=0.0,
            max_tokens=2048,  # 测量时不设限，看它到底能吐多少
        )
        dt = time.perf_counter() - t0
        text = resp.content or ""
        n_tok = len(llm.tokenize(text.encode("utf-8")))
        rows.append(
            {
                "i": i,
                "category": case["category"],
                "out_tokens": n_tok,
                "sec": round(dt, 2),
                "n_calls": len(resp.tool_calls),
            }
        )
        print(f"[{i:3d}] {case['category']:12s} tok={n_tok:5d} {dt:6.2f}s", flush=True)
    total = time.perf_counter() - t_all

    toks = sorted(r["out_tokens"] for r in rows)
    dist = {
        "n": len(toks),
        "prompt_tokens": prompt_tokens,
        "min": toks[0],
        "p50": round(pct(toks, 0.50), 1),
        "p90": round(pct(toks, 0.90), 1),
        "p95": round(pct(toks, 0.95), 1),
        "p99": round(pct(toks, 0.99), 1),
        "max": toks[-1],
        "mean": round(statistics.mean(toks), 1),
        "total_sec": round(total, 1),
    }
    print("\n=== 输出 token 分布 ===", flush=True)
    print(json.dumps(dist, ensure_ascii=False, indent=2), flush=True)

    # 被 max_tokens=512 截断的比例
    over = [r for r in rows if r["out_tokens"] >= 500]
    print(f"\n>=500 token 的样本：{len(over)}/{len(rows)}", flush=True)
    for r in over[:10]:
        print(f"  i={r['i']} {r['category']} tok={r['out_tokens']} calls={r['n_calls']}", flush=True)

    Path(args.out).write_text(
        json.dumps({"dist": dist, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
