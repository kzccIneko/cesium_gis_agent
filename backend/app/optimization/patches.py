"""向量化 + 分块的滑窗 patch 提取。

替换掉原实现里的 Python 双层循环。原实现有两个硬伤：

1. **逐像元 Python 循环**
   每个像元做一次切片 + mean + std，256×256 就是 65536 次 Python 层迭代。
   这一步的开销和模型推理本身在同一量级，属于典型的「Python 循环掩盖了
   真正的计算」——不先干掉它，量化带来的收益会被循环开销吃掉大半。

2. **一次性分配 N²·64²·4 字节**
   256×256 的栅格要预先开出约 1 GB 的 float32 数组，然后才开始第一次推理。
   峰值内存与输入面积成平方关系，稍大的区域直接 OOM。

这里改用 `sliding_window_view` 取视图（零拷贝），再按行分块物化
——峰值内存从 O(N²) 降到 O(块高 × N)，且与输入尺寸无关。

另外提供 `stride`：64×64 的感受野意味着相邻像元的预测高度相关，
隔点采样再最近邻回填，在大幅降低计算量的同时精度损失很小。
损失到底有多小，交给 `validate.py` 实测，不靠拍脑袋。
"""

from __future__ import annotations

from typing import Iterator, Optional, Tuple

import numpy as np

# 实测：峰值内存约为该预算的 3 倍（numpy  fancy-index 物化 + 归一化临时数组），
# 取 64 使峰值落在 200 MB 左右——既能吃满 CPU 缓存行，又不会在笔记本上顶到内存上限。
DEFAULT_MAX_CHUNK_MB = float(64)


def estimate_chunk_rows(
    n_cols: int, patch_size: int, max_chunk_mb: float = DEFAULT_MAX_CHUNK_MB
) -> int:
    """在给定内存预算下，一次最多能物化多少行 patch。"""
    bytes_per_patch = patch_size * patch_size * 4  # float32
    budget_bytes = max(16.0, float(max_chunk_mb)) * 1024 * 1024
    rows = int(budget_bytes // max(1, n_cols * bytes_per_patch))
    return max(1, rows)


def iter_patch_batches(
    dem: np.ndarray,
    patch_size: int = 64,
    stride: int = 1,
    batch_size: int = 256,
    max_chunk_mb: float = DEFAULT_MAX_CHUNK_MB,
) -> Iterator[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """分批产出归一化后的 patch 及其在原栅格中的坐标。

    z-score 逐 patch 归一化（与原实现一致：减均值、除标准差，
    标准差为 0 时用 1e-8 兜底）。

    Args:
        dem: 二维高程数组
        patch_size: patch 边长，需与模型输入一致
        stride: 采样步长。1 = 每个像元都算；2 = 隔一个像元算一次
        batch_size: 每次推理的 patch 数
        max_chunk_mb: 单块 patch 的内存预算

    Yields:
        (batch, rows, cols)
        batch: (B, 1, patch_size, patch_size) float32，已归一化
        rows/cols: 长度 B 的 int32 数组，patch 中心在原栅格中的坐标
    """
    if dem.ndim != 2:
        raise ValueError(f"dem 必须是二维数组，收到 shape={dem.shape}")
    if patch_size < 1 or patch_size % 2 != 0:
        raise ValueError(f"patch_size 必须是正的偶数，收到 {patch_size}")
    stride = max(1, int(stride))
    batch_size = max(1, int(batch_size))

    dem32 = np.ascontiguousarray(dem, dtype=np.float32)
    rows_full, cols_full = dem32.shape
    if rows_full < patch_size or cols_full < patch_size:
        raise ValueError(
            f"DEM 太小（{rows_full}x{cols_full}），至少需要 {patch_size}x{patch_size}"
        )

    half = patch_size // 2
    padded = np.pad(dem32, half, mode="reflect")

    # (rows_full, cols_full, P, P) 的视图，不占额外内存
    windows = np.lib.stride_tricks.sliding_window_view(padded, (patch_size, patch_size))

    row_pos = np.arange(0, rows_full, stride)
    col_pos = np.arange(0, cols_full, stride)

    chunk_rows = estimate_chunk_rows(len(col_pos), patch_size, max_chunk_mb)

    for r_start in range(0, len(row_pos), chunk_rows):
        rr = row_pos[r_start : r_start + chunk_rows]
        # np.ix_ 一次完成二维索引并物化，比先取行再取列少一次拷贝
        block = windows[np.ix_(rr, col_pos)]
        arr = block.reshape(-1, 1, patch_size, patch_size)

        mu = arr.mean(axis=(2, 3), keepdims=True)
        sd = arr.std(axis=(2, 3), keepdims=True)
        np.maximum(sd, 1e-8, out=sd)
        arr -= mu
        arr /= sd

        grid_r = np.repeat(rr, len(col_pos)).astype(np.int32)
        grid_c = np.tile(col_pos, len(rr)).astype(np.int32)

        for b in range(0, arr.shape[0], batch_size):
            yield (
                arr[b : b + batch_size],
                grid_r[b : b + batch_size],
                grid_c[b : b + batch_size],
            )


def fill_from_samples(
    values: np.ndarray,
    shape: Tuple[int, int],
    stride: int = 1,
    row_pos: Optional[np.ndarray] = None,
    col_pos: Optional[np.ndarray] = None,
) -> np.ndarray:
    """把采样的预测结果回填成完整栅格。

    stride=1 时是精确回填；stride>1 时用最近邻扩展（先按行重复再按列重复，
    最后裁剪到目标尺寸）。
    """
    rows_full, cols_full = shape
    stride = max(1, int(stride))

    if row_pos is None:
        row_pos = np.arange(0, rows_full, stride)
    if col_pos is None:
        col_pos = np.arange(0, cols_full, stride)

    small = values.reshape(len(row_pos), len(col_pos))
    if stride == 1:
        return small.astype(np.float32)

    expanded = np.repeat(np.repeat(small, stride, axis=0), stride, axis=1)
    return expanded[:rows_full, :cols_full].astype(np.float32)
