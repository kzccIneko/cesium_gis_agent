"""用嵌入式 llama.cpp（本机 CUDA）跑 Agent tool-calling 评测集。

这是「模型能力」的量化入口：评测集 100 条，考察
  1. 工具选择是否正确（tool_f1）
  2. 参数（尤其 bbox）是否正确（param scores）
  3. 该拒答的是否拒答（refusal accuracy）
  4. JSON 合法性 —— 可在 --grammar 下用 GBNF 强制约束作对比

设计要点（都是踩坑换来的，别改回去）
------------------------------------
* **断点续跑**：每跑完一条就落盘。GPU 偶发 CUDA error 会直接 abort 进程
  （C 层 abort，Python try/except 拦不住），重跑时加 --resume 即可接着跑，
  不需要分块 + sleep 那种低效办法。
* **max_tokens 必设**：不设的话模型会一直生成直到撑爆上下文。
  默认值来自 bench/measure_tokens.py 的实测分布，不是拍脑袋。

用法：
  python bench/eval_agent.py --limit 20
  python bench/eval_agent.py --all --resume --out-json D:\\tmp\\full.json
  python bench/eval_agent.py --mode json --grammar

数字必须来自本机实测，禁止估算。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.agent.llm import EmbeddedLlamaClient  # noqa: E402
from app.eval.metrics import aggregate  # noqa: E402
from app.eval.metrics import score_case  # noqa: E402
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

# 默认生成上限。依据 bench/measure_tokens.py 实测 60 条（放开到 1024）：
#   min=35 p50=116 p90=193 p95=272 p99=318 max=318
#   >256 的占 5%，>384 的占 0%
# 取 384：盖住 p99 且留 21% 余量，又远低于上下文上限 (8192-5323=2869)。
DEFAULT_MAX_TOKENS = 384


def fake_tool_result(name: str) -> Dict[str, Any]:
    """工具的**桩结果**。

    为什么用桩：本评测测的是「模型会不会规划工具链」，不是「工具本身能不能跑」
    ——工具本身有 28 个单测覆盖，且 download_srtm 真跑要联网 10-30 秒。
    给一个结构合理的结果，让模型能接着往下规划即可。
    """
    base: Dict[str, Any] = {"status": "ok"}
    if name == "download_srtm":
        return {**base, "dem_path": "data/dem/srtm_30m.tif", "resolution_m": 30,
                "crs": "EPSG:4326"}
    if name == "get_dem_metadata":
        return {**base, "width": 3601, "height": 3601, "resolution_m": 30,
                "nodata": -32768}
    if name.startswith("compute_"):
        return {**base, "raster_path": f"data/out/{name}.tif",
                "stats": {"min": 0.0, "max": 65.3, "mean": 18.7}}
    if name.startswith("classify_"):
        return {**base, "class_path": f"data/out/{name}.tif", "classes": 6,
                "dominant": "山地"}
    if name == "plan_route":
        return {**base, "path": [[103.5, 30.6], [103.8, 30.9], [104.1, 31.1]],
                "length_km": 62.4}
    if name == "zonal_statistics":
        return {**base, "zones": 6, "mean": 21.4, "std": 9.8}
    return base


def run_case_multiturn(
    runner: EvalRunner, case: Dict[str, Any], max_turns: int, max_tokens: int
) -> tuple:
    """多轮链路：调工具 → 拿到结果 → 继续规划，直到不再调工具。

    单轮直问为什么不够：4B 模型一次只会吐一个工具。像
    「下载 DEM → 算坡度 → 分类」这种链条，必须让模型看到上一步的结果
    才能规划下一步 —— 这正是 Agent 相对单次调用的价值所在。
    """
    from types import SimpleNamespace

    messages: List[Dict[str, Any]] = list(runner._build_messages(case["query"]))
    all_calls: List[Dict[str, Any]] = []
    contents: List[str] = []

    for _ in range(max_turns):
        resp = runner.client.chat(
            messages, tools=runner.tools, temperature=0.0, max_tokens=max_tokens
        )
        contents.append(resp.content or "")
        calls = resp.tool_calls or []
        if not calls:
            break
        all_calls.extend(calls)
        messages.append({"role": "assistant", "content": resp.content or ""})
        for c in calls:
            messages.append(
                {
                    "role": "tool",
                    "name": c["name"],
                    "content": json.dumps(
                        fake_tool_result(c["name"]), ensure_ascii=False
                    ),
                }
            )

    agg = SimpleNamespace(tool_calls=all_calls, content="\n".join(contents))
    return runner._parse_prediction(agg), len(all_calls)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="跑前 N 条（默认 20）")
    ap.add_argument("--offset", type=int, default=0, help="从第 N 条之后开始")
    ap.add_argument("--out-json", default="", help="结果落盘路径（断点续跑的锚点）")
    ap.add_argument("--all", action="store_true", help="跑全量 100 条")
    ap.add_argument("--category", default="", help="只跑某一类：single_tool/multi_tool/out_of_scope")
    ap.add_argument(
        "--resume", action="store_true", help="跳过 out-json 中已完成的样本"
    )
    ap.add_argument("--mode", choices=["tool_calling", "json"], default="tool_calling")
    ap.add_argument("--grammar", action="store_true", help="JSON 模式下启用 GBNF 约束")
    ap.add_argument(
        "--gazetteer",
        action="store_true",
        help="启用地名词典：把 query 里的地名换成精确 bbox（测 param_bbox 的增益）",
    )
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--n-gpu-layers", type=int, default=-1)
    ap.add_argument("--n-batch", type=int, default=512)
    ap.add_argument(
        "--prefix-cache",
        action="store_true",
        help="复用 system+tools 的 KV 前缀（批量评测提速，实测 1.63x）",
    )
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument(
        "--turns",
        type=int,
        default=1,
        help="每条样本最多几轮 tool-calling（>1 即多轮链路评测）",
    )
    ap.add_argument("--report", default=str(REPO / "bench" / "eval_agent_report.md"))
    args = ap.parse_args()

    cases = load_dataset()
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if not args.all:
        cases = cases[args.offset : args.offset + args.limit]

    # ---- 断点续跑：先读出已完成的 id ----
    done: dict[str, dict] = {}
    out_path = Path(args.out_json) if args.out_json else None
    if args.resume and out_path and out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            for d in prev.get("details", []):
                done[str(d["id"])] = d
            print(f"[eval] 续跑：已有 {len(done)} 条，跳过")
        except Exception as exc:
            print(f"[eval] 续跑文件损坏（{exc}），从头开始")
            done = {}

    todo = [c for c in cases if str(c["id"]) not in done]
    if not todo:
        # 仍然汇总一遍，否则续跑完成时看不到分数
        agg = aggregate([d["score"] for d in done.values()])
        print(json.dumps({"cases": len(done), "metrics": agg}, ensure_ascii=False, indent=2))
        return 0

    client = EmbeddedLlamaClient(
        n_ctx=args.n_ctx,
        n_gpu_layers=args.n_gpu_layers,
        n_batch=args.n_batch,
        use_grammar=args.grammar,
        prefix_cache=args.prefix_cache,
    )

    if args.mode == "json" and args.grammar:
        original_chat = client.chat

        def chat_with_grammar(messages, tools=None, temperature=0.0, **kw):
            return original_chat(
                messages,
                tools=tools,
                temperature=temperature,
                response_schema=RESPONSE_SCHEMA,
                **kw,
            )

        client.chat = chat_with_grammar  # type: ignore[method-assign]

    runner = EvalRunner(
        client=client,
        mode=args.mode,
        model_label=f"embedded-Qwen3.5-4B-Q4_K_M/{args.mode}"
        + ("+GBNF" if args.grammar else "")
        + ("+gazetteer" if args.gazetteer else ""),
        use_gazetteer=args.gazetteer,
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

    print(
        f"[eval] 待跑={len(todo)} 已完成={len(done)} "
        f"mode={args.mode} max_tokens={args.max_tokens}"
    )
    t0 = time.perf_counter()
    for i, case in enumerate(todo, 1):
        t_case = time.perf_counter()
        if args.turns > 1:
            prediction, n_calls = run_case_multiturn(
                runner, case, args.turns, args.max_tokens
            )
            elapsed = time.perf_counter() - t_case
            r = {
                "score": score_case(case, prediction),
                "prediction": prediction,
                "elapsed": elapsed,
            }
        else:
            r = runner.run_case(case)
        rec = {
            "id": case["id"],
            "category": case["category"],
            "query": case["query"],
            "expected_tools": case.get("expected_tools"),
            "predicted_tools": r["prediction"]["tools"],
            "predicted_params": r["prediction"]["params"],
            "refused": r["prediction"]["refused"],
            "parsed": r["prediction"]["parsed"],
            "parse_error": r["prediction"].get("parse_error"),
            "elapsed": round(r["elapsed"], 3),
            "score": r["score"],
        }
        done[str(case["id"])] = rec
        print(
            f"  [{i}/{len(todo)}] {case['id']} "
            f"工具={rec['predicted_tools']} 命中={rec['score'].get('tool_exact')} "
            f"({rec['elapsed']:.2f}s)",
            flush=True,
        )
        # 每条落盘：进程被 CUDA abort 杀掉时不会丢进度
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps({"details": list(done.values())}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
    elapsed = time.perf_counter() - t0

    details = list(done.values())
    agg = aggregate([d["score"] for d in details])
    summary = {
        "model": runner.model_label,
        "cases": len(details),
        "elapsed_s": round(elapsed, 1),
        "avg_case_s": round(elapsed / max(len(todo), 1), 2),
        "metrics": agg,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    parsed = sum(1 for d in details if d.get("parsed"))
    errs = [d.get("parse_error") for d in details if d.get("parse_error")]
    if errs:
        print(f"[eval] 解析失败 {len(errs)} 例，样例：{errs[0][:200]}")

    lines = [
        "# Agent Tool-Calling 评测（嵌入式 CUDA）",
        "",
        f"_generated: {time.strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "- 模型：Qwen3.5-4B Q4_K_M（进程内 llama.cpp，CUDA sm_75，全层卸载）",
        f"- 模式：{args.mode}" + (" + GBNF 约束解码" if args.grammar else ""),
        f"- 样本：{len(details)} 条，本次耗时 {elapsed:.1f}s"
        f"（{elapsed/max(len(todo),1):.2f}s/条）",
        f"- 解析成功率：{parsed}/{len(details)}",
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
    sys.exit(main())
