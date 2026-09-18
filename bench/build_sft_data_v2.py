"""构造与【部署形态完全对齐】的 SFT 数据（v2）。

## 为什么要重做（v1 的三个不一致）

v1 数据（`build_sft_data.py`）训出来的 adapter，在主评测集上把 tool_exact
从 98.75% 拉低到 32.5%。逐项比对后发现**训练形态和部署形态三处都不一样**：

| 维度 | v1 训练数据 | 真实部署（backend/app/agent/nodes/planner.py） |
|---|---|---|
| role | `system` 放指令 | **`user`** 放整段 prompt（`llm.chat([{"role":"user",...}])`） |
| 模板 | 三行简写指令 | `prompts/intent.txt` / `prompts/planner.txt` **全文** |
| 输出 | `{intent, understanding, reply}` | planner 侧是**完整 plan JSON**（含 `bbox` + `steps`） |

模型学的是「简写 system → 短 JSON」，部署时收到的是「长 user prompt → 要长 JSON」，
两边对不上；而 LoRA 是全程生效的，于是把底座的规划能力一起带偏了。

**v2 把三者全部对齐到部署形态。**

## 产出

  sft_data_v2/planner.json  —— 只训 planner 形态（方案 a）
  sft_data_v2/mixed.json    —— planner + intent 混合（方案 b）

## 防泄漏

地名词典里 `source='eval'` 的 20 条是从评测集反向灌进去的，**一律排除**，
只用 `source='manual'` 的条目，避免又一轮"训练集含评测数据"。

用法：
    python bench/build_sft_data_v2.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.gazetteer import get_gazetteer  # noqa: E402
from app.agent.nodes.planner import render_tools_section  # noqa: E402

OUT_DIR = ROOT / "bench" / "sft_data_v2"
SEED = 20260917
PROMPTS = ROOT / "backend" / "app" / "agent" / "prompts"

# ---------------------------------------------------------------- 链路模板
# (模板, 工具链, 权重)。链路划分严格照 planner.txt 的 A–H 表。
CHAINS: list[tuple[str, list[str], int]] = [
    # C 行：要坡度 → compute_slope 单步
    ("算一下{place}的坡度", ["compute_slope"], 4),
    ("{place}的坡度是多少", ["compute_slope"], 3),
    ("分析{place}的坡度分布", ["compute_slope"], 2),
    # D 行：要坡向
    ("{place}的坡向分布", ["compute_aspect"], 4),
    ("算一下{place}的坡向", ["compute_aspect"], 2),
    ("{place}的山坡主要朝向哪边", ["compute_aspect"], 2),
    # E 行：曲率 / 山脊沟谷
    ("{place}的曲率是多少", ["compute_curvature"], 3),
    ("{place}哪里是山脊", ["compute_curvature"], 2),
    ("看看{place}哪里是沟谷", ["compute_curvature"], 2),
    # F 行：地貌分类（默认 geomorphons；点名深度学习才用 onnx）
    ("{place}属于什么地貌类型", ["classify_geomorphons"], 5),
    ("判断{place}的地貌类型", ["classify_geomorphons"], 3),
    ("{place}的地形形态分类", ["classify_geomorphons"], 2),
    ("用深度学习模型对{place}做地貌分类", ["classify_terrain_onnx"], 2),
    ("对{place}做快速地貌筛查", ["classify_terrain_rules"], 2),
    # G 行：统计数字
    ("统计{place}坡度在15度以下的比例", ["zonal_statistics"], 4),
    ("{place}有多少面积坡度超过25度", ["zonal_statistics"], 3),
    ("{place}的分区统计", ["zonal_statistics"], 2),
    # B 行：通行性（不要前置 compute_slope）
    ("{place}的通行代价怎么样", ["compute_cost_surface"], 4),
    ("{place}哪里好走", ["compute_cost_surface"], 3),
    ("{place}的越野通行性怎么样", ["compute_cost_surface"], 2),
    # A 行：要一条路线（固定三步）
    ("规划一条穿越{place}的路线", ["compute_slope", "compute_cost_surface", "plan_route"], 4),
    ("{place}从东到西怎么走比较好", ["compute_slope", "compute_cost_surface", "plan_route"], 3),
    ("帮我找一条穿越{place}的最优路径", ["compute_slope", "compute_cost_surface", "plan_route"], 2),
    # H 行：明确要下载数据
    ("下载{place}的高程数据", ["download_srtm", "compute_slope"], 3),
    ("先获取{place}的 SRTM 数据，再算坡度", ["download_srtm", "compute_slope"], 2),
    # 多步：用户把「算坡度」说成独立动作
    ("先算{place}的坡度再做地貌分类", ["compute_slope", "classify_geomorphons"], 4),
    ("算一下{place}的坡度，然后统计有多少面积能走", ["compute_slope", "zonal_statistics"], 3),
]

# 每个工具的参数（除 bbox / resolution 外的固定部分）
RES_OF = {"classify_terrain_onnx": 128}   # 该工具不能超过 128


def tool_arguments(tool: str, bbox: list[float], res: int) -> dict:
    """按工具类型给出参数。plan_route 需要起终点。"""
    w, s, e, n = bbox
    if tool == "plan_route":
        return {"bbox": bbox, "start": [w, s], "end": [e, n]}
    if tool == "download_srtm":
        return {"bbox": bbox}
    if tool == "get_dem_metadata":
        return {"bbox": bbox}
    if tool.startswith("classify_"):
        return {"bbox": bbox, "resolution": RES_OF.get(tool, res)}
    if tool == "zonal_statistics":
        return {"bbox": bbox, "resolution": res}
    return {"bbox": bbox, "resolution": res}


def build_plan(query: str, bbox: list[float], tools: list[str], res: int = 128) -> dict:
    """生成 planner.txt 规定格式的完整 plan JSON。"""
    w, s, e, n = bbox
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


def slim_tools_section() -> str:
    """精简版工具定义。

    为什么要精简：完整版 `render_tools_section()` 会展开每个工具的完整参数
    schema，整段约 2500 token，导致 planner 样本的序列长度达到 ~4300 token。
    实测在 4090（24GB）上，无论 bf16 还是 4-bit + 梯度检查点都会 OOM
    （激活内存约 16GB）。精简后整段约 200 token，序列降到 ~1800，能放下。

    保留的是**结构**：同样的"## 可用工具"标题、同样的工具名与参数名顺序，
    只是把描述压成一句话。工具本身模型是认识的，训练重点是"输出 plan JSON 的格式"。
    """
    from app.tools.registry import list_tools

    lines = ["## 可用工具（**仅在 intent = analysis 时使用**）", ""]
    for t in list_tools():
        name = t.get("name")
        desc = str(t.get("description") or "").split("（")[0].strip("。. ")
        args = {
            "get_dem_metadata": "bbox",
            "download_srtm": "bbox",
            "compute_slope": "bbox, resolution",
            "compute_aspect": "bbox, resolution",
            "compute_curvature": "bbox, resolution",
            "compute_cost_surface": "bbox, resolution",
            "plan_route": "bbox, start, end",
            "classify_terrain_rules": "bbox, resolution",
            "classify_geomorphons": "bbox, resolution",
            "classify_terrain_onnx": "bbox, resolution(<=128)",
            "zonal_statistics": "bbox, resolution",
        }.get(name, "bbox")
        lines.append(f"- `{name}`({args}): {desc[:40]}")
    return "\n".join(lines)


def render_intent_prompt(query: str, view_context: str, gaz: str) -> str:
    tpl = (PROMPTS / "intent.txt").read_text(encoding="utf-8")
    p = tpl.replace("{{VIEW_CONTEXT}}", view_context).replace("{{QUERY}}", query)
    if gaz:
        p += "\n\n" + gaz
    return p


def render_planner_prompt(query: str, view_context: str, tools_section: str) -> str:
    tpl = (PROMPTS / "planner.txt").read_text(encoding="utf-8")
    return (
        tpl.replace("{{TOOLS}}", tools_section)
        .replace("{{VIEW_CONTEXT}}", view_context)
        .replace("{{QUERY}}", query)
        .replace("{{BBOX_HINT}}", "")
        .replace("{{RAG_CONTEXT}}", "")
        .replace("{{HISTORY}}", "")
    )


def view_ctx_of(bbox: list[float], name: str) -> str:
    w, s, e, n = bbox
    return (
        f"当前视野范围：西 {w}，南 {s}，东 {e}，北 {n}\n"
        f"中心点：{(w + e) / 2:.2f}, {(s + n) / 2:.2f}\n"
        f"视口内主要地名：{name}"
    )


def main() -> None:
    random.seed(SEED)

    gz = get_gazetteer()
    conn = gz._connect()  # noqa: SLF001 —— 直接读表以拿到 source 字段
    try:
        rows = conn.execute(
            "SELECT name,west,south,east,north,source FROM gazetteer"
        ).fetchall()
    finally:
        conn.close()

    # 只用人工整理的地名：source='eval' 的来源就是评测集，用了会造成泄漏
    manual = [(r[0], [float(r[1]), float(r[2]), float(r[3]), float(r[4])])
              for r in rows if r[5] != "eval"]
    print(f"词典总条目 {len(rows)}，其中人工条目 {len(manual)}（已排除评测集来源）")

    tools_section = slim_tools_section()

    pool: list[str] = []
    for tpl, tools, w in CHAINS:
        pool.extend([(tpl, tools)] * w)

    planner_rows, intent_rows = [], []
    seen: set[str] = set()
    guard = 0
    target = 1100

    while len(planner_rows) < target and guard < target * 40:
        guard += 1
        tpl, tools = random.choice(pool)
        name, bbox = random.choice(manual)
        q = tpl.replace("{place}", name).strip()
        if q in seen:
            continue
        seen.add(q)

        vctx = view_ctx_of(bbox, name)
        gaz = f"地名词典：{name} 的精确范围是 [{bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]}]"

        # 方案 a 的样本：user = 完整 planner prompt，assistant = 完整 plan JSON
        planner_rows.append({
            "messages": [
                {"role": "user",
                 "content": render_planner_prompt(q, vctx, tools_section)},
                {"role": "assistant",
                 "content": json.dumps(build_plan(q, bbox, tools),
                                       ensure_ascii=False)},
            ]
        })

        # 方案 b 需要的另一半：intent 形态样本
        intent_rows.append({
            "messages": [
                {"role": "user",
                 "content": render_intent_prompt(q, vctx, gaz)},
                {"role": "assistant",
                 "content": json.dumps(
                     {"intent": "analysis",
                      "reply": "",
                      "actions": [],
                      "understanding": f"用户在要求做地形分析：{q}"},
                     ensure_ascii=False)},
            ]
        })

    random.shuffle(planner_rows)
    random.shuffle(intent_rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def dump(dirname: str, rows: list) -> None:
        """写成 <dir>/train.json + eval.json，方便训练脚本用 --data-dir 直接指。"""
        d = OUT_DIR / dirname
        d.mkdir(parents=True, exist_ok=True)
        cut = int(len(rows) * 0.9)
        (d / "train.json").write_text(
            json.dumps(rows[:cut], ensure_ascii=False), encoding="utf-8")
        (d / "eval.json").write_text(
            json.dumps(rows[cut:], ensure_ascii=False), encoding="utf-8")
        print(f"  {dirname:<10} 训练 {cut} / 留出 {len(rows) - cut}")

    # 方案 a：纯 planner 形态
    dump("planner", planner_rows)

    # 方案 b：planner + intent 混合（各半）
    n = min(len(planner_rows), len(intent_rows))
    mixed = planner_rows[:n] + intent_rows[:n]
    random.shuffle(mixed)
    dump("mixed", mixed)

    print(f"\n输出目录: {OUT_DIR}")

    # 打印一条样例，便于人工核对形态
    one = planner_rows[0]["messages"]
    print("\n=== 样例（截断显示）===")
    print("[user 前 200 字]\n" + one[0]["content"][:200])
    print("\n[assistant 前 380 字]\n" + one[1]["content"][:380])


if __name__ == "__main__":
    main()
