"""面向地理场景的量化/加速一致性验证。

通用模型量化只看 top-1 accuracy，在这里不够用。地貌分类有三个特点，
决定了必须换一套验证口径：

1. **类别极度不平衡**。平地、缓坡往往占七八成，悬崖、洼地、山顶可能各不到 1%。
   一个「整体一致率 98%」的量化模型，完全可能已经把悬崖全抹成陡坡 ——
   而悬崖恰恰是地质灾害评估里最要命的那一类。
   所以必须逐类看 IoU，并且对稀有类单独设阈值。

2. **空间连续性比单点精度更重要**。量化噪声的典型表现不是整体偏移，
   而是在大面积同类区域里打出椒盐噪点。单看像素一致率看不出来
   （噪点只占几个百分点），但斑块边界密度会暴涨 —— 而边界密度直接决定
   下游能不能用（一堆伪边界的栅格没法做分区统计）。

3. **误差会传播到下游**。分类结果会转成 cost_surface 再喂给路径规划，
   分类的微小扰动可能让推荐路线换一条。所以最后要看 cost surface 的偏差。

因此本模块的验收口径是四条，任一不过即判定该优化不可用：
  整体一致率、稀有类 IoU、边界密度增幅、cost surface 偏差。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

# 默认判定阈值。放宽任何一个都意味着接受更高的业务风险，
# 改之前请想清楚具体是什么业务在吃这个结果。
DEFAULT_THRESHOLDS = {
    "min_overall_agreement": 0.90,   # 整体像素一致率下限
    "min_rare_class_iou": 0.60,      # 稀有类（面积占比 <2%）IoU 下限
    "min_common_class_iou": 0.75,    # 常见类 IoU 下限
    "max_boundary_density_ratio": 1.30,  # 边界密度相对增幅上限
    "max_cost_rel_diff": 0.05,       # cost surface 平均相对偏差上限
}

RARE_CLASS_AREA_THRESHOLD = 0.02  # 面积占比低于此值视为稀有类


def _as_int(a: np.ndarray) -> np.ndarray:
    return np.asarray(a).astype(np.int64).ravel()


def class_distribution(class_ids: np.ndarray, n_classes: int = 8) -> np.ndarray:
    """各类面积占比。"""
    counts = np.bincount(_as_int(class_ids), minlength=n_classes)
    total = counts.sum()
    if total == 0:
        return np.zeros(n_classes, dtype=np.float64)
    return counts / total


def per_class_iou(
    ref: np.ndarray, new: np.ndarray, n_classes: int = 8
) -> np.ndarray:
    """逐类 IoU。把 ref 当作参考真值（不是绝对真值，只是对照基准）。"""
    r = _as_int(ref)
    n = _as_int(new)
    ious = np.zeros(n_classes, dtype=np.float64)
    for c in range(n_classes):
        inter = np.count_nonzero((r == c) & (n == c))
        union = np.count_nonzero((r == c) | (n == c))
        ious[c] = inter / union if union > 0 else np.nan
    return ious


def boundary_density(class_ids: np.ndarray) -> float:
    """类别斑块边界密度：与右/下邻域类别不同的像元占比。

    这是检测量化椒盐噪声最灵敏的指标 —— 噪声不显著改变一致率，
    但会把连续的斑块打碎。
    """
    a = np.asarray(class_ids)
    if a.ndim != 2 or min(a.shape) < 2:
        return 0.0
    diff_r = (a[:-1, :] != a[1:, :]).mean()
    diff_c = (a[:, :-1] != a[:, 1:]).mean()
    return float((diff_r + diff_c) / 2.0)


def total_variation_distance(p: np.ndarray, q: np.ndarray) -> float:
    """类别分布的总变差距离，衡量整体分布漂移。"""
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    return float(0.5 * np.abs(p - q).sum())


def compare_classifications(
    ref_ids: np.ndarray,
    new_ids: np.ndarray,
    ref_conf: Optional[np.ndarray] = None,
    new_conf: Optional[np.ndarray] = None,
    ref_cost: Optional[np.ndarray] = None,
    new_cost: Optional[np.ndarray] = None,
    n_classes: int = 8,
    class_names: Optional[Sequence[str]] = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """对比两次分类结果，给出是否可接受的判定。

    Args:
        ref_ids: 参考结果（通常是 fp32 原模型 + stride=1）
        new_ids: 待验证结果（量化模型 / 大 stride）
        ref_conf / new_conf: 置信度图，用于看退化是否集中在低置信区
        ref_cost / new_cost: 由分类结果换算出的通行成本面，用于看下游影响
        class_names: 类别名，缺省用 id
        thresholds: 覆盖默认阈值

    Returns:
        含 metrics / per_class / verdict 的 dict，100% 可 JSON 序列化
    """
    thr = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        thr.update(thresholds)

    ref_ids = np.asarray(ref_ids)
    new_ids = np.asarray(new_ids)
    if ref_ids.shape != new_ids.shape:
        raise ValueError(
            f"两次分类结果形状不一致：{ref_ids.shape} vs {new_ids.shape}"
        )

    r = _as_int(ref_ids)
    n = _as_int(new_ids)
    agreement = float(np.count_nonzero(r == n) / r.size)

    dist_ref = class_distribution(ref_ids, n_classes)
    dist_new = class_distribution(new_ids, n_classes)
    ious = per_class_iou(ref_ids, new_ids, n_classes)

    names = list(class_names) if class_names else [str(i) for i in range(n_classes)]
    per_class: List[Dict[str, Any]] = []
    rare_violations: List[str] = []
    common_violations: List[str] = []

    for c in range(n_classes):
        iou = float(ious[c])
        area_ref = float(dist_ref[c])
        area_new = float(dist_new[c])
        rel_change = (
            abs(area_new - area_ref) / area_ref if area_ref > 1e-12 else float("inf")
        )
        # 必须显式转 Python bool：np.bool_ 既是 `is True` 判定的陷阱，
        # 也无法被 json.dumps 序列化（本模块对外承诺可 JSON 序列化）
        is_rare = bool(area_ref < RARE_CLASS_AREA_THRESHOLD and np.isfinite(iou))
        limit = thr["min_rare_class_iou"] if is_rare else thr["min_common_class_iou"]
        passed = bool((not np.isfinite(iou)) or iou >= limit)
        if np.isfinite(iou) and not passed:
            (rare_violations if is_rare else common_violations).append(names[c])

        per_class.append(
            {
                "class": names[c],
                "id": c,
                # round() 作用在 np.float64 上仍返回 np.float64，json 序列化会失败
                "iou": None if not np.isfinite(iou) else round(float(iou), 4),
                "area_ref": round(area_ref, 5),
                "area_new": round(area_new, 5),
                "area_rel_change": None
                if not np.isfinite(rel_change)
                else round(rel_change, 4),
                "rare": is_rare,
                "iou_threshold": limit,
                "passed": passed,
            }
        )

    bd_ref = boundary_density(ref_ids)
    bd_new = boundary_density(new_ids)
    bd_ratio = float(bd_new / bd_ref) if bd_ref > 1e-12 else float("inf")

    conf_block: Dict[str, Any] = {}
    if ref_conf is not None and new_conf is not None:
        rc = np.asarray(ref_conf, dtype=np.float64).ravel()
        nc = np.asarray(new_conf, dtype=np.float64).ravel()
        disagree = r != n
        conf_block = {
            "mean_conf_ref": round(float(rc.mean()), 4),
            "mean_conf_new": round(float(nc.mean()), 4),
            "mean_conf_delta": round(float(nc.mean() - rc.mean()), 4),
            "mean_conf_on_disagreed_pixels": (
                round(float(rc[disagree].mean()), 4)
                if disagree.any()
                else None
            ),
            "disagreement_is_low_confidence": bool(
                disagree.any()
                and rc[disagree].mean() < rc.mean()
            ),
        }

    cost_block: Dict[str, Any] = {}
    cost_ok = True
    if ref_cost is not None and new_cost is not None:
        a = np.asarray(ref_cost, dtype=np.float64)
        b = np.asarray(new_cost, dtype=np.float64)
        denom = np.abs(a)
        denom[denom < 1e-12] = 1e-12
        rel = np.abs(b - a) / denom
        cost_rel = float(rel.mean())
        cost_ok = cost_rel <= thr["max_cost_rel_diff"]
        cost_block = {
            "cost_mean_rel_diff": round(cost_rel, 5),
            "cost_max_rel_diff": round(float(rel.max()), 5),
            "cost_threshold": thr["max_cost_rel_diff"],
            "passed": cost_ok,
        }

    agreement_ok = agreement >= thr["min_overall_agreement"]
    boundary_ok = bd_ratio <= thr["max_boundary_density_ratio"]

    checks = {
        "overall_agreement": {
            "value": round(agreement, 4),
            "threshold": thr["min_overall_agreement"],
            "passed": agreement_ok,
        },
        "rare_class_iou": {
            "value": None if not rare_violations else "见 per_class",
            "threshold": thr["min_rare_class_iou"],
            "passed": not rare_violations,
            "violations": rare_violations,
        },
        "common_class_iou": {
            "value": None if not common_violations else "见 per_class",
            "threshold": thr["min_common_class_iou"],
            "passed": not common_violations,
            "violations": common_violations,
        },
        "boundary_density": {
            "value": round(bd_ratio, 4),
            "threshold": thr["max_boundary_density_ratio"],
            "passed": boundary_ok,
            "ref": round(bd_ref, 5),
            "new": round(bd_new, 5),
        },
    }
    if cost_block:
        checks["cost_surface"] = cost_block

    passed = all(
        c.get("passed", True) for c in checks.values() if isinstance(c, dict)
    )

    return {
        "passed": bool(passed),
        "metrics": {
            "overall_agreement": round(agreement, 4),
            "distribution_tvd": round(total_variation_distance(dist_ref, dist_new), 5),
            "boundary_density_ref": round(bd_ref, 5),
            "boundary_density_new": round(bd_new, 5),
            "boundary_density_ratio": round(bd_ratio, 4),
            **conf_block,
        },
        "per_class": per_class,
        "checks": checks,
        "thresholds": thr,
    }
