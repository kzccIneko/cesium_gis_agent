"""Agent 工具统一错误体系。

设计要点：
- 所有工具返回 ToolResult，绝不抛异常给调用方（Agent 需要能解析并自我修正）
- error_type 使用受控枚举，供 Week 2 的 reflector 节点做「重试 / 放弃 / 换参数」决策
- to_dict() 保证 100% 可 JSON 序列化
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class ToolErrorType:
    """受控错误类型枚举 —— reflector 依据此字段决策。"""

    # 参数类错误：reflector 应调整参数后重试
    INVALID_BBOX = "invalid_bbox"
    INVALID_RESOLUTION = "invalid_resolution"
    INVALID_POINT = "invalid_point"
    UNSUPPORTED_FORMAT = "unsupported_format"
    UNKNOWN_METRIC = "unknown_metric"

    # 数据类错误：reflector 应换数据源或提示用户
    DEM_NOT_FOUND = "dem_not_found"
    DEM_LOAD_FAILED = "dem_load_failed"
    ALL_NODATA = "all_nodata"

    # 能力类错误：reflector 应直接放弃并回复用户
    MODEL_NOT_FOUND = "model_not_found"
    PATH_UNREACHABLE = "path_unreachable"
    OUT_OF_CAPABILITY = "out_of_capability"

    # 兜底
    COMPUTATION_FAILED = "computation_failed"

    # 哪些错误类型值得让 Agent 重试（参数调整可能解决）
    RETRYABLE = {
        INVALID_BBOX,
        INVALID_RESOLUTION,
        INVALID_POINT,
        UNSUPPORTED_FORMAT,
        UNKNOWN_METRIC,
        DEM_LOAD_FAILED,
        ALL_NODATA,
    }

    # 哪些错误应该直接放弃重试（重试无用）
    FATAL = {
        DEM_NOT_FOUND,
        MODEL_NOT_FOUND,
        PATH_UNREACHABLE,
        OUT_OF_CAPABILITY,
    }


@dataclass
class ToolResult:
    """统一的工具返回结构。

    data 约定（成功时）：
        - 必须包含 "summary"：一句话人类可读摘要
        - 数值指标带单位与范围
        - 大数组不内联，改为 artifact 路径 / URL
        - 可选 "warnings"：list[str]，提示数据质量或范围异常
    """

    tool: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "tool": self.tool,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.success:
            out["data"] = self.data or {}
        else:
            out["error"] = self.error
            out["error_type"] = self.error_type
            # 附带重试建议，供 reflector 直接使用
            out["retryable"] = (
                self.error_type in ToolErrorType.RETRYABLE
                if self.error_type
                else False
            )
        return out

    @property
    def retryable(self) -> bool:
        return bool(self.error_type and self.error_type in ToolErrorType.RETRYABLE)

    @property
    def warnings(self) -> list:
        if not self.success or not self.data:
            return []
        return list(self.data.get("warnings", []))


class ToolException(Exception):
    """工具内部异常，由工具实现抛出并在边界转为 ToolResult。"""

    def __init__(self, message: str, error_type: str = ToolErrorType.COMPUTATION_FAILED):
        super().__init__(message)
        self.message = message
        self.error_type = error_type


def ok(tool: str, data: Dict[str, Any], duration_ms: float = 0.0) -> ToolResult:
    return ToolResult(tool=tool, success=True, data=data, duration_ms=duration_ms)


def fail(tool: str, message: str, error_type: str, duration_ms: float = 0.0) -> ToolResult:
    return ToolResult(
        tool=tool,
        success=False,
        error=message,
        error_type=error_type,
        duration_ms=duration_ms,
    )
