"""GeoAgent 模型优化层 —— 面向地理信息处理场景的推理优化与量化。

背景：本项目的 ONNX 地貌分类模型（8 类、3.9 MB、输入 [batch,1,64,64]）
在滑窗推理下，256×256 的栅格需要 65536 次 patch 推理。原实现的瓶颈
不在模型本身，而在 patch 提取的 Python 循环与 O(N²) 的内存分配。

本层的优化按「先算法后算子」的顺序做 —— 先把无谓的计算和内存开销干掉，
再谈量化。顺序反了会得到漂亮的量化加速比和几乎没变的总耗时。

模块：
    session.py     会话构建与执行后端探测（为什么没用上 GPU 要能查出来）
    patches.py     向量化 + 分块的 patch 提取，峰值内存与面积解耦
    classifier.py  OptimizedONNXClassifier，可 drop-in 替换原分类器
    quantize.py    动态量化 + 用真实地形 patch 校准的静态量化
    validate.py    领域一致性验证（整体一致率 / 稀有类 IoU /
                   边界密度 / cost surface 偏差，四道门槛）
    benchmark.py   延迟、吞吐、内存峰值基准

典型流程见 `backend/scripts/optimize_terrain_onnx.py`：
    benchmark → quantize → validate → 给出是否可上线的判定
"""

from __future__ import annotations

from .classifier import (
    DEFAULT_ONNX,
    N_CLASSES,
    PATCH_SIZE,
    QUANTIZED_ONNX,
    ClassifyStats,
    OptimizedONNXClassifier,
)
from .patches import fill_from_samples, iter_patch_batches
from .session import available_providers, build_session, provider_report

__all__ = [
    "OptimizedONNXClassifier",
    "ClassifyStats",
    "iter_patch_batches",
    "fill_from_samples",
    "build_session",
    "available_providers",
    "provider_report",
    "DEFAULT_ONNX",
    "QUANTIZED_ONNX",
    "PATCH_SIZE",
    "N_CLASSES",
]
