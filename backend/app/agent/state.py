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
    result: Dict[str, Any]  # 为前端裁剪过的结构化结果（见 result_view.build_step_view）
                            # ⚠ 曾长期缺失，导致工具算好的统计值到不了前端，只能吐文字


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
    session_dem_path: Optional[str]       # 本次会话的默认 DEM（前端从 Cesium 地形采样写成的 GeoTIFF）
    view_context: Dict[str, Any]          # 前端上报的当前视图（视野 bbox / 中心 / 面积 / 是否全球）
    focus_context: str                    # 跨轮空间焦点文本（上轮 bbox/地名/工具），来自记忆层
    intent: str                           # 规划器判定的意图：analysis | knowledge | action | chat | refuse
    reply: str                            # 非 analysis 意图下直接给用户看的回答
    actions: List[Dict[str, Any]]         # 系统动作（如 flyTo 跳转区域），由前端执行

    # ---- 对话 ----
    messages: List[Dict[str, Any]]        # [{role, content}]，覆盖式更新

    # ---- 计划 ----
    plan: List[PlanStep]
    step_index: int

    # ---- 执行 ----
    tool_calls: List[ToolCallRecord]
    last_result: Optional[Dict[str, Any]]  # 最近一次 ToolResult.to_dict()
    # 前序步骤的关键产出，按工具名索引，供后续步骤取用。
    # 为什么需要它：planner 是 LLM，它会**编造** dem_path 之类的文件名
    # （实测编出过 "SRTM_83_38.5_85_40.npz"），直接传给工具必然失败。
    # 真实路径只有工具执行完才知道，必须由执行层回填。
    step_outputs: Dict[str, Dict[str, Any]]

    # ---- 反思 ----
    reflection: Optional[Dict[str, Any]]
    retry_count: int
    max_retries: int

    # ---- 输出 ----
    final_answer: Optional[str]
    status: str
    trace: List[str]                      # 人类可读的执行轨迹
    refused: bool                         # planner 判定问题越界、主动拒答

    # ---- 规划副产物 ----
    understanding: Optional[str]          # planner 对问题的理解
    final_answer_hint: Optional[str]      # planner 给出的回答组织建议


def create_initial_state(
    query: str,
    bbox: Optional[List[float]] = None,
    session_id: str = "default",
    max_retries: int = DEFAULT_MAX_RETRIES,
    session_dem_path: Optional[str] = None,
    view_context: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    focus_context: str = "",
) -> AgentState:
    """构造初始状态。

    Args:
        query: 用户自然语言问题
        bbox: 可选的研究区范围 [minLon, minLat, maxLon, maxLat]
        session_id: 会话 ID，相同 ID 可从持久化存储恢复
        max_retries: 单步最大重试次数
        session_dem_path: 本次会话的默认 DEM 路径。
            前端从 Cesium 自带地形（Cesium World Terrain）采样高程后写成的 GeoTIFF；
            用户没有自带 DEM 时用它，避免落到"合成地形"上算出没有意义的数字。
        view_context: 前端当前视图信息（视野 bbox / 中心点 / 面积 / 是否全球）。
            用于回答「这里是什么地方」以及支撑「跳转到某地」这类系统操作。
        history: 本会话此前几轮的消息（`[{role, content}]`，时间正序，**不含本轮**）。
            由记忆层从 SQLite 取出，只给最近若干轮 —— 规划器据此理解「这个地方」
            「再算一次」这类跨轮指代。
        focus_context: 跨轮空间焦点的文本描述（上一轮用的 bbox / 地名 / 工具 / 原话）。
            与 view_context 互补：view 是"用户此刻在看哪"，focus 是"这一轮对话在聊哪"，
            两者可能不同（用户跳到海南后问「刚才那个山西的区域」就是这种情况）。
    """
    # 历史在前、当前问题在最后。这一点很关键：
    # 注意力实测呈 U 型（Lost-in-the-Middle），末尾位置最强，
    # 而当前问题恰恰是必须被准确理解的那条。
    msgs: List[Dict[str, Any]] = [dict(m) for m in (history or [])]
    msgs.append({"role": "user", "content": query})

    return AgentState(
        query=query,
        bbox=list(bbox) if bbox else None,
        session_id=session_id,
        session_dem_path=session_dem_path,
        view_context=dict(view_context) if view_context else {},
        focus_context=str(focus_context or ""),
        intent="",
        reply="",
        actions=[],
        messages=msgs,
        plan=[],
        step_index=0,
        tool_calls=[],
        step_outputs={},
        last_result=None,
        reflection=None,
        retry_count=0,
        max_retries=max_retries,
        final_answer=None,
        status=STATUS_PLANNING,
        refused=False,
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
