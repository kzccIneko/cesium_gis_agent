"""ONNX Runtime 会话构建与执行后端探测。

为什么单独抽一层：

1. **后端选择要可观测**。本机 `onnxruntime` 只装了 CPU / Azure provider，
   但用户机器上有独立显卡（台式机 RX 7700 XT、笔记本 RTX 2060）。
   这里把「有哪些 provider 可用、实际用了哪个、为什么」显式暴露出来，
   而不是静默退回 CPU 让人以为是模型慢。
2. **会话选项对吞吐影响很大**。默认的线程数与图优化级别未必适合
   「大量小 batch」这种推理形态，需要能调、能基准测试。
3. 量化模型与 fp32 模型的加载路径要一致，否则基准测试比的是会话配置差异，
   不是量化效果。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# 图优化级别（与 onnxruntime.GraphOptimizationLevel 对应，避免强依赖导入顺序）
ORT_DISABLE_ALL = 0
ORT_ENABLE_BASIC = 1
ORT_ENABLE_EXTENDED = 2
ORT_ENABLE_ALL = 99

_PROVIDER_PREFERENCE = (
    # (provider 名, 说明)
    ("CUDAExecutionProvider", "NVIDIA GPU，需 onnxruntime-gpu"),
    ("DmlExecutionProvider", "Windows 上任意 DX12 显卡（NVIDIA/AMD/Intel），需 onnxruntime-directml"),
    ("CoreMLExecutionProvider", "macOS"),
    ("CPUExecutionProvider", "通用 CPU 后端"),
)


def available_providers() -> List[str]:
    """当前 onnxruntime 实际支持的 provider 列表。"""
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except Exception:
        return ["CPUExecutionProvider"]


def provider_report() -> List[Dict[str, Any]]:
    """列出所有候选 provider 的可用性与启用方式，便于排查「为什么没用上 GPU」。"""
    avail = set(available_providers())
    out: List[Dict[str, Any]] = []
    for name, note in _PROVIDER_PREFERENCE:
        out.append(
            {
                "provider": name,
                "available": name in avail,
                "note": note,
            }
        )
    return out


def recommend_providers(prefer_gpu: Optional[bool] = None) -> List[str]:
    """按优先级给出 provider 列表。

    Args:
        prefer_gpu: True 优先 GPU；False 强制 CPU；None 读环境变量
            GEO_ONNX_PREFER_GPU（默认 "0"，即 CPU）。
            默认走 CPU 是刻意的：GPU provider 首次推理有编译开销，
            对小栅格反而更慢，且不是所有机器都有可用后端。
    """
    if prefer_gpu is None:
        prefer_gpu = os.getenv("GEO_ONNX_PREFER_GPU", "0").lower() in (
            "1",
            "true",
            "yes",
        )

    avail = set(available_providers())
    if not prefer_gpu:
        return ["CPUExecutionProvider"]

    ordered = [name for name, _ in _PROVIDER_PREFERENCE if name in avail]
    # CPU 兜底必须留在最后，否则 GPU 初始化失败会直接抛异常
    if "CPUExecutionProvider" not in ordered:
        ordered.append("CPUExecutionProvider")
    return ordered


def build_session(
    model_path: str | Path,
    providers: Optional[List[str]] = None,
    threads: int = 0,
    opt_level: int = ORT_ENABLE_ALL,
):
    """构建推理会话。

    Args:
        model_path: .onnx 路径
        providers: provider 列表，None 时按 recommend_providers() 决定
        threads: intra_op 线程数，0 表示交给 ORT 自行决定
        opt_level: 图优化级别
    """
    import onnxruntime as ort

    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel(opt_level)
    if threads and threads > 0:
        sess_options.intra_op_num_threads = int(threads)
    # 滑窗推理是一次会话、成千上万次 run，不需要每次都重新编译图
    sess_options.log_severity_level = 3  # 屏蔽 ORT 的 INFO 噪音

    return ort.InferenceSession(
        str(model_path),
        sess_options=sess_options,
        providers=providers or recommend_providers(),
    )


def session_info(session) -> Dict[str, Any]:
    """把会话的关键信息抽成可 JSON 序列化的 dict。"""
    inputs = [
        {"name": i.name, "shape": list(i.shape), "type": i.type}
        for i in session.get_inputs()
    ]
    outputs = [
        {"name": o.name, "shape": list(o.shape), "type": o.type}
        for o in session.get_outputs()
    ]
    try:
        used = [str(p) for p in session.get_providers()]
    except Exception:
        used = ["unknown"]
    return {"providers_in_use": used, "inputs": inputs, "outputs": outputs}


def file_size_mb(path: str | Path) -> float:
    p = Path(path)
    total = 0.0
    if p.is_file():
        total += p.stat().st_size
        # 大模型会把权重外置到同名 .data 文件，只统计 .onnx 会严重低估体积
        external = p.with_suffix(p.suffix + ".data")
        if external.is_file():
            total += external.stat().st_size
    return total / (1024 * 1024)
