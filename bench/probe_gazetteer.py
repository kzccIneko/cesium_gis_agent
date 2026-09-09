"""地名词典的**无泄漏**验证。

为什么需要它
------------
gazetteer 里 source='eval' 的 20 条是从评测集标准答案反推出来的。
拿这批条目去评测同一批样本，等于「用考试答案编小抄再考同一张卷」——
param_bbox 打到 0.985 只能证明**机制可行**，不能证明**词典有用**。

所以这里只用 source='manual' 的地名（评测集里从未出现过：
北京/上海/天山/黄土高原…），单独造一批探针问题。
它们不参与任何评测集样本，测出来的数字才是「模型拿到词典提示后
能不能正确用它」，没有被污染。

用法
----
    python bench/probe_gazetteer.py
    python bench/probe_gazetteer.py --no-gazetteer   # 对照组
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.agent.gazetteer import Gazetteer  # noqa: E402
from app.agent.llm import EmbeddedLlamaClient  # noqa: E402
from app.eval.runner import EvalRunner  # noqa: E402

# 只用 manual 来源的地名，确保与评测集零重叠。
# (query, 期望工具, 期望 bbox)
PROBES: list = [
    ("计算北京的坡度", "compute_slope", [116.0, 39.6, 116.8, 40.2]),
    ("计算上海的坡度分布", "compute_slope", [121.2, 30.9, 121.9, 31.5]),
    ("广州的坡向情况如何", "compute_aspect", [113.0, 22.9, 113.6, 23.4]),
    ("深圳哪里比较陡", "compute_slope", [113.9, 22.5, 114.3, 22.8]),
    ("重庆的曲率分析", "compute_curvature", [106.3, 29.4, 106.9, 29.9]),
    # 注意工具名以 registry 为准：是 compute_cost_surface / classify_geomorphons，
    # 不是 compute_cost / classify_terrain —— 写错会把对的预测判成错。
    ("杭州的通行代价", "compute_cost_surface", [119.9, 30.1, 120.4, 30.5]),
    ("南京的地形分类", "classify_geomorphons", [118.6, 32.0, 119.0, 32.3]),
    ("武汉的坡度栅格", "compute_slope", [114.1, 30.4, 114.6, 30.8]),
    ("天山的地貌类型有哪些", "classify_geomorphons", [80.0, 42.0, 88.0, 44.5]),
    ("黄土高原哪里是沟谷", "compute_curvature", [106.0, 34.0, 114.0, 40.0]),
    ("青藏高原的通行难度", "compute_cost_surface", [78.0, 28.0, 103.0, 38.0]),
    ("武夷山的主要朝向", "compute_aspect", [117.5, 26.5, 118.3, 28.0]),
]

TOL = 0.01  # 与 metrics.param_bbox 一致：约 1.1 km


def bbox_ok(pred, expect) -> bool:
    if not isinstance(pred, (list, tuple)) or len(pred) != 4:
        return False
    try:
        return all(abs(float(a) - float(b)) <= TOL for a, b in zip(pred, expect))
    except (TypeError, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-gazetteer", action="store_true", help="对照组：不注入提示")
    ap.add_argument("--max-tokens", type=int, default=384)
    ap.add_argument("--n-ctx", type=int, default=8192)
    args = ap.parse_args()

    use_gz = not args.no_gazetteer
    gz = Gazetteer() if use_gz else None

    client = EmbeddedLlamaClient(n_ctx=args.n_ctx, n_gpu_layers=-1, prefix_cache=True)
    runner = EvalRunner(client=client, mode="tool_calling")
    client._ensure_model()

    tag = "无词典(对照)" if not use_gz else "有词典"
    print(f"[probe] {tag}  n={len(PROBES)}")

    ok_bbox = ok_tool = 0
    rows = []
    for i, (q, want_tool, want_bbox) in enumerate(PROBES, 1):
        msgs = runner._build_messages(gz.annotate(q) if gz else q)
        t0 = time.perf_counter()
        resp = client.chat(msgs, tools=runner.tools, temperature=0.0,
                           max_tokens=args.max_tokens)
        dt = time.perf_counter() - t0
        pred = runner._parse_prediction(resp)
        tools = pred["tools"]
        # params 是扁平的 {"bbox": [...], "resolution": ...}，不是按工具名嵌套
        params = pred.get("params") or {}
        bbox = params.get("bbox") if isinstance(params, dict) else None
        good_b = bbox_ok(bbox, want_bbox)
        good_t = want_tool in tools
        ok_bbox += good_b
        ok_tool += good_t
        rows.append((q, want_tool, tools, bbox, good_b, good_t))
        print(
            f"  [{i:2d}] bbox={'OK' if good_b else 'X '} tool={'OK' if good_t else 'X '}"
            f" {dt:5.1f}s  pred_bbox={bbox}  want={want_bbox}"
        )

    print()
    print(f"  bbox 正确率: {ok_bbox}/{len(PROBES)} = {ok_bbox/len(PROBES):.3f}")
    print(f"  工具正确率: {ok_tool}/{len(PROBES)} = {ok_tool/len(PROBES):.3f}")
    out = REPO / "bench" / ("probe_gazetteer_off.json" if not use_gz
                            else "probe_gazetteer_on.json")
    out.write_text(
        json.dumps(
            {"use_gazetteer": use_gz, "bbox_rate": ok_bbox / len(PROBES),
             "tool_rate": ok_tool / len(PROBES),
             "rows": rows},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
