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
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..gazetteer import get_gazetteer
from ..llm import LLMClient, extract_json
from ..state import (
    AgentState,
    STATUS_FAILED,
    STATUS_PLANNING,
    append_message,
    append_trace,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_BBOX = [102.9, 30.0, 104.9, 31.5]  # 成都及周边，作为兜底研究区


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
) -> str:
    """渲染 planner 提示词。

    用简单的字符串替换而非 str.format —— 提示词里含大量 JSON 示例，
    format 会把 { } 当占位符而崩溃。
    """
    template = (PROMPTS_DIR / "planner.txt").read_text(encoding="utf-8")
    if bbox:
        bbox_hint = f"研究区范围已指定（WGS84 [minLon, minLat, maxLon, maxLat]）：{list(bbox)}"
    else:
        bbox_hint = (
            "用户未指定研究区。你必须从问题中的地名推断合理范围并填入 bbox；"
            f"若完全无法推断，使用默认范围 {DEFAULT_BBOX} 并在 understanding 中说明这一假设。"
        )
    return (
        template.replace("{{TOOLS}}", tools_section or render_tools_section())
        .replace("{{QUERY}}", query)
        .replace("{{BBOX_HINT}}", bbox_hint)
        .replace("{{HISTORY}}", history or "")
    )


def validate_plan(
    plan_obj: Dict[str, Any], bbox: Optional[List[float]]
) -> Optional[str]:
    """校验 LLM 产出的计划，返回错误描述；合法返回 None。"""
    steps = plan_obj.get("steps")
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
        recent = msgs[:-1][-4:]
        history = "此前对话：\n" + "\n".join(
            f"  {m.get('role')}: {str(m.get('content'))[:200]}" for m in recent
        )

    used_fallback = False
    errors: List[str] = []

    # 未配置 LLM 时直接走启发式规划，不要伪装成"LLM 失败"
    if llm is None:
        plan_obj = heuristic_plan(query, bbox)
        used_fallback = True
        trace.append("未配置 LLM，直接使用关键词启发式规划")
        return _finalize_plan(state, plan_obj, used_fallback, trace, errors)

    prompt = render_planner_prompt(query, bbox, history)
    plan_obj = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = llm.chat([{"role": "user", "content": prompt}], temperature=0.0)
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
    for step in plan_obj["steps"]:
        step = dict(step)
        step["arguments"] = _normalize_arguments(step["tool"], step.get("arguments", {}))
        # bbox 缺省时回填计划级 bbox
        if "bbox" not in step["arguments"] and plan_obj.get("bbox"):
            step["arguments"]["bbox"] = list(plan_obj["bbox"])
        step.setdefault("status", "pending")
        step.setdefault("depends_on", [])
        steps.append(step)

    plan_bbox = state.get("bbox") or plan_obj.get("bbox")
    trace.append(
        "计划步骤：" + " → ".join(s["tool"] for s in steps)
    )

    patch: Dict[str, Any] = {
        "plan": steps,
        "step_index": 0,
        "bbox": list(plan_bbox) if plan_bbox else None,
        "retry_count": 0,
        "status": STATUS_PLANNING,
        "trace": trace,
        "messages": append_message(
            state, "assistant",
            f"已制定计划（{'兜底规则' if used_fallback else 'LLM'}）："
            + "；".join(f"{i + 1}. {s['intent']}" for i, s in enumerate(steps)),
        ),
    }
    if plan_obj.get("final_answer_hint"):
        patch["final_answer_hint"] = plan_obj["final_answer_hint"]
    if plan_obj.get("understanding"):
        patch["understanding"] = plan_obj["understanding"]
    return patch
