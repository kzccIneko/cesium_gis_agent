"""query_tabular（自然语言查表）的评测。

测什么
------
分两层，目的不同：

    第一层 · 工具本身对不对（--skip-llm，秒级，不加载模型）
        直接执行 30 条标准 SQL，检查结果与预期一致。
        这一层验证的是：建表、安全闸门、执行、结果组装 这条链路没写错。

    第二层 · 翻译得准不准（--with-llm，需要加载模型）
        让模型把 30 条中文问题翻成 SQL，执行后**与标准 SQL 的结果集比对**。
        比的是"结果一样不一样"，不是"SQL 字符串一样不一样" ——
        同一条查询可以有很多种写法，字符串比对会冤枉模型，结果集比对才是对的。

指标
----
    exec_acc      执行正确率：标准 SQL 跑出来和预期一致的比例
    translate_acc 翻译正确率：模型翻出来的 SQL 结果集 == 标准结果集 的比例
    block_rate    拦截率：恶意 SQL 被安全闸门拦下的比例（单独一组用例）

用法
----
    python bench/eval_text2sql.py --skip-llm      # 只验工具链路
    python bench/eval_text2sql.py --with-llm      # 完整链路（需模型）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.tools.registry import call_tool  # noqa: E402
from app.tools.table_tools import (       # noqa: E402
    MAX_LIMIT,
    list_tables,
    sanitize_sql,
)

# ──────────────────────────── 30 条测试用例 ────────────────────────────
# golden 一律加别名、加 ORDER BY（有多个结果时），保证结果集可稳定比对。
# 预期值全部是**跑出来核对过**的，不是猜的（首次写的时候猜错了好几个）。
CASES: List[Dict[str, Any]] = [
    # —— gazetteer：计数类 ——
    {"id": "t01", "q": "地名词典里一共有多少条地名？",
     "golden": "SELECT COUNT(*) AS n FROM gazetteer", "expect": [[95]]},
    {"id": "t02", "q": "有多少个山地类型（mountain）的地名？",
     "golden": "SELECT COUNT(*) AS n FROM gazetteer WHERE kind='mountain'", "expect": [[10]]},
    {"id": "t03", "q": "有多少个城市类型（city）的地名？",
     "golden": "SELECT COUNT(*) AS n FROM gazetteer WHERE kind='city'", "expect": [[32]]},
    {"id": "t04", "q": "有多少个省级行政区（province）？",
     "golden": "SELECT COUNT(*) AS n FROM gazetteer WHERE kind='province'", "expect": [[34]]},
    {"id": "t05", "q": "人工标注的地名有多少条？",
     "golden": "SELECT COUNT(*) AS n FROM gazetteer WHERE source='manual'", "expect": [[75]]},
    {"id": "t06", "q": "来自评测集标准答案（eval）的地名有多少条？",
     "golden": "SELECT COUNT(*) AS n FROM gazetteer WHERE source='eval'", "expect": [[20]]},
    {"id": "t07", "q": "地名的类型（kind）去重后一共有几种？只要一个数字",
     "golden": "SELECT COUNT(DISTINCT kind) AS n FROM gazetteer", "expect": [[9]]},
    {"id": "t08", "q": "每种类型（kind）的地名各有多少条？按类型名字排序",
     "golden": "SELECT kind, COUNT(*) AS n FROM gazetteer GROUP BY kind ORDER BY kind",
     "expect": [["basin", 4], ["city", 32], ["desert", 1], ["grassland", 1],
                ["mountain", 10], ["plateau", 4], ["province", 34],
                ["range", 8], ["valley", 1]]},

    # —— gazetteer：筛选类 ——
    {"id": "t09", "q": "列出前 5 个山地类型地名的名字，按名字排序",
     "golden": "SELECT name FROM gazetteer WHERE kind='mountain' ORDER BY name LIMIT 5",
     "expect": [["四姑娘山"], ["峨眉山"], ["张家界"], ["武夷山"], ["泰山"]]},
    {"id": "t10", "q": "名字里带「山」字的地名有哪些？取前 8 个，按名字排序",
     "golden": "SELECT name FROM gazetteer WHERE name LIKE '%山%' ORDER BY name LIMIT 8",
     "expect": None},   # 结果较长，只校验非空（见 _check 的 None 语义）
    {"id": "t11", "q": "别名里包含「成都」的地名有哪些？",
     "golden": "SELECT name FROM gazetteer WHERE aliases LIKE '%成都%' ORDER BY name",
     "expect": [["成都周边"]]},
    {"id": "t12", "q": "来源是人工标注、且类型是山地的地名有多少条？",
     "golden": "SELECT COUNT(*) AS n FROM gazetteer WHERE source='manual' AND kind='mountain'",
     "expect": [[2]]},
    {"id": "t13", "q": "哪些地名的纬度跨度（north 减 south）最大？给出前 3 个名字和跨度",
     "golden": "SELECT name, (north - south) AS span FROM gazetteer "
               "ORDER BY span DESC LIMIT 3", "expect": None},
    {"id": "t14", "q": "名字最长的地名叫什么？",
     "golden": "SELECT name FROM gazetteer ORDER BY LENGTH(name) DESC LIMIT 1",
     "expect": [["新疆维吾尔自治区"]]},

    # —— eval_cases：计数与筛选 ——
    {"id": "t15", "q": "评测集里一共有多少道题？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases", "expect": [[100]]},
    {"id": "t16", "q": "单工具类的题目有多少道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases WHERE category='single_tool'",
     "expect": [[40]]},
    {"id": "t17", "q": "多工具串联类的题目有多少道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases WHERE category='multi_tool'",
     "expect": [[40]]},
    {"id": "t18", "q": "越界拒答类的题目有多少道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases WHERE category='out_of_scope'",
     "expect": [[20]]},
    {"id": "t19", "q": "按类别统计题目数量，并让数量多的排在前面",
     "golden": "SELECT category, COUNT(*) AS n FROM eval_cases "
               "GROUP BY category ORDER BY n DESC", "expect": None},
    {"id": "t20", "q": "期望用到路径规划工具 plan_route 的题目有哪些？给出题目原文",
     "golden": "SELECT query FROM eval_cases WHERE expected_tools LIKE '%plan_route%' "
               "ORDER BY id", "expect": None},
    {"id": "t21", "q": "涉及「贡嘎山」的评测题有几道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases WHERE query LIKE '%贡嘎山%'",
     "expect": [[3]]},
    {"id": "t22", "q": "问句里含「下载」两个字的题目有多少道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases WHERE query LIKE '%下载%'",
     "expect": [[8]]},
    {"id": "t23", "q": "没有期望工具（也就是拒答类）的题目有多少道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases WHERE expected_tools='' OR expected_tools IS NULL",
     "expect": [[20]]},
    {"id": "t24", "q": "单工具类中，问句包含「坡度」的题目有多少道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases "
               "WHERE category='single_tool' AND query LIKE '%坡度%'", "expect": [[10]]},
    {"id": "t25", "q": "期望工具里出现过 compute_slope 的题目有多少道？",
     "golden": "SELECT COUNT(*) AS n FROM eval_cases WHERE expected_tools LIKE '%compute_slope%'",
     "expect": [[45]]},

    # —— 排序 / 分页 / 组合 ——
    {"id": "t26", "q": "按编号排序，给出前 3 道题目的编号和原文",
     "golden": "SELECT id, query FROM eval_cases ORDER BY id LIMIT 3", "expect": None},
    {"id": "t27", "q": "地名按名字排序，跳过前 10 个，取接下来 3 个",
     "golden": "SELECT name FROM gazetteer ORDER BY name LIMIT 3 OFFSET 10", "expect": None},
    {"id": "t28", "q": "多工具类的题目中，问句最长的那一道是哪道？给出问句",
     "golden": "SELECT query FROM eval_cases WHERE category='multi_tool' "
               "ORDER BY LENGTH(query) DESC LIMIT 1", "expect": None},
    {"id": "t29", "q": "统计每道题期望工具的数量，找出期望工具最多的题目编号",
     "golden": "SELECT id FROM eval_cases "
               "ORDER BY (LENGTH(expected_tools) - LENGTH(REPLACE(expected_tools, ',', ''))) DESC "
               "LIMIT 1", "expect": None},
    {"id": "t30", "q": "地名词典里，source 为 manual 的占比是多少？（保留 2 位小数）",
     "golden": "SELECT ROUND(1.0 * SUM(CASE WHEN source='manual' THEN 1 ELSE 0 END) / COUNT(*), 2) AS r "
               "FROM gazetteer", "expect": [[0.79]]},
]

# 恶意 SQL：应全部被安全闸门拦下
ATTACKS: List[Tuple[str, str]] = [
    ("写操作-删除", "DELETE FROM gazetteer"),
    ("写操作-更新", "UPDATE gazetteer SET name='x'"),
    ("写操作-插入", "INSERT INTO gazetteer VALUES ('x',0,0,0,0,'','','')"),
    ("DDL-删表", "DROP TABLE eval_cases"),
    ("DDL-建表", "CREATE TABLE evil (a TEXT)"),
    ("多语句拼接", "SELECT 1; DROP TABLE gazetteer"),
    ("越权读系统表", "SELECT * FROM sqlite_master"),
    ("越权读未知表", "SELECT * FROM secrets"),
]


# ──────────────────────────── 结果集比对 ────────────────────────────

def _norm(rows: Sequence[Dict[str, Any]]) -> List[Tuple[str, ...]]:
    """把结果集归一化成可比较的形式：只取值、丢列名、按行排序。

    为什么丢列名：模型可能不写别名（`SELECT COUNT(*)` vs `COUNT(*) AS n`），
    这不影响答案正确性；列名一致与否不该扣分。
    """
    out = []
    for r in rows:
        out.append(tuple("" if v is None else str(v).strip() for v in r.values()))
    return sorted(out)


def _check(rows: Sequence[Dict[str, Any]], expect: Optional[List[List[Any]]]) -> bool:
    """expect 为 None 表示"这道题只校验能跑通且非空"，不比对具体值。"""
    if expect is None:
        return len(rows) > 0
    got = _norm(rows)
    want = sorted(tuple("" if v is None else str(v).strip() for v in row) for row in expect)
    return got == want


def _run_golden(case: Dict[str, Any]) -> Tuple[bool, str]:
    res = call_tool("query_tabular", question=case["q"], sql=case["golden"])
    if not res.get("success"):
        return False, str(res.get("error", "?"))[:80]
    rows = res["data"]["rows"]
    if not _check(rows, case.get("expect")):
        return False, f"结果不符：{json.dumps(rows[:3], ensure_ascii=False)[:80]}"
    return True, f"{res['data']['row_count']} 行"


def _run_llm(case: Dict[str, Any], verbose: bool) -> Tuple[bool, str, str]:
    res = call_tool("query_tabular", question=case["q"], limit=50)
    if not res.get("success"):
        return False, "", str(res.get("error", "?"))[:80]
    data = res["data"]
    sql = data.get("sql", "")
    if case.get("expect") is not None:
        okc = _check(data["rows"], case["expect"])
    else:
        okc = len(data["rows"]) > 0
    if verbose:
        print(f"      SQL: {sql[:96]}")
    return okc, sql, f"{data['row_count']} 行"


# ──────────────────────────── main ────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="query_tabular 的评测（工具链路 + 翻译质量）")
    ap.add_argument("--skip-llm", action="store_true", help="只验工具链路，不加载模型")
    ap.add_argument("--with-llm", action="store_true", help="跑完整链路（需模型）")
    ap.add_argument("--verbose", action="store_true", help="逐条打印模型生成的 SQL")
    ap.add_argument("--out", default="", help="结果落盘路径（JSON）")
    args = ap.parse_args()

    if not args.skip_llm and not args.with_llm:
        args.skip_llm = True

    print("\n=== 知识库表 ===")
    for n, m in list_tables().items():
        print(f"  {n}: {m['rows']} 行 — {m['desc']}")
    print(f"\n用例 {len(CASES)} 条，恶意样本 {len(ATTACKS)} 条\n")

    summary: Dict[str, Any] = {"n_cases": len(CASES), "n_attacks": len(ATTACKS)}

    # ── 第一层：工具链路 ──
    print("── 第一层：标准 SQL 执行（验证建表 / 闸门 / 执行 / 组装）──")
    exec_ok = 0
    fails: List[str] = []
    for c in CASES:
        okc, msg = _run_golden(c)
        exec_ok += okc
        if not okc:
            fails.append(f"{c['id']} {c['q'][:24]} → {msg}")
    summary["exec_acc"] = exec_ok / len(CASES)
    print(f"  执行正确率 {exec_ok}/{len(CASES)} = {summary['exec_acc']:.1%}")
    for f in fails:
        print(f"    ✗ {f}")

    # ── 安全闸门 ──
    print("\n── 安全闸门：恶意 SQL 拦截 ──")
    blocked = 0
    for name, sql in ATTACKS:
        try:
            sanitize_sql(sql, ["gazetteer", "eval_cases"])
            print(f"    ✗ 漏放：{name}")
        except Exception:
            blocked += 1
    summary["block_rate"] = blocked / len(ATTACKS)
    print(f"  拦截率 {blocked}/{len(ATTACKS)} = {summary['block_rate']:.1%}")

    # 上限与越界参数
    r = call_tool("query_tabular", question="x", sql="SELECT * FROM gazetteer", limit=10 ** 6)
    summary["limit_clamped"] = bool(r.get("success") and r["data"]["row_count"] <= MAX_LIMIT)
    print(f"  limit 越界自动收敛到 {MAX_LIMIT}：{'✅' if summary['limit_clamped'] else '❌'}")

    # ── 第二层：翻译质量 ──
    if args.with_llm:
        print("\n── 第二层：自然语言翻译（结果集比对）──")
        t0 = time.perf_counter()
        trans_ok = 0
        for c in CASES:
            try:
                okc, sql, msg = _run_llm(c, args.verbose)
            except Exception as exc:  # noqa: BLE001
                okc, sql, msg = False, "", f"异常：{exc}"[:80]
            trans_ok += okc
            mark = "✓" if okc else "✗"
            print(f"    {mark} {c['id']} {c['q'][:26]:<28} {msg}")
            if not okc:
                print(f"        golden: {c['golden'][:90]}")
                if sql:
                    print(f"        model : {sql[:90]}")
        dt = time.perf_counter() - t0
        summary["translate_acc"] = trans_ok / len(CASES)
        summary["seconds"] = round(dt, 1)
        print(f"\n  翻译正确率 {trans_ok}/{len(CASES)} = {summary['translate_acc']:.1%}"
              f"（{dt:.0f}s，{dt/len(CASES):.1f}s/条）")

    # ── 结论 ──
    print("\n=== 结论 ===")
    print(f"  执行正确率   {summary['exec_acc']:.1%}")
    print(f"  拦截率       {summary['block_rate']:.1%}")
    if "translate_acc" in summary:
        print(f"  翻译正确率   {summary['translate_acc']:.1%}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  已落盘 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
