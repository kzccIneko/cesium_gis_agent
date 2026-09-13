"""GBNF 约束解码的 A/B 对比实验。

问题：现有基础设施支持 GBNF（`EmbeddedLlamaClient.use_grammar` +
`response_schema`），但业务代码里**一次都没传过** —— 所以 JSON 合法性
完全靠模型自觉，非法就得重试。

本脚本直接对比「不约束」vs「GBNF 约束」两组的：
  1. JSON 解析成功率
  2. 意图判定准确率
  3. 单次耗时

用法：
    python bench/_test_grammar.py
注意：会加载本地模型（约 4.5 GB 显存），跑之前请先停掉后端。
"""
import json
import os
import sys
import time

sys.path.insert(0, "backend")
os.environ.setdefault("TMP", "D:/llama_build/tmp")
os.environ.setdefault("TEMP", "D:/llama_build/tmp")

from app.agent.llm import build_client, extract_json  # noqa: E402
from app.agent.nodes.planner import PROMPTS_DIR, build_view_context  # noqa: E402

VIEW = {
    "bbox": [109.0, 18.49, 111.0, 19.5],
    "center": [110.0, 19.0],
    "area_km2": 45000.0,
    "is_global": False,
}

# (query, 期望意图)
CASES = [
    ("四姑娘山这一带的坡度是多少", "analysis"),
    ("贡嘎山哪里比较陡", "analysis"),
    ("算一下当前视野的坡度分布", "analysis"),
    ("统计珠峰坡度在 15 度以下的比例", "analysis"),
    ("规划一条从 A 点到 B 点的徒步路线", "analysis"),
    ("这片区域属于什么地貌类型", "analysis"),
    ("都江堰的山坡主要朝向哪边", "analysis"),
    ("三峡哪些是阴坡哪些是阳坡", "analysis"),
    ("算一下这片区域的通行代价", "analysis"),
    ("看看这个 DEM 的坐标系和分辨率", "analysis"),
    ("跳转到海南省", "action"),
    ("我想看看五指山", "action"),
    ("放大到云南省", "action"),
    ("这里是什么地方", "knowledge"),
    ("什么是坡度", "knowledge"),
    ("中国有多少个省级行政区", "knowledge"),
    ("DEM 是什么", "knowledge"),
    ("你好", "chat"),
    ("你能做什么", "chat"),
    ("谢谢", "chat"),
    ("今天天气怎么样", "refuse"),
    ("帮我写一首诗", "refuse"),
    ("月球背面的地貌类型", "refuse"),
    ("1 加 1 等于几", "refuse"),
]

# 意图分类的 JSON Schema —— GBNF 会强制模型只能在这个集合里选
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["analysis", "knowledge", "action", "chat", "refuse"],
        },
        "understanding": {"type": "string"},
        "reply": {"type": "string"},
    },
    "required": ["intent", "understanding", "reply"],
}


def build_prompt(template: str, query: str) -> str:
    return (
        template.replace("{{VIEW_CONTEXT}}", build_view_context({"view_context": VIEW}) or "（未知）")
        .replace("{{QUERY}}", query)
    )


PROGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_grammar_progress.json")


def _dump(label: str, ok_json: int, ok_intent: int, done: int) -> None:
    """把当前进度落盘 —— C 层 abort 会直接杀进程，只有写出去的东西留得下。"""
    try:
        cur = {}
        if os.path.exists(PROGRESS):
            with open(PROGRESS, encoding="utf-8") as f:
                cur = json.load(f)
        cur[label] = {"json_ok": ok_json, "intent_ok": ok_intent, "done": done}
        with open(PROGRESS, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def run_group(llm, template, use_grammar: bool):
    label = "GBNF 约束" if use_grammar else "无约束"
    ok_json = ok_intent = 0
    t0 = time.perf_counter()
    details = []

    for i, (query, expect) in enumerate(CASES):
        prompt = build_prompt(template, query)
        try:
            resp = llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
                response_schema=INTENT_SCHEMA if use_grammar else None,
            )
            raw = resp.content or ""
        except Exception as exc:  # noqa: BLE001
            details.append((query, expect, None, f"异常 {type(exc).__name__}"))
            continue

        # 连续生成会让这块 6GB 卡（笔记本 2060）热降频，
        # 实测持续满载 90–120 s 后会在 ggml-cuda.cu:106 抛 C 层 abort。
        # 间隔是实测定出来的：每 6 条歇 3 s 仍然会崩 → 改成每 4 条歇 6 s。
        if (i + 1) % 4 == 0:
            time.sleep(6)
            # 逐条落盘：C 层 abort 时 Python 拦不住，只有已经写出去的结果能留下
            _dump(label, ok_json, ok_intent, i + 1)

        obj = extract_json(raw)
        if isinstance(obj, dict):
            ok_json += 1
            got = str(obj.get("intent") or "").strip().lower()
            if got == expect:
                ok_intent += 1
            else:
                details.append((query, expect, got, "意图不符"))
        else:
            details.append((query, expect, None, "JSON 解析失败"))

    dt = time.perf_counter() - t0
    n = len(CASES)
    print(f"\n【{label}】")
    print(f"  JSON 解析成功: {ok_json}/{n} = {ok_json / n:.1%}")
    print(f"  意图判定正确: {ok_intent}/{n} = {ok_intent / n:.1%}")
    print(f"  总耗时: {dt:.1f}s（平均 {dt / n:.1f}s/条）")
    if details:
        print(f"  失败明细（{len(details)} 条）:")
        for q, exp, got, why in details[:8]:
            print(f"    {q[:24]:26s} 期望={exp:10s} 实际={got} ({why})")
    return {"json": ok_json / n, "intent": ok_intent / n, "sec": dt / n}


def main():
    import argparse

    ap = argparse.ArgumentParser(description="GBNF 约束解码 A/B 对比")
    ap.add_argument(
        "--group", choices=["both", "plain", "grammar"], default="both",
        help="只跑一组。这台 2060 连着跑两组必崩（热降频触发 C 层 abort），"
             "建议分两次调用：先 --group plain，等几分钟再 --group grammar",
    )
    args = ap.parse_args()

    template = (PROMPTS_DIR / "intent.txt").read_text(encoding="utf-8")
    llm = build_client()
    print("模型已加载", flush=True)

    a = b = None
    if args.group in ("both", "plain"):
        a = run_group(llm, template, use_grammar=False)
    if args.group == "both":
        print("\n（等待 GPU 降温 20 s）", flush=True)
        time.sleep(20)
    if args.group in ("both", "grammar"):
        b = run_group(llm, template, use_grammar=True)

    if a is None or b is None:
        return
    print("\n" + "=" * 62)
    print(f"{'指标':<16}{'无约束':>12}{'GBNF':>12}{'变化':>12}")
    print(f"{'JSON 合法性':<16}{a['json']:>11.1%}{b['json']:>12.1%}"
          f"{(b['json'] - a['json']) * 100:>+11.1f}pp")
    print(f"{'意图准确率':<16}{a['intent']:>11.1%}{b['intent']:>12.1%}"
          f"{(b['intent'] - a['intent']) * 100:>+11.1f}pp")
    print(f"{'单条耗时(s)':<16}{a['sec']:>12.1f}{b['sec']:>12.1f}"
          f"{(b['sec'] - a['sec']):>+11.1f}s")


if __name__ == "__main__":
    main()
