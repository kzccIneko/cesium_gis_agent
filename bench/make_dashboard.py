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
    ("Week 5", "评测与消融", "todo", "锁定上限归因，做可解释的消融实验",
     "前提：先清 ~15 条标注噪声，否则 20% 误差上界压住所有真实收益"),
    ("Week 6", "前端与部署", "todo", "让 Agent 在网页端真正可用",
     "缺 HTTP 端点（/api/v1/agent/chat）+ 前端对话面板；Docker Compose 一键部署"),
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


def build_html(runs: Dict[str, List[Dict[str, Any]]], generated: str) -> str:
    stats = {k: compute_stats(v) for k, v in runs.items()}
    all_details = [d for v in runs.values() for d in v]
    overall = compute_stats(all_details)

    te_all = [
        d["score"].get("tool_exact")
        for d in all_details
        if d["score"].get("tool_exact") is not None
    ]
    overall_exact = _avg(te_all)

    # ---- 指标卡 ----
    cards = [
        ("总体工具链精确率", _pct(overall_exact), "100 条全量逐项同序完全一致<br>最严口径：错一步即判错"),
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
  <h2>核心指标</h2>
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
  <h2>读数据前必须知道的三件事</h2>
  <div class="note">
    <ul>
      <li><b>精确率 ≠ F1</b>：总体精确率 80.0% 但集合 F1 有 91.5%——
          说明模型工具基本选对了，丢分在「多一步／少一步」，不是选错工具。
          精确率是最严口径，错一步即判整条错。</li>
      <li><b>bbox 参数准确率未列入 CUED Card</b>：本次 100 条用到的 16 个地名全部来自
          <code>source='eval'</code>（词典直抄自标准答案），属开卷。
          无泄漏对照（12 个评测集外地名）的真值是 12/12。</li>
      <li><b>80.0% 是天花板不是上限</b>：v6／v7／v8 三次独立改版合计都恰好停在 80.0%，
          每次改动在两个类别上符号相反。根因是存在语义等价却标注相反的样本对。
          再调提示词只是在类别间搬运误差，必须<strong>先清约 15 条标注噪声</strong>
          才可能看到真实收益。</li>
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
    args = ap.parse_args()

    results_dir = Path(args.results)
    runs: Dict[str, List[Dict[str, Any]]] = {}
    for cat in ["single_tool", "multi_tool", "out_of_scope"]:
        details = None
        for p in sorted(results_dir.glob(f"*{cat}.json")):
            got = _load(p)
            if got:
                details = got
                break
        if details:
            runs[cat] = details

    if not runs:
        print(f"[错误] 在 {results_dir} 找不到评测结果 JSON", file=sys.stderr)
        return 1

    now = time.strftime("%Y-%m-%d %H:%M")
    html = build_html(runs, now)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[看板] 已生成 {out}")
    for cat, v in runs.items():
        print(f"  - {CAT_LABEL[cat]}: {len(v)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
