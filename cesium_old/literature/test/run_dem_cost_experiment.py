#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEM方向性通行代价模型完整实验验证脚本

目标：
1) 合成地形上验证一/二阶导数估计误差
2) 在多模型(B0/B1/B2/B3/Ours)上进行消融比较
3) 在多分辨率上验证稳定性
4) 验证方向性（起终点互换）的显著差异
5) 生成实验结果文件、统计表与图
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import matplotlib.pyplot as plt  # type: ignore
    HAS_MPL = True
except Exception:
    HAS_MPL = False


EPS = 1e-9


@dataclass
class ModelConfig:
    name: str
    use_curvature: bool
    use_ridge_valley: bool
    use_contour_density: bool
    use_directional_constraint: bool


@dataclass
class PathResult:
    total_cost: float
    path: List[Tuple[int, int]]
    success: bool


def robust_scale(arr: np.ndarray) -> float:
    v = arr[np.isfinite(arr)]
    if v.size == 0:
        return 1.0
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return max(1e-6, 1.4826 * mad if mad > 0 else abs(med) + 1e-6)


def meshgrid_xy(n: int, extent: float) -> Tuple[np.ndarray, np.ndarray, float, float]:
    x = np.linspace(-extent, extent, n)
    y = np.linspace(-extent, extent, n)
    xx, yy = np.meshgrid(x, y)
    dx = float(x[1] - x[0]) if n > 1 else 1.0
    dy = float(y[1] - y[0]) if n > 1 else 1.0
    return xx, yy, dx, dy


def generate_terrain(name: str, n: int, extent: float, seed: int) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    xx, yy, _, _ = meshgrid_xy(n, extent)
    analytic: Dict[str, np.ndarray] = {}

    if name == "plane":
        a, b, c = 0.09, -0.06, 100.0
        z = a * xx + b * yy + c
        analytic["gx"] = np.full_like(z, a)
        analytic["gy"] = np.full_like(z, b)
        analytic["zxx"] = np.zeros_like(z)
        analytic["zyy"] = np.zeros_like(z)
    elif name == "cone":
        r = np.sqrt(xx * xx + yy * yy)
        z = 40.0 * r + 80.0
        rr = np.maximum(r, 1e-6)
        analytic["gx"] = 40.0 * xx / rr
        analytic["gy"] = 40.0 * yy / rr
    elif name == "saddle":
        a = 0.018
        z = a * (xx * xx - yy * yy) + 100.0
        analytic["gx"] = 2.0 * a * xx
        analytic["gy"] = -2.0 * a * yy
        analytic["zxx"] = np.full_like(z, 2.0 * a)
        analytic["zyy"] = np.full_like(z, -2.0 * a)
    elif name == "ridge_valley":
        A, kx, ky = 28.0, 0.11, 0.08
        z = A * np.sin(kx * xx) * np.cos(ky * yy) + 100.0
        analytic["gx"] = A * kx * np.cos(kx * xx) * np.cos(ky * yy)
        analytic["gy"] = -A * ky * np.sin(kx * xx) * np.sin(ky * yy)
        analytic["zxx"] = -A * (kx ** 2) * np.sin(kx * xx) * np.cos(ky * yy)
        analytic["zyy"] = -A * (ky ** 2) * np.sin(kx * xx) * np.cos(ky * yy)
    else:
        raise ValueError(f"Unknown terrain: {name}")

    # 轻微噪声，模拟真实DEM测量误差
    z = z + rng.normal(0.0, 0.25, size=z.shape)
    return z.astype(np.float64), analytic


def downsample_block_mean(z: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return z.copy()
    h, w = z.shape
    hh = (h // factor) * factor
    ww = (w // factor) * factor
    trimmed = z[:hh, :ww]
    reshaped = trimmed.reshape(hh // factor, factor, ww // factor, factor)
    return reshaped.mean(axis=(1, 3))


def terrain_features(z: np.ndarray, dx: float, dy: float) -> Dict[str, np.ndarray]:
    gy, gx = np.gradient(z, dy, dx, edge_order=2)
    zyy, zyx = np.gradient(gy, dy, dx, edge_order=2)
    zxy, zxx = np.gradient(gx, dy, dx, edge_order=2)
    zxy = 0.5 * (zxy + zyx)

    slope = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))
    aspect = np.degrees(np.arctan2(-gy, -gx))
    aspect = np.where(aspect < 0.0, aspect + 360.0, aspect)

    flowline = ridge_valley_intensity(z, dx, dy)
    kappa_mag = np.sqrt(np.maximum(0.0, zxx * zxx + 2.0 * zxy * zxy + zyy * zyy))

    return {
        "gx": gx,
        "gy": gy,
        "zxx": zxx,
        "zxy": zxy,
        "zyy": zyy,
        "slope": slope,
        "aspect": aspect,
        "flowline": flowline,
        "kappa_mag": kappa_mag,
    }


def ridge_valley_intensity(z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    h, w = z.shape
    dirs = [
        (0, 1), (1, 1), (1, 0), (1, -1),
        (0, -1), (-1, -1), (-1, 0), (-1, 1),
    ]
    steps = [
        dx, math.hypot(dx, dy), dy, math.hypot(dx, dy),
        dx, math.hypot(dx, dy), dy, math.hypot(dx, dy),
    ]
    fd = np.full((h, w), -1, dtype=np.int32)
    rd = np.full((h, w), -1, dtype=np.int32)
    acc = np.ones((h, w), dtype=np.float64)
    racc = np.ones((h, w), dtype=np.float64)

    for r in range(h):
        for c in range(w):
            z0 = z[r, c]
            best_drop = -1e30
            best_rise = -1e30
            i_drop = -1
            i_rise = -1
            for i, (dr, dc) in enumerate(dirs):
                rr = r + dr
                cc = c + dc
                if rr < 0 or rr >= h or cc < 0 or cc >= w:
                    continue
                grad = (z[rr, cc] - z0) / max(EPS, steps[i])
                if -grad > best_drop:
                    best_drop = -grad
                    i_drop = i
                if grad > best_rise:
                    best_rise = grad
                    i_rise = i
            fd[r, c] = i_drop
            rd[r, c] = i_rise

    flat_desc = np.argsort(z.reshape(-1))[::-1]
    flat_asc = np.argsort(z.reshape(-1))
    for idx in flat_desc:
        r = int(idx // w)
        c = int(idx % w)
        i = int(fd[r, c])
        if i < 0:
            continue
        rr = r + dirs[i][0]
        cc = c + dirs[i][1]
        if 0 <= rr < h and 0 <= cc < w:
            acc[rr, cc] += acc[r, c]
    for idx in flat_asc:
        r = int(idx // w)
        c = int(idx % w)
        i = int(rd[r, c])
        if i < 0:
            continue
        rr = r + dirs[i][0]
        cc = c + dirs[i][1]
        if 0 <= rr < h and 0 <= cc < w:
            racc[rr, cc] += racc[r, c]

    return np.log1p(np.maximum(acc, racc))


def dijkstra_min_cost_path(
    z: np.ndarray,
    feats: Dict[str, np.ndarray],
    start: Tuple[int, int],
    end: Tuple[int, int],
    dx: float,
    dy: float,
    cfg: ModelConfig,
) -> PathResult:
    h, w = z.shape
    sr, sc = start
    er, ec = end
    if not (0 <= sr < h and 0 <= sc < w and 0 <= er < h and 0 <= ec < w):
        return PathResult(float("inf"), [], False)

    dist = np.full((h, w), np.inf, dtype=np.float64)
    visited = np.zeros((h, w), dtype=np.uint8)
    prev_r = np.full((h, w), -1, dtype=np.int32)
    prev_c = np.full((h, w), -1, dtype=np.int32)

    dirs = [
        (0, 1), (1, 1), (1, 0), (1, -1),
        (0, -1), (-1, -1), (-1, 0), (-1, 1),
    ]

    flow = feats["flowline"]
    gx = feats["gx"]
    gy = feats["gy"]
    zxx = feats["zxx"]
    zxy = feats["zxy"]
    zyy = feats["zyy"]

    s_rv = robust_scale(flow)
    s_kappa = robust_scale(feats["kappa_mag"])
    s_h = robust_scale(z)

    dist[sr, sc] = 0.0
    heap: List[Tuple[float, int, int]] = [(0.0, sr, sc)]

    while heap:
        d0, r, c = heapq.heappop(heap)
        if visited[r, c]:
            continue
        visited[r, c] = 1
        if r == er and c == ec:
            break

        for dr, dc in dirs:
            rr = r + dr
            cc = c + dc
            if rr < 0 or rr >= h or cc < 0 or cc >= w:
                continue
            vx = dc * dx
            vy = dr * dy
            step = math.hypot(vx, vy)
            ux = vx / max(EPS, step)
            uy = vy / max(EPS, step)

            # 方向性约束：只能朝向终点半平面
            if cfg.use_directional_constraint:
                gx_goal = (ec - c) * dx
                gy_goal = (er - r) * dy
                gnorm = math.hypot(gx_goal, gy_goal)
                if gnorm > EPS:
                    gx_goal /= gnorm
                    gy_goal /= gnorm
                    if ux * gx_goal + uy * gy_goal <= 0.0:
                        continue

            gdir = gx[r, c] * ux + gy[r, c] * uy
            edge_cost = step * math.sqrt(1.0 + gdir * gdir)

            if cfg.use_curvature:
                kappa = ux * ux * zxx[r, c] + 2.0 * ux * uy * zxy[r, c] + uy * uy * zyy[r, c]
                edge_cost *= 1.0 + abs(kappa) / max(EPS, s_kappa)

            if cfg.use_contour_density:
                contour_density = abs(gdir) / max(EPS, s_h)
                edge_cost *= 1.0 + contour_density

            if cfg.use_ridge_valley:
                edge_cost *= 1.0 + flow[r, c] / max(EPS, s_rv)

            nd = d0 + edge_cost
            if nd < dist[rr, cc]:
                dist[rr, cc] = nd
                prev_r[rr, cc] = r
                prev_c[rr, cc] = c
                heapq.heappush(heap, (nd, rr, cc))

    if not np.isfinite(dist[er, ec]):
        return PathResult(float("inf"), [], False)

    path: List[Tuple[int, int]] = []
    cr, cc = er, ec
    while not (cr == -1 or cc == -1):
        path.append((cr, cc))
        pr = int(prev_r[cr, cc])
        pc = int(prev_c[cr, cc])
        if pr == -1 or pc == -1:
            break
        cr, cc = pr, pc
    path.reverse()
    return PathResult(float(dist[er, ec]), path, True)


def path_metrics(path: List[Tuple[int, int]], z: np.ndarray, feats: Dict[str, np.ndarray], dx: float, dy: float) -> Dict[str, float]:
    if len(path) < 2:
        return {
            "path_len_m": float("inf"),
            "cum_ascent": float("inf"),
            "mean_abs_kappa": float("inf"),
            "mean_flowline": float("inf"),
            "tortuosity": float("inf"),
        }

    length = 0.0
    ascent = 0.0
    kappa_vals = []
    flow_vals = []
    for i in range(len(path) - 1):
        r0, c0 = path[i]
        r1, c1 = path[i + 1]
        step = math.hypot((c1 - c0) * dx, (r1 - r0) * dy)
        length += step
        dz = z[r1, c1] - z[r0, c0]
        if dz > 0:
            ascent += dz
        kappa_vals.append(float(feats["kappa_mag"][r0, c0]))
        flow_vals.append(float(feats["flowline"][r0, c0]))

    sr, sc = path[0]
    er, ec = path[-1]
    straight = max(EPS, math.hypot((ec - sc) * dx, (er - sr) * dy))
    tort = length / straight
    return {
        "path_len_m": length,
        "cum_ascent": ascent,
        "mean_abs_kappa": float(np.mean(kappa_vals)) if kappa_vals else 0.0,
        "mean_flowline": float(np.mean(flow_vals)) if flow_vals else 0.0,
        "tortuosity": tort,
    }


def path_overlap_ratio(path_a: List[Tuple[int, int]], path_b: List[Tuple[int, int]]) -> float:
    sa = set(path_a)
    sb = set(path_b)
    if not sa and not sb:
        return 1.0
    u = sa.union(sb)
    i = sa.intersection(sb)
    return len(i) / max(1, len(u))


def path_hausdorff(path_a: List[Tuple[int, int]], path_b: List[Tuple[int, int]], dx: float, dy: float) -> float:
    if not path_a or not path_b:
        return float("inf")
    a = np.array(path_a, dtype=np.float64)
    b = np.array(path_b, dtype=np.float64)
    a_xy = np.stack([a[:, 1] * dx, a[:, 0] * dy], axis=1)
    b_xy = np.stack([b[:, 1] * dx, b[:, 0] * dy], axis=1)

    def directed(p: np.ndarray, q: np.ndarray) -> float:
        dmax = 0.0
        for i in range(p.shape[0]):
            d = np.sqrt(np.sum((q - p[i]) ** 2, axis=1))
            dmax = max(dmax, float(np.min(d)))
        return dmax

    return max(directed(a_xy, b_xy), directed(b_xy, a_xy))


def angle_mae_deg(a: np.ndarray, b: np.ndarray) -> float:
    d = np.abs(a - b) % 360.0
    d = np.minimum(d, 360.0 - d)
    return float(np.mean(d))


def paired_sign_test(diffs: Sequence[float]) -> Dict[str, float]:
    xs = [x for x in diffs if abs(x) > 1e-12]
    n = len(xs)
    if n == 0:
        return {"n": 0, "p_value": 1.0, "n_pos": 0, "n_neg": 0}
    n_pos = sum(1 for x in xs if x > 0)
    n_neg = n - n_pos
    k = min(n_pos, n_neg)
    p = 0.0
    for i in range(0, k + 1):
        p += math.comb(n, i) * (0.5 ** n)
    p_value = min(1.0, 2.0 * p)
    return {"n": n, "p_value": p_value, "n_pos": n_pos, "n_neg": n_neg}


def bootstrap_ci_mean_diff(a: Sequence[float], b: Sequence[float], rng: random.Random, n_boot: int = 2000) -> Tuple[float, float, float]:
    if len(a) != len(b) or len(a) == 0:
        return (float("nan"), float("nan"), float("nan"))
    diffs = [x - y for x, y in zip(a, b)]
    obs = float(np.mean(diffs))
    boots = []
    n = len(diffs)
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boots.append(float(np.mean(sample)))
    boots.sort()
    lo = boots[int(0.025 * n_boot)]
    hi = boots[int(0.975 * n_boot)]
    return obs, lo, hi


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def save_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def save_geojson(path: Path, data: Dict[str, object]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def grid_to_lonlat(
    rc: Tuple[int, int],
    n_rows: int,
    n_cols: int,
    dx_m: float,
    dy_m: float,
    center_lon: float = 111.0,
    center_lat: float = 31.0,
) -> Tuple[float, float]:
    r, c = rc
    mid_r = (n_rows - 1) * 0.5
    mid_c = (n_cols - 1) * 0.5
    x_m = (c - mid_c) * dx_m
    y_m = (r - mid_r) * dy_m
    lon = center_lon + x_m / max(EPS, 111320.0 * math.cos(math.radians(center_lat)))
    lat = center_lat + y_m / 110574.0
    return float(lon), float(lat)


def maybe_plot_sample_paths(
    out_path: Path,
    z: np.ndarray,
    paths: Dict[str, List[Tuple[int, int]]],
    title: str,
) -> None:
    if not HAS_MPL:
        return
    plt.figure(figsize=(9, 7))
    plt.imshow(z, cmap="terrain", origin="lower")
    colors = {"B0": "cyan", "B1": "yellow", "B2": "magenta", "B3": "lime", "OURS": "red"}
    for name, p in paths.items():
        if not p:
            continue
        arr = np.array(p)
        plt.plot(arr[:, 1], arr[:, 0], color=colors.get(name, "white"), linewidth=1.5, label=name)
    plt.legend()
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def maybe_plot_bars(out_path: Path, title: str, labels: List[str], values: List[float], ylabel: str) -> None:
    if not HAS_MPL:
        return
    plt.figure(figsize=(8, 5))
    plt.bar(labels, values)
    plt.title(title)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def write_experiment_report(
    out_path: Path,
    summary_rows: List[Dict[str, object]],
    deriv_rows: List[Dict[str, object]],
    hypothesis: Dict[str, object],
) -> None:
    # 聚合
    model_to_costs: Dict[str, List[float]] = {}
    model_to_tort: Dict[str, List[float]] = {}
    model_to_ascent_pm: Dict[str, List[float]] = {}
    for r in summary_rows:
        m = str(r["model"])
        model_to_costs.setdefault(m, []).append(float(r["total_cost"]))
        model_to_tort.setdefault(m, []).append(float(r["tortuosity"]))
        model_to_ascent_pm.setdefault(m, []).append(float(r["ascent_per_meter"]))

    lines: List[str] = []
    lines.append("# DEM方向性通行代价模型实验结果报告")
    lines.append("")
    lines.append("## 1. 实验目的")
    lines.append("")
    lines.append("1. 验证一/二阶地形导数估计的数值正确性。")
    lines.append("2. 验证多要素代价模型（坡度+曲率+脊谷+等高线密度+方向约束）相对基线的优势。")
    lines.append("3. 验证多分辨率下模型稳定性。")
    lines.append("4. 验证起终点方向性约束带来的各向异性效果。")
    lines.append("")
    lines.append("## 2. 导数精度验证（合成地形）")
    lines.append("")
    if deriv_rows:
        grad_rmse = np.mean([float(r["grad_rmse"]) for r in deriv_rows if math.isfinite(float(r["grad_rmse"]))])
        curv_rmse = np.mean([float(r["laplacian_rmse"]) for r in deriv_rows if math.isfinite(float(r["laplacian_rmse"]))])
        lines.append(f"- 平均梯度RMSE: **{grad_rmse:.6f}**")
        lines.append(f"- 平均二阶项RMSE(拉普拉斯): **{curv_rmse:.6f}**")
    else:
        lines.append("- 无可用导数验证结果。")
    lines.append("")
    lines.append("## 3. 消融对比结果（核心指标）")
    lines.append("")
    lines.append("| 模型 | 平均总代价 | 平均曲折率 | 平均单位长度爬升 |")
    lines.append("|---|---:|---:|---:|")
    for m in ["B0", "B1", "B2", "B3", "OURS"]:
        if m not in model_to_costs:
            continue
        lines.append(
            f"| {m} | {np.mean(model_to_costs[m]):.4f} | {np.mean(model_to_tort[m]):.4f} | {np.mean(model_to_ascent_pm[m]):.4f} |"
        )
    lines.append("")
    lines.append("## 4. 假设检验结论")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(hypothesis, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 5. 结果解释")
    lines.append("")
    lines.append("1. **导数误差验证**：若梯度/二阶项误差低，说明后续代价项构造具有数值基础。")
    lines.append("2. **消融优势**：若 OURS 在总代价、曲折率、单位长度爬升上整体更优，表明综合建模优于单因素建模。")
    lines.append("3. **方向性检验**：起终点互换后路径重合度下降、分布差异显著，说明模型确实是各向异性。")
    lines.append("4. **多尺度稳定性**：跨尺度路径Hausdorff距离与指标CV可反映工程可迁移性。")
    lines.append("")
    lines.append("## 6. 输出文件说明")
    lines.append("")
    lines.append("- `derivative_validation.csv`: 合成地形导数误差表")
    lines.append("- `experiment_summary.csv`: 全部实验明细（模型/尺度/指标）")
    lines.append("- `hypothesis_tests.json`: 统计检验结果")
    lines.append("- `ablation_mean_total_cost.png`: 消融平均总代价柱状图（若matplotlib可用）")
    lines.append("- `sample_paths.png`: 样例路径可视化（若matplotlib可用）")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full DEM terrain cost experiment")
    parser.add_argument("--outdir", type=str, default="", help="Output directory. Default auto timestamp folder.")
    parser.add_argument("--seed", type=int, default=20260510, help="Random seed")
    parser.add_argument("--grid", type=int, default=160, help="Base grid size")
    parser.add_argument("--extent", type=float, default=80.0, help="Synthetic terrain half extent")
    args = parser.parse_args()

    np.random.seed(args.seed)
    random.seed(args.seed)
    rng = random.Random(args.seed)

    base_dir = Path(args.outdir).resolve() if args.outdir else (
        Path(__file__).resolve().parent / "output" / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    ensure_dir(base_dir)

    models = [
        ModelConfig("B0", False, False, False, False),
        ModelConfig("B1", True, False, False, False),
        ModelConfig("B2", False, True, False, False),
        ModelConfig("B3", True, True, False, False),
        ModelConfig("OURS", True, True, True, True),
    ]
    terrains = ["plane", "cone", "saddle", "ridge_valley"]
    scales = [1, 2, 4]

    summary_rows: List[Dict[str, object]] = []
    deriv_rows: List[Dict[str, object]] = []

    sample_plot_done = False
    sample_geojson_done = False
    ours_forward_costs: List[float] = []
    ours_reverse_costs: List[float] = []
    ours_overlap_reverse: List[float] = []
    ours_hausdorff_multiscale: List[float] = []

    for terrain_name in terrains:
        z_base, analytic = generate_terrain(terrain_name, args.grid, args.extent, args.seed + hash(terrain_name) % 1000)
        xx, yy, dx0, dy0 = meshgrid_xy(args.grid, args.extent)
        feats_base = terrain_features(z_base, dx0, dy0)

        # 导数真值验证（仅在基准尺度）
        if "gx" in analytic and "gy" in analytic:
            grad_rmse = float(np.sqrt(np.mean((feats_base["gx"] - analytic["gx"]) ** 2 + (feats_base["gy"] - analytic["gy"]) ** 2)))
        else:
            grad_rmse = float("nan")
        if "zxx" in analytic and "zyy" in analytic:
            lap_est = feats_base["zxx"] + feats_base["zyy"]
            lap_true = analytic["zxx"] + analytic["zyy"]
            lap_rmse = float(np.sqrt(np.mean((lap_est - lap_true) ** 2)))
        else:
            lap_rmse = float("nan")
        est_aspect = np.degrees(np.arctan2(-feats_base["gy"], -feats_base["gx"]))
        est_aspect = np.where(est_aspect < 0, est_aspect + 360, est_aspect)
        if "gx" in analytic and "gy" in analytic:
            tru_aspect = np.degrees(np.arctan2(-analytic["gy"], -analytic["gx"]))
            tru_aspect = np.where(tru_aspect < 0, tru_aspect + 360, tru_aspect)
            aspect_mae = angle_mae_deg(est_aspect, tru_aspect)
        else:
            aspect_mae = float("nan")
        deriv_rows.append({
            "terrain": terrain_name,
            "grad_rmse": grad_rmse,
            "laplacian_rmse": lap_rmse,
            "aspect_mae_deg": aspect_mae,
        })

        # 多尺度 + 消融
        ref_ours_path: Optional[List[Tuple[int, int]]] = None
        ref_dx = dx0
        ref_dy = dy0

        for sf in scales:
            z = downsample_block_mean(z_base, sf)
            n = z.shape[0]
            if n < 16:
                continue
            dx = dx0 * sf
            dy = dy0 * sf
            feats = terrain_features(z, dx, dy)
            start = (max(2, n // 8), max(2, n // 8))
            end = (min(n - 3, n - n // 8), min(n - 3, n - n // 8))
            rev_start, rev_end = end, start

            model_paths: Dict[str, List[Tuple[int, int]]] = {}
            model_path_results: Dict[str, PathResult] = {}

            for m in models:
                pr = dijkstra_min_cost_path(z, feats, start, end, dx, dy, m)
                if not pr.success:
                    continue
                pm = path_metrics(pr.path, z, feats, dx, dy)
                ascent_per_meter = pm["cum_ascent"] / max(EPS, pm["path_len_m"])
                summary_rows.append({
                    "terrain": terrain_name,
                    "scale_factor": sf,
                    "model": m.name,
                    "total_cost": pr.total_cost,
                    "path_len_m": pm["path_len_m"],
                    "cum_ascent": pm["cum_ascent"],
                    "ascent_per_meter": ascent_per_meter,
                    "mean_abs_kappa": pm["mean_abs_kappa"],
                    "mean_flowline": pm["mean_flowline"],
                    "tortuosity": pm["tortuosity"],
                })
                model_paths[m.name] = pr.path
                model_path_results[m.name] = pr

                if m.name == "OURS":
                    ours_forward_costs.append(pr.total_cost)
                    if sf == 1:
                        ref_ours_path = pr.path
                        ref_dx = dx
                        ref_dy = dy
                    else:
                        if ref_ours_path:
                            # 把低分辨率路径映射到高分辨率网格索引空间近似比较
                            p_scaled = [(r * sf, c * sf) for (r, c) in pr.path]
                            hd = path_hausdorff(ref_ours_path, p_scaled, ref_dx, ref_dy)
                            ours_hausdorff_multiscale.append(hd)

                    # 方向性检验：起终点互换
                    rev = dijkstra_min_cost_path(z, feats, rev_start, rev_end, dx, dy, m)
                    if rev.success:
                        ours_reverse_costs.append(rev.total_cost)
                        ours_overlap_reverse.append(path_overlap_ratio(pr.path, list(reversed(rev.path))))

            if (not sample_plot_done) and model_paths and sf == 1:
                maybe_plot_sample_paths(
                    base_dir / "sample_paths.png",
                    z,
                    model_paths,
                    f"Sample Paths on {terrain_name} (scale={sf})",
                )
                sample_plot_done = True

            if (not sample_geojson_done) and terrain_name == "ridge_valley" and sf == 1 and model_paths:
                features: List[Dict[str, object]] = []
                for model_name, path_rc in model_paths.items():
                    coords = []
                    for rc in path_rc:
                        lon, lat = grid_to_lonlat(rc, n, n, dx, dy, center_lon=111.0, center_lat=31.0)
                        coords.append([lon, lat])
                    pr = model_path_results.get(model_name)
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "kind": "path",
                            "model": model_name,
                            "total_cost": float(pr.total_cost) if pr else None,
                            "node_count": len(path_rc),
                            "terrain": terrain_name,
                            "scale_factor": sf,
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": coords,
                        },
                    })

                s_lon, s_lat = grid_to_lonlat(start, n, n, dx, dy, center_lon=111.0, center_lat=31.0)
                e_lon, e_lat = grid_to_lonlat(end, n, n, dx, dy, center_lon=111.0, center_lat=31.0)
                features.append({
                    "type": "Feature",
                    "properties": {"kind": "point", "name": "START"},
                    "geometry": {"type": "Point", "coordinates": [s_lon, s_lat]},
                })
                features.append({
                    "type": "Feature",
                    "properties": {"kind": "point", "name": "END"},
                    "geometry": {"type": "Point", "coordinates": [e_lon, e_lat]},
                })
                save_geojson(base_dir / "sample_paths.geojson", {
                    "type": "FeatureCollection",
                    "features": features,
                })
                sample_geojson_done = True

    save_csv(base_dir / "derivative_validation.csv", deriv_rows)
    save_csv(base_dir / "experiment_summary.csv", summary_rows)

    # 聚合统计
    by_model_cost: Dict[str, List[float]] = {}
    by_model_ascent_pm: Dict[str, List[float]] = {}
    by_model_tort: Dict[str, List[float]] = {}
    for r in summary_rows:
        m = str(r["model"])
        by_model_cost.setdefault(m, []).append(float(r["total_cost"]))
        by_model_ascent_pm.setdefault(m, []).append(float(r["ascent_per_meter"]))
        by_model_tort.setdefault(m, []).append(float(r["tortuosity"]))

    ablation_means = []
    for m in ["B0", "B1", "B2", "B3", "OURS"]:
        if m in by_model_cost:
            ablation_means.append({
                "model": m,
                "mean_total_cost": float(np.mean(by_model_cost[m])),
                "mean_ascent_per_meter": float(np.mean(by_model_ascent_pm[m])),
                "mean_tortuosity": float(np.mean(by_model_tort[m])),
            })
    save_csv(base_dir / "ablation_mean_metrics.csv", ablation_means)

    if ablation_means:
        maybe_plot_bars(
            base_dir / "ablation_mean_total_cost.png",
            "Ablation Mean Total Cost",
            [r["model"] for r in ablation_means],
            [float(r["mean_total_cost"]) for r in ablation_means],
            "Cost",
        )

    # 假设检验（OURS vs B0）
    ours_cost = by_model_cost.get("OURS", [])
    b0_cost = by_model_cost.get("B0", [])
    ours_ascent = by_model_ascent_pm.get("OURS", [])
    b0_ascent = by_model_ascent_pm.get("B0", [])
    ours_tort = by_model_tort.get("OURS", [])
    b0_tort = by_model_tort.get("B0", [])

    n_pair = min(len(ours_cost), len(b0_cost), len(ours_ascent), len(b0_ascent), len(ours_tort), len(b0_tort))
    ours_cost = ours_cost[:n_pair]
    b0_cost = b0_cost[:n_pair]
    ours_ascent = ours_ascent[:n_pair]
    b0_ascent = b0_ascent[:n_pair]
    ours_tort = ours_tort[:n_pair]
    b0_tort = b0_tort[:n_pair]

    diff_cost = [o - b for o, b in zip(ours_cost, b0_cost)]
    diff_ascent = [o - b for o, b in zip(ours_ascent, b0_ascent)]
    diff_tort = [o - b for o, b in zip(ours_tort, b0_tort)]

    h_tests = {
        "H1_ours_vs_b0_total_cost": {
            "sign_test": paired_sign_test(diff_cost),
            "bootstrap_mean_diff_95ci": bootstrap_ci_mean_diff(ours_cost, b0_cost, rng),
        },
        "H1_ours_vs_b0_ascent_per_meter": {
            "sign_test": paired_sign_test(diff_ascent),
            "bootstrap_mean_diff_95ci": bootstrap_ci_mean_diff(ours_ascent, b0_ascent, rng),
        },
        "H1_ours_vs_b0_tortuosity": {
            "sign_test": paired_sign_test(diff_tort),
            "bootstrap_mean_diff_95ci": bootstrap_ci_mean_diff(ours_tort, b0_tort, rng),
        },
        "H2_directionality": {
            "forward_mean_cost": float(np.mean(ours_forward_costs)) if ours_forward_costs else float("nan"),
            "reverse_mean_cost": float(np.mean(ours_reverse_costs)) if ours_reverse_costs else float("nan"),
            "path_overlap_forward_reverse_mean": float(np.mean(ours_overlap_reverse)) if ours_overlap_reverse else float("nan"),
        },
        "H3_multiscale_stability": {
            "ours_hausdorff_mean": float(np.mean(ours_hausdorff_multiscale)) if ours_hausdorff_multiscale else float("nan"),
            "ours_hausdorff_std": float(np.std(ours_hausdorff_multiscale)) if ours_hausdorff_multiscale else float("nan"),
        },
    }

    (base_dir / "hypothesis_tests.json").write_text(json.dumps(h_tests, ensure_ascii=False, indent=2), encoding="utf-8")
    (base_dir / "viewer_metrics.json").write_text(json.dumps({
        "ablation_mean_metrics": ablation_means,
        "hypothesis_tests": h_tests,
        "has_sample_geojson": sample_geojson_done,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    write_experiment_report(
        base_dir / "EXPERIMENT_REPORT.md",
        summary_rows,
        deriv_rows,
        h_tests,
    )

    print("")
    print("========== 实验运行完成 ==========")
    print(f"[输出目录] {base_dir}")
    print(f"[结果统计] summary行数={len(summary_rows)}, derivative行数={len(deriv_rows)}")
    print("[关键文件]")
    print(f"  - {base_dir / 'EXPERIMENT_REPORT.md'}")
    print(f"  - {base_dir / 'experiment_summary.csv'}")
    print(f"  - {base_dir / 'hypothesis_tests.json'}")
    print(f"  - {base_dir / 'viewer_metrics.json'}")
    print(f"  - {base_dir / 'sample_paths.geojson'}")
    print("==================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

