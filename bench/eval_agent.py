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
sys.path.insert(0, str(REPO / "bench"))  # graph_eval 与本脚本同目录

from app.agent.llm import EmbeddedLlamaClient  # noqa: E402
from app.eval.metrics import aggregate  # noqa: E402
from app.eval.metrics import score_case  # noqa: E402
from app.eval.runner import EvalRunner, load_dataset  # noqa: E402
from graph_eval import run_case_graph  # noqa: E402

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
        "--orchestrator",
        choices=["langgraph", "loop"],
        default="langgraph",
        help=(
            "编排方式。langgraph = 真实 plan→execute→reflect→summarize 状态图"
            "（默认）；loop = 临时多轮试探（调工具→喂结果→再问），用于对照"
        ),
    )
    ap.add_argument(
        "--reflect-llm",
        action="store_true",
        help="反思节点启用 LLM 语义复核（默认只跑代码规则，省调用开销）",
    )
    ap.add_argument(
        "--summarize-llm",
        action="store_true",
        help="总结节点用 LLM 写回答（默认用模板回答）",
    )
    ap.add_argument(
        "--no-gazetteer",
        action="store_true",
        help="关闭地名词典（langgraph 编排下的对照实验）",
    )
    ap.add_argument(
        "--no-reflector",
        action="store_true",
        help=(
            "关闭反思节点（GEOAGENT_REFLECTOR=0）：结果不做任何校验直接采纳。"
            "用于消融实验对比「有自我校验」与「无自我校验」的差异"
        ),
    )
    ap.add_argument(
        "--turns",
        type=int,
        default=1,
        help="每条样本最多几轮 tool-calling（仅 loop 编排下生效）",
    )
    ap.add_argument("--report", default=str(REPO / "bench" / "eval_agent_report.md"))
    ap.add_argument(
        "--dataset",
        default="",
        help="指定评测集路径（默认 backend/app/eval/dataset.json）。"
        "传入 dataset_heldout.json 可跑未参与调参的保留集，检验修改是否真的泛化。",
    )
    args = ap.parse_args()

    cases = load_dataset(args.dataset or None)
    if args.dataset:
        print(f"[eval] 使用指定评测集：{args.dataset}（{len(cases)} 条）")
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

    if args.no_reflector:
        os.environ["GEOAGENT_REFLECTOR"] = "0"

    orchestrator_desc = (
        "LangGraph 编排（plan→execute→reflect→summarize）"
        if args.orchestrator == "langgraph"
        else f"多轮试探循环（最多 {args.turns} 轮）"
    )
    if args.no_reflector:
        orchestrator_desc += "，反思已关闭"
    runner = EvalRunner(
        client=client,
        mode=args.mode,
        model_label=f"embedded-Qwen3.5-4B-Q4_K_M/{args.orchestrator}"
        + ("+GBNF" if args.grammar else "")
        + ("+gazetteer" if args.gazetteer else "")
        + ("+no-reflector" if args.no_reflector else ""),
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
        extra: Dict[str, Any] = {}
        if args.orchestrator == "langgraph":
            g = run_case_graph(
                case,
                client,
                use_gazetteer=not args.no_gazetteer,
                reflect_llm=args.reflect_llm,
                summarize_llm=args.summarize_llm,
            )
            elapsed_case = g["elapsed"]
            r = {
                "score": score_case(case, g["prediction"]),
                "prediction": g["prediction"],
                "elapsed": elapsed_case,
            }
            extra = {
                "n_llm_calls": g["n_llm_calls"],
                "status": g["status"],
                "n_steps_planned": g["n_steps_planned"],
            }
        elif args.turns > 1:
            prediction, n_calls = run_case_multiturn(
                runner, case, args.turns, args.max_tokens
            )
            elapsed_case = time.perf_counter() - t_case
            r = {
                "score": score_case(case, prediction),
                "prediction": prediction,
                "elapsed": elapsed_case,
            }
            extra = {"n_llm_calls": n_calls}
        else:
            r = runner.run_case(case)
            extra = {}
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
            **extra,
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
    n_calls = [d.get("n_llm_calls") for d in details if d.get("n_llm_calls") is not None]
    avg_calls = round(sum(n_calls) / len(n_calls), 2) if n_calls else None
    statuses: Dict[str, int] = {}
    for d in details:
        s = d.get("status")
        if s:
            statuses[s] = statuses.get(s, 0) + 1

    agg = aggregate([d["score"] for d in details])
    summary = {
        "model": runner.model_label,
        "orchestrator": args.orchestrator,
        "cases": len(details),
        "elapsed_s": round(elapsed, 1),
        "avg_case_s": round(elapsed / max(len(todo), 1), 2),
        "avg_llm_calls_per_case": avg_calls,
        "end_status": statuses,
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
        f"- 编排：{orchestrator_desc}",
        f"- 模式：{args.mode}" + (" + GBNF 约束解码" if args.grammar else ""),
        f"- 样本：{len(details)} 条，本次耗时 {elapsed:.1f}s"
        f"（{elapsed/max(len(todo),1):.2f}s/条）",
    ]
    if avg_calls is not None:
        lines.append(f"- 每样本 LLM 调用次数：{avg_calls}")
    if statuses:
        lines.append(
            "- 结束状态分布："
            + "，".join(f"{k} {v}" for k, v in sorted(statuses.items()))
        )
    lines += [
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
