"""Agent 评测回归：跑主集 → 与基线逐项对比 → 输出涨跌与"翻转样本"清单。

为什么需要这个脚本
------------------
本项目真发生过一次：为了让 multi_tool 学会"不省中间步骤"，在提示词里写了
标准链路模板，multi_tool 从 0.70 涨到 0.825，**但 single_tool 从 0.70 崩到 0.375**
——21 条失分里 19 条是"多算了一个 compute_slope"。当时没人发现，是下一次全量
评测才暴露的。

所以改提示词 / 改图结构之后，必须能一条命令回答两个问题：

    1. 有没有把别的类别搞坏？           → 分项指标对比
    2. 坏的是哪几条、长什么样？          → 翻转样本清单

只报总分是不够的 —— "跌了 5 个点"和"跌的是哪 5 条"是两个完全不同的问题，
后者才是能动手改的前提。

用法
----
    # 只对比已有结果（不加载模型，秒级出结果）
    python bench/run_regression.py --baseline v19 --candidate v21_planner

    # 先跑一次评测，再自动与基线对比
    python bench/run_regression.py --run --tag v23 --baseline v19

    # 只看某一类
    python bench/run_regression.py --baseline v19 --candidate v20 --category single_tool

    # 看看有哪些结果可以用
    python bench/run_regression.py --list

口径
----
指标一律走 app.eval.metrics.aggregate()，与主评测集口径一致：
`tool_exact` 只在有工具期望的样本上计算，越界拒答题不参与（它们的分数看
`refusal_correct`）。**不要**自己对 details 里所有条目取平均 —— 那会把
拒答题按 0 分计入，得出"主集 76.9%"这种错误数字。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.eval.metrics import aggregate  # noqa: E402

RESULTS_DIR = REPO / "bench" / "eval_results"
CATEGORIES = ["single_tool", "multi_tool", "out_of_scope"]

# 对比哪些指标（None 表示该类别不适用，会被 aggregate 自动排除）
METRIC_KEYS = ["completed", "tool_exact", "tool_set_f1", "tool_order",
               "param_bbox", "refusal_correct", "parsed"]


# ──────────────────────────── 结果文件定位 ────────────────────────────

def resolve_tag_files(tag: str, categories: Optional[List[str]] = None) -> Dict[str, Path]:
    """把 tag 解析成 {category: 文件路径}。

    支持两种命名（历史遗留，都要认）：
        {tag}_{category}.json          —— 如 v19_single_tool.json
        {tag}_{子名}_{category}.json    —— 如 v21_planner_single_tool.json
    """
    cats = categories or CATEGORIES
    out: Dict[str, Path] = {}
    for cat in cats:
        exact = RESULTS_DIR / f"{tag}_{cat}.json"
        if exact.exists():
            out[cat] = exact
            continue
        matches = sorted(RESULTS_DIR.glob(f"{tag}_*_{cat}.json"))
        if matches:
            out[cat] = matches[0]
    return out


def load_tag(tag: str, categories: Optional[List[str]] = None
             ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Path]]:
    """加载一个 tag 的全部结果。

    Returns:
        scores  —— 用于 aggregate() 的 score 列表（含 category）
        details —— {case_id: detail}，翻转分析要用 query / 工具对比
        files   —— {category: 路径}，报告里要标出处
    """
    files = resolve_tag_files(tag, categories)
    if not files:
        raise FileNotFoundError(
            f"找不到 tag={tag} 的任何结果文件（在 {RESULTS_DIR} 下）"
        )

    scores: List[Dict[str, Any]] = []
    details: Dict[str, Dict[str, Any]] = {}
    for cat, path in files.items():
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw.get("details", raw if isinstance(raw, list) else [])
        for row in rows:
            score = dict(row.get("score") or {})
            score.setdefault("id", row.get("id"))
            score.setdefault("category", row.get("category", cat))
            score["category"] = cat           # 以文件名为准，避免历史文件缺字段
            scores.append(score)
            details[str(row.get("id"))] = row
    return scores, details, files


def list_tags() -> List[Tuple[str, int, str]]:
    """列出可用的 tag（按最近修改时间倒序）。"""
    seen: "OrderedDict[str, Tuple[int, float]]" = OrderedDict()
    for p in sorted(RESULTS_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        parts = p.stem.split("_")
        # 去掉末尾的类别名，剩下的就是 tag（可能带子名）
        if parts and parts[-1] in ("tool", "scope"):
            parts = parts[:-2] if len(parts) >= 2 and parts[-2] == "single" else (
                parts[:-1] if parts[-1] == "scope" else parts[:-2])
        tag = "_".join([x for x in p.stem.replace("_single_tool", "")
                        .replace("_multi_tool", "").replace("_out_of_scope", "").split("_")])
        if not tag:
            continue
        n, mt = seen.get(tag, (0, 0.0))
        seen[tag] = (n + 1, max(mt, p.stat().st_mtime))
    return sorted(
        [(t, n, time.strftime("%m-%d %H:%M", time.localtime(mt)))
         for t, (n, mt) in seen.items()],
        key=lambda x: x[2], reverse=True,
    )


# ──────────────────────────── 对比逻辑 ────────────────────────────

def _pass_of(score: Dict[str, Any]) -> Optional[bool]:
    """单条样本是否"过关"。

    有工具期望的样本看 tool_exact；越界拒答题看 refusal_correct。
    两者都没有则视为不参与判定（返回 None）。
    """
    v = score.get("tool_exact")
    if v is None:
        v = score.get("refusal_correct")
    if v is None:
        return None
    return float(v) >= 1.0


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.2f}%"


def _delta(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None:
        return "—"
    d = (b - a) * 100
    if abs(d) < 0.005:
        return "持平"
    return f"{d:+.2f}pp"


def compare(base_scores, cand_scores, base_details, cand_details) -> Dict[str, Any]:
    """对比两个 tag，返回分项指标 + 翻转样本。"""
    base_agg = aggregate(base_scores)
    cand_agg = aggregate(cand_scores)

    per_category: Dict[str, Any] = {}
    for cat in CATEGORIES:
        b = base_agg.get("by_category", {}).get(cat)
        c = cand_agg.get("by_category", {}).get(cat)
        if not b and not c:
            continue
        per_category[cat] = {"baseline": b, "candidate": c}

    # ── 翻转样本：以 case id 对齐，只比两边都有的样本 ──
    base_by_id = {str(s.get("id")): s for s in base_scores}
    cand_by_id = {str(s.get("id")): s for s in cand_scores}
    common = sorted(set(base_by_id) & set(cand_by_id))

    regressed, fixed = [], []
    for cid in common:
        pb = _pass_of(base_by_id[cid])
        pc = _pass_of(cand_by_id[cid])
        if pb is None or pc is None or pb == pc:
            continue
        entry = {
            "id": cid,
            "category": base_by_id[cid].get("category"),
            "query": (base_details.get(cid) or cand_details.get(cid) or {}).get("query", ""),
            "base_tools": (base_details.get(cid) or {}).get("predicted_tools"),
            "cand_tools": (cand_details.get(cid) or {}).get("predicted_tools"),
            "expected_tools": (base_details.get(cid) or {}).get("expected_tools"),
        }
        (regressed if pb and not pc else fixed).append(entry)

    return {
        "baseline": {"n": base_agg.get("n"), "metrics": base_agg},
        "candidate": {"n": cand_agg.get("n"), "metrics": cand_agg},
        "per_category": per_category,
        "common_cases": len(common),
        "regressed": regressed,
        "fixed": fixed,
    }


def render_console(cmp: Dict[str, Any], base_tag: str, cand_tag: str) -> str:
    lines: List[str] = []
    add = lines.append

    add("")
    add(f"  基线 {base_tag}  ({cmp['baseline']['n']} 条)"
        f"   →   候选 {cand_tag}  ({cmp['candidate']['n']} 条)")
    add(f"  可比样本 {cmp['common_cases']} 条")
    add("")
    add(f"  {'类别':<14}{'指标':<18}{'基线':>10}{'候选':>10}{'变化':>10}")
    add("  " + "─" * 62)

    def row(cat_label: str, key: str, b: Optional[float], c: Optional[float]):
        add(f"  {cat_label:<14}{key:<18}{_fmt(b):>10}{_fmt(c):>10}{_delta(b, c):>10}")

    # 全量
    bm = cmp["baseline"]["metrics"]
    cm = cmp["candidate"]["metrics"]
    for k in METRIC_KEYS:
        if bm.get(k) is None and cm.get(k) is None:
            continue
        row("合计", k, bm.get(k), cm.get(k))
    add("  " + "─" * 62)

    for cat, d in cmp["per_category"].items():
        b, c = d["baseline"] or {}, d["candidate"] or {}
        row(cat, "tool_exact", b.get("tool_exact"), c.get("tool_exact"))
        row(cat, "completed", b.get("completed"), c.get("completed"))
        if cat == "out_of_scope":
            row(cat, "refusal_correct", b.get("refusal_correct"), c.get("refusal_correct"))

    add("")
    add(f"  🔴 退步 {len(cmp['regressed'])} 条   🟢 修好 {len(cmp['fixed'])} 条")
    for e in cmp["regressed"][:10]:
        add(f"     [退步] {e['id']} {e['query'][:34]}")
        add(f"            期望 {e['expected_tools']}")
        add(f"            基线 {e['base_tools']}  →  候选 {e['cand_tools']}")
    if len(cmp["regressed"]) > 10:
        add(f"     …还有 {len(cmp['regressed']) - 10} 条，见 REGRESSION.md")
    for e in cmp["fixed"][:5]:
        add(f"     [修好] {e['id']} {e['query'][:34]}")
    add("")
    return "\n".join(lines)


def render_markdown(cmp: Dict[str, Any], base_tag: str, cand_tag: str) -> str:
    L: List[str] = []
    add = L.append
    add("# Agent 评测回归报告")
    add("")
    add(f"> 由 `bench/run_regression.py` 自动生成，**请勿手工编辑** —— 重跑即覆盖。")
    add(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    add("")
    add(f"- 基线：`{base_tag}`（{cmp['baseline']['n']} 条）")
    add(f"- 候选：`{cand_tag}`（{cmp['candidate']['n']} 条）")
    add(f"- 可比样本：{cmp['common_cases']} 条")
    add("")
    add("## 一、分项指标")
    add("")
    add("| 类别 | 指标 | 基线 | 候选 | 变化 |")
    add("|---|---|---|---|---|")

    bm, cm = cmp["baseline"]["metrics"], cmp["candidate"]["metrics"]
    for k in METRIC_KEYS:
        if bm.get(k) is None and cm.get(k) is None:
            continue
        add(f"| 合计 | `{k}` | {_fmt(bm.get(k))} | {_fmt(cm.get(k))} | {_delta(bm.get(k), cm.get(k))} |")
    for cat, d in cmp["per_category"].items():
        b, c = d["baseline"] or {}, d["candidate"] or {}
        for k in ("tool_exact", "completed", "refusal_correct"):
            if b.get(k) is None and c.get(k) is None:
                continue
            add(f"| {cat} | `{k}` | {_fmt(b.get(k))} | {_fmt(c.get(k))} | {_delta(b.get(k), c.get(k))} |")
    add("")

    add(f"## 二、退步样本（基线对 → 候选错）：{len(cmp['regressed'])} 条")
    add("")
    if not cmp["regressed"]:
        add("（无）")
    else:
        add("| 用例 | 类别 | 问句 | 期望工具 | 基线输出 | 候选输出 |")
        add("|---|---|---|---|---|---|")
        for e in cmp["regressed"]:
            add(f"| `{e['id']}` | {e['category']} | {e['query'][:40]} | "
                f"`{e['expected_tools']}` | `{e['base_tools']}` | `{e['cand_tools']}` |")
    add("")

    add(f"## 三、修好样本（基线错 → 候选对）：{len(cmp['fixed'])} 条")
    add("")
    if not cmp["fixed"]:
        add("（无）")
    else:
        add("| 用例 | 类别 | 问句 | 期望工具 | 基线输出 | 候选输出 |")
        add("|---|---|---|---|---|---|")
        for e in cmp["fixed"]:
            add(f"| `{e['id']}` | {e['category']} | {e['query'][:40]} | "
                f"`{e['expected_tools']}` | `{e['base_tools']}` | `{e['cand_tools']}` |")
    add("")
    add("---")
    add("")
    add("*口径：所有指标经 `app.eval.metrics.aggregate()`，`tool_exact` 只在有工具期望的"
        "样本上计算（越界拒答题看 `refusal_correct`）。*")
    return "\n".join(L) + "\n"


# ──────────────────────────── 跑评测 ────────────────────────────

def run_eval(tag: str, categories: List[str], limit: int, extra: List[str]) -> bool:
    """调 eval_agent.py 跑一遍，结果落到 {tag}_{category}.json。"""
    ok_all = True
    for cat in categories:
        out = RESULTS_DIR / f"{tag}_{cat}.json"
        cmd = [
            sys.executable, str(REPO / "bench" / "eval_agent.py"),
            "--category", cat,
            "--out-json", str(out),
        ]
        if limit > 0:
            cmd += ["--limit", str(limit)]
        else:
            cmd += ["--all"]
        cmd += extra
        print(f"\n>>> 运行 {cat}：{' '.join(cmd)}", flush=True)
        rc = subprocess.call(cmd, cwd=str(REPO))
        if rc != 0:
            print(f"!!! {cat} 退出码 {rc}（评测脚本自身失败，不是模型答错）", flush=True)
            ok_all = False
    return ok_all


# ──────────────────────────── main ────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Agent 评测回归：跑主集并与基线对比，输出涨跌与翻转样本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--baseline", default="", help="基线 tag，如 v19")
    ap.add_argument("--candidate", default="",
                    help="候选 tag；与 --run 二选一。都不传则用 --list 里最新的")
    ap.add_argument("--run", action="store_true", help="先跑一次评测（--tag 指定新 tag）")
    ap.add_argument("--tag", default="", help="--run 时新结果用的 tag")
    ap.add_argument("--limit", type=int, default=0, help="--run 时每类跑多少条（0=全量）")
    ap.add_argument("--category", default="", help="只比某一类")
    ap.add_argument("--report", default=str(REPO / "bench" / "REGRESSION.md"),
                    help="Markdown 报告输出路径")
    ap.add_argument("--no-report", action="store_true", help="只在控制台输出，不写文件")
    ap.add_argument("--eval-args", default="",
                    help="透传给 eval_agent.py 的额外参数（空格分隔，整体加引号）")
    ap.add_argument("--list", action="store_true", help="列出所有可用 tag 后退出")
    args = ap.parse_args()

    if args.list:
        print(f"\n可用 tag（{RESULTS_DIR}）：\n")
        print(f"  {'tag':<22}{'文件数':>6}   最近修改")
        print("  " + "─" * 44)
        for tag, n, mt in list_tags():
            print(f"  {tag:<22}{n:>6}   {mt}")
        print()
        return 0

    cats = [args.category] if args.category else list(CATEGORIES)

    # ── 1) 决定候选 tag ──
    cand_tag = args.candidate
    if args.run:
        if not args.tag:
            print("--run 需要同时给 --tag 指定新结果的 tag 名", file=sys.stderr)
            return 2
        cand_tag = args.tag
        extra = args.eval_args.split() if args.eval_args else []
        if not run_eval(cand_tag, cats, args.limit, extra):
            print("评测未全部成功，仍继续对比已产出的部分", file=sys.stderr)
    elif not cand_tag:
        tags = [t for t, _, _ in list_tags()]
        cand_tag = tags[0] if tags else ""
        print(f"未指定 --candidate，自动取最近修改的 tag：{cand_tag}")

    base_tag = args.baseline
    if not base_tag:
        print("必须指定 --baseline（或用 --list 查看可用 tag）", file=sys.stderr)
        return 2

    # ── 2) 加载 ──
    try:
        b_scores, b_details, b_files = load_tag(base_tag, cats)
        c_scores, c_details, c_files = load_tag(cand_tag, cats)
    except FileNotFoundError as exc:
        print(f"加载失败：{exc}", file=sys.stderr)
        return 2

    # ── 3) 对比 ──
    cmp = compare(b_scores, c_scores, b_details, c_details)
    print(render_console(cmp, base_tag, cand_tag))

    # ── 4) 报告 ──
    if not args.no_report:
        text = render_markdown(cmp, base_tag, cand_tag)
        text += "\n## 四、结果文件出处\n\n"
        for label, files in ((base_tag, b_files), (cand_tag, c_files)):
            for cat, p in sorted(files.items()):
                text += f"- `{label}` / {cat}：`{p.relative_to(REPO).as_posix()}`\n"
        Path(args.report).write_text(text, encoding="utf-8")
        print(f"  报告已写入 {args.report}")

    # 退出码：有退步样本返回 1（便于将来接 CI）
    return 1 if cmp["regressed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
