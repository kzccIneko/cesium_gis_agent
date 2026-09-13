"""从评测产物生成 GeoAgent 进度看板（单文件 HTML，双击即开）。

用法：
    python bench/make_dashboard.py \
        --results bench/eval_results \
        --out bench/dashboard.html

设计约束：
- **自包含**：所有数据内联进 HTML，无外部请求，断网/离线可看
- **只呈现实测数据**：版本演进曲线来自下方 EVOLUTION 常量，
  每一项都必须能在 bench/eval_results/*.json 或 GEOAGENT_PROGRESS.md 里复核
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CAT_LABEL = {
    "single_tool": "单工具调用",
    "multi_tool": "多工具串联",
    "out_of_scope": "越界拒答",
}

# 版本演进实测记录 —— 每一行的数字都来自当时那一轮的 full run，
# 来源见 GEOAGENT_PROGRESS.md 的「版本演进」表。改这里等于改历史，务必有出处。
EVOLUTION = [
    # (版本, multi_tool 精确率, 说明)
    ("v0 · 单轮直问（无编排）", 0.00, "模型一次只能吐一个工具，多步链路结构性不可能"),
    ("v1 · 临时多轮循环", 0.30, "--turns>1 手工循环，无状态图、无重试"),
    ("v2 · LangGraph 接入", 0.30, "plan→execute→reflect→summarize 接进评测，但指标被截断掩盖"),
    ("v3 · 修 max_tokens", 0.741, "发现 65% 计划输出被 384 上限砍断；27 条时崩于 GPU 降频"),
    ("v4 · 加负向清单", 0.700, "禁止语义联想加步骤；首次跑满 40 条"),
    ("v5 · 必须触发+修标注", 0.825, "补 path 类漏标 compute_slope（5 条）"),
    ("v6 · 决策表重写", 0.825, "按「最终目标」而非「任务类型」定链路长度"),
    ("v7 · 收紧下载触发", 0.775, "过度矫正，牺牲了 multi 换 single"),
    ("v8 · 定稿", 0.850, "三次独立改版合计均停在 80% → 判定到标注噪声天花板，停止调参"),
    ("v9 · 统计类不前置坡度", 0.550, "单工具 100% 但多工具崩到 55% —— 零和搬运，暴露评测集自相矛盾"),
    ("v10 · 改「看点没点名」", 0.800, "多工具恢复至 80%，定位到 5 条标注冲突样本"),
    ("v11 · 统一标注+精简提示词", 0.925, "消除评测集内部矛盾，合计 95.0%"),
    ("v12 · 修完 3 个真机 bug", 0.975, "主集 97.5% / 保留集 95.5% → 停止调参"),
]

# 阶段进度：状态 / 完成情况 / 关键产出
PHASES = [
    ("Week 0", "基线量化", "done", "建立评测口径与性能基线",
     "11 工具 JSON Schema；100 条评测集；嵌入式 llama.cpp 基准 51.3 tok/s"),
    ("Week 1", "工具层", "done", "把 GIS 能力封装为大模型可调用工具",
     "DEM 读取 / 地形因子 / 代价栅格 / 路径规划 / 三种地貌分类 / 分区统计 / 导出，共 11 个"),
    ("Week 2", "编排层", "done", "LangGraph 计划-执行-反思状态图 + 持久化",
     "plan→execute→reflect→summarize；SQLite Checkpointer；领域规则反射器"),
    ("Week 3", "MCP 协议层", "done", "以 MCP 对外暴露工具集",
     "mcp/custom/geo_mcp_server；任意 MCP 客户端可直接调用本地分析能力"),
    ("Week 4", "RAG 知识层", "done", "领域知识入库 + 检索增强，支撑术语/算法原理问答",
     "9 份文献 → 290 块；bge-small-zh GGUF 48MB（llama.cpp/CPU）；15 条问答评测 recall@5 1.00"),
    ("Week 5", "评测与消融", "doing", "归因修复 → 4 组消融 → 出报告回填简历",
     "归因修复完成：主集 80.0% → 97.5%，保留集复检 95.5%；4 组消融已跑完"),
    ("Week 6", "前端与部署", "todo", "让 Agent 在网页端真正可用",
     "缺 HTTP 端点（/api/v1/agent/chat）+ 前端对话面板；Docker Compose 一键部署"),
]

# ── 指标释义 ────────────────────────────────────────────────────────────
# 每条释义必须带一个本项目的真实例子（来自 backend/app/eval/dataset.json 或
# bench/eval_results/v8_*.json），禁止「效果更好」「收益明显」这类空话。
GLOSSARY = [
    ("工具链精确率", "tool_exact",
     "模型给出的工具调用序列，与标准答案<b>逐项相同、顺序相同、不多不少</b>，才算 1 分。",
     "「下载四姑娘山的真实高程数据并计算坡度」标准答案 "
     "<code>[download_srtm, compute_slope]</code>，模型输出同样两项 → 1 分；"
     "「锡林郭勒草原哪里好走」标准答案 <code>[compute_cost_surface]</code>，"
     "模型输出 <code>[compute_slope, compute_cost_surface]</code> → 0 分（多做了一步）。",
     "衡量的是：<b>用户一句话下达后，Agent 规划的这条流水线能不能不多不少地直接跑通</b>。"
     "它同时考「选对工具」和「不做无用功」，是最严的一项。"),

    ("工具集合 F1", "tool_set_f1",
     "只看<b>用到了哪些工具</b>的重合度，不看顺序、不计重复。",
     "期望 <code>{compute_cost_surface}</code>，预测 "
     "<code>{compute_slope, compute_cost_surface}</code>：预测 2 个里命中 1 个 → 精确率 1/2；"
     "期望 1 个全被命中 → 召回率 1/1；F1 = 2×0.5×1.0÷(0.5+1.0) = 0.667。",
     "总精确率 80.0% 而集合 F1 91.5%，这个 11.5 个百分点的差额说明："
     "<b>模型基本都选对了该用的工具，丢分主要来自「多调一步或漏调一步」，不是「选错工具」</b>。"),

    ("顺序正确率", "tool_order",
     "标准答案的步骤序列里，有多大比例被模型<b>按原来的先后顺序</b>保留下来"
     "（最长公共子序列长度 ÷ 期望长度）。",
     "期望 <code>[A, B, C]</code>，预测 <code>[A, C, B]</code>："
     "能保住的最长顺序是 <code>[A, B]</code> 或 <code>[A, C]</code>，长度 2 → 2÷3 = 0.667。",
     "衡量的是<b>步骤依赖有没有搞反</b>。比如必须先有坡度栅格才能算通行代价，"
     "顺序反了整条链就跑不通。当前 95.0% 说明这类错误很少。"),

    ("bbox 参数正确", "param_bbox",
     "分析范围的四个边界值 <code>[西, 南, 东, 北]</code> 与标准答案相差都在 0.01° 以内"
     "（约 1.1 km），<b>且四个位置的顺序不能错</b>。",
     "标准答案 <code>[103.5, 30.2, 104.5, 31.0]</code>（成都周边），"
     "模型输出 <code>[103.5, 31.0, 104.5, 30.2]</code> —— 四个数值都有，"
     "但南北写反了 → 判 0 分。经纬度顺序错了等于分析区域错了。",
     "⚠ <b>当前 100% 是虚高，暂时不能写进简历</b>：评测集里的 bbox 与地名词典共用同一份数据，"
     "模型相当于在抄答案。用词典外区域另做的 12 条对照集，真值 12/12。"),

    ("拒答正确率", "refusal_correct",
     "两个方向都算：越界问题<b>必须</b>明确说做不了；正常问题<b>不许</b>推脱。"
     "任一方向违反即 0 分。",
     "「分析火星地形」「预测明天天气」这类越界问题（20 条），回答「超出能力范围」→ 1 分；"
     "「计算成都周边的坡度」这类正常问题（80 条），如果也答「做不了」→ 0 分。",
     "当前 20/20 且工具类零误拒。这一项要两头看：<b>只把拒答做对很容易（全都拒绝就满分），"
     "难的是同时不误拒正常请求</b>。"),

    ("每样本 LLM 调用次数", "n_llm_calls",
     "完成一条任务平均要问大模型几次。",
     "理想情况：一次规划直接给出完整链路 → 1 次。"
     "如果参数填错被反思节点打回重来，就会变成 2 次、3 次。",
     "接入 LangGraph 前是 2.17 次，现在是 1.05 次，"
     "意味着<b>一次规划就能把链路定完，几乎不需要回头重试</b>。"),

    ("单样本延迟 p50", "elapsed_p50",
     "100 条样本的耗时从短到长排序，取<b>正中间那条</b>的耗时。p90 是排在第 90 位的那条。",
     "100 条里最快的约 4 s、最慢的因 GPU 重试超过 40 s。"
     "用平均值会被这几条慢样本拉偏，看不出常态。",
     "当前 p50 = 9.8 s，在<b>本机 RTX 2060 6GB + Qwen3.5-4B Q4_K_M 全量本地推理</b>下测得，"
     "没有任何云端 API 参与。"),
]

CATEGORY_GLOSSARY = [
    ("单工具调用", "40 条", "一句话用一个工具就能完成。",
     "「计算成都周边的坡度」→ <code>[compute_slope]</code>；"
     "「统计珠峰多少比例的坡度在 15 度以下」→ <code>[zonal_statistics]</code>。",
     "考的是<b>能不能从一句话里认出该用哪个工具</b>，以及不要画蛇添足。"),
    ("多工具串联", "40 条", "需要两个以上工具按依赖顺序串起来，后一步要吃前一步的产出。",
     "「下载四姑娘山的真实高程数据并计算坡度」→ "
     "<code>download_srtm</code> → <code>compute_slope</code>；"
     "「找一条从 A 到 B 坡度小于 15 度的路线」→ "
     "<code>compute_slope</code> → <code>compute_cost_surface</code> → <code>plan_route</code>。",
     "<b>这一项最能说明它是「Agent」而不是「函数调用」</b>："
     "没有编排能力的模型一次只能吐一个工具，此项理论上限为 0。"),
    ("越界拒答", "20 条", "超出系统能力范围，正确行为是明确拒绝而不是硬编一个答案。",
     "「分析火星地形」「预测明天天气」→ 应回答「超出能力范围」。",
     "考的是<b>会不会胡编</b>。地理分析场景下，编一个看似合理的错误结论比直接说不会更危险。"),
]

# ── 失败模式归因规则 ────────────────────────────────────────────────────
# v8 的每条失败样本按规则自动归类；跑完新评测后本表会自动更新。
FAILURE_RULES = [
    ("A 类 · 多插了一次坡度计算",
     lambda exp, pred: (
         set(exp) < set(pred)
         and set(pred) - set(exp) == {"compute_slope"}
         and bool(set(exp) & {"compute_cost_surface", "zonal_statistics"})
     ),
     "判它错是对的。读源码确认：<code>compute_cost_surface</code>（terrain_tools.py:179）"
     "和 <code>zonal_statistics</code>（stats_tools.py:98）都从 <code>terrain_cache</code> "
     "一次性拿到坡度、坡向、曲率，前置 <code>compute_slope</code> 是重复劳动，"
     "白花一次工具调用的时间。",
     "改 planner 决策表：下游工具内部已算坡度的，不得前置 compute_slope"
     "（用户明确要「坡度图」时除外）。"),

    ("B 类 · 三种地貌分类方法没定默认",
     lambda exp, pred: (
         bool([t for t in exp if t.startswith("classify_")])
         and bool([t for t in pred if t.startswith("classify_")])
         and set(t for t in exp if t.startswith("classify_"))
         != set(t for t in pred if t.startswith("classify_"))
     ),
     "两边都有理，属于<b>约定缺失</b>而非模型犯蠢：工具自述里 geomorphons 写着"
     "「精度与速度均衡，推荐默认使用」，模型照做了；但评测集标的是 rules。"
     "用户说「做个地貌分类」时并没指定方法。",
     "提示词定死「未指明方法时默认 classify_geomorphons」，"
     "评测集相关条目同步改标注，并注明这是<b>口径统一</b>不是模型变强。"),

    ("C 类 · 漏掉明确要求的数据下载",
     lambda exp, pred: "download_srtm" in exp and "download_srtm" not in pred,
     "真错。样本原话是「<b>获取</b>贡嘎山的 SRTM 数据然后算坡度」"
     "「<b>先下载</b>三峡高程数据，再分析那里的坡度」，"
     "动词已经写明要下载，模型却只给了 compute_slope。",
     "提示词加硬规则：出现「下载 / 获取 / 抓取 … 数据」时必须含 download_srtm。"),

    ("D 类 · 没要求却自作主张下载",
     lambda exp, pred: "download_srtm" not in exp and "download_srtm" in pred,
     "轻度冗余。样本原话「三峡用深度学习模型分类地貌」没提数据来源，"
     "模型自己加了一步下载。结果没错，但多花时间。",
     "提示词补反向规则：用户未提数据来源时不主动插入 download_srtm。"),

    ("E 类 · 路线链路少了一步",
     lambda exp, pred: "plan_route" in exp and "plan_route" in pred
     and "compute_slope" in exp and "compute_slope" not in pred,
     "真错。只要最终目标是「一条路线」，链路就固定是 "
     "<code>compute_slope</code> → <code>compute_cost_surface</code> → "
     "<code>plan_route</code> 三步。模型把第一步省了 —— "
     "多半是因为提示词里「不要重复算坡度」的规则被过度套用到了这一行。",
     "提示词里把路线链路单独提为「规则 1」，写明三步固定、"
     "即使前面加了 download_srtm 也不省。"),
]


def classify_failure(exp: list, pred: list) -> tuple:
    """把一条失败样本归入已知模式；都匹配不上则归为「其他」。"""
    for name, rule, why, fix in FAILURE_RULES:
        try:
            if rule(exp, pred):
                return name, why, fix
        except Exception:  # noqa: BLE001
            continue
    return "其他", "未归入已知模式，需要单独看。", "人工复核后再定。"

ABLATION_GROUPS = [
    ("g1_react", "① 临时多轮试探", "没有状态图，也没有自我校验；拿到工具结果后直接进下一步"),
    ("g2_noreflect", "② 有编排无校验", "有计划-执行-总结的状态图，但关掉自我校验，结果直接放行"),
    ("g3_baseline", "③ 完整编排（基线）", "计划→执行→反思→总结，含参数校验与失败重试"),
    ("g4_rag", "④ 完整编排 + 知识库", "在基线之上，规划前先检索领域文献作为上下文"),
]


def _ablation_rows(results_dir: Path) -> str:
    """从 ab_*.json 生成消融对比表；没跑完的组标注出来而不是填 0。"""
    import statistics as _st

    rows: List[str] = []
    cache: Dict[str, Dict[str, Any]] = {}

    for key, title, desc in ABLATION_GROUPS:
        details: List[Dict[str, Any]] = []
        complete = True
        for cat in ["single_tool", "multi_tool", "out_of_scope"]:
            p = results_dir / f"ab_{key}_{cat}.json"
            got = _load(p) if p.exists() else None
            n_expect = 20 if cat == "out_of_scope" else 40
            if not got:
                complete = False
                continue
            if len(got) < n_expect:
                complete = False
            details += got
        if not details:
            rows.append(
                f"<tr><td><b>{title}</b></td><td>{desc}</td>"
                f"<td colspan='5' class='dim'>尚未跑</td></tr>"
            )
            continue

        def _ex(cat: str) -> str:
            sub = [d for d in details if d.get("category") == cat]
            vals = [d["score"].get("tool_exact") for d in sub
                    if d["score"].get("tool_exact") is not None]
            return "—" if not vals else _pct(_avg(vals))

        # 工具类与拒答类分开取：拒答类不参与工具链精确率
        te = [d["score"].get("tool_exact") for d in details
              if d["score"].get("tool_exact") is not None]
        rc = [d["score"].get("refusal_correct") for d in details
              if d["score"].get("refusal_correct") is not None]
        calls = _avg([d.get("n_llm_calls") or 1 for d in details])
        p50 = _st.median([d.get("elapsed", 0.0) for d in details])
        cache[key] = _avg(te)

        rows.append(
            f"<tr><td><b>{title}</b>{'' if complete else ' ⚠'}</td><td>{desc}</td>"
            f"<td class='num strong'>{_pct(_avg(te))}</td>"
            f"<td class='num'>{_ex('single_tool')}</td>"
            f"<td class='num'>{_ex('multi_tool')}</td>"
            f"<td class='num'>{_pct(_avg(rc))}</td>"
            f"<td class='num'>{calls:.2f}</td>"
            f"<td class='num'>{p50:.1f}s</td></tr>"
        )

    # 组间差值的解读（差值小于 3 个百分点时不下结论）
    notes: List[str] = []
    SE = 0.02
    def _diff(a: str, b: str, label: str) -> None:
        va, vb = cache.get(a), cache.get(b)
        if va is None or vb is None:
            return
        d = vb - va
        judge = (
            "差值小于 3 个百分点，属随机波动范围，不能据此下结论"
            if abs(d) < 0.03 else
            f"{label}确实带来 {'提升' if d > 0 else '下降'}"
        )
        notes.append(f"<li><b>{label}</b>：{d * 100:+.1f} 个百分点 —— {judge}。</li>")
    _diff("g1_react", "g3_baseline", "状态图编排")
    _diff("g2_noreflect", "g3_baseline", "自我校验")
    _diff("g3_baseline", "g4_rag", "知识库检索")

    note_html = (
        f'<ul style="margin-top:10px">{"".join(notes)}'
        f'<li class="dim">100 条样本的标准误约 {SE * 100:.0f} 个百分点，'
        f'更小的差值需要更多样本才能确认。</li></ul>'
        if notes else ""
    )
    return "".join(rows) + "</tbody></table>" + note_html


# ── Week 5 执行计划（每步都要有可验证的产出）────────────────────────────
WEEK5_PLAN = [
    ("W5-0 ✅", "补工具层算法语料（含 Geomorphons）",
     "RAG 知识库目前只有 9 份 literature 文档，问「什么是 Geomorphons」会召回无关内容。"
     "内容取自 <code>classify_tools.py</code> 源码与实测数据表，不是虚构文献。",
     "新增语料后重建索引，15 条问答评测 recall@5 不退化，且新增 Geomorphons 问答可命中"),
    ("W5-1 ✅", "修 A 类：禁止冗余坡度计算",
     "改 planner 决策表，明确 compute_cost_surface / zonal_statistics / classify_* "
     "内部已含坡度，不得前置。",
     "单工具类精确率 75.0% → <b>97.5%</b>（判据：用户有没有点名要算坡度）"),
    ("W5-2 ✅", "修 B 类：定死分类方法默认",
     "提示词与评测集双向对齐，默认取 geomorphons。",
     "多工具类 +5 条、单工具类 +1 条；报告中明确标注这是口径统一"),
    ("W5-3 ✅", "修 C/D 类：下载步骤判定",
     "显式动词必须触发下载；未提数据来源不主动下载。",
     "multi_003 / multi_005 / single_031 三条归位"),
    ("W5-4 ✅", "补 reflector 开关",
     "计划里的第 4 组消融需要「关掉反思」这一档，但 langgraph 图里 reflect 是硬编码节点，"
     "目前没有开关，导致 4 组消融只能做 3 组。",
     "新增环境变量可关掉 reflect 节点，4 组配置全部可跑"),
    ("W5-5 ✅", "跑 4 组消融（每组 100 条）",
     "固定模型与提示词，只改工作方式：①无状态图的临时多轮试探 → ②有编排但关掉自我校验 → "
     "③完整编排（计划-执行-反思-总结）→ ④完整编排 + 规划前检索领域文献。"
     "用断点续跑扛 GPU 降频崩溃。",
     "已产出 <code>bench/ablation.md</code>：①40.0% → ③96.2%（编排 +56.2 点），"
     "②92.5%（校验 +3.7 点），④91.2%（知识库 <b>-5.0 点，负收益</b>）。"
     "已回填 A/B/C 三版简历：工具选择准确率 40.0% → <b>97.5%</b>"),
    ("W5-6 ✅", "最小可用网页对话（从 Week 6 提前）",
     "后端加 <code>/api/v1/agent/chat</code>，前端加对话面板。"
     "Week 6 剩下的 Docker Compose / README / 演示视频不动。",
     "浏览器里输入一句中文，能看到规划链路与结果 —— 面试可当场演示"),
]

# Week 6：把 Agent 从"独立网页"改成"主系统里的一块面板"
# 起因：W5-6 交的 agent_chat.html 是独立页面，用户实测后指出 —— 脱离系统、
# 「你好」被拒答、且回复只有纯文字（没有数据/表/图/图层）。诊断后发现是后端
# 数据通路断了 5 处，不是前端没画。详见 IMPROVEMENT_PLAN.md Week 6 章。
WEEK6_PLAN = [
    ("W6-1 ✅", "让产物能被访问",
     "工具把 GeoJSON/CZML 写进 geoagent_artifacts/，但 HTTP 只挂载了 "
     "cesiumjs_debug_outputs/ —— 前端根本下载不到。",
     "加 /artifacts 挂载；产物返回值补 url 字段。GET /artifacts/xxx/slope.geojson 可下载"),
    ("W6-2 ✅", "把结构化结果传出来",
     "工具算好的「每级坡度多大面积、8 类地貌各占几成、路径多长爬升多少」"
     "在回传时被丢掉了 —— 执行记录只留了工具名和耗时。",
     "新增 result_view.py 裁剪白名单；JSON 里能看到 zonal 的 classes 数组"),
    ("W6-3 ✅", "寒暄不再被当成越界任务",
     "以前「你好」也要跑一遍大模型规划，19 秒后回一句机器话，"
     "还把内部提示词模板（「向用户说明…」）当成答案吐出来。",
     "规则直答：<b>19.2 s → 0.2 s</b>，回复是人话；拒答不再是模板泄漏"),
    ("W6-4 ✅", "导出地图加载能力",
     "加载后端的整套管道（分批、注册侧栏、数值提示）是封闭的，"
     "Agent 拿不到，只能另写一套 —— 那就是两套渲染行为。",
     "新增 window.TerrainBackendBridge（只加导出，未改内部逻辑）"),
    ("W6-5 ✅", "面板进主系统",
     "Agent 不再是独立页面，而是主页面里第 15 个悬浮窗，"
     "与「坡度坡向分析」同款拖拽/折叠/置顶。",
     "顶部菜单「智能体分析助手」可开面板；主 HTML 仅末尾追加 2 个 script"),
    ("W6-6 ✅", "结果变成表和图",
     "按结果类型分派：分级统计表 + 面积柱状图、地类构成饼图 + 图例色卡、"
     "路径里程/爬升指标卡。",
     "问「统计坡度分级」能出表格 + 图表 + 指标卡，不再是纯文字"),
    ("W6-7 ✅", "结果落到三维地球上",
     "矢量产物一键叠加，自动注册进主系统的侧栏图层树，可显隐、可定位。",
     "真机冒烟：侧栏图层数 <b>0 → 1</b>，出现 slope_deg 图层"),
    ("W6-8 ✅", "所见即所问",
     "分析范围默认取当前相机视野，相机移动时实时刷新；"
     "视野过大（如对着整个地球）会被拦下并提示放大。",
     "飞到贡嘎山后范围自动变为 101.58,29.52 → 102.16,29.80"),
    ("W6-9 ✅", "入口独立且常驻（用户反馈）",
     "上一版把入口塞在「空间分析」下拉里 —— 但 Agent 不是空间分析工具，"
     "它该是贯穿全系统的对话入口（对标商业 GIS 的做法：独立菜单 + 悬浮按钮）。",
     "顶部**独立常驻菜单项**，按项目约定只用图标（顶部栏本身常驻，不需要再加悬浮按钮）"),
    ("W6-10 ✅", "用 Cesium 自带地形，不再拿合成地形糊弄（用户反馈）",
     "用户没上传 DEM 时，后端会回退到<b>合成的正弦曲面</b>，"
     "算出来的坡度与实际地表毫无关系（冒烟截图里整片绿油油就是它）。",
     "前端在视野内按 128×128 采样 Cesium World Terrain，落成 GeoTIFF 交给后端；"
     "贡嘎山实测平均坡度 <b>4.79° → 20.33°</b>，最大坡度 8.56° → <b>54.25°</b>"),
    ("W6-11 ✅", "意图分层：别让模型只会分析地形（用户反馈，本轮核心）",
     "planner 只给了模型<b>两条路</b>：做地形分析 / 拒答。"
     "于是「这里是什么地方」「你有什么功能模块」「跳转到海南省」全被拒答或硬做分析。"
     "用户判断得准：<b>不是模型参数小，是我们没给它别的路走</b>。",
     "五类意图（analysis / knowledge / action / chat / refuse）+ <b>两段式分类</b>"
     "（先用极短提示词单独定意图，是 analysis 才进工具链）+ 地名反查 + 省级地名库（93 条）"),
]

# 真机冒烟（系统 Chrome + SwiftShader 软件渲染，脚本 cesium_old/_smoke_agent.js）
WEEK6_SMOKE = [
    ("入口：顶部独立菜单项 + 右下角常驻悬浮按钮（均不隶属任何功能分组）", True,
     "此前误挂在「空间分析」下拉里 —— 它不是一个空间分析工具"),
    ("悬浮按钮开合面板、按钮明暗跟随状态", True, "复用系统 .functionWin 的拖拽/折叠/关闭"),
    ("问「现在的视野是什么区域范围」（元问题）", True,
     "本地直答，<b>0 次工具调用、0 张结果卡</b>；以前会跑一遍大模型再拒答"),
    ("视野还是全球时问「算一下坡度」", True,
     "被拦下：提示放大地图或点明地名，<b>不再让规划器自选区域乱算</b>"),
    ("飞到贡嘎山问「算一下当前视野的坡度」", True,
     "数据来源「Cesium 世界地形」；平均坡度 <b>20.33°</b>、最大 54.25°、标准差 9.01°"),
    ("点「叠加到地图」", True, "侧栏图层数 0 → 1，图层 slope_deg [Analysis]"),
    ("问「这里有什么国家/地区」（常识问答）", True,
     "意图判定 <b>knowledge</b>，不再拒答；主权表述正确：「中国台湾省和福建省，都是中国的一部分」"),
    ("问「你有什么功能模块」（元问题）", True,
     "意图判定 <b>chat</b>，正常介绍能力；以前换个说法就命不中关键词表、被拒答"),
    ("说「为跳转到海南省区域」（系统操作）", True,
     "意图判定 <b>action</b>，下发 flyTo 动作；bbox 用词典精确值 <b>[108.6, 18.15, 111.05, 20.15]</b>"
     "（模型自己编的是 [110,20,118,25]，把整个南海都框进去了）"),
]

# 回归评测（v13）：改了 executor / main / summarizer 三处后端代码，必须确认分数没掉。
# ⚠ tool_exact 只在"有工具期望"的样本上算，拒答题看 refusal_correct ——
#    直接对全部条目取平均会得出「主集 76.9%」这种错误数字。
WEEK6_REGRESSION = [
    ("单工具类", 40, "97.5%", "1.000", "40/40", "持平（v13 也是 100%，本轮 39/40）", True),
    ("多工具类", 40, "95.0%", "0.988", "40/40", "持平（v13 也是 95%）", True),
    ("越界拒答", 20, "—", "—", "20/20", "持平", True),
    ("主集合计", 100, "96.25%", "0.990", "100/100", "↓ 1.25 点（v13 = 97.5%，差约 1 条样本）", None),
    ("保留集（未参与调参）", 22, "81.8%", "0.880", "—", "↓ 18 点（v13 = 100%）—— 泛化能力的代价", False),
]


# ---------------------------------------------------------------- Week 7
# 起因（用户实测反馈）：
#   ① Agent 不保留、也不阅读上下文 —— 上一轮聊完五指山，下一句「跳转到这个地方」
#      它答"请提供具体地名"；
#   ② 同样操作换个地名就变样 ——「跳转到五指山」秒回，「跳转到阿尔卑斯山」
#      先跑几分钟地形采样才跳转。
WEEK7_PLAN = [
    ("W7-1 ✅", "记忆存储层",
     "SQLite 五张表：turns（会话轮次）/ spatial_focus（空间焦点卡片）/ "
     "region_memory（常用区域，含访问次数与时间衰减）/ user_profile / confirmed_facts。"
     "刻意<b>不用 LangGraph checkpointer</b> —— 它存的是整个图状态快照"
     "（我们的 state 里有 DEM 路径、产物列表、trace 等大对象），"
     "而且项目是双运行时，checkpointer 只在图分支生效会造成行为分叉。",
     "《三·六》设计文档已落盘；<code>memory/store.py</code> 单测通过"),
    ("W7-2 ✅", "跨轮指代消解",
     "划清边界：<b>规则只做确定性替换</b>（「这个地方」→「五指山一带（北纬18.5°–19.5°…）」），"
     "<b>意图判断仍交给模型</b>。代词指向什么是已经发生过的事实，查库即可；"
     "用户想干什么才需要语义理解。另外区分「这里」=当前视野、「刚才那个」=上一轮焦点。",
     "补全后的句子与视图、历史一起交给模型，泛化能力仍由模型提供"),
    ("W7-3 ✅", "接入请求链路",
     "读：取最近 6 轮 + 空间焦点 → 指代替换 → 一并注入提示词（关键约束后置）。"
     "写：本轮结束落轮次、更新焦点、分析类任务进长期区域记忆、超窗口的旧轮整条删除。",
     "「这个区域」类问题第一次真正被理解"),
    ("W7-4 ✅", "前端会话管理",
     "session_id 持久化到 localStorage（以前硬编码 'web-panel'，所有会话共用一个 ID），"
     "顶栏加纯图标「新会话」按钮，对话区给出<i>结合上文理解</i>的可见提示。",
     "记忆必须可见 —— 猜错了用户要能立刻发现并纠正"),
    ("W7-5 ✅", "修「换地名就多绕几分钟」",
     "根因不在后端（<code>classify_intent</code> 对 9 个句式实测 8 个正确）："
     "<b>前端在发请求之前就无条件采样了 128×128 高程点</b>，"
     "「跳转到阿尔卑斯山」也要先等几分钟才把请求发出去。"
     "改为按需采样 + 后端 <code>need_terrain</code> 回退补采。",
     "三种跳转问法全程 0 次采样，耗时 3.9–5.5 s"),
    ("W7-6 ✅", "验证",
     "多轮真机冒烟（<code>cesium_old/_smoke_memory.js</code>）+ 全量评测确认单轮准确率不降。",
     "见下方冒烟与回归表"),
]

WEEK7_SMOKE = [
    ("入口为纯图标（顶部菜单常驻，不需要文字占位）", True, "右下角悬浮按钮已按要求移除"),
    ("会话 ID 持久化到 localStorage", True, "首次发送时生成，刷新页面后上文仍可续接"),
    ("第 1 句「我想看看五指山」", True,
     "意图 <b>action</b> → 直接跳转（以前只回一段五指山的风土介绍）；<b>未触发任何地形采样</b>"),
    ("第 2 句「跳转到这个地方」", True,
     "记忆：「这个地方」→ <b>五指山一带（北纬18.50°–19.50°，东经109.50°–110.50°）</b>"
     "；改造前答的是「请提供具体的地名或坐标」"),
    ("第 3 句「跳转到阿尔卑斯山」（换地名）", True,
     "仍是 <b>action</b>、<b>仍未触发采样</b>；后端实测 4.4 s 返回"),
    ("第 4 句「跳转到这个地方」", True,
     "记忆跟上最新一轮 → <b>阿尔卑斯山一带（北纬46.00°–48.00°，东经6.86°–15.00°）</b>"),
    ("点「新会话」图标", True, "对话区清空、会话 ID 更换；旧会话记忆仍留在库里不误删"),
]

# 回归评测（v19）：加了记忆层之后，确认单轮准确率没有下降。
# 评测时显式关闭记忆（GEOAGENT_MEMORY=0）—— 评测集是单轮任务且所有样本
# 共用默认 session_id，开着记忆会让第 N 题读到前 N-1 题的历史。
WEEK7_REGRESSION = [
    ("单工具类", 40, "100.0%", "1.000", "40/40", "↑ 2.5 点（v18 = 97.5%）", True),
    ("多工具类", 40, "97.5%", "0.992", "40/40", "↑ 2.5 点（v18 = 95.0%）", True),
    ("越界拒答", 20, "—", "—", "20/20", "持平", True),
    ("主集合计", 100, "98.75%", "0.996", "100/100", "↑ 2.5 点（v18 = 96.25%）—— 历史最高", True),
    ("保留集（未参与调参）", 22, "81.8%", "0.921", "—", "与 v18 持平；与主集仍有 17 点差距", False),
]

# GBNF 约束解码 A/B 实测（bench/_test_grammar.py，24 条意图分类样本）。
# 结论出乎意料：**无约束时 JSON 解析成功率已经是 100%** ——
# 说明 GBNF 想解决的"格式不合法"在本项目的意图分类环节并不存在，
# 它唯一可能的价值是用 enum 收窄选择空间来提升决策准确率。
GBNF_AB = [
    ("JSON 解析成功率", "100.0%（24/24）", "格式问题在实测中不存在", False),
    ("意图判定准确率", "91.7%（22/24）", "失败的 2 条：「统计珠峰坡度在15度以下的比例」→ refuse、"
     "「这片区域属于什么地貌类型」→ knowledge", False),
]


def _load(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["details"] if isinstance(data, dict) else data



def _avg(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _pctl(values: List[float], p: float) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


def compute_stats(details: List[Dict[str, Any]]) -> Dict[str, Any]:
    scores = [d["score"] for d in details]
    elapsed = [d.get("elapsed", 0.0) for d in details]
    calls = [d.get("n_llm_calls") or 1 for d in details]
    return {
        "n": len(details),
        "parsed": _avg([s.get("parsed") for s in scores]),
        "tool_exact": _avg([s.get("tool_exact") for s in scores]),
        "tool_set_f1": _avg([s.get("tool_set_f1") for s in scores]),
        "tool_order": _avg([s.get("tool_order") for s in scores]),
        "param_bbox": _avg(
            [1.0 if s.get("param_bbox") else 0.0 for s in scores if s.get("param_bbox") is not None]
        ),
        "refusal": _avg([s.get("refusal_correct") for s in scores]),
        "completed": _avg([s.get("completed") for s in scores]),
        "elapsed_p50": statistics.median(elapsed) if elapsed else 0.0,
        "elapsed_p90": _pctl(elapsed, 0.9),
        "calls": _avg(calls),
    }


def _svg_bar_chart(evolution: List[tuple], width: int = 860, height: int = 260) -> str:
    """版本演进柱状图（纯 SVG，无依赖）。"""
    pad_l, pad_r, pad_t, pad_b = 46, 16, 18, 62
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(evolution)
    slot = plot_w / n
    bar_w = slot * 0.56

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="多工具类工具链精确率版本演进">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    # 网格线
    for i in range(5):
        y = pad_t + plot_h * i / 4
        val = 1.0 - i * 0.25
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="#e6e8eb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" font-size="11" fill="#8b939c" '
            f'text-anchor="end">{val * 100:.0f}%</text>'
        )
    # 柱
    for i, (label, val, _desc) in enumerate(evolution):
        x = pad_l + slot * i + (slot - bar_w) / 2
        h = plot_h * val
        y = pad_t + plot_h - h
        color = "#2f6feb" if i < len(evolution) - 1 else "#d9534f"
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
            f'fill="{color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" font-size="12" '
            f'font-weight="600" fill="{color}" text-anchor="middle">{val * 100:.0f}%</text>'
        )
        # 标签两行：版本 + 说明
        cx = x + bar_w / 2
        ver = label.split(" · ")[0]
        tip = label.split(" · ")[1] if " · " in label else ""
        parts.append(
            f'<text x="{cx:.1f}" y="{pad_t + plot_h + 18:.1f}" font-size="11" '
            f'font-weight="600" fill="#3d4450" text-anchor="middle">{ver}</text>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{pad_t + plot_h + 34:.1f}" font-size="10" '
            f'fill="#8b939c" text-anchor="middle">{tip}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def build_html(
    runs: Dict[str, List[Dict[str, Any]]],
    generated: str,
    heldout: Optional[List[Dict[str, Any]]] = None,
    tag: str = "",
    results_dir: Optional[Path] = None,
) -> str:
    stats = {k: compute_stats(v) for k, v in runs.items()}
    all_details = [d for v in runs.values() for d in v]
    overall = compute_stats(all_details)

    te_all = [
        d["score"].get("tool_exact")
        for d in all_details
        if d["score"].get("tool_exact") is not None
    ]
    overall_exact = _avg(te_all)

    # ---- 保留集（未参与调参）----
    ho_exact = None
    ho_refusal = None
    ho_n = 0
    if heldout:
        ho_te = [d["score"].get("tool_exact") for d in heldout
                 if d["score"].get("tool_exact") is not None]
        ho_rc = [d["score"].get("refusal_correct") for d in heldout
                 if d["score"].get("refusal_correct") is not None]
        ho_exact = _avg(ho_te)
        ho_refusal = _avg(ho_rc)
        ho_n = len(heldout)

    # ---- 指标卡 ----
    cards = [
        ("总体工具链精确率", _pct(overall_exact), "100 条全量逐项同序完全一致<br>最严口径：错一步即判错"),
        ("未见过的题", _pct(ho_exact) if ho_exact is not None else "—",
         f"保留集 {ho_n} 条，改提示词时从未看过<br>"
         f"与主集差距 {abs((overall_exact or 0) - (ho_exact or 0)) * 100:.1f} 个百分点"
         if ho_exact is not None else "尚未跑保留集"),
        ("多工具类", _pct(stats.get("multi_tool", {}).get("tool_exact")),
         "接入 LangGraph 前 0.00 → 现 0.85<br>最能说明「Agent 会编排」的一项"),
        ("单工具类", _pct(stats.get("single_tool", {}).get("tool_exact")),
         "历史最高 0.825<br>曾因链路模板硬编码跌到 0.375"),
        ("越界拒答", f"{sum(1 for d in runs.get('out_of_scope', []) if d['score'].get('refusal_correct') == 1.0)}/20",
         "越界问题全数正确拒绝<br>且工具类零误拒"),
        ("工具集合 F1", _pct(overall.get("tool_set_f1")),
         "高于精确率 → 说明工具基本选对<br>丢分在「多一步/少一步」而非选错"),
        ("每样本 LLM 调用", f"{overall.get('calls'):.2f}",
         "接入前 2.17 次（含重试）<br>现在 1 次规划即成型"),
        ("单样本延迟 p50", f"{overall.get('elapsed_p50'):.1f}s",
         f"p90 {overall.get('elapsed_p90'):.1f}s<br>RTX 2060 / Qwen3.5-4B Q4_K_M"),
        ("领域问答 recall@5", "1.00", "15 条自建问答评测集<br>命中正确文档率同为 1.00"),
        ("推理吞吐", "51.3 tok/s",
         "嵌入式 llama.cpp + CUDA sm_75<br>较 Ollama HTTP 快 28%"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="card-label">{lbl}</div>'
        f'<div class="card-value">{val}</div>'
        f'<div class="card-note">{note}</div></div>'
        for lbl, val, note in cards
    )

    # ---- 分项表 ----
    row_html = []
    for cat in ["single_tool", "multi_tool", "out_of_scope"]:
        if cat not in stats:
            continue
        s = stats[cat]
        row_html.append(
            f"<tr><td><b>{CAT_LABEL[cat]}</b></td><td>{s['n']}</td>"
            f"<td class='num strong'>{_pct(s['tool_exact'])}</td>"
            f"<td class='num'>{_pct(s['tool_set_f1'])}</td>"
            f"<td class='num'>{_pct(s['tool_order'])}</td>"
            f"<td class='num'>{_pct(s['refusal'])}</td>"
            f"<td class='num'>{s['elapsed_p50']:.1f}s</td>"
            f"<td class='num'>{s['calls']:.2f}</td></tr>"
        )
    rows = "".join(row_html)

    # ---- 阶段进度 ----
    phase_html = []
    for code, name, state, goal, deliverable in PHASES:
        cls = {"done": "done", "doing": "doing", "todo": "todo"}[state]
        badge = {"done": "已完成", "doing": "进行中", "todo": "未开始"}[state]
        phase_html.append(
            f'<div class="phase {cls}">'
            f'<div class="phase-head"><span class="phase-code">{code.strip()}</span>'
            f'<span class="phase-name">{name}</span>'
            f'<span class="badge {cls}">{badge}</span></div>'
            f'<div class="phase-goal">{goal}</div>'
            f'<div class="phase-deliver">{deliverable}</div>'
            f"</div>"
        )
    phases = "".join(phase_html)

    chart = _svg_bar_chart(EVOLUTION)

    # ---- 指标释义 ----
    glossary_html = "".join(
        f'<div class="gloss">'
        f'<div class="gloss-head"><span class="gloss-name">{name}</span>'
        f'<span class="gloss-key">{key}</span></div>'
        f'<div class="gloss-row"><span class="tag">怎么算</span>{formula}</div>'
        f'<div class="gloss-row"><span class="tag tag-ex">本项目例子</span>{example}</div>'
        f'<div class="gloss-row"><span class="tag tag-mean">说明什么</span>{meaning}</div>'
        f"</div>"
        for name, key, formula, example, meaning in GLOSSARY
    )

    catgloss_html = "".join(
        f'<tr><td><b>{name}</b><div class="dim">{n}</div></td>'
        f"<td>{defn}</td><td>{example}</td><td>{meaning}</td></tr>"
        for name, n, defn, example, meaning in CATEGORY_GLOSSARY
    )

    # ---- 失败样本归因（自动从最新结果统计）----
    failures = []
    for cat, details in runs.items():
        for d in details:
            s = d["score"]
            if s.get("tool_exact") == 0.0 or s.get("refusal_correct") == 0.0:
                failures.append(d)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for d in failures:
        name, why, fix = classify_failure(
            d.get("expected_tools") or [], d.get("predicted_tools") or []
        )
        grouped.setdefault(name, []).append(d)

    fail_html = []
    for name, _rule, why, fix in FAILURE_RULES:
        items = grouped.get(name, [])
        if not items:
            continue
        lis = "".join(
            f"<li><code>{c['id']}</code> {c['query']}<br>"
            f"<span class='dim'>期望 {c['expected_tools']} → 实得 {c['predicted_tools']}</span></li>"
            for c in items
        )
        fail_html.append(
            f'<div class="fail">'
            f'<div class="fail-head">{name}'
            f'<span class="cnt">{len(items)} 条 / 占全部失败 {len(items)/max(len(failures),1)*100:.0f}%</span></div>'
            f'<div class="fail-why"><b>为什么判它错：</b>{why}</div>'
            f'<div class="fail-fix"><b>怎么改：</b>{fix}</div>'
            f"<ul>{lis}</ul></div>"
        )
    others = grouped.get("其他", [])
    if others:
        lis = "".join(
            f"<li><code>{c['id']}</code> {c['query']}<br>"
            f"<span class='dim'>期望 {c['expected_tools']} → 实得 {c['predicted_tools']}</span></li>"
            for c in others
        )
        fail_html.append(
            f'<div class="fail"><div class="fail-head">其他'
            f'<span class="cnt">{len(others)} 条</span></div><ul>{lis}</ul></div>'
        )
    fail_block = "".join(fail_html) or '<div class="dim">当前结果里没有失败样本。</div>'
    fail_summary = (
        f'<div class="note">共 <b>{len(failures)}</b> 条失败样本，'
        f'归为 <b>{len(grouped)}</b> 类。'
        f'这 {len(failures)} 条不是随机错误 —— 每一类都有明确的成因和对应的修法，'
        f'所以 Week 5 的第一件事是<b>修这些成因</b>，而不是先跑消融：'
        f'在一条已知有系统性缺陷的基线上做消融，比出来的只是缺陷的排列组合。</div>'
    )

    # ---- 消融对比 ----
    if results_dir is not None:
        ablation_rows = _ablation_rows(results_dir)
    else:
        ablation_rows = (
            "<tr><td colspan='8' class='dim'>未提供结果目录</td></tr>"
            "</tbody></table>"
        )

    # ---- Week 5 计划 ----
    plan_html = "".join(
        f'<div class="step"><div class="step-head">'
        f'<span class="step-code">{code}</span><span class="step-title">{title}</span></div>'
        f'<div class="step-why">{why}</div>'
        f'<div class="step-done"><span class="tag tag-mean">验收</span>{done}</div></div>'
        for code, title, why, done in WEEK5_PLAN
    )

    # ---- Week 6 集成 ----
    week6_html = "".join(
        f'<div class="step"><div class="step-head">'
        f'<span class="step-code">{code}</span><span class="step-title">{title}</span></div>'
        f'<div class="step-why">{why}</div>'
        f'<div class="step-done"><span class="tag tag-mean">验收</span>{done}</div></div>'
        for code, title, why, done in WEEK6_PLAN
    )
    smoke_html = "".join(
        f'<tr><td>{name}</td><td class="{"ok" if passed else "bad"}">'
        f'{"✅ 通过" if passed else "❌ 未通过"}</td><td class="dim">{note}</td></tr>'
        for name, passed, note in WEEK6_SMOKE
    )
    reg_html = "".join(
        f'<tr><td>{name}</td><td style="text-align:right">{n}</td>'
        f'<td style="text-align:right"><b>{te}</b></td>'
        f'<td style="text-align:right">{f1}</td>'
        f'<td style="text-align:right">{rc}</td>'
        f'<td class="dim">{note}</td></tr>'
        for name, n, te, f1, rc, note, _ok in WEEK6_REGRESSION
    )

    # ---- Week 7 记忆 ----
    week7_html = "".join(
        f'<div class="step"><div class="step-head">'
        f'<span class="step-code">{code}</span><span class="step-title">{title}</span></div>'
        f'<div class="step-why">{why}</div>'
        f'<div class="step-done"><span class="tag tag-mean">验收</span>{done}</div></div>'
        for code, title, why, done in WEEK7_PLAN
    )
    smoke7_html = "".join(
        f'<tr><td>{name}</td><td class="{"ok" if passed else "bad"}">'
        f'{"✅ 通过" if passed else "❌ 未通过"}</td><td class="dim">{note}</td></tr>'
        for name, passed, note in WEEK7_SMOKE
    )
    reg7_html = "".join(
        f'<tr><td>{name}</td><td style="text-align:right">{n}</td>'
        f'<td style="text-align:right"><b>{te}</b></td>'
        f'<td style="text-align:right">{f1}</td>'
        f'<td style="text-align:right">{rc}</td>'
        f'<td class="dim">{note}</td></tr>'
        for name, n, te, f1, rc, note, _ok in WEEK7_REGRESSION
    )
    gbnf_html = "".join(
        f'<tr><td>{name}</td><td style="text-align:right"><b>{value}</b></td>'
        f'<td class="dim">{note}</td></tr>'
        for name, value, note, _ok in GBNF_AB
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GeoAgent 进度看板</title>
<style>
  :root {{
    --bg: #f6f7f9; --panel: #ffffff; --line: #e6e8eb;
    --text: #1f242c; --muted: #6b747f; --accent: #2f6feb; --warn: #d9534f; --ok: #2e9e5b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei",
                 "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 14px; line-height: 1.6;
  }}
  .wrap {{ max-width: 1120px; margin: 0 auto; padding: 28px 22px 56px; }}
  header {{ margin-bottom: 22px; }}
  h1 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: .3px; }}
  .sub {{ color: var(--muted); font-size: 13px; }}
  .sub code {{
    background: #eef1f4; padding: 1px 6px; border-radius: 4px;
    font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  }}
  section {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 18px 20px; margin-bottom: 18px;
  }}
  h2 {{
    margin: 0 0 14px; font-size: 15px; font-weight: 600;
    padding-left: 10px; border-left: 3px solid var(--accent);
  }}
  .cards {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 12px;
  }}
  .card {{
    background: #fbfcfd; border: 1px solid var(--line);
    border-radius: 8px; padding: 12px 14px;
  }}
  .card-label {{ font-size: 12px; color: var(--muted); }}
  .card-value {{ font-size: 25px; font-weight: 650; margin: 2px 0 4px; letter-spacing: -.5px; }}
  .card-note {{ font-size: 11px; color: var(--muted); line-height: 1.45; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; }}
  th {{ color: var(--muted); font-weight: 500; font-size: 12px; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.strong {{ font-weight: 650; }}
  tr:last-child td {{ border-bottom: none; }}
  .phases {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }}
  .phase {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; background: #fbfcfd; }}
  .phase-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .phase-code {{
    font-family: ui-monospace, Consolas, monospace; font-size: 11px;
    background: #eef1f4; padding: 1px 6px; border-radius: 4px; color: var(--muted);
  }}
  .phase-name {{ font-weight: 600; font-size: 14px; }}
  .badge {{ margin-left: auto; font-size: 11px; padding: 1px 8px; border-radius: 10px; }}
  .badge.done {{ background: #e6f4ec; color: var(--ok); }}
  .badge.doing {{ background: #e7effd; color: var(--accent); }}
  .badge.todo {{ background: #f0f1f3; color: var(--muted); }}
  .phase.doing {{ border-color: #b8cdfb; background: #fbfdff; }}
  .phase-goal {{ font-size: 12px; color: var(--text); margin-bottom: 3px; }}
  .phase-deliver {{ font-size: 11px; color: var(--muted); }}
  .note {{
    background: #fff8e6; border: 1px solid #f0dfae; border-radius: 8px;
    padding: 12px 14px; font-size: 12.5px; color: #6b5320;
  }}
  .note b {{ color: #4a3a12; }}
  ul {{ margin: 6px 0 0; padding-left: 18px; }}
  li {{ margin-bottom: 3px; }}
  code {{
    background: #eef1f4; padding: 1px 5px; border-radius: 4px;
    font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  }}
  .dim {{ color: var(--muted); font-size: 11.5px; font-weight: 400; }}
  .ok {{ color: var(--ok); font-weight: 600; white-space: nowrap; }}
  .bad {{ color: var(--warn); font-weight: 600; white-space: nowrap; }}
  /* 指标释义 */
  .gloss {{
    border: 1px solid var(--line); border-radius: 8px;
    padding: 12px 14px; margin-bottom: 10px; background: #fbfcfd;
  }}
  .gloss-head {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }}
  .gloss-name {{ font-weight: 650; font-size: 14px; }}
  .gloss-key {{
    font-family: ui-monospace, Consolas, monospace; font-size: 11px;
    color: var(--muted); background: #eef1f4; padding: 1px 6px; border-radius: 4px;
  }}
  .gloss-row {{ font-size: 12.5px; margin-bottom: 4px; line-height: 1.6; }}
  .tag {{
    display: inline-block; min-width: 62px; text-align: center;
    font-size: 10.5px; padding: 1px 6px; border-radius: 4px; margin-right: 8px;
    background: #eef1f4; color: var(--muted); vertical-align: 1px;
  }}
  .tag-ex {{ background: #e7effd; color: var(--accent); }}
  .tag-mean {{ background: #e6f4ec; color: var(--ok); }}
  /* 失败归因 */
  .fail {{
    border: 1px solid #f0d9d7; border-left: 3px solid var(--warn);
    border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; background: #fffbfb;
  }}
  .fail-head {{
    font-weight: 650; font-size: 13.5px; margin-bottom: 6px;
    display: flex; align-items: baseline; gap: 10px;
  }}
  .cnt {{
    margin-left: auto; font-size: 11px; font-weight: 400;
    color: var(--warn); background: #fdeceb; padding: 1px 8px; border-radius: 10px;
  }}
  .fail-why, .fail-fix {{ font-size: 12.5px; margin-bottom: 4px; line-height: 1.6; }}
  .fail-fix {{ color: #1d6b3f; }}
  .fail ul {{ margin-top: 8px; }}
  .fail li {{ font-size: 12.5px; margin-bottom: 6px; }}
  /* Week 5 计划 */
  .step {{
    border: 1px solid var(--line); border-radius: 8px;
    padding: 11px 14px; margin-bottom: 9px; background: #fbfcfd;
  }}
  .step-head {{ display: flex; align-items: baseline; gap: 9px; margin-bottom: 5px; }}
  .step-code {{
    font-family: ui-monospace, Consolas, monospace; font-size: 11px;
    background: #e7effd; color: var(--accent); padding: 1px 7px; border-radius: 4px;
  }}
  .step-title {{ font-weight: 650; font-size: 13.5px; }}
  .step-why {{ font-size: 12.5px; color: var(--text); line-height: 1.6; }}
  .step-done {{ font-size: 12.5px; margin-top: 5px; line-height: 1.6; }}
  footer {{ color: var(--muted); font-size: 12px; text-align: center; margin-top: 26px; }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>GeoAgent · 地理空间分析智能体 · 进度看板</h1>
  <div class="sub">
    数据源 <code>bench/eval_results/v8_*.json</code>（100 条全量实测）·
    更新于 {generated} ·
    详细归因见 <code>GEOAGENT_PROGRESS.md</code>、<code>bench/EVAL_REPORT.md</code>
  </div>
</header>

<section>
  <h2>核心指标（{tag} 轮实测）</h2>
  <div class="cards">{card_html}</div>
</section>

<section>
  <h2>分类结果</h2>
  <table>
    <thead><tr>
      <th>类别</th><th>样本</th><th style="text-align:right">工具链精确率</th>
      <th style="text-align:right">集合 F1</th><th style="text-align:right">顺序正确</th>
      <th style="text-align:right">拒答正确</th>
      <th style="text-align:right">延迟 p50</th><th style="text-align:right">LLM 调用/条</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>

<section>
  <h2>多工具类版本演进（同一批 40 条）</h2>
  {chart}
  <div class="sub" style="margin-top:8px">
    柱体从淡蓝到红色：前 8 版是迭代过程，<b>红色为 v8 定稿</b>。
    0.00 → 0.85 的跃迁并非模型变强，而是逐层排除了四种非模型能力问题。
  </div>
</section>

<section>
  <h2>阶段进度</h2>
  <div class="phases">{phases}</div>
</section>

<section>
  <h2>指标释义（每条都带本项目的真实例子）</h2>
  <div class="sub" style="margin-bottom:12px">
    评测对象是「用户说一句中文 → Agent 给出一条可执行的工具调用链路」。
    下面每一项都说明：<b>怎么算</b>、<b>拿本项目哪条样本举例</b>、<b>这个数字低了意味着什么</b>。
  </div>
  <h3 style="font-size:13px;margin:0 0 8px;color:var(--muted);font-weight:600">
    一、三项样本类别怎么划分
  </h3>
  <table style="margin-bottom:16px">
    <thead><tr><th style="width:15%">类别</th><th style="width:24%">定义</th>
      <th style="width:33%">例子</th><th style="width:28%">考的是什么</th></tr></thead>
    <tbody>{catgloss_html}</tbody>
  </table>
  <h3 style="font-size:13px;margin:0 0 8px;color:var(--muted);font-weight:600">
    二、每个指标怎么算
  </h3>
  {glossary_html}
</section>

<section>
  <h2>失败样本归因（v8 全部失败条目逐条归类）</h2>
  {fail_summary}
  <div style="margin-top:12px">{fail_block}</div>
</section>

<section>
  <h2>消融对比：换 4 种工作方式跑同一批 100 条题</h2>
  <div class="sub" style="margin-bottom:12px">
    提示词、模型、题目全部不变，只改变 Agent 的工作方式，看每一样改动分别值多少分。
    这是简历上「由 X% 提升至 Y%」那句话的唯一合法来源。
  </div>
  <table>
    <thead><tr>
      <th style="width:14%">组别</th><th style="width:26%">改了什么</th>
      <th style="text-align:right">总精确率</th><th style="text-align:right">单工具</th>
      <th style="text-align:right">多工具</th><th style="text-align:right">拒答</th>
      <th style="text-align:right">调用/条</th><th style="text-align:right">延迟 p50</th>
    </tr></thead>
    <tbody>{ablation_rows}
</section>

<section>
  <h2>Week 5 执行计划（先修成因，再跑消融）</h2>
  <div class="sub" style="margin-bottom:12px">
    顺序不能颠倒：先在一条已知有系统性缺陷的基线上做消融，
    比出来的只是缺陷的排列组合，数字没有解释力。
  </div>
  {plan_html}
</section>

<section>
  <h2>Week 6 · 把 Agent 装进三维地理系统</h2>
  <div class="sub" style="margin-bottom:12px">
    起因：W5-6 交的是一个<b>独立网页</b>。用户实测后指出三条硬伤 ——
    脱离主系统用不上地图上下文、「你好」被当成越界任务拒答、
    且回复<b>只有纯文字，没有数据 / 表格 / 图表 / 图层</b>。<br>
    诊断结论：<b>不是前端没画图表，是后端数据通路断了 5 处</b> ——
    产物目录没挂载、字段名单复数对不上、只返回本地路径没有 URL、
    执行记录丢弃结构化结果、寒暄走错分支且模板泄漏。
  </div>
  {week6_html}

  <h3 style="font-size:14px;margin:20px 0 8px">真机冒烟（不是离线单测）</h3>
  <div class="sub" style="margin-bottom:10px">
    用系统自带 Chrome 以软件渲染跑通全流程，脚本 <code>cesium_old/_smoke_agent.js</code>。
  </div>
  <table>
    <thead><tr>
      <th style="width:46%">检查项</th><th style="width:14%">结果</th><th>说明</th>
    </tr></thead>
    <tbody>{smoke_html}</tbody>
  </table>

  <h3 style="font-size:14px;margin:22px 0 8px">回归评测：改完代码，分数掉了没有？</h3>
  <div class="sub" style="margin-bottom:10px">
    意图分层把每条分析任务多出一次分类调用，并改写了主 planner 提示词，
    改完必须重跑全量确认。<b>结论：主集 96.25%（改造前 97.5%，差约 1 条样本），越界拒答仍是 20/20</b>；
    但保留集由 100% 降到 81.8% —— 这是换取泛化能力付出的代价，如实记录不做美化。
  </div>
  <table>
    <thead><tr>
      <th style="width:26%">数据集</th>
      <th style="text-align:right">条数</th>
      <th style="text-align:right">工具链精确率</th>
      <th style="text-align:right">集合 F1</th>
      <th style="text-align:right">拒答正确</th>
      <th>对比上一版</th>
    </tr></thead>
    <tbody>{reg_html}</tbody>
  </table>
  <div class="note" style="margin-top:10px">
    ⚠ <b>口径提醒</b>：工具链精确率只在「有工具期望」的样本上计算，越界拒答题不参与该指标
    （它们看「拒答正确」那一列）。直接对全部条目取平均会把拒答题按 0 分计入，
    得出「主集 76.9%」这种错误数字 —— 必须用
    <code>app.eval.metrics.aggregate()</code>，它在内部做了分口径处理。
  </div>
</section>

<section>
  <h2>Week 7 · 对话记忆与上下文管理</h2>
  <div class="sub" style="margin-bottom:12px">
    起因：用户实测反馈两条 —— ① Agent <b>不保留、也不阅读上下文</b>，
    上一轮刚聊完五指山，下一句「跳转到这个地方」它答"请提供具体地名"；
    ② 同样的操作换个地名就变样，「跳转到五指山」秒回，
    「跳转到阿尔卑斯山」却先跑几分钟地形采样才跳转。<br>
    诊断结论：两条都<b>不是模型不够聪明，是架构缺口</b> ——
    第二条尤其反直觉，<b>后端意图判断一直是对的</b>（9 个句式实测 8 个正确），
    问题出在<b>前端抢跑</b>：请求还没发出去，它就先无条件采样了 16384 个高程点。
  </div>
  {week7_html}

  <h3 style="font-size:14px;margin:20px 0 8px">多轮连续对话真机冒烟</h3>
  <div class="sub" style="margin-bottom:10px">
    脚本 <code>cesium_old/_smoke_memory.js</code>：在同一会话里连问四句，
    验证「记忆能不能理解指代」与「跳转还会不会被抢跑采样」。
  </div>
  <table>
    <thead><tr>
      <th style="width:46%">检查项</th><th style="width:14%">结果</th><th>说明</th>
    </tr></thead>
    <tbody>{smoke7_html}</tbody>
  </table>

  <h3 style="font-size:14px;margin:22px 0 8px">回归评测：加了记忆层，单轮准确率掉了没有？</h3>
  <div class="sub" style="margin-bottom:10px">
    评测时<b>显式关闭会话记忆</b>（<code>GEOAGENT_MEMORY=0</code>）—— 评测集是单轮任务，
    且所有样本共用默认 session_id，开着记忆会让第 N 题读到前 N-1 题的历史，基线就被污染了。
    <b>结论：主集 98.75%（历史最高，改造前 96.25%），单工具类 100%</b>。
  </div>
  <table>
    <thead><tr>
      <th style="width:26%">数据集</th>
      <th style="text-align:right">条数</th>
      <th style="text-align:right">工具链精确率</th>
      <th style="text-align:right">集合 F1</th>
      <th style="text-align:right">拒答正确</th>
      <th>对比上一版</th>
    </tr></thead>
    <tbody>{reg7_html}</tbody>
  </table>

  <h3 style="font-size:14px;margin:22px 0 8px">一个被实测否定的技术方案：GBNF 约束解码</h3>
  <div class="sub" style="margin-bottom:10px">
    我原本的计划是给意图分类加上 GBNF 文法约束（基础设施早就写好了但一直没调用），
    理由是"JSON 偶尔不合法"。<b>实测把这个假设证伪了</b> ——
    无约束时 JSON 解析成功率本来就是 100%，GBNF 对决策准确率零影响，还慢 32%。
    两组失败的样本完全相同，说明错因是<b>语义理解</b>，而 GBNF 只管语法。
    这条否定结果把问题精确定位到了"模型能力"而非"格式"，直接决定了下一步方向。
  </div>
  <table>
    <thead><tr>
      <th style="width:40%">指标</th><th style="text-align:right">实测值</th><th>说明</th>
    </tr></thead>
    <tbody>{gbnf_html}</tbody>
  </table>

  <h3 style="font-size:14px;margin:22px 0 8px">设计取舍（面试会问的三点）</h3>
  <div class="note">
    <ul>
      <li><b>为什么不用 LangGraph checkpointer？</b>它解决的是"断点续跑"（存整个图状态快照），
        而记忆解决的是"理解上下文"。我们的 state 里有 DEM 路径、产物列表、trace 等大对象，
        每轮快照既慢又脏；且项目是 LangGraph + 自研循环双运行时，
        checkpointer 只在图分支生效会造成行为分叉。</li>
      <li><b>为什么短期只截断不摘要？</b>已实测 4B 模型做"转述"会改坏事实；
        且 Lost-in-the-Middle 实测注意力呈 U 型、中段信息召回率约 20% ——
        历史塞得越多整体准确率越低，与信息是否在窗口内无关。</li>
      <li><b>为什么指代消解用规则而不是让模型做？</b>代词指向什么是<b>已经发生过的事实</b>
        （库里记着上一轮的 bbox），查一下即可；让 4B 去猜等于抽奖。
        但<b>意图判断仍交给模型</b> —— 规则只补事实，不替模型做决定，
        否则就会回到用户批评过的"只会回答写死的问题"。</li>
    </ul>
  </div>
</section>

<section>
  <h2>读数据前必须知道的三件事</h2>
  <div class="note">
    <ul>
      <li><b>精确率 ≠ 集合 F1</b>：总体精确率 80.0% 但集合 F1 有 91.5%——
          说明模型工具基本选对了，丢分在「多一步／少一步」，不是选错工具。
          精确率是最严口径，错一步即判整条错。</li>
      <li><b>bbox 参数 100% 不能写进简历</b>：100 条用到的 16 个地名全部来自
          <code>source='eval'</code>（词典直抄自标准答案），属开卷。
          无泄漏对照（12 个评测集外地名）真值 12/12，样本量还不足以支撑指标。</li>
      <li><b>v6／v7／v8 三次独立改版都恰好停在 80.0%</b>：此前判定为「标注噪声天花板」，
          本次逐条归因后修正了这个判断——<strong>16 条失败里有 11 条是模型真实缺陷、
          5 条是约定缺失</strong>，不是噪声。详见上方归因表。</li>
    </ul>
  </div>
</section>

<footer>本页所有数字均可由仓库内评测产物复核 · 生成脚本 <code>bench/make_dashboard.py</code></footer>

</div>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 GeoAgent 进度看板")
    repo = Path(__file__).resolve().parents[1]
    ap.add_argument("--results", default=str(repo / "bench" / "eval_results"))
    ap.add_argument("--out", default=str(repo / "bench" / "dashboard.html"))
    ap.add_argument("--tag", default="", help="指定结果版本前缀，如 v12；留空自动取最新")
    args = ap.parse_args()

    results_dir = Path(args.results)
    tag = args.tag

    def latest(cat: str):
        """取该类别下版本号最大的一轮结果（v8 < v9 < v11 < v12）。"""
        cands = []
        for p in results_dir.glob(f"v*_{cat}.json"):
            num = "".join(ch for ch in p.stem.split("_")[0][1:] if ch.isdigit())
            cands.append((int(num) if num else 0, p))
        if tag:
            cands = [(n, p) for n, p in cands if p.stem.startswith(tag)]
        if not cands:
            return None, None
        num, p = max(cands)
        return _load(p), p.stem.split("_")[0]

    runs: Dict[str, List[Dict[str, Any]]] = {}
    used_tag = ""
    for cat in ["single_tool", "multi_tool", "out_of_scope"]:
        details, t = latest(cat)
        if details:
            runs[cat] = details
            used_tag = t or used_tag

    if not runs:
        print(f"[错误] 在 {results_dir} 找不到评测结果 JSON", file=sys.stderr)
        return 1

    # 保留集（未参与调参，用于检验泛化而非死记）
    heldout = None
    for p in sorted(results_dir.glob("v*_heldout.json"), reverse=True):
        heldout = _load(p)
        if heldout:
            break

    now = time.strftime("%Y-%m-%d %H:%M")
    html = build_html(runs, now, heldout=heldout, tag=used_tag, results_dir=results_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[看板] 已生成 {out}")
    for cat, v in runs.items():
        print(f"  - {CAT_LABEL[cat]}: {len(v)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
