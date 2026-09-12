"""为前端裁剪工具返回的结构化结果。

为什么单独开这个文件：

工具返回的 `data` 里有完整的统计结果（每一级坡度多大面积、8 类地物各占多少比例、
路径里程与爬升…），但也可能混着大数组。直接整个塞进 HTTP 响应有两个问题：

1. 响应体可能几 MB —— 一个 128×128 的栅格 list 就是 1.6 万个数字；
2. 前端根本用不了栅格原始值，它要的是**已经算好的聚合结果**。

以前图省事，执行记录里只留了「工具名 / 成败 / 耗时」，这些统计值**从来没出过后端** ——
结果就是用户看到的 Agent 只能吐纯文字，没有任何表格和图表。这里的职责就是
把「前端渲染真正需要的那部分」挑出来，不多不少。

设计原则：
- **白名单**，不是黑名单：名单外的字段一律不带，避免将来某个工具塞进奇怪的大对象；
- **防御性裁剪**：白名单内的字段如果 unexpectedly 是个超长序列，也会被丢掉；
- **不改工具层**：工具该怎么返回还怎么返回，裁剪只发生在回传前端的路上。
"""

from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

# 绝大多数工具都有的通用字段
_COMMON: Tuple[str, ...] = (
    "summary",
    "bbox",
    "resolution",
    "cell_size_m",
    "dem_source",
    "cache_hit",
    "artifact",
    "warnings",
)

# 各工具独有、且前端要用到的字段
_EXTRA: Dict[str, Tuple[str, ...]] = {
    # 地形因子：坡度 / 坡向 / 曲率
    "compute_slope": ("metric", "label_cn", "statistics"),
    "compute_aspect": ("metric", "label_cn", "statistics"),
    "compute_curvature": ("metric", "label_cn", "statistics"),
    # 通行代价栅格
    "compute_cost_surface": ("directional", "statistics", "min_cost_dir_stats"),
    # 分区统计 —— 前端表格与柱状图的数据源
    "zonal_statistics": (
        "metric",
        "label_cn",
        "unit",
        "total_area_km2",
        "valid_cells",
        "total_cells",
        "valid_ratio",
        "overall",
        "classes",
    ),
    # 地貌分类 —— 前端饼图与图例色卡的数据源
    "classify_terrain_rules": ("distribution", "legend", "class_count"),
    "classify_geomorphons": ("distribution", "legend", "class_count", "method"),
    "classify_terrain_onnx": (
        "distribution",
        "legend",
        "class_count",
        "mean_confidence",
        "infer_ms",
        "cost_adjustment_stats",
    ),
    # 路径规划 —— 前端指标卡片的数据源
    "plan_route": (
        "reachable",
        "distance_m",
        "straight_line_m",
        "detour_ratio",
        "node_count",
        "explored_nodes",
        "ascent_m",
        "descent_m",
        "mean_slope_deg",
        "max_slope_deg",
        "start_elevation_m",
        "end_elevation_m",
        "start_point",
        "end_point",
    ),
    # DEM 数据准备
    "download_srtm": ("dem_path", "bounds", "shape", "source", "size_bytes", "resolution_m"),
    "get_dem_metadata": ("dem_path", "bounds", "shape", "crs", "nodata", "resolution_m", "source"),
}

# 单个序列字段允许的最大长度 —— 超过就判定为"栅格原始值"，丢掉
_MAX_SEQ = 512


def _is_plain(value: Any) -> bool:
    """标量或 None —— 可安全回传。"""
    return value is None or isinstance(value, (bool, int, float, str))


def _clean(value: Any, depth: int = 0) -> Any:
    """递归裁剪：丢掉任何体积异常的部分。

    返回 None 表示"这个字段不适合回传"，调用方据此决定是否丢弃该 key。
    """
    if _is_plain(value):
        return value
    if depth > 4:
        return None
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            cv = _clean(v, depth + 1)
            if cv is not None:
                out[str(k)] = cv
        return out or None
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_SEQ:
            return None
        items = [_clean(v, depth + 1) for v in value]
        return [v for v in items if v is not None] or None
    # numpy 标量之类：转字符串总比丢掉好
    return str(value)


def build_step_view(tool: str, data: Dict[str, Any] | None) -> Dict[str, Any]:
    """把一个工具的 `data` 裁剪成前端可以直接渲染的结构。

    Args:
        tool: 工具名，用于在 _EXTRA 里查独有字段
        data: 工具返回里的 data 字典

    Returns:
        裁剪后的字典；输入为空或全部被裁掉时返回空字典。
    """
    if not isinstance(data, dict):
        return {}

    wanted = set(_COMMON) | set(_EXTRA.get(tool, ()))
    view: Dict[str, Any] = {}
    for key in wanted:
        if key not in data:
            continue
        cleaned = _clean(data[key])
        if cleaned is not None:
            view[key] = cleaned

    view["tool"] = tool
    return view


def collect_artifacts(step_views: Sequence[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """从各步的视图里收集可加载的矢量产物（带 url 的才算）。

    以前这里按 `artifacts`（复数）取值，而工具返回的是 `artifact`（单数），
    并且要求 `url` 字段 —— 工具当时只返回本地 `path`。两个条件都对不上，
    于是这个数组**永远是空的**，前端一个图层都拿不到。
    """
    out: list[Dict[str, Any]] = []
    for view in step_views or []:
        art = view.get("artifact")
        if isinstance(art, dict) and art.get("url"):
            item = dict(art)
            item["tool"] = view.get("tool", "")
            item["label"] = view.get("label_cn") or item.get("name") or item["tool"]
            out.append(item)
    return out
