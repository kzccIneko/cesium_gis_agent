"""汇总 4 组消融结果，输出对比表（Markdown）并回填看板数据。

用法：
    python bench/summarize_ablation.py --results bench/eval_results

设计原则：
- **只呈现跑出来的数字**，没有跑完的组标注"未完成"而不是填 0
  （填 0 会让对比表看起来像"这组得 0 分"，那是假的）
- 每组同时给出主集与保留集（如果有），便于看是否过拟合
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

CATS = ["single_tool", "multi_tool", "out_of_scope"]
CAT_LABEL = {
    "single_tool": "单工具调用",
    "multi_tool": "多工具串联",
    "out_of_scope": "越界拒答",
}

# 组名 → 表格里显示的名字 + 一句话说明它改变了什么
GROUPS = [
    ("g1_react", "① 临时多轮试探", "没有状态图，也没有自我校验；拿到工具结果后直接进下一步"),
    ("g2_noreflect", "② 有编排无校验", "有计划-执行-总结的状态图，但关掉自我校验（反思节点直接放行）"),
    ("g3_baseline", "③ 完整编排（基线）", "计划→执行→反思→总结，含参数校验与重试"),
    ("g4_rag", "④ 完整编排 + 知识库", "在基线之上，规划前先检索领域文献作为上下文"),
]


def _load(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data["details"] if isinstance(data, dict) else data


def _mean(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def score_group(results_dir: Path, name: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"name": name, "by_cat": {}, "complete": True}
    all_details: List[Dict[str, Any]] = []
    for cat in CATS:
        d = _load(results_dir / f"ab_{name}_{cat}.json")
        n_expect = 20 if cat == "out_of_scope" else 40
        if not d:
            out["complete"] = False
            out["by_cat"][cat] = None
            continue
        if len(d) < n_expect:
            out["complete"] = False
        te = [c["score"].get("tool_exact") for c in d
              if c["score"].get("tool_exact") is not None]
        out["by_cat"][cat] = {
            "n": len(d),
            "exact": _mean(te),
            "elapsed_p50": statistics.median([c.get("elapsed", 0.0) for c in d]),
        }
        all_details += d

    te = [c["score"].get("tool_exact") for c in all_details
          if c["score"].get("tool_exact") is not None]
    rc = [c["score"].get("refusal_correct") for c in all_details
          if c["score"].get("refusal_correct") is not None]
    out["n"] = len(all_details)
    out["exact"] = _mean(te)
    out["refusal"] = _mean(rc)
    out["calls"] = _mean([c.get("n_llm_calls") or 1 for c in all_details])
    out["elapsed_p50"] = statistics.median(
        [c.get("elapsed", 0.0) for c in all_details]) if all_details else 0.0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="汇总消融结果")
    repo = Path(__file__).resolve().parents[1]
    ap.add_argument("--results", default=str(repo / "bench" / "eval_results"))
    ap.add_argument("--out", default=str(repo / "bench" / "ablation.md"))
    args = ap.parse_args()

    results_dir = Path(args.results)
    rows = [score_group(results_dir, g[0]) for g in GROUPS]

    def pct(v: Optional[float]) -> str:
        return "—" if v is None else f"{v * 100:.1f}%"

    lines = [
        "# 消融实验：4 种工作方式的对比",
        "",
        "同一批 100 条题目（单工具 40 / 多工具 40 / 越界拒答 20），"
        "在同一套提示词与同一个本地模型下，只改变 Agent 的工作方式。",
        "",
        "| 组别 | 做了什么 | 总精确率 | 单工具 | 多工具 | 拒答 | 调用/条 | 延迟 p50 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for (key, title, desc), r in zip(GROUPS, rows):
        if r["n"] == 0:
            lines.append(f"| {title} | {desc} | 未完成 | — | — | — | — | — |")
            continue
        def cat_exact(c: str) -> str:
            v = r["by_cat"].get(c)
            return "—" if not v or v["exact"] is None else pct(v["exact"])
        mark = "" if r["complete"] else " ⚠未跑满"
        lines.append(
            f"| {title}{mark} | {desc} | **{pct(r['exact'])}** | "
            f"{cat_exact('single_tool')} | {cat_exact('multi_tool')} | "
            f"{pct(r['refusal'])} | {r['calls']:.2f} | {r['elapsed_p50']:.1f}s |"
        )

    lines += ["", "## 每组说明了什么", ""]
    if rows[0]["n"] and rows[2]["n"]:
        d = (rows[2]["exact"] or 0) - (rows[0]["exact"] or 0)
        lines.append(
            f"- **状态图编排值不值**：① 与 ③ 的差 = {d * 100:+.1f} 个百分点。"
            f"（① 没有计划-执行-反思结构，一次只吐一个工具）"
        )
    if rows[1]["n"] and rows[2]["n"]:
        d = (rows[2]["exact"] or 0) - (rows[1]["exact"] or 0)
        lines.append(
            f"- **自我校验值不值**：② 与 ③ 的差 = {d * 100:+.1f} 个百分点。"
            f"（② 关掉反思节点，结果不做任何校验直接采纳）"
        )
    if rows[3]["n"] and rows[2]["n"]:
        d = (rows[3]["exact"] or 0) - (rows[2]["exact"] or 0)
        lines.append(
            f"- **知识库检索值不值**：③ 与 ④ 的差 = {d * 100:+.1f} 个百分点。"
            f"（④ 规划前先检索 literature/ 的 303 块语料）"
        )
    lines += [
        "",
        "> ⚠ 差值小于约 3 个百分点时不要下结论：100 条样本的标准误约 2 个百分点，"
        "这个量级的差异可能只是随机波动。",
        "",
    ]

    out = Path(args.out)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[消融] 已生成 {out}")
    for (key, title, _desc), r in zip(GROUPS, rows):
        print(f"  {title}: n={r['n']} 精确率={pct(r['exact'])}"
              f"{'' if r['complete'] else '  ⚠未跑满'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
