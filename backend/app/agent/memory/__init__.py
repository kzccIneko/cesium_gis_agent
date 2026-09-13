"""Agent 对话记忆层。

对外只暴露三样东西：

    get_memory_store()   —— SQLite 存储（轮次 / 空间焦点 / 长期记忆）
    resolve_coreference()—— 跨轮指代消解（规则定坐标）
    build_history_text() —— 把最近几轮拼成给规划器看的历史文本

设计边界（用户明确要求过，见 IMPROVEMENT_PLAN.md 三·六·7.4）：

**规则只负责"代词指向哪个坐标"这件确定性的事，意图判断仍然交给模型。**

理由是这两件事的性质不同：
  - 代词指向什么，是**已经发生过的事实**（上一轮用的 bbox 就记在库里），
    查一下即可，让 4B 模型去猜等于抽奖；
  - 而用户想干什么（分析 / 跳转 / 常识问答），需要语义理解和泛化，那才是模型该做的。

所以流程是：规则把「跳转到这个地方」补全成「跳转到五指山一带（北纬 18.49–19.50、
东经 109.00–111.00）」，再把**完整的句子 + 历史 + 当前视野**一起交给模型判断意图。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .store import MemoryStore, get_memory_store, memory_enabled  # noqa: F401

__all__ = [
    "MemoryStore",
    "get_memory_store",
    "memory_enabled",
    "resolve_coreference",
    "build_history_text",
    "build_focus_text",
    "describe_bbox",
    "infer_place_name",
]


def infer_place_name(
    query: str, actions: Optional[Sequence[Dict[str, Any]]] = None
) -> Optional[str]:
    """从这一轮里推断出"用户说的是哪个地方"，用于长期区域记忆。

    优先用模型给出的动作名（模型对"五指山""阿尔卑斯山"这类专名的提取最直接），
    其次查地名词典（确定性的行政地名）。都取不到就返回 None —— **不猜**，
    宁可这一次不记住，也不要把一个错地名写进长期记忆里污染后续所有推荐。
    """
    for a in actions or []:
        name = str((a or {}).get("name") or "").strip()
        if name:
            return name
    try:
        from ..gazetteer import get_gazetteer

        hits = get_gazetteer().lookup(str(query or ""), limit=1)
        if hits:
            return str(hits[0].name)
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------- 指代表达表
# 两类代词分开处理 —— 这是本模块最关键的一个判断：
#
#   ① 「这里 / 这片 / 当前视野」→ 用**当前视野** bbox
#      用户是**指着屏幕**说话，"这里"就是他此刻看到的地方。上一轮讨论过哪里并不重要。
#
#   ② 「刚才那个 / 上面说的 / 这个地方 / 那个区域」→ 用**空间焦点**（上一轮实际用过的 bbox）
#      用户说的是"刚才提到的那个地方"，而视野可能已经被跳转走了。
#
# 把这两类混为一谈，就会出现"用户说『这里』却被带到上一轮的地方"这种低级错误。
_HERE_WORDS = ("这里", "这片", "这块", "这一片", "这一块", "当前视野", "现在的视野", "图上的", "屏幕上")

_FOCUS_WORDS = (
    "这个地方", "那个地方", "该地方", "这个区域", "那个区域", "该区域",
    "刚才那个", "刚才说的", "上面说的", "之前那个", "之前说的",
    "刚才分析", "刚才算", "上次那个", "那个位置",
)

# 复用上一次操作的说法
_REPEAT_WORDS = ("再算一次", "重新算", "再来一次", "再来一遍", "再分析一次", "重新分析", "同样的分析", "和刚才一样")


def describe_bbox(bbox: Sequence[float], place: Optional[str] = None) -> str:
    """把 bbox 说成人能读的方位描述，供指代替换后拼句子用。

    例：[109.0, 18.49, 111.0, 19.5], "五指山" →
        「五指山一带（北纬 18.49°–19.50°，东经 109.00°–111.00°）」
    """
    try:
        west, south, east, north = (float(x) for x in list(bbox)[:4])
    except (TypeError, ValueError):
        return str(place or "该区域")

    def _lat(v: float) -> str:
        return f"{'北纬' if v >= 0 else '南纬'}{abs(v):.2f}°"

    def _lon(v: float) -> str:
        return f"{'东经' if v >= 0 else '西经'}{abs(v):.2f}°"

    # 同半球时省略重复的方位词（「北纬18.50°–19.20°」比「北纬18.50°–北纬19.20°」好读）
    lat = f"{_lat(south)}–{abs(north):.2f}°" if south >= 0 and north >= 0 else f"{_lat(south)}–{_lat(north)}"
    lon = f"{_lon(west)}–{abs(east):.2f}°" if west >= 0 and east >= 0 else f"{_lon(west)}–{_lon(east)}"
    head = f"{place}一带" if place else "该区域"
    return f"{head}（{lat}，{lon}）"


def resolve_coreference(
    query: str,
    focus: Optional[Dict[str, Any]] = None,
    view_context: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[str]]:
    """把句子里的指代表达替换成显式的地理描述。

    Args:
        query: 用户原句
        focus: 空间焦点卡片（上一轮的 bbox / 地点 / 工具）
        view_context: 当前视野（前端上报）

    Returns:
        (补全后的句子, 说明列表)。说明列表会写进 trace，让用户看得见
        "系统把『这个地方』理解成了什么" —— 记忆生效时必须可见，否则用户无从判断对错。
    """
    raw = str(query or "")
    if not raw.strip():
        return raw, []

    focus = focus or {}
    view_bbox = None
    if view_context:
        vb = view_context.get("bbox")
        if vb and len(vb) >= 4:
            view_bbox = list(vb)[:4]

    focus_bbox = focus.get("last_bbox") or None
    focus_place = (focus.get("last_place") or "").strip() or None

    notes: List[str] = []
    out = raw

    # —— ① "再算一次"类：直接补全成"对上一轮的区域再做一次同样的分析" ——
    if any(w in raw for w in _REPEAT_WORDS):
        if focus_bbox or focus_place:
            where = (
                describe_bbox(focus_bbox, focus_place) if focus_bbox
                else f"{focus_place}一带"
            )
            tool = focus.get("last_tool")
            prev = (focus.get("last_query") or "").strip()
            detail = f"，上一轮做的是「{prev}」" if prev else ""
            extra = f"（用的工具是 {tool}）" if tool else ""
            out = f"{raw}——请对{where}再做一次同样的分析{detail}{extra}"
            notes.append(f"「{'/'.join(w for w in _REPEAT_WORDS if w in raw)}」→ {where}")
        else:
            notes.append("出现『再来一次』类说法，但没有可复用的上一轮记录，按原句处理")

    # —— ② "刚才那个地方"类：用空间焦点 ——
    elif any(w in raw for w in _FOCUS_WORDS):
        if focus_bbox:
            where = describe_bbox(focus_bbox, focus_place)
            for w in _FOCUS_WORDS:
                if w in out:
                    out = out.replace(w, where)
                    break
            notes.append(f"「{w}」→ {where}（取自上一轮记录）")
        elif focus_place:
            # 只知道地名、不知道坐标 —— 实例：「我想看看五指山」（模型只回答了介绍，
            # 没有产生坐标）之后接「跳转到这个地方」。这种情况不能退回视野，
            # 那会跳到用户根本没在说的区域；把代词换成地名文字即可，
            # 模型自己的地理知识足以给出合理范围（实测它能给出五指山的大致经纬度）。
            where = f"{focus_place}一带"
            for w in _FOCUS_WORDS:
                if w in out:
                    out = out.replace(w, where)
                    break
            notes.append(f"「{w}」→ {where}（取自上一轮提到的地方）")
        elif view_bbox:
            where = describe_bbox(view_bbox)
            for w in _FOCUS_WORDS:
                if w in out:
                    out = out.replace(w, where)
                    break
            notes.append(f"「{w}」→ {where}（无上一轮记录，退回当前视野）")
        else:
            notes.append("出现指代表达，但既没有上一轮记录也没有视野范围，交给模型")

    # —— ③ "这里"类：用当前视野 ——
    elif any(w in raw for w in _HERE_WORDS):
        if view_bbox:
            where = describe_bbox(view_bbox)
            for w in _HERE_WORDS:
                if w in out:
                    out = out.replace(w, where)
                    break
            notes.append(f"「{w}」→ {where}（当前视野）")
        elif focus_bbox:
            where = describe_bbox(focus_bbox, focus_place)
            for w in _HERE_WORDS:
                if w in out:
                    out = out.replace(w, where)
                    break
            notes.append(f"「{w}」→ {where}（视野未知，退回上一轮记录）")
        elif focus_place:
            where = f"{focus_place}一带"
            for w in _HERE_WORDS:
                if w in out:
                    out = out.replace(w, where)
                    break
            notes.append(f"「{w}」→ {where}（视野未知，按上一轮提到的地方）")

    return out, notes


def build_history_text(
    turns: Sequence[Dict[str, Any]], max_chars_per_turn: int = 200
) -> str:
    """把最近几轮拼成给规划器看的历史文本。

    刻意保持简短：
      - 每条截到 max_chars_per_turn（默认 200 字）：4B 模型的注意力对长历史很不友好；
      - 只保留角色和内容，不带工具细节 —— 那些通过"空间焦点卡片"以结构化方式给，
        比塞在自然语言历史里可靠得多。
    """
    if not turns:
        return ""
    lines: List[str] = []
    for t in turns:
        role = {"user": "用户", "assistant": "助手"}.get(str(t.get("role")), str(t.get("role")))
        content = str(t.get("content") or "").replace("\n", " ").strip()
        if not content:
            continue
        if len(content) > max_chars_per_turn:
            content = content[:max_chars_per_turn] + "…"
        lines.append(f"  {role}：{content}")
    return "\n".join(lines)


def build_focus_text(
    focus: Optional[Dict[str, Any]], view_context: Optional[Dict[str, Any]] = None
) -> str:
    """把空间焦点卡片写成一行提示词文本。

    与"当前视图"分开给：视图是用户此刻在看哪，焦点是**这一轮对话在聊哪**，
    两者可能不同（例如用户跳转到海南后问"刚才那个山西的区域"）。
    """
    focus = focus or {}
    bits: List[str] = []
    if focus.get("last_place"):
        bits.append(f"上一次讨论的地点：{focus['last_place']}")
    if focus.get("last_bbox"):
        bits.append(f"它的大致范围：{list(focus['last_bbox'])}")
    if focus.get("last_intent"):
        bits.append(f"上一次的意图类型：{focus['last_intent']}")
    if focus.get("last_query"):
        q = str(focus["last_query"])[:60]
        bits.append(f"上一轮用户说的是：{q}")
    if not bits:
        return ""
    return "本轮对话的历史上下文（供理解指代）：\n  " + "；".join(bits)
