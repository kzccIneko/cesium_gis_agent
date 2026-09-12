from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional, Tuple
import numpy as np


# ── Geomorphons classifier (Phase A, Jasiewicz & Stepinski 2013) ────

# Map: Geomorphons form_id -> our class_id
# 1=Flat, 2=Peak, 3=Ridge, 4=Shoulder, 5=Spur, 6=Slope,
# 7=Hollow, 8=Footslope, 9=Valley, 10=Pit
GEOMORPHON_TO_CLASS: Dict[int, int] = {
    1: 0,   # Flat     -> flat
    2: 1,   # Peak     -> peak
    3: 2,   # Ridge    -> ridge
    4: 4,   # Shoulder -> gentle_slope
    5: 2,   # Spur     -> ridge
    7: 5,   # Hollow   -> valley
    8: 4,   # Footslope -> gentle_slope
    9: 5,   # Valley   -> valley
    10: 6,  # Pit      -> depression
}
# Class 6 (Slope) is split by slope_deg threshold


class GeomorphonsClassifier:
    """Terrain morphology classifier using the Geomorphons algorithm.

    Wraps WhiteboxTools ``geomorphons`` function. Saves the DEM grid to a
    temporary GeoTIFF, runs the analysis, maps the 10-form output to our 8
    terrain classes, and applies slope-based steep_slope/gentle_slope split
    plus cliff detection.
    """

    SLOPE_STEEP: float = 25.0   # >= this → 3 (steep_slope)
    SLOPE_CLIFF: float = 45.0   # >= this → 7 (cliff)

    def __init__(self, search: int = 0, threshold: float = 0.0):
        self.search = search
        self.threshold = threshold
        self._wbt = None

    def _get_wbt(self):
        if self._wbt is None:
            from whitebox import WhiteboxTools
            self._wbt = WhiteboxTools()
            self._wbt.set_verbose_mode(False)
        return self._wbt

    def classify(
        self,
        dem: np.ndarray,
        slope_deg: Optional[np.ndarray] = None,
        curvature: Optional[np.ndarray] = None,
        cell_size_m: float = 30.0,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        rows, cols = dem.shape
        if rows < 5 or cols < 5:
            return classify_terrain(dem, slope_deg or np.zeros_like(dem),
                                    curvature or np.zeros_like(dem), cell_size_m)

        # Determine search radius if not set: aim for ~500m real-world distance
        search = self.search or max(5, int(round(500.0 / max(1.0, cell_size_m))))

        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dem_tif = str(tmp / "dem.tif")
            out_tif = str(tmp / "geomorphons.tif")

            # Write DEM as GeoTIFF (no real geo-ref needed)
            self._write_geotiff(dem, dem_tif)

            # Run geomorphons
            wbt = self._get_wbt()
            wbt.geomorphons(
                dem=dem_tif,
                output=out_tif,
                search=search,
                threshold=self.threshold,
                forms=True,
            )

            # Read result
            result = self._read_geotiff(out_tif)

        # Map classes
        class_ids = np.full((rows, cols), 0, dtype=np.int32)
        confidence = np.ones((rows, cols), dtype=np.float64)

        for gid, cid in GEOMORPHON_TO_CLASS.items():
            mask = result == gid
            class_ids[mask] = cid

        # Class 6 (Slope) → split by slope_deg
        slope_mask = result == 6
        if slope_deg is not None:
            steep = slope_mask & (slope_deg >= self.SLOPE_STEEP)
            gentle = slope_mask & (slope_deg < self.SLOPE_STEEP)
        else:
            steep = np.zeros_like(slope_mask, dtype=bool)
            gentle = slope_mask
        class_ids[steep] = 3   # steep_slope
        class_ids[gentle] = 4  # gentle_slope

        # Cliff override
        if slope_deg is not None:
            class_ids[slope_deg >= self.SLOPE_CLIFF] = 7

        # Unclassified cells (e.g. NoData) → flat
        class_ids[result < 1] = 0

        # Cost adjustment
        cost_adjustment = np.ones((rows, cols), dtype=np.float64)
        for cid, meta in TERRAIN_CLASSES.items():
            cost_adjustment[class_ids == cid] = float(meta["cost_factor"])

        return class_ids, cost_adjustment, confidence

    @staticmethod
    def _write_geotiff(arr: np.ndarray, path: str):
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import from_origin
        with rasterio.open(
            path, "w", driver="GTiff",
            height=arr.shape[0], width=arr.shape[1],
            count=1, dtype=arr.dtype,
            crs=CRS.from_epsg(3857),  # projected CRS required by WhiteboxTools
            transform=from_origin(0, arr.shape[0], 1.0, 1.0),
        ) as dst:
            dst.write(arr, 1)

    @staticmethod
    def _read_geotiff(path: str) -> np.ndarray:
        import rasterio
        with rasterio.open(path) as src:
            return src.read(1).astype(np.int32)


# ── ONNX terrain morphology classifier ──────────────────────────────

MODEL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "models" / "terrain_morphology"
ONNX_PATH = MODEL_DIR / "terrain_morphology.onnx"
PATCH_SIZE = 64


class ONNXTerrainClassifier:
    """Sliding-window ONNX inference wrapper for the 8-class terrain morphology model.

    Loads model lazily on first call. Runs 64×64 patches via ONNX Runtime,
    z-score normalizes each patch, classifies center pixel, stitches results.
    """

    def __init__(self, model_path: str | Path = ONNX_PATH):
        self._model_path = Path(model_path)
        self._session: object = None  # onnxruntime.InferenceSession

    def _load(self):
        import onnxruntime as ort
        self._session = ort.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name

    def classify(self, dem: np.ndarray, slope_deg: Optional[np.ndarray] = None,
                 curvature: Optional[np.ndarray] = None,
                 cell_size_m: float = 30.0,
                 progress_callback = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Classify a DEM grid using sliding-window ONNX inference.

        Returns same signature as `classify_terrain()` for drop-in replacement:
            class_ids, cost_adjustment, confidence
        """
        if self._session is None:
            self._load()
        rows, cols = dem.shape
        if rows < PATCH_SIZE or cols < PATCH_SIZE:
            msg = f"DEM too small ({rows}x{cols}), need at least {PATCH_SIZE}x{PATCH_SIZE}"
            return self._fallback(dem, rows, cols, msg)

        half = PATCH_SIZE // 2
        padded = np.pad(dem, half, mode="reflect")

        flat_patches = np.zeros((rows * cols, 1, PATCH_SIZE, PATCH_SIZE), dtype=np.float32)
        idx = 0
        for r in range(rows):
            pr = r  # offset in padded
            for c in range(cols):
                pc = c
                patch = padded[pr:pr + PATCH_SIZE, pc:pc + PATCH_SIZE]
                mu = float(patch.mean())
                sd = float(patch.std()) or 1e-8
                flat_patches[idx, 0] = (patch - mu) / sd
                idx += 1

        total_patches = idx
        batch_size = 256
        logits_list = []
        for start in range(0, idx, batch_size):
            end = min(start + batch_size, idx)
            batch = flat_patches[start:end]
            logits_batch = self._session.run(None, {self._input_name: batch})[0]
            logits_list.append(logits_batch)
            if progress_callback:
                progress_callback(min(end, total_patches), total_patches)
        logits = np.concatenate(logits_list, axis=0)
        class_ids = logits.argmax(axis=1).astype(np.int32).reshape(rows, cols)

        # softmax for confidence
        logits_max = logits.max(axis=1, keepdims=True)
        exp_logits = np.exp(logits - logits_max)
        probs = exp_logits / exp_logits.sum(axis=1, keepdims=True)
        confidence = probs.max(axis=1).reshape(rows, cols)

        cost_adjustment = np.ones((rows, cols), dtype=np.float64)
        for cid, meta in TERRAIN_CLASSES.items():
            mask = class_ids == cid
            cost_adjustment[mask] = float(meta["cost_factor"])

        return class_ids, cost_adjustment, confidence

    def _fallback(self, dem, rows, cols, msg: str):
        import warnings
        warnings.warn(f"ONNX fallback (DEM too small): {msg}")
        return classify_terrain(dem, np.zeros_like(dem), np.zeros_like(dem))


# 8 类纯局部形态分类（无斜坡相对位置概念）
# 完全基于每个栅格单元的局部 morphometric 特征：
# 坡度、曲率、TPI（地形位置指数），无需流向或坡位上下文。
TERRAIN_CLASSES: Dict[int, Dict[str, object]] = {
    0: {"name": "flat",        "label_cn": "平地",    "color": "#38a800", "cost_factor": 0.5},
    1: {"name": "peak",        "label_cn": "山顶",    "color": "#ff0000", "cost_factor": 2.5},
    2: {"name": "ridge",       "label_cn": "山脊",    "color": "#ff8000", "cost_factor": 2.0},
    3: {"name": "steep_slope", "label_cn": "陡坡",    "color": "#ff00ff", "cost_factor": 3.0},
    4: {"name": "gentle_slope","label_cn": "缓坡",    "color": "#ffff00", "cost_factor": 1.2},
    5: {"name": "valley",      "label_cn": "山谷",    "color": "#00a6ff", "cost_factor": 1.8},
    6: {"name": "depression",  "label_cn": "洼地",    "color": "#0040ff", "cost_factor": 2.2},
    7: {"name": "cliff",       "label_cn": "陡崖",    "color": "#8b0000", "cost_factor": 4.0},
}

# 颜色去重用：flat vs valley 之前都是 #38a800，改为 flat #38a800, valley #00a6ff


def _tpi(dem: np.ndarray, window: int = 3) -> np.ndarray:
    """Topographic Position Index: 中心高程 - 邻域平均高程。向量化 O(window²)。"""
    half = window // 2
    padded = np.pad(dem, half, mode="reflect")
    rows, cols = dem.shape
    mean = np.zeros_like(dem, dtype=np.float64)
    for i in range(window):
        for j in range(window):
            mean += padded[i:i + rows, j:j + cols]
    mean /= float(window * window)
    return dem - mean


def classify_terrain(
    dem: np.ndarray,
    slope_deg: np.ndarray,
    curvature: np.ndarray,
    cell_size_m: float = 30.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """纯局部形态地貌分类（无斜坡相对位置概念）。

    分类规则完全基于每个单元的局部特征：
    - slope_deg: 坡度（度）
    - curvature: 曲率（正值=凸，负值=凹）
    - TPI: 地形位置指数（正值=凸起，负值=凹陷）

    返回:
        class_ids: 整数分类 ID 栅格 (rows, cols)
        cost_adjustment: 分类对应的代价调整系数栅格
        confidence: 分类置信度（0~1）
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

    std_s = float(np.std(tpi_small[np.isfinite(tpi_small)])) or 1.0
    std_l = float(np.std(tpi_large[np.isfinite(tpi_large)])) or 1.0
    tpi_small_n = tpi_small / std_s
    tpi_large_n = tpi_large / std_l

    class_ids = np.zeros((rows, cols), dtype=np.int32)
    confidence = np.zeros((rows, cols), dtype=np.float64)

    for r in range(rows):
        for c in range(cols):
            sl = float(slope_deg[r, c])
            curv = float(curvature[r, c])
            ts = float(tpi_small_n[r, c])
            tl = float(tpi_large_n[r, c])

            tpi_mag = abs(ts) * 0.5 + abs(tl) * 0.5
            conf = min(1.0, tpi_mag * 0.15 + abs(curv) * 0.02)
            confidence[r, c] = min(1.0, conf)

            if sl >= 45.0:
                cid = 7  # cliff
            elif sl >= 25.0:
                cid = 3  # steep_slope
            elif sl < 3.0 and abs(ts) < 0.6:
                cid = 0  # flat
            elif ts > 1.2 and tl > 0.5:
                cid = 1  # peak
            elif ts < -1.2 and tl < -0.5:
                cid = 6  # depression
            elif tl > 0.4 and curv > 0.0:
                cid = 2  # ridge
            elif tl < -0.4 and curv < 0.0:
                cid = 5  # valley
            elif sl >= 8.0:
                cid = 3  # steep_slope (medium steep)
            elif sl >= 3.0:
                cid = 4  # gentle_slope
            else:
                cid = 0  # flat fallback

            class_ids[r, c] = cid

    cost_adjustment = np.zeros((rows, cols), dtype=np.float64)
    for cid, meta in TERRAIN_CLASSES.items():
        cf = float(meta["cost_factor"])
        mask = class_ids == cid
        cost_adjustment[mask] = cf

    return class_ids, cost_adjustment, confidence


def get_terrain_class_legend() -> List[Dict[str, object]]:
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
