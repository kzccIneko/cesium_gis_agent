"""给 Agent 提供领域知识上下文（RAG 与编排层之间的唯一接缝）。

设计取舍
--------
**不把 RAG 做成独立图节点，而是在 planner 内前置注入**，原因是：

1. LangGraph 图里再加一个节点会改变拓扑（checkpointer 的迁移、批量评测的
   调用次数统计都要跟着改），而当前收益只是「多一次取数」，不值得为此
   引入拓扑变更带来的回归风险。
2. RAG 的产出只对 planner 有意义（决定调什么工具），对 executor / reflector
   无用，硬做成节点反而要把它塞进 state 一路传递。

代价是 planner 多承担一项职责 —— 但它本来就负责「理解问题」，
拿外部知识辅助理解，没有越界。

**降级必须静默**：索引未构建时直接返回 None，不能因为没有知识库就让
Agent 整体不可用 —— 评测环境与他人的部署环境很可能没有跑过 build。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_CONTEXT_TEMPLATE = """## 领域知识参考（来自本项目文献库，可能有用）

{body}

说明：以上资料仅作背景参考。**它不能替代工具调用** —— 涉及具体地形数据的
分析仍然必须调用工具得出；但资料里的定义、算法原理、参数取值依据，
可以直接用于组织回答。"""


def retrieve_for_query(
    query: str,
    topk: int = 3,
    max_chars: int = 1800,
    enabled: bool = True,
) -> Optional[str]:
    """返回可直接拼进 planner 提示词的知识上下文；无可用知识时返回 None。"""
    if not enabled:
        return None

    try:
        from ..rag.retriever import Retriever
    except Exception as exc:  # pragma: no cover - 依赖缺失时走降级
        logger.debug("RAG 依赖不可用，跳过知识增强：%s", exc)
        return None

    try:
        r = Retriever.load()
    except FileNotFoundError:
        logger.debug("尚未构建 RAG 索引，跳过知识增强")
        return None
    except Exception as exc:
        logger.warning("加载 RAG 索引失败，改为无增强运行：%s", exc)
        return None

    if not r.store.chunks:
        return None

    items = r.retrieve(query, topk=topk)
    if not items:
        return None

    body = Retriever.format_context(items, max_chars=max_chars)
    return _CONTEXT_TEMPLATE.format(body=body) if body else None
