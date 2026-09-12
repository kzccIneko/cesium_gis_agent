"""总结节点：把工具执行结果组织成面向用户的回答。

两层策略：
    LLM 可用  → 让模型基于结构化结果写自然语言回答
    LLM 不可用 → 模板拼接（仍然要给出可用的答案，而不是抛异常）

模板路径不是"降级敷衍"，而是刻意的兜底：
Agent 的核心价值是工具执行与自校验，回答措辞是次要的。
即使没有 LLM，用户也应该拿到结构化的可信结论。

模板回答会强制包含三部分：
    1. 每个步骤的结论（来自工具的 summary 字段）
    2. 数据局限（合成地形 / 有效数据占比 / 规则告警）
    3. 失败步骤的说明（若有）
第 2 点是刻意设计的 —— 宁可显得啰嗦，也不能让用户拿着合成地形的
结果去做真实决策。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..llm import LLMClient, SUMMARIZER_MAX_TOKENS
from ..state import (
    AgentState,
    STATUS_DONE,
    STATUS_FAILED,
    append_message,
    append_trace,
)

SUMMARY_PROMPT = """你是地理空间分析助手。基于以下工具执行结果，用中文回答用户的问题。

用户问题：{query}

工具执行结果：
{results}

执行轨迹：
{trace}

回答要求：
- 直接回答问题，不要复述过程
- 引用具体数值（带单位），数值必须来自上述结果，不得编造
- 若结果基于合成地形或存在数据局限，必须在结尾用一句话明确说明
- 若某些步骤失败，如实说明哪部分没能完成
- 控制在 300 字以内
"""


# 不规范的地区表述：把中国的一部分当成独立国家，或与之对等并列。
# 出现即说明模型这条回答不能用，换回标准话术。
_IMPROPER_REGION_PATTERNS = (
    "台湾国", "台灣國", "台湾是一个国家", "台湾是独立国家", "台湾独立",
    "香港国", "澳门国",
    "中国和台湾", "中国与台湾", "台湾和中国", "台湾与中国",
    "大陆和台湾", "大陆与台湾", "台湾和大陆",
)


def _has_improper_region_wording(text: str) -> bool:
    """回答里是否出现不规范的地区表述。"""
    return any(p in text for p in _IMPROPER_REGION_PATTERNS)


def _refusal_answer(query: str) -> str:
    """越界问题时给用户的回答 —— 必须是人话，不能是给 LLM 的指令。

    planner 生成的 `final_answer_hint` 是写给总结节点的**指令**（典型样子：
    「向用户说明问候语不属于地理空间分析能力范围…」）。以前这条指令被原样当成
    回答吐给用户，看起来就像系统在对用户下命令 —— 直接照搬是不可接受的。
    """
    return (
        f"「{query}」不在我的能力范围内。\n\n"
        "我只做地球表面的地理空间分析，具体是这几类：\n"
        "· 地形因子 —— 坡度、坡向、曲率\n"
        "· 地貌分类 —— 判断某片区域属于山脊、山谷、平原等哪一类\n"
        "· 通行性与路径 —— 哪里好走、两点之间怎么走最省力\n"
        "· 分区统计 —— 某个指标各占多少面积、多大比例\n\n"
        "换个问法就行，比如「算一下贡嘎山的坡度分布」。"
    )


def _template_summary(state: AgentState) -> str:
    """无 LLM 时的模板化回答。"""
    calls: List[Dict[str, Any]] = list(state.get("tool_calls") or [])
    lines: List[str] = []

    # 越界拒答：不用 planner 的 hint 原文（那是给 LLM 的指令，不是给用户的话）。
    # 没有工具调用不代表分析失败，这两件事不能混为一谈。
    if state.get("refused"):
        return _refusal_answer(state.get("query", ""))

    if not calls:
        return (
            "未能获得有效的分析结果。"
            + (f"原因：{(state.get('reflection') or {}).get('reason', '未知')}"
               if state.get("reflection") else "")
        )

    lines.append(f"针对「{state.get('query', '')}」，完成 {len(calls)} 项分析：")

    ok_calls = [c for c in calls if c.get("success")]
    failed_calls = [c for c in calls if not c.get("success")]

    for i, c in enumerate(ok_calls, 1):
        lines.append(f"{i}. {c.get('tool')}：{c.get('summary')}")
        args = c.get("arguments") or {}
        if args.get("resolution"):
            lines.append(f"   栅格分辨率 {args['resolution']}×{args['resolution']}")

    if failed_calls:
        lines.append("")
        lines.append("以下分析未能完成：")
        for c in failed_calls:
            lines.append(
                f"- {c.get('tool')}：{c.get('error')}（错误类型：{c.get('error_type')}）"
            )

    # 数据局限必须显式声明
    caveats: List[str] = []
    for c in ok_calls:
        pass
    reflections = state.get("reflection") or {}
    for w in reflections.get("code_warnings", []) or []:
        caveats.append(str(w))
    if any("合成地形" in str(c.get("summary", "")) for c in ok_calls):
        caveats.append(
            "注意：本次分析基于合成地形（未提供真实 DEM），"
            "结果仅用于验证分析流程，不能作为真实地理结论。"
            "如需真实数据，请先调用 download_srtm 下载 SRTM 高程数据。"
        )
    if caveats:
        lines.append("")
        lines.append("数据说明：")
        seen = set()
        for cv in caveats:
            key = cv[:40]
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {cv}")

    return "\n".join(lines)


def summarize_node(state: AgentState, llm: Optional[LLMClient]) -> Dict[str, Any]:
    """总结节点：生成最终回答。"""
    trace = list(state.get("trace") or [])
    calls = list(state.get("tool_calls") or [])

    # —— 非分析意图：规划器已经写好了回答，直接采用 ——
    # 不要再用 LLM 二次加工：让 4B 模型"转述一段本来就说清楚了的话"，
    # 它经常画蛇添足，甚至把事实改掉。对话/常识回答尤其经不起这种损耗。
    intent = str(state.get("intent") or "").strip()
    planner_reply = str(state.get("reply") or "").strip()
    if intent in ("knowledge", "chat", "action", "refuse") and planner_reply:
        # 主权表述兜底：模型偶尔会写出不规范的地区表述，命中即换回标准话术。
        # 这类内容宁可保守，也不能让它在界面上出现。
        if _has_improper_region_wording(planner_reply):
            trace.append("⚠ 回答中出现不规范的地区表述，已替换为标准说明")
            planner_reply = _refusal_answer(state.get("query", ""))
        final_status = (
            STATUS_FAILED if state.get("status") == STATUS_FAILED else STATUS_DONE
        )
        trace.append(f"意图={intent}：直接采用规划器给出的回答（不再二次总结）")
        return {
            "final_answer": planner_reply,
            "status": final_status,
            "trace": trace,
            "messages": append_message(state, "assistant", planner_reply),
        }

    answer: Optional[str] = None
    if llm is not None and calls:
        results_text = "\n".join(
            f"- {c.get('tool')}（第 {c.get('attempt')} 次尝试，"
            f"{'成功' if c.get('success') else '失败'}）：{c.get('summary')}"
            for c in calls
        )
        trace_text = "\n".join(f"- {t}" for t in (state.get("trace") or [])[-10:])
        try:
            resp = llm.chat(
                [
                    {
                        "role": "user",
                        "content": SUMMARY_PROMPT.format(
                            query=state.get("query", ""),
                            results=results_text,
                            trace=trace_text,
                        ),
                    }
                ],
                temperature=0.0,
                max_tokens=SUMMARIZER_MAX_TOKENS,
            )
            if resp.content and resp.content.strip():
                answer = resp.content.strip()
                trace.append("由 LLM 生成最终回答")
        except Exception as exc:
            trace.append(f"LLM 总结失败（{type(exc).__name__}），改用模板回答")

    if not answer:
        answer = _template_summary(state)
        trace.append("由模板生成最终回答")

    # 保留失败状态：放弃（abort）时同样会走到总结节点 —— 用户需要知道为什么
    # 拿不到结果 —— 但这时不能把 status 改回 done，否则调用方无法区分
    # "分析成功完成" 与 "分析失败但已向用户说明"。
    final_status = (
        STATUS_FAILED if state.get("status") == STATUS_FAILED else STATUS_DONE
    )

    return {
        "final_answer": answer,
        "status": final_status,
        "trace": trace,
        "messages": append_message(state, "assistant", answer),
    }
