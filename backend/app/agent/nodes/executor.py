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
from typing import Any, Dict, List

from ...tools.registry import dispatch
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


def execute_node(state: AgentState) -> Dict[str, Any]:
    """执行当前步骤的工具调用。

    Returns:
        patch：更新 tool_calls / last_result / trace / plan（步骤状态）
    """
    trace = list(state.get("trace") or [])
    step = current_step(state)

    if step is None:
        trace.append("执行节点被调用但没有待执行步骤 —— 计划可能已执行完毕")
        return {"trace": trace}

    tool = step.get("tool", "")
    arguments = dict(step.get("arguments") or {})
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
    )

    # 更新计划中该步的状态
    plan: List[Dict[str, Any]] = [dict(s) for s in (state.get("plan") or [])]
    if 0 <= idx < len(plan):
        plan[idx]["status"] = "done" if success else "failed"

    trace.append(
        f"  → {'成功' if success else '失败'}，耗时 {elapsed_ms:.0f} ms：{summary[:120]}"
    )

    return {
        "tool_calls": list(state.get("tool_calls") or []) + [record],
        "last_result": result,
        "plan": plan,
        "status": STATUS_EXECUTING,
        "trace": trace,
    }
