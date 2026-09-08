"""用嵌入式 llama.cpp（本机 CUDA）跑 Agent tool-calling 评测集。

这是「模型能力」的量化入口：评测集 100 条，考察
  1. 工具选择是否正确（tool_f1）
  2. 参数（尤其 bbox）是否正确（param scores）
  3. 该拒答的是否拒答（refusal accuracy）
  4. JSON 合法性 —— 可在 --grammar 下用 GBNF 强制约束作对比

用法：
  python bench/eval_agent.py --limit 20                 # 前 20 条，tool_calling
  python bench/eval_agent.py --mode json --grammar      # JSON 模式 + GBNF 约束
  python bench/eval_agent.py --all                      # 全量 100 条

数字必须来自本机实测，禁止估算。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.agent.llm import EmbeddedLlamaClient  # noqa: E402
from app.eval.metrics import aggregate  # noqa: E402
from app.eval.runner import EvalRunner, load_dataset  # noqa: E402

# JSON 模式下的输出结构 —— 同时作为 GBNF 文法的约束源
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tools": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
        "refused": {"type": "boolean"},
    },
    "required": ["tools"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="跑前 N 条（默认 20）")
    ap.add_argument("--all", action="store_true", help="跑全量 100 条")
    ap.add_argument("--mode", choices=["tool_calling", "json"], default="tool_calling")
    ap.add_argument("--grammar", action="store_true", help="JSON 模式下启用 GBNF 约束解码")
    # 11 个工具的 JSON Schema 约 5.2k tokens，n_ctx 必须留足余量
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--n-gpu-layers", type=int, default=-1)
    ap.add_argument("--report", default=str(REPO / "bench" / "eval_agent_report.md"))
    args = ap.parse_args()

    cases = load_dataset()
    if not args.all:
        cases = cases[: args.limit]

    client = EmbeddedLlamaClient(
        n_ctx=args.n_ctx,
        n_gpu_layers=args.n_gpu_layers,
        use_grammar=args.grammar,
    )

    # JSON 模式下把 schema 通过闭包注入（EvalRunner 不支持透传 response_schema）
    if args.mode == "json" and args.grammar:
        original_chat = client.chat

        def chat_with_grammar(messages, tools=None, temperature=0.0):
            return original_chat(
                messages,
                tools=tools,
                temperature=temperature,
                response_schema=RESPONSE_SCHEMA,
            )

        client.chat = chat_with_grammar  # type: ignore[method-assign]

    runner = EvalRunner(
        client=client,
        mode=args.mode,
        model_label=f"embedded-Qwen3.5-4B-Q4_K_M/{args.mode}"
        + ("+GBNF" if args.grammar else ""),
    )

    # 预热：显存被其他程序占用时 CUDA 初始化会偶发失败，重试即可
    for attempt in range(4):
        try:
            client._ensure_model()
            break
        except Exception as exc:
            if attempt == 3:
                raise
            print(f"[eval] 模型加载失败（{exc}），{5 * (attempt + 1)}s 后重试")
            time.sleep(5 * (attempt + 1))

    print(f"[eval] cases={len(cases)} mode={args.mode} grammar={args.grammar}")
    t0 = time.perf_counter()
    result = runner.run_all(cases, verbose=False)
    elapsed = time.perf_counter() - t0

    agg = aggregate([d["score"] for d in result["details"]])
    summary = {
        "model": runner.model_label,
        "cases": len(cases),
        "elapsed_s": round(elapsed, 1),
        "avg_case_s": round(elapsed / max(len(cases), 1), 2),
        "metrics": agg,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    parsed = sum(1 for d in result["details"] if d.get("parsed"))
    errs = [d.get("parse_error") for d in result["details"] if d.get("parse_error")]
    if errs:
        print(f"[eval] 解析失败 {len(errs)} 例，样例：{errs[0][:200]}")
    lines = [
        "# Agent Tool-Calling 评测（嵌入式 CUDA）",
        "",
        f"_generated: {time.strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        f"- 模型：Qwen3.5-4B Q4_K_M（进程内 llama.cpp，CUDA sm_75，全层卸载）",
        f"- 模式：{args.mode}" + (" + GBNF 约束解码" if args.grammar else ""),
        f"- 样本：{len(cases)} 条，总耗时 {elapsed:.1f}s（{elapsed/max(len(cases),1):.2f}s/条）",
        f"- 解析成功率：{parsed}/{len(cases)}",
        "",
        "```json",
        json.dumps(agg, ensure_ascii=False, indent=2),
        "```",
        "",
        "> 本机实测。写进简历/汇报的数字必须来自本表。",
    ]
    Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    print(f"[eval] report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
