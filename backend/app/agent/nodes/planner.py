"""规划节点：把用户问题拆解成工具调用序列。

健壮性设计（三层降级，保证 Agent 不会因为 LLM 不稳定而瘫痪）：

    第 1 层  LLM 正常返回合法 JSON          → 使用 LLM 计划
    第 2 层  LLM 返回非法 JSON / 工具名不存在 → 重新询问，最多 max_retries 次
    第 3 层  重试耗尽仍失败                  → 关键词启发式兜底计划

第 3 层是刻意的：地理分析的多数问题有强模式（"坡度"→compute_slope，
"路径/路线"→plan_route，"分类"→classify_*），用规则兜底能覆盖大部分场景。
这让系统在 LLM 不可用时仍是一个能干活的确定性工作流引擎。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..gazetteer import get_gazetteer
from ..memory import build_history_text
from ...rag.context import retrieve_for_query
from ..llm import (
    LLMClient,
    PLANNER_MAX_TOKENS,
    extract_json,
)
from ..state import (
    AgentState,
    STATUS_FAILED,
    STATUS_PLANNING,
    append_message,
    append_trace,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_BBOX = [102.9, 30.0, 104.9, 31.5]  # 成都及周边，作为兜底研究区

# 规划器可以输出的五种意图。以前只有「分析 / 拒答」两种，
# 结果模型被框成只会做地形分析 —— 问「这里是什么地方」都拒答（用户实测反馈）。
_VALID_INTENTS = {"analysis", "knowledge", "action", "chat", "refuse"}
# 不调工具、直接回答的意图
_NON_ANALYSIS = ("knowledge", "action", "chat", "refuse")
# 意图分类的输出上限：要装得下 intent + 一段 reply（能力介绍类回答约 200 字）
INTENT_MAX_TOKENS = 512

# 模型没给 reply 时的兜底话术（宁可给一句通用的话，也不要回空字符串）
_DEFAULT_REPLY = {
    "refuse": (
        "这个问题跟地球表面的地理分析没关系，我帮不上忙。\n\n"
        "我能做的是：算坡度坡向曲率、判地貌类型、评价通行性与规划路径、做分区统计，"
        "以及帮你把地图跳转到某个地方。"
    ),
    "chat": "我在。你可以让我算某片区域的坡度、判断地貌类型，或者跳转到某个地方看看。",
    "knowledge": "这一点我不太确定。你可以换个更具体的问法，或者让我直接分析某个区域的地形。",
    "action": "我需要一个明确的地点才能跳转，比如「跳转到海南省」。",
}


def render_tools_section() -> str:
    """把工具注册表渲染成提示词中的工具清单。"""
    from ...tools.registry import TOOL_REGISTRY

    lines = []
    for name, item in TOOL_REGISTRY.items():
        fn_schema = item["schema"]["function"]
        desc = fn_schema.get("description", "").strip().split("\n")[0]
        params = fn_schema.get("parameters", {})
        props = params.get("properties", {})
        required = set(params.get("required", []))
        arg_desc = []
        for pname, pinfo in props.items():
            mark = "*" if pname in required else ""
            ptype = pinfo.get("type", "any")
            arg_desc.append(f"{pname}{mark}: {ptype}")
        lines.append(f"- `{name}`: {desc}")
        lines.append(f"  参数: {', '.join(arg_desc)}（* 为必填）")
    return "\n".join(lines)


def render_planner_prompt(
    query: str,
    bbox: Optional[List[float]] = None,
    history: str = "",
    tools_section: Optional[str] = None,
    rag_context: Optional[str] = None,
    view_context: Optional[str] = None,
) -> str:
    """渲染 planner 提示词。

    用简单的字符串替换而非 str.format —— 提示词里含大量 JSON 示例，
    format 会把 { } 当占位符而崩溃。
    """
    template = (PROMPTS_DIR / "planner.txt").read_text(encoding="utf-8")
    if bbox:
        bbox_hint = f"研究区范围已由调用方指定（WGS84 [minLon, minLat, maxLon, maxLat]）：{list(bbox)}"
    else:
        bbox_hint = (
            "用户没有直接指定研究区（也可能是「这里 / 这片 / 当前视野」这类指代）。"
            "请从问题里的地名推断；推断不出来就看下面的「当前视图」。"
            "**两处都没有时不要自己编一个地方** —— 按提示词里的规则改成 chat 并请用户指明区域。"
        )
    return (
        template.replace("{{TOOLS}}", tools_section or render_tools_section())
        .replace("{{QUERY}}", query)
        .replace("{{BBOX_HINT}}", bbox_hint)
        .replace("{{VIEW_CONTEXT}}", view_context or "")
        .replace("{{RAG_CONTEXT}}", rag_context or "")
        .replace("{{HISTORY}}", history or "")
    )


def build_view_context(state: AgentState) -> str:
    """把「用户此刻在看哪」渲染成给模型看的文本。

    包含四样东西：
      1. 视野 bbox 与中心点；
      2. 跨度与覆盖面积（模型据此判断"这个范围能不能算"）；
      3. **中心点落到哪些地名里**（地名词典反查）；
      4. 视野是否过大。

    第 3 项是关键。4B 模型记不住"坐标 (120.5, 23.7) 在中国台湾省"这类对应关系，
    而用户偏偏最爱问「这里是什么地方」。以前的结果是它判定"越界"直接拒答；
    现在由词典把答案喂到嘴边，模型只负责组织语言。
    """
    view = state.get("view_context") or {}
    if not isinstance(view, dict):
        return ""
    bbox = view.get("bbox")
    if not bbox or len(bbox) < 4:
        return "（视图信息不可用，地图可能尚未就绪）"

    try:
        west, south, east, north = (float(v) for v in bbox[:4])
    except (TypeError, ValueError):
        return "（视图信息格式异常）"

    span_lon = abs(east - west)
    span_lat = abs(north - south)
    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0

    lines = [
        f"视野 bbox = [{west:.3f}, {south:.3f}, {east:.3f}, {north:.3f}]（西,南,东,北）",
        f"中心点 = ({center_lon:.3f}, {center_lat:.3f})，跨度 = {span_lon:.2f}° × {span_lat:.2f}°",
    ]

    area = view.get("area_km2")
    if area:
        try:
            lines.append(f"覆盖面积约 {float(area):,.0f} 平方公里")
        except (TypeError, ValueError):
            pass

    if span_lon > 20 or span_lat > 20:
        lines.append(
            "⚠ 视野很大（超过 20°）。用户若要求做地形分析，"
            "应先请他放大地图到具体区域或直接说出地名，不要自己挑一块地方开算。"
        )

    try:
        desc = get_gazetteer().describe_point(center_lon, center_lat)
        lines.append(f"视野中心落在地名词典收录的：{desc}")
    except Exception:  # noqa: BLE001 —— 反查失败不影响主流程
        pass

    return "\n".join(lines)


# 强分析信号词。命中即强制按 analysis 处理。
# ⚠ 用法：作为**安全网**兜住分类器的漏判，不是主要判断手段。
#   实测（2026-09-12）没有它时，分类器把「四姑娘山这一带的坡度是多少」
#   「贡嘎山哪里比较陡」判成了非分析，单工具类准确率从 100% 掉到 30%。
#   扩充依据：v15 评测残留的 10 条失败（朝向/阴坡/阳坡/山脊/沟谷/地貌/DEM 都没覆盖到）。
_FORCE_ANALYSIS_KEYWORDS = (
    # 地形因子（「朝向 / 阴坡 / 阳坡」也是坡向的说法）
    "坡度", "坡向", "朝向", "阴坡", "阳坡", "曲率",
    "山脊", "沟谷", "山谷线", "地形因子", "地形起伏", "地形",
    # 地貌分类（「地貌怎么分类」不含连写的"地貌分类"，故单列"地貌"）
    "地貌", "地形分类", "地形形态", "分类",
    # 通行性与路径
    "通行", "代价栅格", "路径", "路线", "越野", "穿越", "徒步",
    # 分区统计
    "分区统计", "面积占比", "多少面积", "多大面积",
    # 口语说法
    "陡", "好走", "能走", "爬升", "起伏",
    # 数据准备
    "dem", "DEM", "高程", "栅格", "srtm", "SRTM", "下载",
    # 分析动作
    "分析", "统计", "规划",
)

# 问「概念」的句式：命中则不做强制改判 —— 这类在问"是什么"，该交给 knowledge 回答。
_CONCEPT_PATTERNS = ("什么是", "是什么", "什么意思", "怎么算的", "咋算的", "的定义")

# 外星天体：提到这些就不是地球表面的分析了，走 refuse。
# ⚠ 实测翻车：安全网把「分析月球背面的地貌类型」「金星表面的坡度是多少」
#   强行拉去做分析（因为含"地貌""坡度"），越界拒答率掉了 5 个点。
_ALIEN_PATTERNS = (
    "火星", "月球", "金星", "木星", "土星", "冥王星", "水星", "天王", "海王",
    "外星", "外星球", "宇宙", "太空", "星系", "银河",
)


# 跟地理/地形沾边的词。用于一个**很窄**的兜底场景：
# 意图分类没给出结论时，如果这句话连一个地理相关词都没有，就别硬当分析任务处理。
# 实测「这首歌叫什么名字」在分类失败后被规划成了 compute_slope，纯属帮倒忙。
_GEO_SIGNAL = (
    "坡度", "坡向", "朝向", "阴坡", "阳坡", "曲率", "山脊", "沟谷", "起伏",
    "地形", "地貌", "高程", "海拔", "dem", "DEM", "栅格", "srtm", "SRTM",
    "路径", "路线", "通行", "代价", "越野", "穿越", "徒步", "导航",
    "分区统计", "统计", "分类", "占比", "面积",
    "区域", "范围", "这片", "这一片", "这块", "这里", "视野", "坐标",
    "经度", "纬度", "经纬度", "地图", "地名", "地方",
    "山", "峰", "谷", "河", "江", "湖", "平原", "盆地", "高原", "沙漠",
    "草原", "森林", "丘陵", "峡谷", "悬崖", "陡崖",
    "省", "市", "县", "区", "镇", "村", "岛", "半岛", "群岛",
)


def _has_geo_signal(query: str) -> bool:
    """句子里有没有任何跟地理/地形沾边的词。"""
    q = str(query or "")
    return any(k in q for k in _GEO_SIGNAL)


def _force_analysis(query: str) -> bool:
    """判断这句话是否**词面上明显是分析任务**。

    这是**安全网**，不是主要判断手段（主要判断交给小模型，泛化才靠它）。
    但它还有第二个作用 —— 见 plan_node：**命中时直接跳过意图分类**，
    让明显的分析题走和改造前完全一样的路径（一次规划调用，不掉准确率）。

    没有它代价太大：实测（2026-09-12）分类器把
    「四姑娘山这一带的坡度是多少」「贡嘎山哪里比较陡」判成了非分析，
    单工具类准确率从 100% 掉到 30% —— 用户看到的是"问了半天什么都没发生"。

    三种例外（不能强行拉去做计算）：
      1. 问概念的句式（「什么是坡度」「DEM 是什么」）→ knowledge；
      2. 外星天体（「月球背面的地貌」「金星表面的坡度」）→ refuse；
      3. 单独出现的"面积"（「圆的面积公式」）→ 由"面积占比/多少面积"精确匹配来兜。
    """
    q = str(query or "")
    if any(p in q for p in _ALIEN_PATTERNS):
        return False
    if any(p in q for p in _CONCEPT_PATTERNS):
        return False
    return any(k in q for k in _FORCE_ANALYSIS_KEYWORDS)


def classify_intent(state: AgentState, llm: LLMClient) -> Optional[Dict[str, Any]]:
    """第一段：用一段**很短的**提示词单独判断意图。

    为什么不让主规划器顺手判断（2026-09-12 实测教训）：
        把意图分类写进主 planner 提示词后，4B 模型**完全无视**它 ——
        提示词里那套详尽的工具选择规则（决策表 / 三条硬规则 / 负向清单）太强势，
        模型一旦进入"我是规划器"的角色，就不管问什么都去规划 compute_slope。
        用户的原话是「是个只会分析地形的傻子」。
        把意图章节挪到提示词末尾（最靠近问题处）也没用，仍然全部判成 analysis。

    所以拆成两次调用：先用只讲意图、**不含任何工具规则**的短提示词定方向，
    是 analysis 才交给主规划器。分类输出很短（约 20 token），代价可控。

    Returns:
        解析出的意图字典；分类失败时返回 None（调用方按原流程继续）。
    """
    try:
        template = (PROMPTS_DIR / "intent.txt").read_text(encoding="utf-8")
    except OSError:
        return None

    # 视图 + 历史焦点一起给它：分类器需要知道「这个地方」指的是哪儿，
    # 才能判断用户是要"跳过去"还是"分析那一带"。
    ctx = build_view_context(state) or "（未知）"
    focus_txt = str(state.get("focus_context") or "").strip()
    if focus_txt:
        ctx = ctx + "\n\n" + focus_txt
    prompt = (
        template.replace("{{VIEW_CONTEXT}}", ctx)
        .replace("{{QUERY}}", str(state.get("query") or ""))
    )

    # 把地名词典命中的精确 bbox 一并给它 —— 否则模型会自己编坐标：
    # 实测问「跳转到海南省」，它给出 [110, 20, 118, 25]（那是南海一大片），
    # 而词典里的海南省是 [108.6, 18.15, 111.05, 20.15]。差得很远。
    try:
        annotated = get_gazetteer().annotate(str(state.get("query") or ""))
        if annotated and annotated != state.get("query"):
            prompt += "\n\n" + annotated
    except Exception:  # noqa: BLE001
        pass
    # 重试一次：本机 RTX 2060 在持续负载后会热降频，C 层直接 abort，
    # 表现为这里偶发抛异常。实测「这首歌叫什么名字」就撞上一次 —— 分类失败后
    # 默认走分析，结果被规划成了 compute_slope。
    obj = None
    for _attempt in range(2):
        try:
            resp = llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=INTENT_MAX_TOKENS,
            )
        except Exception:  # noqa: BLE001 —— 分类失败不该让整轮对话挂掉
            continue
        obj = extract_json(resp.content or "")
        if isinstance(obj, dict):
            break

    if not isinstance(obj, dict):
        return None
    intent = str(obj.get("intent") or "").strip().lower()
    if intent not in _VALID_INTENTS:
        return None
    obj["intent"] = intent
    return obj


def finish_non_analysis(
    state: AgentState, cls: Dict[str, Any], trace: List[str]
) -> Dict[str, Any]:
    """非 analysis 意图：不调工具，直接把回答交给总结节点。"""
    intent = str(cls.get("intent") or "chat").strip().lower()
    if intent not in _NON_ANALYSIS:
        intent = "chat"

    actions = [
        a for a in (cls.get("actions") or [])
        if isinstance(a, dict) and a.get("type")
    ]
    # ⚠ 动作里的 bbox 一律以地名词典为准。
    # 4B 模型给坐标经常差得离谱（实测「跳转到海南省」编出 [110,20,118,25]，
    # 把整个南海都框进去了）。词典是确定性数据，能查到就覆盖。
    for a in actions:
        if a.get("type") != "flyTo":
            continue
        name = str(a.get("name") or "").strip()
        if not name:
            continue
        try:
            resolved = get_gazetteer().resolve_bbox(name)
        except Exception:  # noqa: BLE001
            resolved = None
        if resolved:
            a["bbox"] = list(resolved)

    if intent == "action" and not actions:
        # 说要操作地图却没给出动作 —— 降级成对话，别让用户干等
        intent = "chat"
        trace.append("意图=action 但未给出有效动作，降级为对话回答")

    reply = str(cls.get("reply") or "").strip()
    if not reply:
        # 4B 模型给不给 reply 不稳定。对地图操作这类结果确定的动作，
        # 与其用通用兜底话术，不如按实际执行的动作生成一句准确的。
        names = [str(a.get("name")) for a in actions if a.get("name")]
        if intent == "action" and names:
            reply = f"已为你跳转到{names[0]}。"
        else:
            reply = _DEFAULT_REPLY.get(intent, _DEFAULT_REPLY["chat"])

    label = {"knowledge": "地理常识问答", "action": "地图操作",
             "chat": "对话", "refuse": "越界拒答"}.get(intent, intent)
    trace.append(f"意图分类：{label} —— 不调用工具")

    return {
        "plan": [],
        "step_index": 0,
        "bbox": state.get("bbox"),
        "retry_count": 0,
        "refused": (intent == "refuse"),
        "intent": intent,
        "reply": reply,
        "actions": actions,
        "status": STATUS_PLANNING,
        "trace": trace,
        "messages": append_message(state, "assistant", f"意图判定：{label}"),
    }


def validate_plan(
    plan_obj: Dict[str, Any], bbox: Optional[List[float]]
) -> Optional[str]:
    """校验 LLM 产出的计划，返回错误描述；合法返回 None。

    唯一的例外是**显式拒答**：planner 判定问题越界时输出
    `{"steps": [], "refused": true}`，这是合法计划（"什么都不做"也是
    一种决策），不能当成格式错误去重试 —— 否则模型会被反复逼着
    为一个无法回答的问题编造工具调用。
    """
    steps = plan_obj.get("steps")

    if plan_obj.get("refused") is True:
        if steps:
            return "声明 refused 时 steps 必须为空"
        return None

    if not isinstance(steps, list) or not steps:
        return "计划中没有 steps 或 steps 为空"

    from ...tools.registry import TOOL_REGISTRY

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return f"第 {i} 步不是对象"
        tool = step.get("tool")
        if tool not in TOOL_REGISTRY:
            return f"第 {i} 步引用了不存在的工具：{tool!r}"
        args = step.get("arguments")
        if not isinstance(args, dict):
            return f"第 {i} 步缺少 arguments 对象"
    return None


def _normalize_arguments(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 常见参数写法归一化为工具期望的形式。

    实测中模型常犯的错：
        - 把 bbox 写成 bounds / extent / bbox_wsen
        - 分辨率写成字符串 "128"
        - 点位写成 {"lon": .., "lat": ..}
    """
    args = dict(arguments or {})

    for alias in ("bounds", "extent", "bbox_wsen", "region", "area"):
        if alias in args and "bbox" not in args:
            args["bbox"] = args.pop(alias)

    if "resolution" in args:
        try:
            args["resolution"] = int(float(args["resolution"]))
        except (TypeError, ValueError):
            args.pop("resolution")

    for key in ("start_point", "end_point"):
        val = args.get(key)
        if isinstance(val, dict):
            lon = val.get("lon", val.get("lng", val.get("longitude")))
            lat = val.get("lat", val.get("latitude"))
            if lon is not None and lat is not None:
                args[key] = [float(lon), float(lat)]
    return args


def heuristic_plan(query: str, bbox: Optional[List[float]]) -> Dict[str, Any]:
    """关键词启发式兜底计划 —— LLM 完全不可用时使用。

    覆盖本项目支持的核心意图。顺序按「先粗后细」：
    先算地形因子，再按需分类、规划、统计。
    """
    bbox = list(bbox) if bbox else DEFAULT_BBOX
    q = query.lower()
    steps: List[Dict[str, Any]] = []
    hints: List[str] = []

    # 关键词表是启发式兜底的全部依据，覆盖面直接决定 LLM 不可用时的可用性。
    # 收录的是真实问法，不是术语表 —— 例如用户会说"哪里可以修路"，
    # 而不是"请做一次基于成本表面的路径规划"。
    wants_route = any(k in q for k in (
        "路径", "路线", "规划", "修路", "选线", "布线", "穿越",
        "通达", "可达", "通行", "导航", "最短", "绕行",
        "route", "path", "corridor",
    ))
    wants_class = any(k in q for k in (
        "分类", "地貌", "形态", "识别", "判别", "类型",
        "classif", "geomorphon", "landform",
    ))
    wants_stats = any(k in q for k in (
        "多少", "占比", "面积", "比例", "统计", "适合", "可通行",
        "哪里", "哪些", "多大", "适宜", "选址", "评估", "可行性",
    ))
    wants_aspect = any(k in q for k in ("坡向", "朝向", "aspect"))
    wants_curv = any(k in q for k in ("曲率", "起伏", "curvature"))
    wants_slope = any(k in q for k in ("坡度", "陡", "缓", "slope", "倾斜"))

    res = 128 if wants_route or wants_class else 256
    base = {"bbox": bbox, "resolution": res}

    if wants_slope or not (wants_aspect or wants_curv or wants_class or wants_route):
        steps.append({
            "tool": "compute_slope",
            "intent": "计算研究区坡度分布",
            "arguments": base,
            "depends_on": [],
        })
    if wants_aspect:
        steps.append({
            "tool": "compute_aspect",
            "intent": "计算坡向分布",
            "arguments": base,
            "depends_on": [],
        })
    if wants_curv:
        steps.append({
            "tool": "compute_curvature",
            "intent": "计算曲率分布",
            "arguments": base,
            "depends_on": [],
        })
    if wants_class:
        steps.append({
            "tool": "classify_geomorphons",
            "intent": "对地形形态进行分类",
            "arguments": base,
            "depends_on": [],
        })
    if wants_stats:
        steps.append({
            "tool": "zonal_statistics",
            "intent": "按坡度分级统计面积占比",
            "arguments": {"bbox": bbox, "resolution": res, "metric": "slope"},
            "depends_on": [],
        })
    if wants_route:
        # 起终点未知时，取 bbox 内两个对角附近的点（避开边界像元）
        w, s, e, n = bbox
        mx, my = (e - w) * 0.15, (n - s) * 0.15
        steps.append({
            "tool": "plan_route",
            "intent": "在成本表面上规划路径",
            "arguments": {
                "bbox": bbox,
                "resolution": res,
                "start_point": [w + mx, s + my],
                "end_point": [e - mx, n - my],
            },
            "depends_on": [],
        })
        hints.append("路径规划的起终点由 bbox 自动推断（用户未明确给出），结果仅供参考")

    if not steps:
        steps.append({
            "tool": "compute_slope",
            "intent": "兜底：计算坡度",
            "arguments": base,
            "depends_on": [],
        })

    return {
        "bbox": bbox,
        "understanding": "（兜底计划）" + (hints[0] if hints else "由关键词规则推断用户意图"),
        "steps": steps,
        "final_answer_hint": "结合各步骤的统计摘要回答用户，并说明数据来源与局限",
    }


def plan_node(state: AgentState, llm: LLMClient) -> Dict[str, Any]:
    """规划节点。

    读取 state.query / state.bbox / state.messages，产出 state.plan。
    返回 patch 字典（覆盖式合并）。
    """
    query = state.get("query", "")
    bbox = state.get("bbox")
    max_retries = state.get("max_retries", 3)
    trace = list(state.get("trace") or [])

    # RAG 知识增强。**默认关闭**，因为：
    #   ① 评测要做 ±RAG 消融对比，开关必须在外部可控；
    #   ② 注入上下文会让 prompt 变长，进而抬高延迟，
    #      只有在知识真正影响工具选择时才值得付这个代价。
    # 由环境变量 GEOAGENT_RAG=1 开启，缺失索引时静默降级。
    use_rag = os.environ.get("GEOAGENT_RAG", "0").strip().lower() in {"1", "true", "yes", "on"}

    # 用户没给 bbox 时先查地名词典。
    # 4B 模型的权重里装不下精确的地理坐标，让它"从地名推断"只能猜
    # （实测 param_bbox 仅 0.35）；查表是确定性的，且对下面的
    # heuristic_plan 兜底路径同样生效。
    if bbox is None:
        resolved = get_gazetteer().resolve_bbox(query)
        if resolved:
            bbox = resolved
            trace.append(f"地名词典命中：bbox={list(bbox)}")

    history = ""
    msgs = state.get("messages") or []
    if len(msgs) > 1:
        # 消息流本身已由记忆层裁到最近若干轮（见 memory.store.trim_turns），
        # 这里再取尾部若干条并逐条截断 —— 4B 模型对长历史很不友好，
        # 与其塞满不如只留最近的（Lost-in-the-Middle：中段信息基本被忽略）。
        recent = msgs[:-1][-8:]
        history = "此前对话：\n" + build_history_text(recent, max_chars_per_turn=160)

    used_fallback = False
    errors: List[str] = []

    # 未配置 LLM 时直接走启发式规划，不要伪装成"LLM 失败"
    if llm is None:
        plan_obj = heuristic_plan(query, bbox)
        used_fallback = True
        trace.append("未配置 LLM，直接使用关键词启发式规划")
        return _finalize_plan(state, plan_obj, used_fallback, trace, errors)

    # —— 第一段：先定意图 ——
    # 注意顺序：词面明显是分析任务时**跳过分类器**，直接走完整规划。
    # 这样分析类问题走的是和改造前完全一样的路径（单次规划调用），
    # 工具链准确率不受影响；只有"看起来不像分析"的问题才花钱去问模型。
    if _force_analysis(query):
        trace.append("词面含强分析关键词 —— 直接进入工具规划（跳过意图分类）")
        cls = None
    else:
        cls = classify_intent(state, llm)

    if cls is None:
        # 分类器没给出结论。若这句话连一个地理相关词都没有，就别硬当分析任务 ——
        # 实测「这首歌叫什么名字」在这种情况下被规划成了 compute_slope。
        if not _has_geo_signal(query):
            trace.append("意图分类无结论且句子不含地理相关表述 —— 按越界处理")
            return finish_non_analysis(state, {"intent": "refuse", "reply": ""}, trace)
        trace.append("意图分类无结论，按分析任务继续")
    elif cls.get("intent") != "analysis":
        return finish_non_analysis(state, cls, trace)
    else:
        trace.append("意图分类：analysis —— 进入工具规划")

    rag_ctx = retrieve_for_query(query) if use_rag else None
    if rag_ctx:
        trace.append("已注入领域知识上下文（RAG）")

    # 把"用户当前在看哪"告诉模型。
    # 没有这段，模型回答不了「这里是什么地方」，也无法理解「跳转到海南省」之后
    # 该把视角放哪 —— 它只能靠猜或干脆拒答（这正是用户实测反馈的问题）。
    view_ctx = build_view_context(state)
    # 再叠上"这一轮对话在聊哪"（跨轮空间焦点）。
    # 两者可能不同：用户跳转到海南之后问「刚才那个山西的区域」，
    # 视图在海南、焦点在山西，缺了焦点这段模型必然理解错。
    focus_txt = str(state.get("focus_context") or "").strip()
    if focus_txt:
        view_ctx = (view_ctx + "\n\n" + focus_txt).strip() if view_ctx else focus_txt
    if view_ctx:
        trace.append("已注入当前视图" + ("与历史焦点上下文" if focus_txt else "上下文"))

    prompt = render_planner_prompt(
        query, bbox, history, rag_context=rag_ctx, view_context=view_ctx
    )
    plan_obj = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                # 必须显式给足：默认值是 tool_calling 场景标定的 384，
                # 而完整计划 JSON 的 p95 是 827 token，用 384 会截断 65%。
                max_tokens=PLANNER_MAX_TOKENS,
            )
        except Exception as exc:
            errors.append(f"LLM 调用失败：{exc}")
            break

        obj = extract_json(resp.content)
        if obj is None:
            errors.append(f"第 {attempt} 次：无法从输出解析 JSON（前 120 字符：{resp.content[:120]!r}）")
            continue

        err = validate_plan(obj, bbox)
        if err:
            errors.append(f"第 {attempt} 次：计划校验失败 —— {err}")
            # 把错误反馈给 LLM 重试（自我修正）
            prompt += f"\n\n上一次输出不合法：{err}。请修正后重新输出 JSON。"
            continue

        plan_obj = obj
        trace.append(f"LLM 规划成功（第 {attempt} 次尝试），共 {len(obj['steps'])} 步")
        break

    if plan_obj is None:
        plan_obj = heuristic_plan(query, bbox)
        used_fallback = True
        trace.append("LLM 规划失败，启用关键词启发式兜底计划：" + "；".join(errors[:2]))

    return _finalize_plan(state, plan_obj, used_fallback, trace, errors)


def _finalize_plan(
    state: AgentState,
    plan_obj: Dict[str, Any],
    used_fallback: bool,
    trace: List[str],
    errors: List[str],
) -> Dict[str, Any]:
    """归一化计划参数并生成 patch —— LLM 路径与兜底路径共用。"""
    # 归一化每一步的参数
    steps: List[Dict[str, Any]] = []
    for step in plan_obj.get("steps") or []:
        step = dict(step)
        step["arguments"] = _normalize_arguments(step["tool"], step.get("arguments", {}))
        # bbox 缺省时回填计划级 bbox
        if "bbox" not in step["arguments"] and plan_obj.get("bbox"):
            step["arguments"]["bbox"] = list(plan_obj["bbox"])
        step.setdefault("status", "pending")
        step.setdefault("depends_on", [])
        steps.append(step)

    plan_bbox = state.get("bbox") or plan_obj.get("bbox")

    # —— 意图分流 ——
    # 以前这里只有两种结局：要么规划出一串工具调用，要么判定"越界"拒答。
    # 模型因此被框成"只会做地形分析的傻子"：问「这里是什么地方」「你有什么功能」
    # 一律被拒答，让它跳转到某个省更是完全无法理解（用户实测反馈）。
    # 现在把意图摊开成五类，非分析类直接把回答交给总结节点。
    intent = str(plan_obj.get("intent") or "").strip().lower()
    if intent not in _VALID_INTENTS:
        # 兼容旧格式（没有 intent 字段）：按有没有步骤来推断
        if steps:
            intent = "analysis"
        elif plan_obj.get("refused"):
            intent = "refuse"
        else:
            intent = "chat"

    actions = [
        a for a in (plan_obj.get("actions") or [])
        if isinstance(a, dict) and a.get("type")
    ]
    if intent == "action" and not actions:
        # 说要操作地图却没给出动作 —— 退化成对话，别让用户干等
        intent = "chat"
        trace.append("意图=action 但未给出有效动作，降级为对话回答")

    reply = str(plan_obj.get("reply") or "").strip()

    if intent == "analysis":
        # 空计划 = 规划器主动拒答。这是一个**有效结论**，不是失败：
        # 走 route_after_plan → summarize，由总结节点向用户说明为什么答不了。
        refused = bool(plan_obj.get("refused")) or not steps
        if refused:
            trace.append("计划为空 —— 判定超出能力范围，进入拒答说明")
            plan_desc = (
                "该请求超出地理空间分析能力范围："
                + str(plan_obj.get("understanding") or "无法规划出有效步骤")
            )
        else:
            trace.append("计划步骤：" + " → ".join(s["tool"] for s in steps))
            plan_desc = (
                f"已制定计划（{'兜底规则' if used_fallback else 'LLM'}）："
                + "；".join(f"{i + 1}. {s['intent']}" for i, s in enumerate(steps))
            )
    else:
        steps = []           # 非分析意图一律不调工具
        refused = (intent == "refuse")
        label = {"knowledge": "地理常识问答", "action": "系统操作", "chat": "对话"}.get(intent, intent)
        trace.append(f"意图={intent}（{label}）—— 不调用工具")
        plan_desc = f"意图判定：{label}"

    patch: Dict[str, Any] = {
        "plan": steps,
        "step_index": 0,
        "bbox": list(plan_bbox) if plan_bbox else None,
        "retry_count": 0,
        "refused": refused,
        "intent": intent,
        "reply": reply,
        "actions": actions,
        "status": STATUS_PLANNING,
        "trace": trace,
        "messages": append_message(state, "assistant", plan_desc),
    }
    if plan_obj.get("final_answer_hint"):
        patch["final_answer_hint"] = plan_obj["final_answer_hint"]
    if plan_obj.get("understanding"):
        patch["understanding"] = plan_obj["understanding"]
    return patch
