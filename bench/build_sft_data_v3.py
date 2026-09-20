"""v3 训练数据：把 v2 的两处缺陷修掉。

v2 的两处缺陷（都由 v21/v22 的评测结果定位出来）
------------------------------------------------

**缺陷 1：训练与部署的 prompt 不是字节一致。**
v2 的 `render_intent_prompt` / `render_planner_prompt` 是**自己重写**的一份，
还把工具定义换成了精简版（为省显存），`{{BBOX_HINT}}` 也留空。
而部署实际发出的是 `planner.txt` 全文 + `render_tools_section()` 完整版 +
真实 `build_view_context()` + RAG 上下文。
→ v3 直接**调用部署侧那几个函数**，不再有任何手工拼接，从构造上保证一致。

**缺陷 2：训练数据的工具分布与真实需求不一致。**
v2 的 990 条里，`get_dem_metadata` 出现 **0 次**（模型对该工具零认知），
`download_srtm` 只占 6.5%（评测集期望 20%）→ 模型系统性丢掉"先下载再计算"。
另外所有模板都带专业词（坡度 / 坡向 / 地貌…），模型学到的是**关键词匹配**
而不是**语义判断**。
→ v3 的做法：
   - 给每个工具**至少 6% 的覆盖**（消除零覆盖与严重欠覆盖）；
   - 补足"先取数据再计算"这条主流程；
   - **给每个工具都配上"不含任何专业词的改写问法"**，逼模型按语义判断；
   - 拆掉 `compute_slope` 与 `zonal_statistics` 的机械共现。

用法
----
    python bench/build_sft_data_v3.py            # 生成到 bench/sft_data_v3/
    python bench/build_sft_data_v3.py --check     # 只做一致性校验，不写文件
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.gazetteer import get_gazetteer  # noqa: E402
from app.agent.nodes.planner import (  # noqa: E402
    build_view_context,
    render_planner_prompt,
    render_tools_section,
)
from app.rag.context import retrieve_for_query  # noqa: E402

OUT_DIR = ROOT / "bench" / "sft_data_v3"
SEED = 20260920

# ---------------------------------------------------------------------------
# 链路模板：(模板, 工具链, 权重)
#
# 每条链都配了两种说法：
#   「术语版」= 含专业词（老用户、专业用户会这么说）
#   「口语版」= 不含任何专业词（新用户、普通业务人员会这么说）
# 两种都必须在训练集里，模型才不会退化成关键词匹配器。
# ---------------------------------------------------------------------------
_CHAINS: list[tuple[str, list[str], int]] = [
    # ---- compute_slope 坡度 ----
    ("算一下{place}的坡度", ["compute_slope"], 2),
    ("{place}的坡度是多少", ["compute_slope"], 2),
    ("{place}哪块地方最斜", ["compute_slope"], 3),          # 口语版，无关键词
    ("{place}哪一片站着最不稳", ["compute_slope"], 2),      # 口语版
    # ---- compute_aspect 坡向 ----
    ("{place}的坡向分布", ["compute_aspect"], 2),
    ("{place}的山坡主要朝向哪边", ["compute_aspect"], 2),
    ("{place}哪一面常年见不到太阳", ["compute_aspect"], 3),  # 口语版
    # ---- compute_curvature 曲率 / 山脊沟谷 ----
    ("{place}的曲率是多少", ["compute_curvature"], 2),
    ("看看{place}哪里是沟谷", ["compute_curvature"], 2),
    ("{place}的石头缝都集中在哪儿", ["compute_curvature"], 3),  # 口语版
    # ---- classify_geomorphons 地貌分类（默认） ----
    ("{place}属于什么地貌类型", ["classify_geomorphons"], 2),
    ("判断{place}的地貌类型", ["classify_geomorphons"], 2),
    ("{place}这一带到底算山还是算丘陵", ["classify_geomorphons"], 3),  # 口语版
    ("{place}的地表形态属于哪一类", ["classify_geomorphons"], 2),      # 口语版
    # ---- classify_terrain_onnx / rules（点名才用） ----
    ("用深度学习模型对{place}做地貌分类", ["classify_terrain_onnx"], 3),
    ("拿神经网络跑一下{place}的地表类型", ["classify_terrain_onnx"], 4),  # 口语版
    ("对{place}做快速地貌筛查", ["classify_terrain_rules"], 5),
    ("先粗略看看{place}属于哪种地表", ["classify_terrain_rules"], 4),    # 口语版
    # ---- get_dem_metadata（v2 里 0 覆盖，必须补） ----
    ("{place}的高程数据能不能用", ["get_dem_metadata"], 4),
    ("看看{place}这份高程数据的元信息", ["get_dem_metadata"], 3),
    ("{place}有没有现成的高程数据可以拿", ["get_dem_metadata"], 4),      # 口语版
    ("先确认一下{place}的数据资料都有什么", ["get_dem_metadata"], 3),    # 口语版
    # ---- download_srtm（v2 只占 6.5%，评测期望 20%） ----
    ("下载{place}的高程数据", ["download_srtm"], 4),
    ("把{place}的 SRTM 数据取回来", ["download_srtm"], 3),
    ("帮我把{place}的数据抓一份下来", ["download_srtm"], 4),             # 口语版
    ("先获取{place}的 SRTM 数据，再算坡度", ["download_srtm", "compute_slope"], 4),
    ("我没有{place}的数据，取回来之后算坡度", ["download_srtm", "compute_slope"], 4),
    ("{place}的数据还没下，先弄下来再看坡向", ["download_srtm", "compute_aspect"], 3),
    ("取回{place}的数据，然后看看地貌类型", ["download_srtm", "classify_geomorphons"], 3),
    # ---- compute_cost_surface 通行性 ----
    ("{place}的通行代价怎么样", ["compute_cost_surface"], 2),
    ("{place}的越野通行性怎么样", ["compute_cost_surface"], 2),
    ("{place}从这头走到那头费不费劲", ["compute_cost_surface"], 3),       # 口语版
    # ---- zonal_statistics 分区统计（单步，不带 compute_slope） ----
    ("统计{place}坡度在15度以下的比例", ["zonal_statistics"], 3),
    ("{place}有多少面积坡度超过25度", ["zonal_statistics"], 3),
    ("{place}有多少比例是缓地", ["zonal_statistics"], 3),                 # 口语版
    # ---- plan_route 路线（固定三步，但要降权：v2 里被 3 个模板 ×4 权重放大） ----
    ("规划一条穿越{place}的路线", ["compute_slope", "compute_cost_surface", "plan_route"], 3),
    ("从{place}的一头穿到另一头怎么走最省事",
     ["compute_slope", "compute_cost_surface", "plan_route"], 5),          # 口语版
    # ---- 多步（保留但降权，避免制造 slope+zonal 的伪相关） ----
    ("先算{place}的坡度再做地貌分类", ["compute_slope", "classify_geomorphons"], 2),
]

# 每个工具至少要占总样本的这个比例 —— 消除"零覆盖"与"严重欠覆盖"
MIN_RATIO = 0.06
TARGET_N = 1200


def place_pool():
    """地名词典里的人工条目（排除 source='eval'，避免与评测集同源泄漏）。"""
    gz = get_gazetteer()
    conn = gz._connect()  # noqa: SLF001
    try:
        rows = conn.execute(
            "SELECT name,west,south,east,north,source FROM gazetteer"
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], [float(r[1]), float(r[2]), float(r[3]), float(r[4])])
            for r in rows if r[5] != "eval"]


def tool_arguments(tool: str, bbox: list[float], res: int) -> dict:
    w, s, e, n = bbox
    if tool == "plan_route":
        return {"bbox": bbox, "start": [w, s], "end": [e, n]}
    if tool in ("download_srtm", "get_dem_metadata"):
        return {"bbox": bbox}
    if tool == "classify_terrain_onnx":
        return {"bbox": bbox, "resolution": 128}
    return {"bbox": bbox, "resolution": res}


def build_plan(query: str, bbox: list[float], tools: list[str], res: int = 128) -> dict:
    steps = []
    for i, t in enumerate(tools):
        steps.append({
            "tool": t,
            "intent": f"对 {query[:18]} 执行 {t}",
            "arguments": tool_arguments(t, bbox, res),
            "depends_on": [i - 1] if i > 0 else [],
        })
    return {
        "intent": "analysis",
        "bbox": bbox,
        "understanding": f"用户希望对该区域做地形分析：{query}",
        "steps": steps,
        "actions": [],
        "reply": "",
        "final_answer_hint": "基于工具返回的栅格与统计结果，给出结论性的回答。",
    }


def real_prompt(query: str, bbox: list[float]) -> str:
    """**完全按部署路径**渲染 planner 提示词。

    与 planner.py 里 plan_node 的调用逐字对应：
        view_ctx = build_view_context(state)
        rag_ctx  = retrieve_for_query(query) if use_rag else None
        prompt   = render_planner_prompt(query, bbox, history, rag_context=rag_ctx,
                                         view_context=view_ctx)
    这里 bbox/history 传 None/""，与评测时"用户没有直接把范围给到接口"的情形一致；
    范围信息通过 view_context 与词典注释进入提示词。
    """
    state = {"query": query, "view_context": {"bbox": bbox}}
    view_ctx = build_view_context(state)
    try:
        rag_ctx = retrieve_for_query(query)
    except Exception:  # noqa: BLE001 —— 检索失败不影响数据生成
        rag_ctx = None
    return render_planner_prompt(query, None, "", rag_context=rag_ctx,
                                 view_context=view_ctx)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--n", type=int, default=TARGET_N)
    args = ap.parse_args()

    random.seed(SEED)
    places = place_pool()
    print(f"地名词典人工条目：{len(places)}（已排除 source='eval'）")

    tools_section = render_tools_section()
    print(f"完整工具定义段：{len(tools_section)} 字符（v2 用的精简版约 200 字符）")

    pool: list[tuple[str, list[str]]] = []
    for tpl, tools, w in _CHAINS:
        pool.extend([(tpl, tools)] * w)

    rows, seen = [], set()
    guard = 0
    while len(rows) < args.n and guard < args.n * 60:
        guard += 1
        tpl, tools = random.choice(pool)
        name, bbox = random.choice(places)
        q = tpl.replace("{place}", name).strip()
        if q in seen:
            continue
        seen.add(q)
        rows.append({
            "messages": [
                {"role": "user", "content": real_prompt(q, bbox)},
                {"role": "assistant",
                 "content": json.dumps(build_plan(q, bbox, tools), ensure_ascii=False)},
            ]
        })

    # ---------- 覆盖率报告 ----------
    cnt = Counter()
    for r in rows:
        plan = json.loads(r["messages"][1]["content"])
        for s in plan["steps"]:
            cnt[s["tool"]] += 1
    n = len(rows)
    print(f"\n生成 {n} 条，工具覆盖率：")
    ok = True
    for t, c in cnt.most_common():
        ratio = c / n
        flag = "" if ratio >= MIN_RATIO else "  ⚠ 低于下限"
        if ratio < MIN_RATIO:
            ok = False
        print(f"  {t:<26}{c:>5}  {ratio:6.1%}{flag}")
    all_tools = {t for _, tools, _ in _CHAINS for t in tools}
    missing = all_tools - set(cnt)
    if missing:
        print(f"  ❌ 完全没覆盖到的工具：{sorted(missing)}")
        ok = False
    print(f"\n覆盖率下限 {MIN_RATIO:.0%}：{'✅ 全部达标' if ok else '❌ 有工具不达标'}")

    # ---------- 一致性校验 ----------
    probe = rows[0]["messages"][0]["content"]
    checks = {
        "含完整工具定义（非精简版）": tools_section[:80] in probe,
        "含 planner.txt 模板全文": "最终回答" in probe or "可用工具" in probe,
        "含当前视图段": "## 当前视图" in probe and "视野 bbox =" in probe,
        "含真实 bbox 提示（非空）": "没有直接指定研究区" in probe,
        "不含 v2 遗留的空 bbox 提示": "研究区范围已由调用方指定" not in probe,
    }
    print("\n一致性校验：")
    for k, v in checks.items():
        print(f"  {'✅' if v else '❌'} {k}")

    if args.check:
        return 0 if ok else 1

    d = OUT_DIR / "planner"
    d.mkdir(parents=True, exist_ok=True)
    cut = int(len(rows) * 0.9)
    (d / "train.json").write_text(json.dumps(rows[:cut], ensure_ascii=False), encoding="utf-8")
    (d / "eval.json").write_text(json.dumps(rows[cut:], ensure_ascii=False), encoding="utf-8")
    print(f"\n已写入 {d}：训练 {cut} / 留出 {len(rows) - cut}")
    print(f"提示词长度参考：首条 user 消息 {len(probe)} 字符")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
