"""结构化数据查询工具（自然语言 → SQL）。

包含工具：
    query_tabular —— 对白名单内的数据表做条件查询 / 计数 / 聚合

与 compute_* / zonal_statistics 的区别（这条写进 description 是为了让模型选对工具）
------------------------------------------------------------------
    compute_*、zonal_statistics 算的是**栅格** —— 每个像元一个值，描述连续的地表；
    query_tabular 查的是**属性表** —— 一行一条记录：点位、台账、清单。

    前者回答"这片区域的坡度有多大"；
    后者回答"哪些点位海拔超过 3000 米""多工具类的题目有多少条"。

为什么要有这个工具
------------------
工具层原有 11 个工具**全是空间计算**，没有任何"查表"能力。而"按条件筛出一批记录"
是业务系统里最常见的诉求（工单查询、台账筛选、SLA 统计）。

为什么不让模型直接读整张表
--------------------------
表一大就塞不进提示词，而且模型不是计算器 —— 让它数数、求和、比大小会算错。
正确分工是：**模型只负责把中文翻译成 SQL，数据库负责精确计算**。
（这个做法叫 text-to-SQL。）

安全边界（三条，缺一不可）
--------------------------
1. **只允许 SELECT**（含 WITH ... SELECT），任何写操作一律拒绝；
2. **表名白名单** —— 只认 TABLE_SPECS 里注册过的表，防止读任意表；
3. **行数上限** —— 防止"把全表给我"把内存和上下文打爆。

表从哪来
--------
- 内置：gazetteer（地名词典）、eval_cases（评测集），均由**项目真实数据**构建；
- 扩展：把任意 CSV 丢进 `.data/tables/`，启动时自动注册为一张表。
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .errors import ToolErrorType, ToolException, fail, ok

# ── 路径 ────────────────────────────────────────────────────────────
_BACKEND = Path(__file__).resolve().parents[2]          # backend/
DATA_DIR = _BACKEND / ".data"
TABLE_DB = DATA_DIR / "tables.db"
CSV_DIR = DATA_DIR / "tables"                            # 放 *.csv 即自动注册
EVAL_DATASET = _BACKEND / "app" / "eval" / "dataset.json"

# 单次查询默认/最大返回行数
DEFAULT_LIMIT = 50
MAX_LIMIT = 500

# SQL 里禁止出现的关键字（写操作 / DDL / 事务 / 元操作）
#
# 注意两个"误伤"陷阱（都是被 eval_text2sql 的 t29 用例逼出来的）：
#   1) REPLACE 既是写操作（REPLACE INTO t VALUES ...），
#      又是 SQLite 的字符串函数（REPLACE(x, ',', '')）。
#      用「后面不跟左括号」来区分：跟括号的是函数调用，放行。
#   2) VIEW / TRIGGER 单独列出来会误伤同名的列。
#      但它们只可能以 CREATE VIEW / CREATE TRIGGER 形式出现，而 CREATE 已被拦，
#      所以不必单列。
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|"
    r"pragma|vacuum|reindex|begin|commit|rollback|savepoint|trigger)\b"
    r"|\breplace\b(?!\s*\()",
    re.IGNORECASE,
)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
# WITH 子句定义的临时名字（CTE），它们不是真实表，不能被白名单拦下
_CTE_REF = re.compile(
    r"(?:\bwith\b|,)\s*[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)[`\"\]]?\s+as\s*\(",
    re.IGNORECASE,
)


# ──────────────────────────── 表注册与构建 ────────────────────────────

def _build_gazetteer(conn: sqlite3.Connection) -> str:
    """从地名词典库把 95 条地名搬进来。"""
    from app.agent.gazetteer import get_gazetteer

    src = get_gazetteer()
    rows = sqlite3.connect(str(src.db_path)).execute(
        "SELECT name, west, south, east, north, kind, aliases, source FROM gazetteer"
    ).fetchall()
    conn.execute(
        "CREATE TABLE gazetteer (name TEXT, west REAL, south REAL, east REAL, "
        "north REAL, kind TEXT, aliases TEXT, source TEXT)"
    )
    conn.executemany("INSERT INTO gazetteer VALUES (?,?,?,?,?,?,?,?)", rows)
    return f"写入 {len(rows)} 条"


def _build_eval_cases(conn: sqlite3.Connection) -> str:
    """从评测集把 100 条任务搬进来（含类别与期望工具）。"""
    if not EVAL_DATASET.exists():
        raise FileNotFoundError(f"评测集不存在：{EVAL_DATASET}")
    cases = json.loads(EVAL_DATASET.read_text(encoding="utf-8"))
    conn.execute(
        "CREATE TABLE eval_cases (id TEXT, category TEXT, query TEXT, "
        "expected_tools TEXT, region TEXT)"
    )
    rows = [
        (
            c.get("id"),
            c.get("category"),
            c.get("query"),
            ",".join(c.get("expected_tools") or []),
            c.get("region"),
        )
        for c in cases
    ]
    conn.executemany("INSERT INTO eval_cases VALUES (?,?,?,?,?)", rows)
    return f"写入 {len(rows)} 条"


def _build_csv(conn: sqlite3.Connection, path: Path) -> str:
    """把一张 CSV 注册成表（列名取首行，类型一律按 TEXT 存，查询时靠 SQLite 自动转换）。"""
    name = path.stem
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"CSV 为空：{path.name}")
        cols = [re.sub(r"\W", "_", (h or f"c{i}").strip()) or f"c{i}"
                for i, h in enumerate(header)]
        col_defs = ",".join('"{}" TEXT'.format(c) for c in cols)
        conn.execute(f'CREATE TABLE "{name}" ({col_defs})')
        placeholders = ",".join("?" * len(cols))
        insert_sql = f'INSERT INTO "{name}" VALUES ({placeholders})'
        n = 0
        for row in reader:
            row = (row + [None] * len(cols))[: len(cols)]
            conn.execute(insert_sql, row)
            n += 1
    return f"写入 {n} 行"


# 表白名单：名字 → {描述, 列说明, 构建函数}
TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "gazetteer": {
        "desc": "地名词典：中国境内的地名及其经纬度包围盒",
        "columns": {
            "name": "地名（如 四姑娘山、成都周边）",
            "west": "西经（包围盒左边界）",
            "south": "南纬（下边界）",
            "east": "东经（右边界）",
            "north": "北纬（上边界）",
            "kind": "类型：mountain / city / province …",
            "aliases": "别名，逗号分隔",
            "source": "来源：manual=人工标注，eval=评测集标准答案",
        },
        "build": _build_gazetteer,
    },
    "eval_cases": {
        "desc": "GeoAgent 主评测集：100 条中文地理空间任务",
        "columns": {
            "id": "用例编号（如 single_001）",
            "category": "类别：single_tool / multi_tool / out_of_scope",
            "query": "用户问句原文",
            "expected_tools": "标准答案要求的工具，逗号分隔（拒答题为空）",
            "region": "涉及的地名",
        },
        "build": _build_eval_cases,
    },
}


def _ensure_tables(force: bool = False) -> Dict[str, str]:
    """确保 tables.db 存在且是最新的，返回 {表名: 构建说明}。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    built: Dict[str, str] = {}

    if force and TABLE_DB.exists():
        TABLE_DB.unlink()

    fresh = not TABLE_DB.exists()
    conn = sqlite3.connect(str(TABLE_DB))
    try:
        existing = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for name, spec in TABLE_SPECS.items():
            if fresh or name not in existing:
                conn.execute(f'DROP TABLE IF EXISTS "{name}"')
                built[name] = spec["build"](conn)
        # CSV 自动注册
        if CSV_DIR.exists():
            for csv_path in sorted(CSV_DIR.glob("*.csv")):
                name = csv_path.stem
                if fresh or name not in existing:
                    built[name] = _build_csv(conn, csv_path)
        conn.commit()
    finally:
        conn.close()
    return built


def list_tables(refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """返回可用于查询的表：{表名: {rows, desc, columns}}。"""
    _ensure_tables(force=refresh)
    out: Dict[str, Dict[str, Any]] = {}
    conn = sqlite3.connect(str(TABLE_DB))
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        for n in names:
            cnt = conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
            spec = TABLE_SPECS.get(n, {})
            cols = spec.get("columns")
            if not cols:
                info = conn.execute(f'PRAGMA table_info("{n}")').fetchall()
                cols = {r[1]: "（CSV 列）" for r in info}
            out[n] = {"rows": cnt, "desc": spec.get("desc", "外部 CSV"), "columns": cols}
    finally:
        conn.close()
    return out


def render_schema() -> str:
    """给 LLM 看的表结构说明。"""
    lines: List[str] = []
    for name, meta in list_tables().items():
        lines.append(f"表 {name}（{meta['rows']} 行）—— {meta['desc']}")
        for col, desc in meta["columns"].items():
            lines.append(f"    {col}: {desc}")
    return "\n".join(lines)


# ──────────────────────────── 安全闸门 ────────────────────────────

def sanitize_sql(sql: str, allowed_tables: Sequence[str]) -> str:
    """把模型产出的 SQL 清洗成可安全执行的一条 SELECT。不合规直接抛错。

    做四件事：去注释 → 去首尾 → 卡单语句 → 卡只读 → 卡表名白名单。
    """
    s = (sql or "").strip()

    # 1) 去掉 markdown 代码块围栏
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()

    # 2) 去掉注释（-- 行注释与 /* */ 块注释）
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    s = re.sub(r"--[^\n]*", " ", s).strip()

    if not s:
        raise ToolException("没有拿到可执行的查询语句", ToolErrorType.OUT_OF_CAPABILITY)

    # 3) 只允许单条语句
    body = s.rstrip(";").strip()
    if ";" in body:
        raise ToolException(
            "只允许执行单条查询语句（检测到多条语句）",
            ToolErrorType.OUT_OF_CAPABILITY,
        )

    # 4) 只允许 SELECT / WITH ... SELECT
    if not re.match(r"^(select|with)\b", body, re.IGNORECASE):
        raise ToolException(
            "只允许 SELECT 查询（本工具是只读的，不能改数据）",
            ToolErrorType.OUT_OF_CAPABILITY,
        )

    # 5) 禁止写操作关键字（即使出现在子查询里）
    hit = _FORBIDDEN.search(body)
    if hit:
        raise ToolException(
            f"查询里出现了被禁止的关键字 {hit.group(1).upper()}（本工具只读）",
            ToolErrorType.OUT_OF_CAPABILITY,
        )

    # 6) 表名白名单（WITH 子句定义的临时名不算表）
    cte_names = {m.group(1).lower() for m in _CTE_REF.finditer(body)}
    used = {m.group(1).lower() for m in _TABLE_REF.finditer(body)}
    unknown = used - {t.lower() for t in allowed_tables} - cte_names
    if unknown:
        raise ToolException(
            f"引用了未登记的表：{', '.join(sorted(unknown))}。"
            f"可用的表：{', '.join(allowed_tables)}",
            ToolErrorType.OUT_OF_CAPABILITY,
        )

    return body


# ──────────────────────────── 自然语言 → SQL ────────────────────────────

_SQL_PROMPT = """你是一个 SQL 生成器。请根据用户的问题，写出**一条** SQLite 查询语句。

可用的表和字段：
{schema}

要求：
1. 只生成 SELECT 查询，绝对不要生成任何修改数据的语句；
2. 只能使用上面列出的表和字段名；
3. 结果最多返回 {limit} 行；
4. 只输出 SQL 本身 —— 不要解释，不要 Markdown 代码块，不要分号结尾。

用户问题：{question}
"""

_LLM_CACHE: Dict[str, Any] = {}


def _get_llm():
    """懒加载 LLM 客户端（进程内 llama.cpp）。加载一次后缓存。"""
    if "llm" not in _LLM_CACHE:
        from app.agent.llm import build_client

        _LLM_CACHE["llm"] = build_client()
    return _LLM_CACHE["llm"]


def _extract_sql(text: str) -> str:
    """从模型输出里抠出 SQL。

    模型可能带前导说明或思考碎片，这里只认第一个 SELECT / WITH 开头、
    到分号（或文本末尾）为止的片段。
    """
    if not text:
        return ""
    s = re.sub(r"```[a-zA-Z]*", "", text)
    m = re.search(r"\b(select|with)\b.*", s, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    frag = m.group(0)
    # 截到第一个分号（若有）
    if ";" in frag:
        frag = frag.split(";")[0]
    return frag.strip()


def nl_to_sql(question: str, limit: int) -> str:
    llm = _get_llm()
    prompt = _SQL_PROMPT.format(schema=render_schema(), limit=limit, question=question)
    resp = llm.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        # 一句 SQL 通常 50–120 token；给 384 是护栏，防止模型写飞
        max_tokens=384,
    )
    return _extract_sql(getattr(resp, "content", "") or "")


# ──────────────────────────── 工具本体 ────────────────────────────

def query_tabular(
    question: str,
    table: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    sql: Optional[str] = None,
) -> Dict[str, Any]:
    """对结构化数据表做条件查询与统计。

    典型用途：
        - 「有哪些地名在四川」            → 筛 gazetteer
        - 「多工具类的评测题一共有多少条」 → 数 eval_cases
        - 「海拔超过 3000 米的点位有哪些」 → 查外部 CSV 表

    Args:
        question: 用户的自然语言问题
        table: 指定要查的表；不传则由模型根据表清单自行选择
        limit: 返回行数上限
        sql: 直接给定 SQL（跳过自然语言翻译，便于人工调试与回归测试）

    Returns:
        data.sql        —— 实际执行的 SQL（可复核）
        data.columns    —— 列名
        data.rows       —— 结果（每行一个字典）
        data.row_count  —— 返回行数
        data.summary    —— 一句话结论
    """
    tool = "query_tabular"
    t0 = time.perf_counter()

    try:
        limit = int(limit or DEFAULT_LIMIT)
        limit = max(1, min(limit, MAX_LIMIT))

        tables = list_tables()
        if not tables:
            return fail(tool, "没有任何已登记的数据表", ToolErrorType.MODEL_NOT_FOUND,
                        (time.perf_counter() - t0) * 1000).to_dict()

        allowed = list(tables.keys())
        if table:
            table = str(table).strip()
            if table not in allowed:
                raise ToolException(
                    f"表 {table} 未登记。可用的表：{', '.join(allowed)}",
                    ToolErrorType.OUT_OF_CAPABILITY,
                )
            allowed = [table]

        # 1) 拿到 SQL：优先用调用方直接给的，否则让模型翻译
        if sql:
            raw_sql = str(sql)
            source = "caller"
        else:
            if not question or not str(question).strip():
                raise ToolException("缺少 question（或用 sql 直接给查询语句）",
                                    ToolErrorType.UNKNOWN_METRIC)
            raw_sql = nl_to_sql(str(question), limit)
            source = "llm"
            if not raw_sql:
                return fail(
                    tool,
                    "模型没有产出可用的查询语句（可能问题与这些表无关）",
                    ToolErrorType.OUT_OF_CAPABILITY,
                    (time.perf_counter() - t0) * 1000,
                ).to_dict()

        # 2) 安全闸门
        safe_sql = sanitize_sql(raw_sql, allowed)

        # 3) 执行（多取一行用于判断是否被截断）
        conn = sqlite3.connect(str(TABLE_DB))
        try:
            cur = conn.execute(safe_sql)
            cols = [d[0] for d in (cur.description or [])]
            fetched = cur.fetchmany(limit + 1)
        finally:
            conn.close()

        truncated = len(fetched) > limit
        fetched = fetched[:limit]
        rows = [dict(zip(cols, r)) for r in fetched]

        cte_names = {m.group(1).lower() for m in _CTE_REF.finditer(safe_sql)}
        used_tables = sorted(
            {m.group(1) for m in _TABLE_REF.finditer(safe_sql)
             if m.group(1).lower() not in cte_names}
        )

        data: Dict[str, Any] = {
            "question": question,
            "sql": safe_sql,
            "sql_source": source,
            "tables_used": used_tables,
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "summary": (
                f"查到 {len(rows)} 行" + ("（已截断，可缩小条件或提高 limit）" if truncated else "")
            ),
            "available_tables": {k: f"{v['rows']} 行" for k, v in tables.items()},
        }
        if not rows:
            data["summary"] = "没有查到符合条件的记录"
        return ok(tool, data, (time.perf_counter() - t0) * 1000).to_dict()

    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except sqlite3.Error as exc:
        return fail(tool, f"SQL 执行失败：{exc}", ToolErrorType.OUT_OF_CAPABILITY,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"查表失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()
