from __future__ import annotations

from typing import Dict, List, Tuple
import numpy as np


# 12 类地貌分类体系（Iwahashi & Pike 启发 + GIS 常用分类）
TERRAIN_CLASSES: Dict[int, Dict[str, object]] = {
    0:  {"name": "flat",        "label_cn": "平地",    "color": "#38a800", "cost_factor": 0.5},
    1:  {"name": "peak",        "label_cn": "山顶",    "color": "#ff0000", "cost_factor": 2.5},
    2:  {"name": "ridge",       "label_cn": "山脊",    "color": "#ff8000", "cost_factor": 2.0},
    3:  {"name": "upper_slope", "label_cn": "上坡",    "color": "#ffbf00", "cost_factor": 1.5},
    4:  {"name": "middle_slope","label_cn": "中坡",    "color": "#ffff00", "cost_factor": 1.2},
    5:  {"name": "lower_slope", "label_cn": "下坡",    "color": "#c1e800", "cost_factor": 1.0},
    6:  {"name": "valley",      "label_cn": "山谷",    "color": "#38a800", "cost_factor": 1.8},
    7:  {"name": "depression",  "label_cn": "洼地",    "color": "#0040ff", "cost_factor": 2.2},
    8:  {"name": "scarp",       "label_cn": "陡崖",    "color": "#ff00ff", "cost_factor": 3.0},
    9:  {"name": "watercourse", "label_cn": "水道",    "color": "#00a6ff", "cost_factor": 2.8},
    10: {"name": "shoulder",    "label_cn": "肩坡",    "color": "#5ebd00", "cost_factor": 1.3},
    11: {"name": "toe_slope",   "label_cn": "麓坡",    "color": "#8bd100", "cost_factor": 1.1},
}


def _tpi(dem: np.ndarray, window: int = 3) -> np.ndarray:
    """Topographic Position Index: 中心高程 - 邻域平均高程。
    window 必须是奇数。正值 = 凸地形(山脊/山顶), 负值 = 凹地形(山谷/洼地)。
    """
    rows, cols = dem.shape
    out = np.zeros_like(dem, dtype=np.float64)
    half = window // 2
    for r in range(rows):
        r0 = max(0, r - half)
        r1 = min(rows, r + half + 1)
        for c in range(cols):
            c0 = max(0, c - half)
            c1 = min(cols, c + half + 1)
            patch = dem[r0:r1, c0:c1]
            out[r, c] = float(dem[r, c]) - float(np.mean(patch))
    return out


def _multi_scale_tpi(dem: np.ndarray, scales: List[int]) -> np.ndarray:
    """多尺度 TPI 融合：对不同窗口的 TPI 取均值，避免单尺度偏差。"""
    acc = None
    for w in scales:
        t = _tpi(dem, w)
        if acc is None:
            acc = t
        else:
            acc += t
    return acc / max(1, len(scales))


def classify_terrain(
    dem: np.ndarray,
    slope_deg: np.ndarray,
    curvature: np.ndarray,
    cell_size_m: float = 30.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """地貌分类入口。

    输入:
        dem: 高程栅格 (rows, cols)
        slope_deg: 坡度栅格 (度)
        curvature: 曲率栅格
        cell_size_m: 栅格单元大小（米），用于自适应窗口

    返回:
        class_ids: 整数分类 ID 栅格 (rows, cols)
        cost_adjustment: 分类对应的代价调整系数栅格
        confidence: 分类置信度（0~1），基于 TPI 幅度
    """
    rows, cols = dem.shape
    if rows < 3 or cols < 3:
        z = np.zeros((rows, cols), dtype=np.int32)
        return z, np.ones_like(dem), np.ones_like(dem)

    win_small = max(3, int(round(3.0 * cell_size_m / max(1.0, cell_size_m))))
    win_large = max(5, int(round(11.0 * cell_size_m / max(1.0, cell_size_m))))
    if win_small % 2 == 0:
        win_small += 1
    if win_large % 2 == 0:
        win_large += 1

    tpi_small = _tpi(dem, win_small)
    tpi_large = _tpi(dem, win_large)
    tpi_fused = (np.abs(tpi_small) + np.abs(tpi_large)) * 0.5

    tpi_small_norm = tpi_small / max(1e-9, float(np.std(tpi_small[np.isfinite(tpi_small)])))
    tpi_large_norm = tpi_large / max(1e-9, float(np.std(tpi_large[np.isfinite(tpi_large)])))

    class_ids = np.zeros((rows, cols), dtype=np.int32)
    confidence = np.zeros((rows, cols), dtype=np.float64)

    for r in range(rows):
        for c in range(cols):
            sl = float(slope_deg[r, c])
            curv = float(curvature[r, c])
            ts = float(tpi_small_norm[r, c])
            tl = float(tpi_large_norm[r, c])
            tpi_mag = float(tpi_fused[r, c])

            conf = min(1.0, abs(ts) * 0.3 + abs(tl) * 0.2 + tpi_mag * 0.01)
            confidence[r, c] = min(1.0, conf)

            if sl < 2.0 and abs(ts) < 0.5:
                cid = 0  # flat
            elif sl > 45.0:
                cid = 8  # scarp
            elif ts > 1.5 and tl > 0.8:
                cid = 1  # peak
            elif ts > 0.8 and tl > 0.3:
                cid = 2  # ridge
            elif ts < -1.5 and tl < -0.8:
                cid = 7  # depression
            elif ts < -0.8 and tl < -0.3:
                cid = 6  # valley
            elif curv < -5.0:
                cid = 9  # watercourse (强凹曲率)
            elif ts > 0.3 and sl > 10.0:
                cid = 10  # shoulder
            elif ts < -0.3 and sl > 5.0:
                cid = 11  # toe_slope
            elif sl > 15.0 and ts > 0.0:
                cid = 3  # upper_slope
            elif sl > 5.0 and ts > -0.3:
                cid = 4  # middle_slope
            elif sl > 2.0:
                cid = 5  # lower_slope
            else:
                cid = 4  # middle_slope fallback

            class_ids[r, c] = cid

    cost_adjustment = np.zeros((rows, cols), dtype=np.float64)
    for cid, meta in TERRAIN_CLASSES.items():
        cf = float(meta["cost_factor"])
        mask = class_ids == cid
        cost_adjustment[mask] = cf

    return class_ids, cost_adjustment, confidence


def get_terrain_class_legend() -> List[Dict[str, object]]:
    """返回分类图例，供前端渲染色带使用。"""
    legend = []
    for cid in sorted(TERRAIN_CLASSES.keys()):
        meta = TERRAIN_CLASSES[cid]
        legend.append({
            "id": cid,
            "name": str(meta["name"]),
            "label_cn": str(meta["label_cn"]),
            "color": str(meta["color"]),
            "cost_factor": float(meta["cost_factor"]),
        })
    return legend
