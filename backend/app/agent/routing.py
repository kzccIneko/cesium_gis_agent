"""状态图路由函数。

全部写成纯函数（输入 state，输出下一节点名），
这样 LangGraph 与内置 runner 可以共享同一套流转逻辑，
不会出现"两种运行时行为不一致"的经典 bug。
"""

from __future__ import annotations

from .state import AgentState, plan_remaining

NODE_PLAN = "plan"
NODE_EXECUTE = "execute"
NODE_REFLECT = "reflect"
NODE_SUMMARIZE = "summarize"


def route_after_plan(state: AgentState) -> str:
    """规划后：有步骤就执行，没有就直接总结（说明为何无法规划）。"""
    plan = state.get("plan") or []
    if not plan:
        return NODE_SUMMARIZE
    return NODE_EXECUTE


def route_after_execute(state: AgentState) -> str:
    """执行后一律进入反思，由反思节点判断成败。"""
    return NODE_REFLECT


def route_after_reflect(state: AgentState) -> str:
    """反思后：重试回执行；放弃或全部完成则总结。"""
    reflection = state.get("reflection") or {}
    action = reflection.get("action")

    if action == "retry":
        return NODE_EXECUTE
    if action == "abort":
        # 放弃也要总结 —— 用户需要知道为什么拿不到结果
        return NODE_SUMMARIZE
    # accept
    if plan_remaining(state) <= 0:
        return NODE_SUMMARIZE
    return NODE_EXECUTE
