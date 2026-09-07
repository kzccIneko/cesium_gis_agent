#!/usr/bin/env python
"""地形分类模型优化流水线：检查 → 基准 → 量化 → 验证。

用法::

    python backend/scripts/optimize_terrain_onnx.py check
    python backend/scripts/optimize_terrain_onnx.py bench --sizes 64,128
    python backend/scripts/optimize_terrain_onnx.py quantize
    python backend/scripts/optimize_terrain_onnx.py validate
    python backend/scripts/optimize_terrain_onnx.py all --json report.json

设计取向：**优化是否可上线由 validate 说了算，不由加速比说了算**。
一个快 4 倍但把稀有地貌类抹掉的模型，在地理场景里是不可用的。
所以 `all` 的最后一步是验证，并把结论写进报告。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.optimization import DEFAULT_ONNX, OptimizedONNXClassifier  # noqa: E402
from app.optimization import QUANTIZED_ONNX  # noqa: E402
from app.optimization.benchmark import synthetic_dem  # noqa: E402
from app.optimization.session import file_size_mb, provider_report  # noqa: E402
from app.optimization.validate import compare_classifications  # noqa: E402

MODEL_DIR = DEFAULT_ONNX.parent
FIXED_ONNX = MODEL_DIR / "terrain_morphology.fixed.onnx"
STATIC_ONNX = MODEL_DIR / "terrain_morphology.quant.static.onnx"
LEGEND_PATH = MODEL_DIR / "legend.json"


def _class_names() -> List[str]:
    if LEGEND_PATH.is_file():
        try:
            legend = json.loads(LEGEND_PATH.read_text(encoding="utf-8"))
            return [c["label_cn"] for c in sorted(legend, key=lambda x: x["id"])]
        except Exception:
            pass
    return [str(i) for i in range(8)]


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def cmd_check(args) -> Dict[str, Any]:
    from app.optimization.graph import fix_dynamic_flatten

    print("=== 执行后端 ===")
    for p in provider_report():
        flag = "可用" if p["available"] else "不可用"
        print(f"  {p['provider']:28s} {flag:6s} {p['note']}")

    print()
    print("=== 模型 ===")
    print(f"  路径: {DEFAULT_ONNX}")
    print(f"  体积: {file_size_mb(DEFAULT_ONNX):.2f} MB")
    try:
        info = OptimizedONNXClassifier(DEFAULT_ONNX).info()
        for io in info["inputs"]:
            print(f"  输入: {io['name']} {io['shape']}")
        for io in info["outputs"]:
            print(f"  输出: {io['name']} {io['shape']}")
    except Exception as exc:
        print(f"  加载失败: {exc}")
        return {"ok": False}

    print()
    print("=== 图结构（能否被量化工具链处理）===")
    if FIXED_ONNX.is_file():
        print(f"  已存在修好的图: {FIXED_ONNX.name}")
    else:
        print("  未找到修好的图，正在生成……")
    res = fix_dynamic_flatten(DEFAULT_ONNX, FIXED_ONNX)
    print(f"  修改: {res.get('changed')}  移除节点: {res.get('removed_nodes')}")
    print(f"  shape_inference: {'OK' if res.get('shape_inference_ok') else 'FAIL'}")
    if res.get("shape_error"):
        print(f"  错误: {res['shape_error']}")
    return {"ok": bool(res.get("shape_inference_ok")), "graph": res}


# ---------------------------------------------------------------------------
# bench
# ---------------------------------------------------------------------------


def cmd_bench(args) -> Dict[str, Any]:
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    strides = [int(s) for s in args.strides.split(",") if s.strip()]
    # 默认带上已量化的模型作为对比项；只有显式 --no-quant 才关闭
    with_quant = not getattr(args, "no_quant", False)
    quant = STATIC_ONNX if (with_quant and STATIC_ONNX.is_file()) else None

    rows: List[Dict[str, Any]] = []
    for n in sizes:
        dem = synthetic_dem(n, seed=args.seed)
        print(f"=== DEM {n}×{n}（{n * n} patch）===")
        variants = []
        for st in strides:
            variants.append(
                (
                    f"fp32 stride={st}",
                    OptimizedONNXClassifier(FIXED_ONNX, stride=st).classify,
                )
            )
            if quant:
                variants.append(
                    (
                        f"int8 stride={st}",
                        OptimizedONNXClassifier(quant, stride=st).classify,
                    )
                )

        baseline = None
        for name, fn in variants:
            fn(dem)  # 预热
            t = time.perf_counter()
            fn(dem)
            ms = (time.perf_counter() - t) * 1000.0
            if baseline is None:
                baseline = ms
            rows.append(
                {
                    "size": n,
                    "variant": name,
                    "ms": round(ms, 1),
                    "speedup": round(baseline / ms, 2),
                }
            )
            print(f"  {name:18s} {ms:9.1f} ms   加速 {baseline / ms:5.2f}x")
        print()
    return {"rows": rows}


# ---------------------------------------------------------------------------
# quantize
# ---------------------------------------------------------------------------


def cmd_quantize(args) -> Dict[str, Any]:
    from app.optimization.quantize import quantize_static

    if not FIXED_ONNX.is_file():
        print("先跑 `check` 生成修好的图")
        return {"ok": False}

    # all 子命令不带 quantize 的专属参数，用 getattr 兜底
    real_dem = getattr(args, "real_dem", None)
    n_calib = getattr(args, "calibration", 200)

    dems = [synthetic_dem(128, seed=s) for s in (0, 1, 2)]
    if real_dem:
        import numpy as np

        dems.insert(0, np.load(real_dem))

    rep = quantize_static(FIXED_ONNX, STATIC_ONNX, dems, n_samples=n_calib)
    print(
        f"静态量化: {rep['size_mb_before']:.2f} MB -> {rep['size_mb_after']:.2f} MB"
        f"（{rep['compression_ratio']}x），校准 {rep['calibration_patches']} 个地形 patch"
    )
    return {"ok": True, "report": rep}


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def cmd_validate(args) -> Dict[str, Any]:
    if not FIXED_ONNX.is_file():
        print("先跑 `check`")
        return {"ok": False}

    names = _class_names()
    size = getattr(args, "size", 128)
    seed = getattr(args, "seed", 0)
    strides_arg = getattr(args, "strides", "1,2")
    dem = synthetic_dem(size, seed=seed)
    ref = OptimizedONNXClassifier(FIXED_ONNX, stride=1)
    ref_ids, ref_cost, ref_conf = ref.classify(dem)

    results: Dict[str, Any] = {}
    print(f"参考基准：fp32 / stride=1 / {size}×{size}")
    print()

    candidates = [
        int(s) for s in strides_arg.split(",") if s.strip() and int(s) > 1
    ]
    for st in candidates:
        c = OptimizedONNXClassifier(FIXED_ONNX, stride=st)
        ids, cost, conf = c.classify(dem)
        res = compare_classifications(
            ref_ids, ids, ref_conf, conf, ref_cost, cost, class_names=names
        )
        results[f"stride_{st}"] = res
        _print_verdict(f"fp32 stride={st}", res)

    if STATIC_ONNX.is_file():
        c = OptimizedONNXClassifier(STATIC_ONNX, stride=1)
        ids, cost, conf = c.classify(dem)
        res = compare_classifications(
            ref_ids, ids, ref_conf, conf, ref_cost, cost, class_names=names
        )
        results["int8_static"] = res
        _print_verdict("int8 静态量化 stride=1", res)

        if getattr(args, "strides_quantized", False):
            for st in candidates:
                c = OptimizedONNXClassifier(STATIC_ONNX, stride=st)
                ids, cost, conf = c.classify(dem)
                res = compare_classifications(
                    ref_ids, ids, ref_conf, conf, ref_cost, cost, class_names=names
                )
                results[f"int8_stride_{st}"] = res
                _print_verdict(f"int8 stride={st}", res)

    # 给出可上线的组合
    usable = [k for k, v in results.items() if v.get("passed")]
    print("=== 结论 ===")
    print(f"  通过验证的组合: {usable or '无'}")
    return {"ok": True, "results": results, "usable": usable}


def _print_verdict(tag: str, res: Dict[str, Any]) -> None:
    m = res["metrics"]
    print(f"--- {tag} ---")
    print(f"  判定: {'PASS' if res['passed'] else 'FAIL'}")
    print(
        f"  一致率 {m['overall_agreement']:.4f} | 分布TVD {m['distribution_tvd']:.5f}"
        f" | 边界密度比 {m['boundary_density_ratio']:.4f}"
    )
    cost = res["checks"].get("cost_surface")
    if cost:
        print(
            f"  cost 平均相对偏差 {cost['cost_mean_rel_diff']:.5f}"
            f"（阈值 {cost['cost_threshold']}）"
        )
    if m.get("mean_conf_delta") is not None:
        print(
            f"  平均置信度 {m['mean_conf_ref']:.4f} -> {m['mean_conf_new']:.4f}"
            f"（Δ {m['mean_conf_delta']:+.4f}）"
        )
    bad = [c["class"] for c in res["per_class"] if not c["passed"]]
    if bad:
        print(f"  未达标类别: {', '.join(bad)}")
    print()


# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="检查执行后端、模型与图结构")

    p_bench = sub.add_parser("bench", help="性能基准")
    p_bench.add_argument("--sizes", default="64,128")
    p_bench.add_argument("--strides", default="1,2")
    p_bench.add_argument("--seed", type=int, default=0)
    p_bench.add_argument("--no-quant", action="store_true", help="基准中不含 int8 量化模型")

    p_q = sub.add_parser("quantize", help="量化模型")
    p_q.add_argument("--calibration", type=int, default=200)
    p_q.add_argument("--real-dem", default=None, help="真实 DEM 的 .npy，优先用作校准")

    p_v = sub.add_parser("validate", help="领域一致性验证")
    p_v.add_argument("--size", type=int, default=128)
    p_v.add_argument("--seed", type=int, default=0)
    p_v.add_argument("--strides", default="1,2")
    p_v.add_argument("--strides-quantized", action="store_true")

    p_all = sub.add_parser("all", help="完整流水线")
    p_all.add_argument("--sizes", default="64,128")
    p_all.add_argument("--strides", default="1,2")
    p_all.add_argument("--size", type=int, default=128)
    p_all.add_argument("--seed", type=int, default=0)
    p_all.add_argument("--json", default=None)
    # all 会依次调用 bench / quantize / validate，故需要这几个子命令的参数
    p_all.add_argument("--no-quant", action="store_true", help="基准中不含 int8 量化模型")
    p_all.add_argument("--calibration", type=int, default=200)
    p_all.add_argument("--real-dem", default=None, help="真实 DEM 的 .npy，优先用作校准")
    p_all.add_argument("--strides-quantized", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "check":
        out = cmd_check(args)
    elif args.cmd == "bench":
        out = cmd_bench(args)
    elif args.cmd == "quantize":
        out = cmd_quantize(args)
    elif args.cmd == "validate":
        out = cmd_validate(args)
    else:
        out = {"check": cmd_check(args)}
        out["quantize"] = cmd_quantize(args)
        out["bench"] = cmd_bench(args)
        out["validate"] = cmd_validate(args)
        if args.json:
            Path(args.json).write_text(
                json.dumps(out, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"报告已写入 {args.json}")

    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
