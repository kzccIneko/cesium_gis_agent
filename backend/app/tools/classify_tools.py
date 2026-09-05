"""地貌语义分类工具（三种方法）。

包含工具：
    classify_terrain_rules      规则分类：基于坡度/曲率/TPI 的纯局部形态判据
    classify_geomorphons        Geomorphons：Jasiewicz & Stepinski (2013) 地形形态算法
    classify_terrain_onnx       ONNX CNN：滑窗推理，复现 Geomorphons 判定（蒸馏模型）

三者的性能与适用面差异显著，工具会通过 warnings 与错误提示引导 Agent 正确选择。

实测数据（本机 CPU，见 bench/results/onnx_sliding_window_bench.md）：

    方法           64×64     128×128    192×128    256×256      特点
    rules          <0.1 s    <0.1 s     ~0.1 s     ~0.2 s       最快，纯向量化
    geomorphons    ~0.2 s    ~0.8 s     ~1.9 s     ~3.3 s       经典算法，精度速度均衡
    onnx            6.5 s     24.5 s     55.4 s     ~98 s(推算)  滑窗，仅限 ≤128

关于 ONNX 方法的重要约束：
    该实现为逐像元滑窗（每个像元取 64×64 patch），
    N×N 栅格需要 N² 次 patch 推理并一次性分配 N²·64²·4 字节数组
    （256×256 约 1.07 GB）。
    实测 128×128 需 24.5 s、192×192 需 55.4 s，已超出交互式可用范围。
    工具层对此设有分辨率守卫（上限 128），超限直接拒绝并给出替代建议。

优化方向（未实施）：改为分块构建 patch 批量推理，
可将峰值内存从 O(N²·64²) 降至 O(chunk·64²)，但耗时量级不变。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional, Sequence

import numpy as np

from .base import (
    ARTIFACT_ROOT,
    cell_size_m,
    class_distribution,
    validate_bbox,
    validate_resolution,
)
from .cache import terrain_cache
from .errors import ToolErrorType, ToolException, fail, ok

# ONNX 滑窗分类的分辨率上限（超出则内存/耗时不可接受）
ONNX_MAX_RESOLUTION = 128

_METHOD_INFO: Dict[str, Dict[str, Any]] = {
    "rules": {
        "label_cn": "规则分类",
        "desc": "基于坡度、曲率、TPI 的局部形态判据",
        "perf_hint": "最快，适合大范围快速筛查",
    },
    "geomorphons": {
        "label_cn": "Geomorphons",
        "desc": "Jasiewicz & Stepinski (2013) 八方向视线地形形态算法",
        "perf_hint": "精度与速度均衡，推荐默认使用",
    },
    "onnx": {
        "label_cn": "ONNX CNN",
        "desc": "以 CNN 蒸馏 Geomorphons 判定，滑窗推理",
        "perf_hint": "滑窗开销大，仅限小范围（≤128）或需要 GPU/批量场景",
    },
}


def _run_classify(
    tool: str,
    method: str,
    bbox: Sequence[float],
    resolution: int,
    dem_path: Optional[str],
    output_format: str,
    t0: float,
) -> Dict[str, Any]:
    """三种分类方法的公共执行逻辑。"""
    from ..services.export_service import (
        export_grid_as_czml,
        export_grid_as_kml,
        export_grid_classification_as_geojson,
    )
    from ..services.terrain_classifier import (
        TERRAIN_CLASSES,
        GeomorphonsClassifier,
        ONNXTerrainClassifier,
        ONNX_PATH,
        classify_terrain,
        get_terrain_class_legend,
    )

    west, south, east, north = validate_bbox(bbox)
    res = validate_resolution(resolution)

    if method == "onnx" and res > ONNX_MAX_RESOLUTION:
        est_sec = res * res * 1.53 / 1000.0
        est_mem = res * res * 64 * 64 * 4 / 1e9
        return fail(
            tool,
            f"ONNX 滑窗分类在 {res}×{res} 栅格上需要 {res*res:,} 次 patch 推理"
            f"（约 {est_sec:,.0f} 秒、{est_mem:.1f} GB 内存），超出可用范围。"
            f"建议：① 将 resolution 降至 {ONNX_MAX_RESOLUTION} 或以下；"
            f"② 改用 classify_geomorphons（256×256 约 3.3 秒）；"
            f"③ 改用 classify_terrain_rules（最快，约 0.2 秒）",
            ToolErrorType.INVALID_RESOLUTION,
            (time.perf_counter() - t0) * 1000,
        ).to_dict()

    terrain, cache_hit = terrain_cache.get_or_compute(
        (west, south, east, north), res, dem_path=dem_path
    )
    cell = cell_size_m((west, south, east, north), res)

    t_infer = time.perf_counter()
    if method == "rules":
        ids, cost_adj, conf = classify_terrain(
            dem=terrain.dem_grid,
            slope_deg=terrain.slope_deg,
            curvature=terrain.curvature,
            cell_size_m=cell,
        )
    elif method == "geomorphons":
        ids, cost_adj, conf = GeomorphonsClassifier().classify(
            dem=terrain.dem_grid,
            slope_deg=terrain.slope_deg,
            curvature=terrain.curvature,
            cell_size_m=cell,
        )
    else:
        if not ONNX_PATH.exists():
            return fail(
                tool,
                f"ONNX 模型不存在：{ONNX_PATH}。请先运行 train_morphology.py 训练并导出模型",
                ToolErrorType.MODEL_NOT_FOUND,
                (time.perf_counter() - t0) * 1000,
            ).to_dict()
        ids, cost_adj, conf = ONNXTerrainClassifier().classify(terrain.dem_grid)
    infer_ms = (time.perf_counter() - t_infer) * 1000

    legend = get_terrain_class_legend()
    dist = class_distribution(ids, legend)

    # 落盘（分类结果需带类别名与置信度，故用专用导出函数）
    fmt = (output_format or "geojson").lower()
    if fmt not in {"geojson", "czml", "kml", "npz"}:
        raise ToolException(
            f"不支持的导出格式 {output_format!r}，可选 geojson / czml / kml / npz",
            ToolErrorType.UNSUPPORTED_FORMAT,
        )

    subdir = ARTIFACT_ROOT / uuid.uuid4().hex[:12]
    subdir.mkdir(parents=True, exist_ok=True)
    if fmt == "geojson":
        path = subdir / "terrain_classification.geojson"
        cnt = export_grid_classification_as_geojson(
            path, terrain.lon_grid, terrain.lat_grid, ids, conf, legend, stride=1
        )
    elif fmt == "czml":
        path = subdir / "terrain_classification.czml"
        cnt = export_grid_as_czml(
            path, terrain.lon_grid, terrain.lat_grid, ids.astype(np.float64),
            "terrain_classification"
        )
    elif fmt == "kml":
        path = subdir / "terrain_classification.kml"
        cnt = export_grid_as_kml(
            path, terrain.lon_grid, terrain.lat_grid, ids.astype(np.float64),
            "terrain_classification"
        )
    else:
        path = subdir / "terrain_classification.npz"
        np.savez_compressed(path, class_ids=ids, confidence=conf)
        cnt = int(ids.size)

    warnings = list(dist.pop("warnings", []))
    if terrain.dem_source == "synthetic":
        warnings.append("当前使用合成地形，分类结果仅用于流程验证")
    if method == "onnx":
        warnings.append(
            "ONNX 模型的标签来自 Geomorphons 伪标签，"
            "其输出应理解为「复现 Geomorphons 判定的结果」，而非独立的真实地貌判读"
        )

    dominant = dist.get("dominant_class")
    dominant_cn = next(
        (c["label_cn"] for c in legend if (c.get("label_cn") or c.get("name")) == dominant),
        dominant,
    )

    data: Dict[str, Any] = {
        "summary": (
            f"{_METHOD_INFO[method]['label_cn']}：{res}×{res} 栅格，"
            f"共 {dist['distinct_classes']} 类，以「{dominant_cn}」为主"
            f"（占 {dist['dominant_ratio']:.1%}），耗时 {infer_ms:.0f} ms"
        ),
        "method": method,
        "method_desc": _METHOD_INFO[method]["desc"],
        "bbox": [west, south, east, north],
        "resolution": res,
        "cell_size_m": cell,
        "dem_source": terrain.dem_source,
        "distribution": dist,
        "mean_confidence": round(float(np.nanmean(conf)), 4) if conf.size else None,
        "cost_adjustment_stats": {
            "min": round(float(np.nanmin(cost_adj)), 3),
            "max": round(float(np.nanmax(cost_adj)), 3),
            "mean": round(float(np.nanmean(cost_adj)), 3),
        },
        "legend": legend,
        "infer_ms": round(infer_ms, 1),
        "artifact": {
            "format": fmt,
            "name": "terrain_classification",
            "path": str(path),
            "feature_count": cnt,
        },
        "cache_hit": cache_hit,
    }
    if warnings:
        data["warnings"] = warnings

    return ok(tool, data, (time.perf_counter() - t0) * 1000).to_dict()


def classify_terrain_rules(
    bbox: Sequence[float],
    resolution: int = 256,
    dem_path: Optional[str] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """基于局部形态判据的地貌分类（8 类）。

    判据为坡度、曲率与 TPI（地形位置指数）的组合规则，
    纯向量化实现，速度最快，适合大范围快速筛查。

    8 个类别：平地 / 山顶 / 山脊 / 陡坡 / 缓坡 / 山谷 / 洼地 / 陡崖
    """
    tool = "classify_terrain_rules"
    t0 = time.perf_counter()
    try:
        return _run_classify(tool, "rules", bbox, resolution, dem_path, output_format, t0)
    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"规则分类失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()


def classify_geomorphons(
    bbox: Sequence[float],
    resolution: int = 256,
    dem_path: Optional[str] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """Geomorphons 地形形态分类（8 类）。

    采用 Jasiewicz & Stepinski (2013) 提出的算法，通过八方向视线
    与高程差判别局部地形形态，是地形形态学领域的经典方法。
    精度与速度均衡，推荐作为默认分类方法。
    """
    tool = "classify_geomorphons"
    t0 = time.perf_counter()
    try:
        return _run_classify(tool, "geomorphons", bbox, resolution, dem_path, output_format, t0)
    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"Geomorphons 分类失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()


def classify_terrain_onnx(
    bbox: Sequence[float],
    resolution: int = 128,
    dem_path: Optional[str] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """ONNX CNN 地形形态分类（8 类）。

    以 CNN 蒸馏 Geomorphons 判定结果，单 patch 推理 1.53 ms
    （较 PyTorch 提速 2.34x，输出一致性 100%）。

    ⚠ 性能约束：实现为逐像元滑窗，N×N 栅格需 N² 次 patch 推理，
    因此 resolution 上限为 128。更大范围请改用 classify_geomorphons。
    """
    tool = "classify_terrain_onnx"
    t0 = time.perf_counter()
    try:
        return _run_classify(tool, "onnx", bbox, resolution, dem_path, output_format, t0)
    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"ONNX 分类失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()
