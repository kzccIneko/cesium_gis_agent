"""ONNX 模型量化：动态量化 + 用真实地形数据校准的静态量化。

两种路线，取舍不同：

- **动态量化**：不需要数据，权重转 int8、激活值在推理时动态定标。
  几分钟就能出结果，但对卷积类模型的加速不如静态量化。
- **静态量化**：需要用代表性数据跑一遍来标定激活值的量化范围。
  这里用**真实 DEM 切出来的 patch** 做校准，而不是随机数 ——
  地形 patch 的数值分布高度集中（z-score 归一化后近似标准正态，
  且空间自相关很强），用随机张量标定会给出错误的激活范围，
  把量化误差放大到肉眼可见。这是「垂直场景量化」最实在的一条经验。

量化本身不保证可用。产出的模型必须过 `validate.compare_classifications`
的四道检查才允许上线。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger("geo_optimization")

PATCH_SIZE = 64


class DemPatchCalibrationReader:
    """从真实/合成 DEM 上切 patch 作为静态量化校准集。

    这是 CalibrationDataReader 的领域化实现：校准数据来自实际会喂给模型的
    数据分布，而不是随机噪声。
    """

    def __init__(
        self,
        dems: Sequence[np.ndarray],
        n_samples: int = 200,
        patch_size: int = PATCH_SIZE,
        seed: int = 0,
    ):
        if not dems:
            raise ValueError("至少需要提供一份 DEM 用于校准")
        self.n_samples = int(n_samples)
        self.patch_size = int(patch_size)
        self.rng = np.random.default_rng(seed)
        self._patches = self._build(dems)
        self._iter = None

    def _build(self, dems: Sequence[np.ndarray]) -> np.ndarray:
        out: List[np.ndarray] = []
        per_dem = max(1, self.n_samples // len(dems))
        for dem in dems:
            dem = np.asarray(dem, dtype=np.float32)
            rows, cols = dem.shape
            if rows < self.patch_size or cols < self.patch_size:
                continue
            for _ in range(per_dem):
                r = int(self.rng.integers(0, rows - self.patch_size + 1))
                c = int(self.rng.integers(0, cols - self.patch_size + 1))
                p = dem[r : r + self.patch_size, c : c + self.patch_size]
                sd = float(p.std()) or 1e-8
                out.append(((p - float(p.mean())) / sd).astype(np.float32))
        if not out:
            raise ValueError(
                "所有提供的 DEM 都小于 patch 尺寸，无法构造校准集"
            )
        return np.stack(out)[:, None, :, :]

    def get_next(self) -> Optional[Dict[str, np.ndarray]]:
        if self._iter is None:
            self._iter = iter(self._patches)
        try:
            batch = next(self._iter)
        except StopIteration:
            return None
        return {"dem_patch": batch[None, ...]}

    def rewind(self) -> None:
        self._iter = None


def size_report(src: Path, dst: Path) -> Dict[str, Any]:
    from .session import file_size_mb

    before = file_size_mb(src)
    after = file_size_mb(dst)
    return {
        "src": str(src),
        "dst": str(dst),
        "size_mb_before": round(before, 3),
        "size_mb_after": round(after, 3),
        "compression_ratio": round(before / after, 2) if after > 0 else None,
    }


def quantize_dynamic(
    src: str | Path,
    dst: str | Path,
    per_channel: bool = True,
    reduce_range: bool = False,
) -> Dict[str, Any]:
    """动态量化。无需校准数据。

    Args:
        src / dst: 模型路径
        per_channel: 逐通道量化权重，通常精度更好
        reduce_range: 老款 CPU（无 VNNI 指令）上建议开启以避免溢出
    """
    from onnxruntime.quantization import QuantType, quantize_dynamic

    src, dst = Path(src), Path(dst)
    if not src.is_file():
        raise FileNotFoundError(f"源模型不存在：{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    quantize_dynamic(
        model_input=str(src),
        model_output=str(dst),
        weight_type=QuantType.QInt8,
        per_channel=per_channel,
        reduce_range=reduce_range,
        extra_options={"EnableSubgraph": False},
    )

    report = size_report(src, dst)
    report["method"] = "dynamic"
    report["per_channel"] = per_channel
    logger.info(
        "动态量化完成：%.2fMB -> %.2fMB（%.2fx）",
        report["size_mb_before"],
        report["size_mb_after"],
        report["compression_ratio"] or 0,
    )
    return report


def quantize_static(
    src: str | Path,
    dst: str | Path,
    dems: Sequence[np.ndarray],
    n_samples: int = 200,
    seed: int = 0,
) -> Dict[str, Any]:
    """静态量化，用真实地形 patch 标定激活范围。

    Args:
        dems: 用于校准的 DEM 数组（真实 SRTM 最佳）
        n_samples: 校准 patch 数量
    """
    from onnxruntime.quantization import CalibrationMethod, QuantType, quantize_static

    src, dst = Path(src), Path(dst)
    if not src.is_file():
        raise FileNotFoundError(f"源模型不存在：{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    reader = DemPatchCalibrationReader(dems, n_samples=n_samples, seed=seed)

    quantize_static(
        model_input=str(src),
        model_output=str(dst),
        calibration_data_reader=reader,
        weight_type=QuantType.QInt8,
        activation_type=QuantType.QUInt8,
        # 必须显式给：传 None 会报 "Unsupported calibration method None"
        calibrate_method=CalibrationMethod.MinMax,
        extra_options={"EnableSubgraph": False},
    )

    report = size_report(src, dst)
    report["method"] = "static"
    report["calibration_patches"] = len(reader._patches)
    return report


def try_quantize_static(
    src: str | Path, dst: str | Path, dems: Sequence[np.ndarray], **kwargs
) -> Dict[str, Any]:
    """静态量化的容错包装。

    静态量化对模型形态更敏感（动态 batch 轴、不支持的算子都会失败），
    失败时不应中断整条优化流水线 —— 回退到动态量化即可。
    """
    try:
        return quantize_static(src, dst, dems, **kwargs)
    except Exception as exc:
        logger.warning("静态量化失败（将回退动态量化）：%s", exc)
        return {"method": "static", "failed": True, "error": f"{type(exc).__name__}: {exc}"}
