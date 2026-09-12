"""诊断 planner 节点的失败模式。

起因：LangGraph 编排跑 40 条 multi_tool，`n_llm_calls=3` 的样本占了 23/40。
planner 的 `max_retries=3`，调到 3 次意味着**每次都失败、最后落到
heuristic_plan 兜底** —— 也就是说评测打的分里，有一大半根本不是 LLM 的
规划结果。这种情况下任何"工具链准确率"的结论都不成立，必须先查清原因。

本脚本直接调 `plan_node`，把每次尝试的原始输出和校验错误原样打印出来，
用肉眼确认是「被截断」还是「格式乱」。不猜。

用法：
    python bench/diag_planner.py --limit 8 --max-tokens 384
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.agent.llm import EmbeddedLlamaClient, extract_json  # noqa: E402
from app.agent.nodes.planner import (  # noqa: E402
    render_planner_prompt,
    validate_plan,
)
from app.eval.runner import load_dataset  # noqa: E402


def _measure(llm, client, cases, max_tokens: int) -> int:
    """把上限放大到几乎不设限，测出 planner 到底要生成多少 token。

    和 tool_calling 场景那次 384 的标定同一个方法：**先测分布，再定值**。
    只有测得合理，"被截断导致的假失败"才不会混进准确率里。
    """
    tokens: list[int] = []
    lens: list[int] = []
    ok = 0

    for i, case in enumerate(cases, 1):
        prompt = render_planner_prompt(case["query"], None)
        resp = client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        content = resp.content or ""
        try:
            n = len(llm.tokenize(content.encode("utf-8")))
        except Exception:
            n = -1
        tokens.append(n)
        lens.append(len(content))

        obj = extract_json(content)
        err = validate_plan(obj, None) if obj else "no_json"
        if err is None:
            ok += 1
        print(
            f"[{i}/{len(cases)}] {case['id']} {n:>4} token "
            f"{len(content):>5} 字符  合法={err is None}  {err if err else ''}",
            flush=True,
        )

    tokens_sorted = sorted(t for t in tokens if t > 0)

    def pct(p: float) -> int:
        if not tokens_sorted:
            return -1
        return tokens_sorted[min(int(len(tokens_sorted) * p), len(tokens_sorted) - 1)]

    print("=" * 70)
    print(
        f"n={len(tokens_sorted)}  min={tokens_sorted[0]}  p50={pct(0.5)}  "
        f"p90={pct(0.9)}  p95={pct(0.95)}  p99={pct(0.99)}  max={tokens_sorted[-1]}"
    )
    print(f"合法率 {ok}/{len(cases)}")
    for cap in (384, 512, 640, 768, 1024):
        truncated = sum(1 for t in tokens if 0 < t >= cap)
        print(f"  上限 {cap}: 疑似截断 {truncated} 条（{truncated/len(cases):.1%}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--category", default="multi_tool")
    ap.add_argument("--offset", type=int, default=10, help="从第 N 条开始（默认跳过前 10 条满分样本）")
    ap.add_argument("--max-tokens", type=int, default=384)
    ap.add_argument("--raw", action="store_true", help="打印完整原始输出")
    ap.add_argument(
        "--measure",
        action="store_true",
        help="用大上限跑一遍，测出 planner 输出的 token 分布（用于定 max_tokens）",
    )
    ap.add_argument("--all", action="store_true", help="跑全部该类别样本")
    args = ap.parse_args()

    cases = [c for c in load_dataset() if c["category"] == args.category]
    if not args.all:
        cases = cases[args.offset : args.offset + args.limit]

    client = EmbeddedLlamaClient()
    client._ensure_model()
    llm = client._ensure_model()

    if args.measure:
        return _measure(llm, client, cases, args.max_tokens)

    print(f"max_tokens={args.max_tokens}  样本数={len(cases)}\n" + "=" * 70)

    stats = {"ok": 0, "no_json": 0, "invalid": 0}

    for i, case in enumerate(cases, 1):
        prompt = render_planner_prompt(case["query"], None)
        resp = client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=args.max_tokens,
        )
        content = resp.content or ""
        obj = extract_json(content)
        err = validate_plan(obj, None) if obj else "extract_json 返回 None"

        if obj and err is None:
            stats["ok"] += 1
            verdict = f"OK  {len(obj.get('steps') or [])} 步"
        elif obj is None:
            stats["no_json"] += 1
            verdict = f"NO_JSON  {err}"
        else:
            stats["invalid"] += 1
            verdict = f"INVALID  {err}"

        n_approx_tokens = None
        try:
            n_approx_tokens = len(client._ensure_model().tokenize(content.encode("utf-8")))
        except Exception:
            pass

        print(
            f"[{i}] {case['id']}  {verdict}  "
            f"| 输出 {len(content)} 字符 / ~{n_approx_tokens} token "
            f"| 期望 {case.get('expected_tools')}"
        )
        # 被截断的特征：没走到 JSON 结尾就到上限
        if obj is None:
            tail = content[-160:].replace("\n", "\\n")
            print(f"     尾部：...{tail}")
        if args.raw:
            print(content)

    print("=" * 70)
    print(
        f"合法 {stats['ok']} / JSON 解析失败 {stats['no_json']} / 校验不通过 {stats['invalid']}"
        f"  共 {len(cases)} 条"
    )
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
