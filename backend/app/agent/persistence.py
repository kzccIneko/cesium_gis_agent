"""状态持久化配置。

用途：
    1. 多轮对话 —— 同一个 thread_id 能接着上次的上下文继续
    2. 中断恢复 —— 服务重启/崩溃后能从数据库恢复未完成的分析
    3. 可审计 —— 每次工具调用、每次重试都有记录，便于事后复盘

使用方式：
    checkpointer = build_checkpointer("backend/.data/geoagent.sqlite")
    agent = build_graph(llm, checkpointer)
    agent.invoke(state, config={"configurable": {"thread_id": "user-123"}})
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

# persistence.py 位于 backend/app/agent/，parents[2] 即 backend/
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / ".data" / "geoagent.sqlite"


def build_checkpointer(db_path: Optional[str] = None) -> Optional[Any]:
    """创建 SqliteSaver。

    环境缺少依赖或 SQLite 不可写时返回 None（降级为无持久化），
    而不是让整个 Agent 起不来 —— 持久化是增强项，不是必需项。
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    # LangGraph 1.x 把 SQLite 检查点拆到了独立包 langgraph-checkpoint-sqlite，
    # 0.x 时代它在 langgraph.checkpoint.sqlite。两个路径都要试。
    saver_cls = None
    for mod_name in (
        "langgraph.checkpoint.sqlite",
        "langgraph_checkpoint.sqlite",
        "langgraph_checkpoint_sqlite",
    ):
        try:
            mod = __import__(mod_name, fromlist=["SqliteSaver"])
            saver_cls = getattr(mod, "SqliteSaver", None)
            if saver_cls:
                break
        except Exception:
            continue

    if saver_cls is not None:
        # 优先直接构造：新版 SqliteSaver.from_conn_string 返回的是上下文管理器
        # （_GeneratorContextManager）而非 saver 实例，直接传给 compile() 会报
        # "Invalid checkpointer provided"。用 SqliteSaver(conn) 拿到的才是真正的
        # BaseCheckpointSaver 实例。
        try:
            import sqlite3

            conn = sqlite3.connect(str(path), check_same_thread=False)
            saver = saver_cls(conn)
            from langgraph.checkpoint.base import BaseCheckpointSaver

            if isinstance(saver, BaseCheckpointSaver):
                saver._geoagent_conn = conn  # 保持引用，避免被 GC 关闭
                return saver
        except Exception:
            pass

        try:
            cm = saver_cls.from_conn_string(str(path))
            if hasattr(cm, "__enter__"):
                saver = cm.__enter__()
                saver._geoagent_cm = cm  # 保持引用
                return saver
        except Exception:
            pass

    # SQLite 不可用 → 退回内存检查点。
    # 多轮对话仍可用（同一进程内），只是不跨进程持久化。
    try:
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    except Exception:
        try:
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver()
        except Exception:
            return None


def default_db_path() -> str:
    return str(DEFAULT_DB_PATH)
