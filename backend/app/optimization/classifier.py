"""优化后的 ONNX 地貌分类器。

与 `services.terrain_classifier.ONNXTerrainClassifier` 接口完全一致
（`classify()` 返回 `class_ids, cost_adjustment, confidence`），可以直接替换。
差异全在内部：

| 维度 | 原实现 | 本实现 |
|---|---|---|
| patch 提取 | Python 双层循环 | `sliding_window_view` 向量化 |
| 峰值内存 | O(N²·64²·4)，256² 约 1 GB | 分块，O(块高·N)，与面积无关 |
| 采样 | 每像元必算 | 可选 stride，隔点采样 + 最近邻回填 |
| 会话配置 | 默认 | 可调线程数 / 图优化级别 / provider |
| 模型 | fp32 | 可加载量化后的 int8 模型 |

量化与 stride 都是「有损优化」，代价必须由 `validate.py` 实测给出，
不能只报加速比 —— 这在地理场景里尤其重要，见 validate.py 的文档说明。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from ..services.terrain_classifier import TERRAIN_CLASSES
from .patches import DEFAULT_MAX_CHUNK_MB, fill_from_samples, iter_patch_batches
from .session import build_session, session_info

MODEL_DIR = (
    Path(__file__).resolve().parents[3] / "models" / "terrain_morphology"
)
DEFAULT_ONNX = MODEL_DIR / "terrain_morphology.onnx"
QUANTIZED_ONNX = MODEL_DIR / "terrain_morphology.quant.onnx"
PATCH_SIZE = 64
N_CLASSES = 8


@dataclass
class ClassifyStats:
    """一次分类的运行时统计，用于基准测试与问题定位。"""

    rows: int = 0
    cols: int = 0
    patches: int = 0
    batches: int = 0
    extract_ms: float = 0.0
    infer_ms: float = 0.0
    total_ms: float = 0.0
    model_mb: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "rows": self.rows,
            "cols": self.cols,
            "patches": self.patches,
            "batches": self.batches,
            "extract_ms": round(self.extract_ms, 2),
            "infer_ms": round(self.infer_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "model_mb": round(self.model_mb, 3),
            "throughput_patches_per_s": (
                round(self.patches / (self.total_ms / 1000.0), 1)
                if self.total_ms > 0
                else 0.0
            ),
        }
        d.update(self.extra)
        return d


class OptimizedONNXClassifier:
    """优化后的滑窗 ONNX 分类器。

    Args:
        model_path: .onnx 路径；None 时按 prefer_quantized 在默认模型与
            量化模型之间选择，量化模型不存在则回退到 fp32
        stride: 采样步长，1 为逐像元
        batch_size: 单批推理的 patch 数
        max_chunk_mb: patch 分块内存预算
        providers / threads / opt_level: 会话配置，见 session.build_session
        prefer_quantized: True 时优先加载量化模型
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        stride: int = 1,
        batch_size: int = 256,
        max_chunk_mb: float = DEFAULT_MAX_CHUNK_MB,
        providers: Optional[list] = None,
        threads: int = 0,
        opt_level: int = 99,
        prefer_quantized: bool = False,
    ):
        self.stride = max(1, int(stride))
        self.batch_size = int(batch_size)
        self.max_chunk_mb = float(max_chunk_mb)
        self.providers = providers
        self.threads = threads
        self.opt_level = opt_level
        self.model_path = self._resolve_model_path(model_path, prefer_quantized)
        self._session = None
        self._input_name: Optional[str] = None
        self.last_stats: Optional[ClassifyStats] = None

    @staticmethod
    def _resolve_model_path(
        model_path: Optional[str | Path], prefer_quantized: bool
    ) -> Path:
        if model_path is not None:
            return Path(model_path)
        if prefer_quantized and QUANTIZED_ONNX.is_file():
            return QUANTIZED_ONNX
        return DEFAULT_ONNX

    @property
    def is_quantized_model(self) -> bool:
        return self.model_path.name.endswith(".quant.onnx")

    def _load(self):
        if self._session is None:
            self._session = build_session(
                self.model_path,
                providers=self.providers,
                threads=self.threads,
                opt_level=self.opt_level,
            )
            self._input_name = self._session.get_inputs()[0].name

    def info(self) -> Dict[str, Any]:
        self._load()
        from .session import file_size_mb

        out = session_info(self._session)
        out["model_path"] = str(self.model_path)
        out["model_mb"] = round(file_size_mb(self.model_path), 3)
        out["quantized"] = self.is_quantized_model
        out["stride"] = self.stride
        out["batch_size"] = self.batch_size
        return out

    def classify(
        self,
        dem: np.ndarray,
        slope_deg: Optional[np.ndarray] = None,
        curvature: Optional[np.ndarray] = None,
        cell_size_m: float = 30.0,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """与 ONNXTerrainClassifier.classify 同签名，可 drop-in 替换。"""
        self._load()
        dem = np.asarray(dem)
        rows, cols = dem.shape
        if rows < PATCH_SIZE or cols < PATCH_SIZE:
            raise ValueError(
                f"DEM 太小（{rows}x{cols}），至少需要 {PATCH_SIZE}x{PATCH_SIZE}。"
                "小栅格请改用规则法或 Geomorphons 分类。"
            )

        stats = ClassifyStats(rows=rows, cols=cols)
        t0 = time.perf_counter()

        n_row = len(range(0, rows, self.stride))
        n_col = len(range(0, cols, self.stride))
        class_buf = np.empty(n_row * n_col, dtype=np.int64)
        conf_buf = np.empty(n_row * n_col, dtype=np.float32)

        infer_ms = 0.0
        n_batches = 0
        done = 0
        total_patches = n_row * n_col

        for batch, rr, cc in iter_patch_batches(
            dem,
            patch_size=PATCH_SIZE,
            stride=self.stride,
            batch_size=self.batch_size,
            max_chunk_mb=self.max_chunk_mb,
        ):
            t_inf = time.perf_counter()
            logits = self._session.run(None, {self._input_name: batch})[0]
            infer_ms += (time.perf_counter() - t_inf) * 1000.0
            n_batches += 1

            b = logits.shape[0]
            class_buf[done : done + b] = logits.argmax(axis=1)

            shifted = logits - logits.max(axis=1, keepdims=True)
            np.exp(shifted, out=shifted)
            shifted /= shifted.sum(axis=1, keepdims=True)
            conf_buf[done : done + b] = shifted.max(axis=1)

            done += b
            if progress_callback:
                progress_callback(done, total_patches)

        # stride=1 时坐标是规则网格，直接 reshape；否则按采样位置回填
        class_ids = fill_from_samples(
            class_buf.astype(np.int32), (rows, cols), stride=self.stride
        ).astype(np.int32)
        confidence = fill_from_samples(conf_buf, (rows, cols), stride=self.stride)

        cost_adjustment = np.ones((rows, cols), dtype=np.float64)
        for cid, meta in TERRAIN_CLASSES.items():
            cost_adjustment[class_ids == cid] = float(meta["cost_factor"])

        total_ms = (time.perf_counter() - t0) * 1000.0
        from .session import file_size_mb

        stats.patches = done
        stats.batches = n_batches
        stats.infer_ms = infer_ms
        stats.extract_ms = max(0.0, total_ms - infer_ms)
        stats.total_ms = total_ms
        stats.model_mb = file_size_mb(self.model_path)
        self.last_stats = stats

        return class_ids, cost_adjustment, confidence
