"""把各类别的评测 JSON 合成一份总报告（含指标含义说明）。

用法：
    python bench/make_eval_report.py \
        --in D:/tmp/geoagent_eval/graph_single_40.json \
        --in D:/tmp/geoagent_eval/graph_multi_40_v5.json \
        --in D:/tmp/geoagent_eval/graph_refuse_20.json \
        --out D:/tmp/geoagent_eval/EVAL_REPORT.md
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List

CAT_LABEL = {
    "single_tool": "单工具调用",
    "multi_tool": "多工具串联",
    "out_of_scope": "越界拒答",
}

METRIC_DOC = [
    ("parsed", "**解析成功率**",
     "模型输出能被解析成合法 JSON 的比例。这是漏斗第一层 —— 解析失败后面全部为 0。"),
    ("tool_exact", "**工具链完全命中率（主指标）**",
     "预测的工具序列与标准答案**逐项且同序**完全一致的比例。最严格，也是真实业务里"
     "「整条链路能不能跑通」的代理指标。"),
    ("tool_set_f1", "**工具集合 F1**",
     "把工具序列当集合，算查准率与查全率的调和平均。它**不看顺序**，"
     "所以高于 tool_exact 就说明「工具选对了但顺序错了或多了/少了」。"),
    ("tool_order", "**步骤顺序正确率**",
     "工具都选对的前提下，执行顺序也对的比例。与 tool_set_f1 配合看："
     "两者都高而 tool_exact 低 → 纯顺序问题；tool_set_f1 高而 tool_order 低 → 依赖倒置。"),
    ("param_bbox", "**bbox 参数准确率**",
     "预测的经纬度范围与标准答案的误差在 0.01°（约 1.1 km）以内的比例。"
     "衡量的是**地理知识**，不是推理能力。"),
    ("refusal_correct", "**拒答正确率**",
     "该拒答的拒了、不该拒答的没拒。越界类看它，工具类看「没有误拒」。"),
    ("completed", "**任务完成率**",
     "智能体走完整条状态图并给出最终回答的比例（未卡在重试/异常）。"),
]


def _pct(x: Any) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _load(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _case_stats(details: List[Dict[str, Any]]) -> str:
    el = [d["elapsed"] for d in details if d.get("elapsed")]
    calls = [d.get("n_llm_calls") for d in details if d.get("n_llm_calls") is not None]
    if not el:
        return "—"
    parts = [f"p50 {statistics.median(el):.1f}s"]
    parts.append(f"p90 {sorted(el)[max(int(len(el) * 0.9) - 1, 0)]:.1f}s")
    if calls:
        parts.append(f"LLM 调用 {sum(calls) / len(calls):.2f} 次/条")
    return " / ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", action="append", required=True, dest="inputs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    runs = [_load(p) for p in args.inputs]
    all_details: List[Dict[str, Any]] = []
    for r in runs:
        all_details.extend(r["details"])
        r.setdefault("metrics", {"n": len(r["details"])})

    lines: List[str] = []
    lines.append("# GeoAgent 工具调用评测报告（LangGraph 编排）")
    lines.append("")
    lines.append(f"_生成时间：{_now()}_")
    lines.append("")
    lines.append(f"- 模型：Qwen3.5-4B Q4_K_M，进程内 llama.cpp + CUDA（RTX 2060 6GB，全层卸载）")
    lines.append("- 编排：LangGraph `plan → execute → reflect → summarize`")
    lines.append(f"- 样本：{len(all_details)} 条")
    lines.append("")

    # ---- 指标含义 ----
    lines.append("## 一、指标含义（先读懂再看数）")
    lines.append("")
    lines.append("| 指标 | 含义 | 它低说明什么 |")
    lines.append("|---|---|---|")
    for key, name, doc in METRIC_DOC:
        lines.append(f"| {name} | `{key}` | {doc} |")
    lines.append("")
    lines.append("**怎么看一组数**：`tool_set_f1` 明显高于 `tool_exact` → 工具选对了但"
                 "顺序或数量不对；`param_bbox` 低 → 缺地理知识而非不会推理；"
                 "`parsed` < 1 → 先修解析/截断，别急着调提示词。")
    lines.append("")

    # ---- 总体 ----
    lines.append("## 二、总体结果")
    lines.append("")
    lines.append("| 类别 | 样本 | 工具链完全命中 | 集合 F1 | 顺序正确 | bbox 准确 | 拒答正确 | 延迟 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in runs:
        det = r["details"]
        cat = det[0]["category"] if det else "?"

        def _m(k: str) -> Any:
            vals = [d["score"].get(k) for d in det if d["score"].get(k) is not None]
            return sum(vals) / len(vals) if vals else None

        lines.append(
            f"| {CAT_LABEL.get(cat, cat)} | {len(det)} "
            f"| {_pct(_m('tool_exact'))} | {_pct(_m('tool_set_f1'))} "
            f"| {_pct(_m('tool_order'))} | {_pct(_m('param_bbox'))} "
            f"| {_pct(_m('refusal_correct'))} | {_case_stats(det)} |"
        )
    # 合计
    n = len(all_details)
    def _agg(k: str) -> Any:
        vals = [d["score"].get(k) for d in all_details if d["score"].get(k) is not None]
        return sum(vals) / len(vals) if vals else None
    lines.append(
        f"| **合计** | **{n}** "
        f"| **{_pct(_agg('tool_exact'))}** | **{_pct(_agg('tool_set_f1'))}** "
        f"| **{_pct(_agg('tool_order'))}** | **{_pct(_agg('param_bbox'))}** "
        f"| **{_pct(_agg('refusal_correct'))}** | {_case_stats(all_details)} |"
    )
    lines.append("")
    lines.append(
        "> 注：`out_of_scope` 类本就没有标准工具链，`tool_exact` 记为 `—` 属正常，"
        "该类只看 `拒答正确率`。"
    )
    lines.append("")

    if args.note:
        lines.append(args.note)
        lines.append("")

    # ---- 失分明细 ----
    lines.append("## 三、失分明细")
    lines.append("")
    miss = [d for d in all_details if d["score"].get("tool_exact") == 0.0]
    if not miss:
        lines.append("无失分。")
    else:
        lines.append(f"共 {len(miss)} 条 `tool_exact` 未命中：")
        lines.append("")
        lines.append("| 样本 | 问题 | 期望 | 实际 | 多 | 缺 |")
        lines.append("|---|---|---|---|---|---|")
        for d in miss:
            e = d["expected_tools"] or []
            p = d["predicted_tools"] or []
            extra = [t for t in p if t not in e]
            lack = [t for t in e if t not in p]
            lines.append(
                f"| {d['id']} | {d['query'][:28]} | {'→'.join(e) or '（拒答）'} "
                f"| {'→'.join(p) or '（拒答）'} | {', '.join(extra) or '—'} "
                f"| {', '.join(lack) or '—'} |"
            )
    lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] -> {out}")
    return 0


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
