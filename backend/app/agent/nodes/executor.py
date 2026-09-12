"""执行节点：调用工具并记录完整调用轨迹。

职责边界（刻意保持狭窄）：
    只负责「按参数调用工具 + 如实记录结果」，不做任何判断。
    结果好坏由 reflector 判定，重试与否由路由函数决定。

这样设计的原因：执行节点是所有失败模式的汇聚点（工具报错、超时、
参数非法、返回结构异常）。若在这里加判断逻辑，会和 reflector 的决策重叠，
出现两处互相矛盾的修复策略。让执行层保持"哑"的，调试时会非常轻松。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from ...tools.registry import dispatch
from ..result_view import build_step_view
from ..state import AgentState, STATUS_EXECUTING, ToolCallRecord, append_trace, current_step


def _summarize(result: Dict[str, Any]) -> str:
    """从工具结果中提取一句话摘要。"""
    if not result.get("success"):
        return f"失败（{result.get('error_type')}）：{result.get('error')}"
    data = result.get("data") or {}
    summary = data.get("summary")
    if summary:
        return str(summary)
    return f"成功（返回字段：{', '.join(list(data)[:6])}）"


# 这些工具的关键入参来自前序步骤的产出，而不是用户说的话。
# 没有这张表，"下载数据 → 用数据算坡度"这种最常见的两连就会断在半路。
_UPSTREAM_KEYS = {
    "compute_slope": ("dem_path",),
    "compute_aspect": ("dem_path",),
    "compute_curvature": ("dem_path",),
    "compute_cost_surface": ("dem_path",),
    "zonal_statistics": ("dem_path",),
    "classify_terrain_rules": ("dem_path",),
    "classify_geomorphons": ("dem_path",),
    "classify_terrain_onnx": ("dem_path",),
    "get_dem_metadata": ("dem_path",),
}

# 产出 dem_path 的工具（即"上游"）
_DEM_PRODUCER = "download_srtm"


def _inject_upstream(
    state: AgentState, tool: str, arguments: Dict[str, Any], trace: List[str]
) -> Dict[str, Any]:
    """把前序步骤的真实产出填进当前步骤的参数。

    问题背景：planner 是 LLM，它在规划第 2 步时并不知道第 1 步会产出什么文件名，
    于是会**编一个**（实测编出过 `SRTM_83_38.5_85_40.npz`），直接传给工具必然
    报"文件不存在"。真实路径只有工具跑完才知道，因此必须由执行层回填。

    覆盖策略：只要上游成功产出过，就以它为准。模型给的值一律不信 ——
    它不是故意编造，是结构上不可能提前知道。
    """
    keys = _UPSTREAM_KEYS.get(tool)
    if not keys:
        return arguments

    outputs = (state.get("step_outputs") or {}).get(_DEM_PRODUCER) or {}
    produced = outputs.get("dem_path")
    source_note = "上一步的产出"
    if not produced:
        # 没有显式下载过 DEM —— 用前端从 Cesium 自带地形采样出来的那一份。
        # 这是「用户没提供数据时不要糊弄成合成地形」的落点：
        # 有了它，工具算出的是真实地表的高程，而不是一张构造出来的正弦曲面。
        produced = state.get("session_dem_path")
        source_note = "前端 Cesium 地形采样"
    if not produced:
        # 既没有下载过、前端也没采到地形 —— 至少把模型编的假路径清掉，
        # 让它安静地落到默认数据源上，而不是拿一个不存在的文件去报错。
        return _drop_fake_paths(arguments, keys, trace)

    for k in keys:
        old = arguments.get(k)
        if old != produced:
            arguments = dict(arguments)
            arguments[k] = produced
            if old:
                trace.append(
                    f"  ↑ 用{source_note}替换了模型给出的 {k}"
                    f"（{old} → {produced}）"
                )
            else:
                trace.append(f"  ↑ 填入{source_note} {k}={produced}")
    return _drop_fake_paths(arguments, keys, trace)


def _drop_fake_paths(
    arguments: Dict[str, Any], keys: Any, trace: List[str]
) -> Dict[str, Any]:
    """去掉模型凭空编出来的、磁盘上并不存在的文件路径。

    规划器偶尔会自己造一个 dem_path（实测编出过 `local_cache`、`auto` 这种词），
    工具拿着它必然报「DEM 文件不存在」。但用户本来就没提供文件，
    正确行为是**当作没给**，让工具走默认数据源，而不是让整步失败。
    """
    for k in keys:
        v = arguments.get(k)
        if isinstance(v, str) and v and not Path(v).exists():
            arguments = dict(arguments)
            arguments.pop(k, None)
            trace.append(f"  ⚠ 模型给出的 {k}={v} 在磁盘上不存在，已忽略并改用默认数据源")
    return arguments


def execute_node(state: AgentState) -> Dict[str, Any]:
    """执行当前步骤的工具调用。

    Returns:
        patch：更新 tool_calls / last_result / trace / plan / step_outputs
    """
    trace = list(state.get("trace") or [])
    step = current_step(state)

    if step is None:
        trace.append("执行节点被调用但没有待执行步骤 —— 计划可能已执行完毕")
        return {"trace": trace}

    tool = step.get("tool", "")
    arguments = dict(step.get("arguments") or {})
    arguments = _inject_upstream(state, tool, arguments, trace)
    attempt = state.get("retry_count", 0) + 1
    idx = state.get("step_index", 0)

    trace.append(
        f"执行第 {idx + 1} 步：{tool}（第 {attempt} 次尝试）"
    )

    started = time.perf_counter()
    try:
        result = dispatch(tool, arguments)
    except Exception as exc:
        # 工具层契约是"绝不抛异常"，但第三方依赖（rasterio/dem_stitcher）可能抛。
        # 这里兜底，保证 Agent 不会因工具崩溃而中断。
        result = {
            "tool": tool,
            "success": False,
            "error": f"工具抛出未捕获异常：{type(exc).__name__}: {exc}",
            "error_type": "computation_failed",
            "retryable": False,
            "duration_ms": 0.0,
        }
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    success = bool(result.get("success"))
    summary = _summarize(result)

    # 如果这一步吃的是前端 Cesium 地形采样来的 DEM，就把结果里的数据来源改写清楚。
    # 工具层只知道"这是真实 DEM"，但界面上要如实告诉用户这份高程是哪来的。
    session_dem = state.get("session_dem_path")
    if success and session_dem and arguments.get("dem_path") == session_dem:
        data_ref = result.get("data")
        if isinstance(data_ref, dict) and data_ref.get("dem_source") == "real_dem":
            data_ref["dem_source"] = "cesium_terrain"

    # 为前端裁剪一份结构化结果（统计值 / 分类构成 / 路径指标 / 产物 URL）。
    # 以前只保留 tool/success/duration，工具算出来的东西一概丢弃 —— 前端拿不到数据，
    # 自然只能显示一句文字总结。
    frontend_view: Dict[str, Any] = {}
    if success:
        frontend_view = build_step_view(tool, result.get("data") or {})

    record = ToolCallRecord(
        step=idx,
        tool=tool,
        arguments=arguments,
        success=success,
        error_type=result.get("error_type"),
        error=result.get("error"),
        duration_ms=round(elapsed_ms, 2),
        summary=summary,
        attempt=attempt,
        result=frontend_view,
    )

    # 更新计划中该步的状态
    plan: List[Dict[str, Any]] = [dict(s) for s in (state.get("plan") or [])]
    if 0 <= idx < len(plan):
        plan[idx]["status"] = "done" if success else "failed"

    trace.append(
        f"  → {'成功' if success else '失败'}，耗时 {elapsed_ms:.0f} ms：{summary[:120]}"
    )

    # 记录本步产出，供后续步骤取用（只存标量，避免把整块栅格塞进状态里）
    step_outputs: Dict[str, Dict[str, Any]] = {
        k: dict(v) for k, v in (state.get("step_outputs") or {}).items()
    }
    if success:
        data = result.get("data") or {}
        captured = {
            k: v for k, v in data.items()
            if k in ("dem_path",) and isinstance(v, (str, int, float))
        }
        if captured:
            merged = dict(step_outputs.get(tool) or {})
            merged.update(captured)
            step_outputs[tool] = merged
            trace.append(f"  ↓ 记录产出供后续步骤使用：{captured}")

    return {
        "tool_calls": list(state.get("tool_calls") or []) + [record],
        "last_result": result,
        "plan": plan,
        "step_outputs": step_outputs,
        "status": STATUS_EXECUTING,
        "trace": trace,
    }
