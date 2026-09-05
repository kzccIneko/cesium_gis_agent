"""LangGraph 状态图定义：计划 → 执行 → 反思 →（重试 | 下一步 | 总结）。

图结构：

                 ┌─────────────────────────────┐
                 │                             │
    START → plan → execute → reflect ──accept──┤
                     ↑          │              │
                     │          │              ├→ 还有步骤 → execute
                     └──retry───┘              │
                                               └→ 无剩余步骤 → summarize → END
                                    abort ─────┘

重试边（reflect → execute）是本项目 reflect 机制的核心：
它让 Agent 在参数错误时有机会自我修正，而不是把错误抛给用户。
为防止死循环，重试次数由 reflector 维护（retry_count vs max_retries），
同时 LangGraph 的 recursion_limit 提供第二道保险。
"""

from __future__ import annotations

from typing import Any, Optional

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
from .state import AgentState

DEFAULT_RECURSION_LIMIT = 60


def build_graph(
    llm: Optional[LLMClient] = None,
    checkpointer: Optional[Any] = None,
):
    """编译 LangGraph 状态图。

    Args:
        llm: LLM 客户端；None 时规划走启发式兜底、反思只做代码校验
        checkpointer: LangGraph checkpointer（SqliteSaver 等），用于持久化

    Returns:
        编译后的图（可 .invoke() / .stream()）
    """
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(AgentState)

    graph.add_node(NODE_PLAN, lambda s: plan_node(s, llm))
    graph.add_node(NODE_EXECUTE, execute_node)
    graph.add_node(NODE_REFLECT, lambda s: reflect_node(s, llm))
    graph.add_node(NODE_SUMMARIZE, lambda s: summarize_node(s, llm))

    graph.add_edge(START, NODE_PLAN)

    graph.add_conditional_edges(
        NODE_PLAN,
        route_after_plan,
        {NODE_EXECUTE: NODE_EXECUTE, NODE_SUMMARIZE: NODE_SUMMARIZE},
    )

    # execute → reflect 是无条件的，但用条件边形式统一，便于将来插入人工审核节点
    graph.add_conditional_edges(
        NODE_EXECUTE,
        route_after_execute,
        {NODE_REFLECT: NODE_REFLECT},
    )

    graph.add_conditional_edges(
        NODE_REFLECT,
        route_after_reflect,
        {NODE_EXECUTE: NODE_EXECUTE, NODE_SUMMARIZE: NODE_SUMMARIZE},
    )

    graph.add_edge(NODE_SUMMARIZE, END)

    return graph.compile(checkpointer=checkpointer)
