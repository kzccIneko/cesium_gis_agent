"""修复导出图结构，使其可被量化工具链处理。

导出的模型里有这么一段（PyTorch `x.view(x.size(0), -1)` 的标准产物）::

    Shape(dem_patch)[0:1]  ->  val_0        # 动态 batch
    Concat(val_0, val_33)  ->  val_34       # [batch, -1]
    Reshape(max_pool2d_3, val_34) -> view   # [batch, 4096]

动态 batch 叠上 `-1` 会让 ONNX 的 shape inference 推不出形状，
报错 `Inferred shape and existing shape differ in dimension 0: (4096) vs (8)`，
结果是 **量化直接失败** —— 而推理时 ORT 能容忍，所以这个缺陷一直没暴露，
直到要做量化才炸出来。

修法：把 Reshape 的目标形状换成静态常量 `[-1, flat_dim]`，
`flat_dim` 从 `fc.weight` 的第二维反推（8×4096 里的 4096），
不硬编码，模型改了也不会错。Shape / Concat 两个节点随之删除。

这是「模型优化」里常被跳过的一步：图不是导出来就能直接优化的，
导出产物里藏着不少只有量化/编译阶段才会暴露的问题。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

logger = logging.getLogger("geo_optimization")


def _find_flatten_reshape(model: onnx.ModelProto) -> Optional[Tuple[Any, Any, Any]]:
    """定位「喂给 Gemm 的那个 Reshape」及其配套 Shape/Concat 节点。"""
    gemm_inputs = set()
    for node in model.graph.node:
        if node.op_type == "Gemm":
            gemm_inputs.add(node.input[0])

    for reshape in model.graph.node:
        if reshape.op_type != "Reshape":
            continue
        if reshape.output[0] not in gemm_inputs or len(reshape.input) < 2:
            continue
        shape_name = reshape.input[1]
        producer = next(
            (n for n in model.graph.node if n.output and n.output[0] == shape_name),
            None,
        )
        return reshape, producer, shape_name
    return None


def _flat_dim_from_gemm(model: onnx.ModelProto) -> Optional[int]:
    """从 Gemm 的权重形状反推展平维度，避免硬编码 4096。"""
    for node in model.graph.node:
        if node.op_type != "Gemm":
            continue
        weight_name = node.input[1]
        for init in model.graph.initializer:
            if init.name == weight_name and len(init.dims) == 2:
                # fc.weight 是 [n_classes, flat_dim]
                return int(init.dims[1])
    return None


def fix_dynamic_flatten(
    src: str | Path, dst: str | Path, flat_dim: Optional[int] = None
) -> Dict[str, Any]:
    """把动态展平替换为静态 Reshape，产出可量化的模型。

    Args:
        src / dst: 模型路径
        flat_dim: 展平维度，None 时从 Gemm 权重自动推断
    """
    src, dst = Path(src), Path(dst)
    model = onnx.load(str(src))

    found = _find_flatten_reshape(model)
    if found is None:
        return {"changed": False, "reason": "未找到需要修复的 Reshape"}

    reshape, producer, shape_name = found
    dim = flat_dim or _flat_dim_from_gemm(model)
    if not dim:
        return {"changed": False, "reason": "无法推断展平维度"}

    const_name = "flatten_shape_static"
    shape_arr = np.array([-1, dim], dtype=np.int64)
    model.graph.initializer.append(numpy_helper.from_array(shape_arr, const_name))
    reshape.input[1] = const_name

    # 删掉只服务于旧展平逻辑的节点：Concat 本身，以及上游的 Shape。
    # 按节点对象收集而不是按名字，很多导出产物里节点 name 是空的。
    to_remove: List[Any] = []

    def _collect(node) -> None:
        for inp in node.input:
            up = next(
                (n for n in model.graph.node if n.output and n.output[0] == inp),
                None,
            )
            if up is not None and up not in to_remove:
                to_remove.append(up)
                _collect(up)

    if producer is not None:
        to_remove.append(producer)
        _collect(producer)

    removed_op_types: List[str] = []
    for node in to_remove:
        if node in model.graph.node:
            removed_op_types.append(node.op_type)
            model.graph.node.remove(node)

    # 清理随之失效的 initializer 与 value_info
    consumed = {i for n in model.graph.node for i in n.input}
    for init in list(model.graph.initializer):
        if init.name not in consumed and init.name != const_name:
            model.graph.initializer.remove(init)
    for vi in list(model.graph.value_info):
        if vi.name not in consumed and vi.name not in {n.output[0] for n in model.graph.node if n.output}:
            model.graph.value_info.remove(vi)

    # 重新做一次 shape inference，同时充当「修好了没有」的验收
    try:
        model = onnx.shape_inference.infer_shapes(model)
        shape_ok = True
        shape_error = None
    except Exception as exc:
        shape_ok = False
        shape_error = f"{type(exc).__name__}: {exc}"

    dst.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(dst))

    return {
        "changed": True,
        "flat_dim": dim,
        "removed_nodes": removed_op_types,
        "shape_inference_ok": shape_ok,
        "shape_error": shape_error,
        "src": str(src),
        "dst": str(dst),
    }


def verify_outputs_match(
    model_a: str | Path, model_b: str | Path, sample: np.ndarray, atol: float = 1e-5
) -> Dict[str, Any]:
    """用同一份输入跑两个模型，确认改图没有改变数值行为。

    改图优化最容易犯的错是「看起来成功了、输出悄悄变了」，
    所以这一步不能省。
    """
    from .session import build_session

    out = {}
    for tag, path in (("a", model_a), ("b", model_b)):
        sess = build_session(path)
        name = sess.get_inputs()[0].name
        out[tag] = sess.run(None, {name: sample})[0]

    a, b = out["a"], out["b"]
    if a.shape != b.shape:
        return {"match": False, "reason": f"输出形状不同 {a.shape} vs {b.shape}"}

    max_abs = float(np.abs(a - b).max())
    argmax_same = bool(np.array_equal(a.argmax(axis=1), b.argmax(axis=1)))
    return {
        "match": bool(max_abs <= atol),
        "max_abs_diff": max_abs,
        "argmax_identical": argmax_same,
        "atol": atol,
    }
