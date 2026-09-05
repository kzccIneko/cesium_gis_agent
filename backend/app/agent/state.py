"""GeoAgent 状态定义。

设计约束（三条，决定了后面所有代码的写法）：

1. **100% 可 JSON 序列化**
   SqliteSaver 要把 state 写进数据库，任何 numpy 数组 / 栅格对象都不能进 state。
   栅格一律以 artifact 路径引用，数值指标以 dict 内联。

2. **节点返回「完整替换值」而非增量**
   这是为了 LangGraph 与内置 runner 行为一致。若节点返回增量
   （如 messages = [new_msg]），两种运行时的合并语义会分叉：
   LangGraph 默认覆盖、add_messages reducer 追加、自研 runner 需要自定义规则。
   改为「读旧值 → 拼新列表 → 返回完整列表」，所有运行时语义统一为覆盖。

3. **失败信息结构化**
   reflector 需要依据 error_type 决策重试还是放弃，因此错误必须保留受控枚举，
   不能退化成一句自然语言。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

# Agent 生命周期状态
STATUS_PLANNING = "planning"
STATUS_EXECUTING = "executing"
STATUS_REFLECTING = "reflecting"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# 单步默认重试上限（计划要求 3 次）
DEFAULT_MAX_RETRIES = 3


class PlanStep(TypedDict, total=False):
    """计划中的单步 —— 一次工具调用。"""

    tool: str            # 工具名，必须在 TOOL_REGISTRY 中
    intent: str          # 这一步的意图（人类可读，用于 trace 与调试）
    arguments: Dict[str, Any]  # 工具参数
    status: str          # pending / running / done / failed / skipped
    depends_on: List[int]      # 依赖的前序步骤索引（用于参数占位符解析）


class ToolCallRecord(TypedDict, total=False):
    """一次工具调用的完整记录 —— 写入 trace，用于复盘与评测。"""

    step: int
    tool: str
    arguments: Dict[str, Any]
    success: bool
    error_type: Optional[str]
    error: Optional[str]
    duration_ms: float
    summary: str         # 结果的一句话摘要
    attempt: int         # 第几次尝试（1 表示首次）


class AgentState(TypedDict, total=False):
    """Agent 全局状态。

    字段分组：
        输入     query / bbox / session_id
        对话     messages
        计划     plan / step_index
        执行     tool_calls / last_result
        反思     reflection / retry_count / max_retries
        输出     final_answer / status / trace
    """

    # ---- 输入 ----
    query: str
    bbox: Optional[List[float]]          # [minLon, minLat, maxLon, maxLat]，WGS84
    session_id: str                       # 会话标识，用于持久化与多轮恢复

    # ---- 对话 ----
    messages: List[Dict[str, Any]]        # [{role, content}]，覆盖式更新

    # ---- 计划 ----
    plan: List[PlanStep]
    step_index: int

    # ---- 执行 ----
    tool_calls: List[ToolCallRecord]
    last_result: Optional[Dict[str, Any]]  # 最近一次 ToolResult.to_dict()

    # ---- 反思 ----
    reflection: Optional[Dict[str, Any]]
    retry_count: int
    max_retries: int

    # ---- 输出 ----
    final_answer: Optional[str]
    status: str
    trace: List[str]                      # 人类可读的执行轨迹

    # ---- 规划副产物 ----
    understanding: Optional[str]          # planner 对问题的理解
    final_answer_hint: Optional[str]      # planner 给出的回答组织建议


def create_initial_state(
    query: str,
    bbox: Optional[List[float]] = None,
    session_id: str = "default",
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> AgentState:
    """构造初始状态。

    Args:
        query: 用户自然语言问题
        bbox: 可选的研究区范围 [minLon, minLat, maxLon, maxLat]
        session_id: 会话 ID，相同 ID 可从持久化存储恢复
        max_retries: 单步最大重试次数
    """
    return AgentState(
        query=query,
        bbox=list(bbox) if bbox else None,
        session_id=session_id,
        messages=[{"role": "user", "content": query}],
        plan=[],
        step_index=0,
        tool_calls=[],
        last_result=None,
        reflection=None,
        retry_count=0,
        max_retries=max_retries,
        final_answer=None,
        status=STATUS_PLANNING,
        trace=[f"收到问题：{query}"],
    )


def merge_patch(state: AgentState, patch: Optional[Dict[str, Any]]) -> AgentState:
    """把节点返回的 patch 合并回状态（覆盖语义）。

    单独抽出这个函数是为了让两种运行时（LangGraph / 内置 runner）
    共用同一套合并逻辑，避免行为分叉。
    """
    if not patch:
        return state
    new_state = dict(state)
    new_state.update(patch)
    return AgentState(**new_state)


def current_step(state: AgentState) -> Optional[PlanStep]:
    """取当前待执行的步骤，越界返回 None。"""
    plan = state.get("plan") or []
    idx = state.get("step_index", 0)
    if 0 <= idx < len(plan):
        return plan[idx]
    return None


def append_trace(state: AgentState, message: str) -> List[str]:
    """返回追加一条记录后的 trace 列表（覆盖式更新用）。"""
    return list(state.get("trace") or []) + [message]


def append_message(
    state: AgentState, role: str, content: str
) -> List[Dict[str, Any]]:
    """返回追加一条消息后的 messages 列表（覆盖式更新用）。"""
    return list(state.get("messages") or []) + [{"role": role, "content": content}]


def append_tool_call(
    state: AgentState, record: ToolCallRecord
) -> List[ToolCallRecord]:
    """返回追加一条工具调用记录后的列表。"""
    return list(state.get("tool_calls") or []) + [record]


def plan_remaining(state: AgentState) -> int:
    """还剩多少步没执行。"""
    plan = state.get("plan") or []
    return max(0, len(plan) - state.get("step_index", 0))
