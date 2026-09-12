"""Agent 运行入口。

双运行时设计：

    优先  LangGraph   —— 具备持久化、流式输出、可视化等能力，对外说"基于 LangGraph"
    降级  内置循环    —— LangGraph 缺失/版本不兼容时自动接管

两者**共享同一套节点函数与路由函数**（见 routing.py），因此行为一致，
不存在"换了个运行时结果不一样"的问题。降级路径不是摆设：
部署到没有 langgraph 的环境（如给面试官的演示包）时它会自动生效。
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional

from .graph import DEFAULT_RECURSION_LIMIT, build_graph
from .llm import LLMClient
from .nodes.executor import execute_node
from .nodes.planner import plan_node
from .nodes.reflector import reflect_node
from .nodes.summarizer import summarize_node
from .routing import (
    NODE_EXECUTE,
    NODE_PLAN,
    NODE_REFLECT,
    NODE_SUMMARIZE,
    route_after_execute,
    route_after_plan,
    route_after_reflect,
)
from .state import AgentState, create_initial_state, merge_patch


def _run_without_langgraph(
    state: AgentState,
    llm: Optional[LLMClient] = None,
    max_steps: int = DEFAULT_RECURSION_LIMIT,
) -> AgentState:
    """内置执行循环 —— 与 LangGraph 图结构等价的手动调度。"""
    cur = state
    node = NODE_PLAN

    for _ in range(max_steps):
        if node == NODE_PLAN:
            patch = plan_node(cur, llm)
            next_node = route_after_plan(merge_patch(cur, patch))
        elif node == NODE_EXECUTE:
            patch = execute_node(cur)
            next_node = route_after_execute(merge_patch(cur, patch))
        elif node == NODE_REFLECT:
            patch = reflect_node(cur, llm)
            next_after = route_after_reflect(merge_patch(cur, patch))
            next_node = next_after
        elif node == NODE_SUMMARIZE:
            patch = summarize_node(cur, llm)
            cur = merge_patch(cur, patch)
            break
        else:
            break

        cur = merge_patch(cur, patch)
        node = next_node

    return cur


def run_agent(
    query: str,
    bbox: Optional[List[float]] = None,
    llm: Optional[LLMClient] = None,
    session_id: str = "default",
    checkpointer: Optional[Any] = None,
    use_langgraph: bool = True,
    max_retries: int = 3,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    session_dem_path: Optional[str] = None,
) -> AgentState:
    """运行一次完整的 Agent 分析流程。

    Args:
        query: 用户自然语言问题
        bbox: 可选研究区 [minLon, minLat, maxLon, maxLat]
        llm: LLM 客户端；None 表示纯规则模式（无 LLM 也能跑通全流程）
        session_id: 会话 ID，配合 checkpointer 实现多轮与恢复
        checkpointer: LangGraph checkpointer
        use_langgraph: False 时强制使用内置循环
        max_retries: 单步最大重试次数
        recursion_limit: LangGraph 递归上限（防止死循环的第二道保险）
        session_dem_path: 本次会话的默认 DEM（前端从 Cesium 地形采样得到的 GeoTIFF）。
            工具参数里没给 dem_path 时用它，避免回退到合成地形。

    Returns:
        最终 AgentState（含 final_answer / tool_calls / trace / reflection）

    示例：
        >>> from app.agent import run_agent
        >>> state = run_agent("分析这片区域的坡度", bbox=[103.5, 30.2, 103.7, 30.4])
        >>> print(state["final_answer"])
    """
    initial = create_initial_state(
        query=query,
        bbox=bbox,
        session_id=session_id,
        max_retries=max_retries,
        session_dem_path=session_dem_path,
    )

    if use_langgraph:
        try:
            graph = build_graph(llm=llm, checkpointer=checkpointer)
            config: Dict[str, Any] = {
                "recursion_limit": recursion_limit,
                "configurable": {"thread_id": session_id},
            }
            out = graph.invoke(initial, config=config)
            return AgentState(**dict(out))
        except Exception as exc:  # LangGraph 不可用 → 降级
            warnings.warn(
                f"LangGraph 执行失败，降级为内置执行循环：{type(exc).__name__}: {exc}",
                RuntimeWarning,
            )

    return _run_without_langgraph(initial, llm=llm, max_steps=recursion_limit)


def stream_agent(
    query: str,
    bbox: Optional[List[float]] = None,
    llm: Optional[LLMClient] = None,
    session_id: str = "default",
    checkpointer: Optional[Any] = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
):
    """流式运行 —— 每完成一个节点产出一次状态快照，供前端逐步展示。

    LangGraph 不可用时退化为"只在结束时产出一次"。
    """
    initial = create_initial_state(query=query, bbox=bbox, session_id=session_id)
    config: Dict[str, Any] = {
        "recursion_limit": recursion_limit,
        "configurable": {"thread_id": session_id},
    }
    try:
        graph = build_graph(llm=llm, checkpointer=checkpointer)
        for chunk in graph.stream(initial, config=config):
            yield chunk
    except Exception:
        yield {NODE_SUMMARIZE: _run_without_langgraph(initial, llm=llm)}
