"""Agent 对话记忆存储（SQLite）。

三层记忆的落盘部分（工作记忆不入库，只存在于单次请求的 state 里）：

    turns          —— 会话内轮次，用于短期记忆（滑动窗口）
    spatial_focus  —— 每个会话一行「空间焦点卡片」，指代消解的**唯一依据**
    region_memory  —— 长期：用户分析过的区域（含访问次数与时间，供衰减排序）
    user_profile   —— 长期：用户偏好（坐标系 / 单位 / 输出格式等）
    confirmed_facts—— 长期：已确认的结论，**原样存储不摘要**

设计取舍（详见 IMPROVEMENT_PLAN.md 三·六）：

1. **不用 LangGraph checkpointer**。它解决的是"断点续跑"（存整个图状态快照），
   而我们 state 里有 DEM 路径 / 产物列表 / trace 等大对象，每轮快照既慢又脏；
   且项目是 LangGraph + 自研循环双运行时，checkpointer 只在图分支生效会造成行为分叉。
   记忆与检查点语义不同，不该混用。

2. **短期只截断、不摘要**。本项目已实测：让 4B 模型"转述一段本来就说清楚的话"，
   它会画蛇添足甚至改坏事实。摘要对 4B 是净损失，宁可把旧轮整条丢掉。

3. **事实原样存**。长期记忆里存用户确认过的原始表述，不做二次加工。

4. **连接即用即开**。FastAPI 的同步端点跑在线程池里，SQLite 连接不能跨线程复用。
   每轮只有个位数的小查询，新建连接的开销可以忽略，换来的是零并发风险。
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 短期记忆保留的轮数（一个"轮"= 一问一答，这里按消息条数算）
DEFAULT_WINDOW = 12  # 12 条消息 ≈ 6 轮对话

# 长期区域记忆返回条数上限
DEFAULT_TOP_REGIONS = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    turn_index  INTEGER NOT NULL,
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    intent      TEXT,
    bbox        TEXT,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn_index);

CREATE TABLE IF NOT EXISTS spatial_focus (
    session_id  TEXT PRIMARY KEY,
    last_bbox   TEXT,
    last_place  TEXT,
    last_intent TEXT,
    last_tool   TEXT,
    last_query  TEXT,
    last_answer TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS region_memory (
    name         TEXT PRIMARY KEY,
    bbox         TEXT NOT NULL,
    kind         TEXT,
    note         TEXT,
    access_count INTEGER NOT NULL DEFAULT 1,
    last_access  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confirmed_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject    TEXT NOT NULL,
    fact       TEXT NOT NULL,
    source     TEXT,
    session_id TEXT,
    invalid    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    """ISO 时间戳（本地时区，便于人看）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _default_db_path() -> Path:
    """默认落在 backend/.data/memory/ 下（该目录已在 .gitignore）。"""
    root = Path(__file__).resolve().parents[3]  # → backend/
    d = root / ".data" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "agent_memory.db"


class MemoryStore:
    """对话记忆读写。所有方法都可在多线程下安全调用。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = str(db_path or os.getenv("GEOAGENT_MEMORY_DB") or _default_db_path())
        self._lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------------ 底层
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _exec(self, sql: str, args: tuple = ()) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(sql, args)
            conn.commit()

    def _query(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        with self._lock, closing(self._connect()) as conn:
            return conn.execute(sql, args).fetchall()

    def _one(self, sql: str, args: tuple = ()) -> Optional[sqlite3.Row]:
        rows = self._query(sql, args)
        return rows[0] if rows else None

    # -------------------------------------------------------- 短期：轮次历史
    def append_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        bbox: Optional[List[float]] = None,
    ) -> None:
        """追加一条消息。turn_index 由库内自增维护，避免调用方算错。"""
        if not session_id or not str(content or "").strip():
            return
        row = self._one(
            "SELECT COALESCE(MAX(turn_index), 0) AS m FROM turns WHERE session_id = ?",
            (session_id,),
        )
        nxt = int(row["m"] if row else 0) + 1
        self._exec(
            "INSERT INTO turns (session_id, turn_index, role, content, intent, bbox, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                nxt,
                role,
                str(content),
                intent,
                json.dumps(bbox, ensure_ascii=False) if bbox else None,
                _now(),
            ),
        )

    def recent_turns(
        self, session_id: str, limit: int = DEFAULT_WINDOW
    ) -> List[Dict[str, Any]]:
        """取最近 limit 条消息，按时间正序返回（最老的在前）。

        只取"尾部"是刻意的：Lost-in-the-Middle 实测注意力呈 U 型，
        中段信息召回率极低，塞更多历史反而拖累准确率。
        """
        if not session_id:
            return []
        rows = self._query(
            "SELECT role, content, intent, bbox, turn_index FROM turns"
            " WHERE session_id = ? ORDER BY turn_index DESC LIMIT ?",
            (session_id, int(limit)),
        )
        out = [
            {
                "role": r["role"],
                "content": r["content"],
                "intent": r["intent"],
                "bbox": json.loads(r["bbox"]) if r["bbox"] else None,
            }
            for r in rows
        ]
        out.reverse()
        return out

    def trim_turns(self, session_id: str, keep: int = DEFAULT_WINDOW) -> int:
        """把会话裁到最近 keep 条，返回删除条数。

        注意：这里是**真删**而不是摘要。对 4B 模型来说，摘要一次等于引入一次
        事实损坏的机会，不如干脆丢掉旧轮。
        """
        row = self._one(
            "SELECT COALESCE(MAX(turn_index), 0) AS m FROM turns WHERE session_id = ?",
            (session_id,),
        )
        if not row:
            return 0
        cutoff = int(row["m"]) - int(keep)
        if cutoff <= 0:
            return 0
        n = self._one(
            "SELECT COUNT(*) AS c FROM turns WHERE session_id = ? AND turn_index <= ?",
            (session_id, cutoff),
        )
        self._exec(
            "DELETE FROM turns WHERE session_id = ? AND turn_index <= ?",
            (session_id, cutoff),
        )
        return int(n["c"] if n else 0)

    # ---------------------------------------------------------- 短期：空间焦点
    def get_focus(self, session_id: str) -> Dict[str, Any]:
        """取该会话的空间焦点卡片（指代消解的唯一依据）。没有则返回空字典。"""
        if not session_id:
            return {}
        row = self._one("SELECT * FROM spatial_focus WHERE session_id = ?", (session_id,))
        if not row:
            return {}
        focus = dict(row)
        focus["last_bbox"] = json.loads(focus["last_bbox"]) if focus.get("last_bbox") else None
        return focus

    def update_focus(
        self,
        session_id: str,
        *,
        last_bbox: Optional[List[float]] = None,
        last_place: Optional[str] = None,
        last_intent: Optional[str] = None,
        last_tool: Optional[str] = None,
        last_query: Optional[str] = None,
        last_answer: Optional[str] = None,
    ) -> None:
        """更新空间焦点。只覆盖传入的字段，None 表示"不动这一项"。"""
        if not session_id:
            return
        cur = self.get_focus(session_id)
        fields = {
            "last_bbox": cur.get("last_bbox"),
            "last_place": cur.get("last_place"),
            "last_intent": cur.get("last_intent"),
            "last_tool": cur.get("last_tool"),
            "last_query": cur.get("last_query"),
            "last_answer": cur.get("last_answer"),
        }
        for k, v in (
            ("last_bbox", last_bbox),
            ("last_place", last_place),
            ("last_intent", last_intent),
            ("last_tool", last_tool),
            ("last_query", last_query),
            ("last_answer", last_answer),
        ):
            if v is not None:
                fields[k] = v
        self._exec(
            "INSERT INTO spatial_focus"
            " (session_id, last_bbox, last_place, last_intent, last_tool, last_query, last_answer, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            "   last_bbox=excluded.last_bbox, last_place=excluded.last_place,"
            "   last_intent=excluded.last_intent, last_tool=excluded.last_tool,"
            "   last_query=excluded.last_query, last_answer=excluded.last_answer,"
            "   updated_at=excluded.updated_at",
            (
                session_id,
                json.dumps(fields["last_bbox"], ensure_ascii=False) if fields["last_bbox"] else None,
                fields["last_place"],
                fields["last_intent"],
                fields["last_tool"],
                fields["last_query"],
                fields["last_answer"],
                _now(),
            ),
        )

    # ------------------------------------------------------------- 长期：区域
    def remember_region(
        self,
        name: str,
        bbox: List[float],
        kind: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        """记住一个被分析过的区域；已存在则累加访问次数并刷新时间。"""
        name = str(name or "").strip()
        if not name or not bbox or len(bbox) < 4:
            return
        self._exec(
            "INSERT INTO region_memory (name, bbox, kind, note, access_count, last_access)"
            " VALUES (?, ?, ?, ?, 1, ?)"
            " ON CONFLICT(name) DO UPDATE SET"
            "   bbox=excluded.bbox,"
            "   kind=COALESCE(excluded.kind, region_memory.kind),"
            "   note=COALESCE(excluded.note, region_memory.note),"
            "   access_count=region_memory.access_count + 1,"
            "   last_access=excluded.last_access",
            (name, json.dumps(list(bbox), ensure_ascii=False), kind, note, _now()),
        )

    def top_regions(self, limit: int = DEFAULT_TOP_REGIONS) -> List[Dict[str, Any]]:
        """按「访问频次 × 时间衰减」排序返回常用区域。

        衰减借鉴 Generative Agents 的做法：越久没访问，权重越低，
        避免两个月前看过一次的地方永远压在最近常看的区域上面。
        """
        rows = self._query("SELECT * FROM region_memory")
        items: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for r in rows:
            try:
                last = datetime.fromisoformat(r["last_access"])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                days = max((now - last).total_seconds() / 86400.0, 0.0)
            except Exception:  # noqa: BLE001
                days = 0.0
            score = float(r["access_count"]) * math.exp(-days / 30.0)
            items.append(
                {
                    "name": r["name"],
                    "bbox": json.loads(r["bbox"]) if r["bbox"] else None,
                    "kind": r["kind"],
                    "note": r["note"],
                    "access_count": int(r["access_count"]),
                    "last_access": r["last_access"],
                    "score": round(score, 4),
                }
            )
        items.sort(key=lambda x: x["score"], reverse=True)
        return items[: int(limit)]

    # ------------------------------------------------------------- 长期：偏好
    def set_pref(self, key: str, value: str) -> None:
        self._exec(
            "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(key), str(value), _now()),
        )

    def get_prefs(self) -> Dict[str, str]:
        return {r["key"]: r["value"] for r in self._query("SELECT key, value FROM user_profile")}

    # ------------------------------------------------------- 长期：确认过的事实
    def add_fact(
        self,
        subject: str,
        fact: str,
        source: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """记录一条已确认的结论。**原样存储**，不做摘要或改写。"""
        if not str(fact or "").strip():
            return
        self._exec(
            "INSERT INTO confirmed_facts (subject, fact, source, session_id, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(subject), str(fact), source, session_id, _now()),
        )

    def recall_facts(self, subject: str, limit: int = 3) -> List[Dict[str, Any]]:
        """按主题回忆结论（当前用精确/包含匹配；接向量检索是第二阶段的事）。"""
        rows = self._query(
            "SELECT subject, fact, source, created_at FROM confirmed_facts"
            " WHERE invalid = 0 AND subject LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{subject}%", int(limit)),
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ 维护
    def reset_session(self, session_id: str) -> None:
        """清空某个会话的记忆（前端「新会话」按钮）。长期记忆不动。"""
        if not session_id:
            return
        with self._lock, closing(self._connect()) as conn:
            conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM spatial_focus WHERE session_id = ?", (session_id,))
            conn.commit()

    def stats(self) -> Dict[str, Any]:
        """给看板 / 前端状态显示用的小结。"""
        def _c(sql: str) -> int:
            r = self._one(sql)
            return int(r[0]) if r and r[0] is not None else 0

        return {
            "db_path": self.db_path,
            "sessions": _c("SELECT COUNT(DISTINCT session_id) FROM turns"),
            "turns": _c("SELECT COUNT(*) FROM turns"),
            "regions": _c("SELECT COUNT(*) FROM region_memory"),
            "facts": _c("SELECT COUNT(*) FROM confirmed_facts WHERE invalid = 0"),
        }


# ------------------------------------------------------------------ 单例
_STORE: Optional[MemoryStore] = None
_STORE_LOCK = threading.Lock()


def memory_enabled() -> bool:
    """记忆总开关。评测单轮准确率时置 GEOAGENT_MEMORY=0，
    保证基线不会被历史污染（评测每题都是独立任务，不该有上下文）。"""
    return os.getenv("GEOAGENT_MEMORY", "1") not in ("0", "false", "False", "")


def get_memory_store() -> Optional[MemoryStore]:
    """取全局记忆存储；`GEOAGENT_MEMORY=0` 时返回 None（调用方需容忍）。"""
    global _STORE
    if not memory_enabled():
        return None
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = MemoryStore()
    return _STORE
