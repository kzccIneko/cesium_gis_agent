"""工具的 JSON Schema 定义（OpenAI Function Calling / MCP 格式）。

设计原则：
- description 是 LLM 选择工具的唯一依据，必须说清「什么时候用」而非仅「是什么」
- 显式声明默认值与取值范围，减少 LLM 瞎填参数
- 对易错参数（如 bbox 顺序、ONNX 分辨率上限）在 description 中写明约束
"""

from __future__ import annotations

from typing import Any, Dict

# ── 可复用参数片段 ──────────────────────────────────────────────────
BBOX_PARAM: Dict[str, Any] = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 4,
    "maxItems": 4,
    "description": (
        "分析范围的经纬度包围盒，顺序固定为 [west, south, east, north]，"
        "即 [西经, 南纬, 东经, 北纬]。必须满足 west < east 且 south < north。"
        "示例：分析成都周边用 [103.5, 30.2, 104.5, 31.0]"
    ),
}

RES_PARAM: Dict[str, Any] = {
    "type": "integer",
    "minimum": 16,
    "maximum": 2048,
    "default": 256,
    "description": (
        "栅格分辨率（边长像元数）。范围越大需要越高的分辨率，"
        "但计算量按平方增长。建议：小范围（数公里）用 128–256，"
        "中等范围用 256–512，大范围用 512–1024"
    ),
}

DEM_PARAM: Dict[str, Any] = {
    "type": "string",
    "description": (
        "本地 DEM 文件（GeoTIFF）路径。留空则使用程序生成的合成地形，"
        "合成地形仅用于流程验证，不能用于真实分析。"
        "可先调用 download_srtm 获取真实 DEM 再传入其返回的 dem_path"
    ),
}

FMT_PARAM: Dict[str, Any] = {
    "type": "string",
    "enum": ["geojson", "czml", "kml", "npz"],
    "default": "geojson",
    "description": (
        "结果导出格式。geojson 通用；czml 用于 Cesium 三维动态展示；"
        "kml 用于 Google Earth；npz 为 NumPy 原始数组（供程序后续处理）"
    ),
}

POINT_PARAM = lambda desc: {  # noqa: E731
    "type": "array",
    "items": {"type": "number"},
    "minItems": 2,
    "maxItems": 2,
    "description": desc,
}


def _tool(name: str, description: str, properties: Dict[str, Any],
          required: list) -> Dict[str, Any]:
    """构造 OpenAI tools 格式的函数定义。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# ── 工具定义表 ──────────────────────────────────────────────────────
TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "get_dem_metadata": _tool(
        "get_dem_metadata",
        "读取本地 DEM 文件的元信息（坐标系、尺寸、波段、nodata、是否需要解码）。"
        "当用户提供了 DEM 文件路径，或需要确认某个 DEM 能否直接用于分析时调用本工具。"
        "它不做任何计算，只做检查。",
        {
            "dem_path": {
                "type": "string",
                "description": "DEM 文件（GeoTIFF）路径",
            }
        },
        ["dem_path"],
    ),
    "download_srtm": _tool(
        "download_srtm",
        "按经纬度范围下载真实 DEM 数据（Copernicus GLO-30，30 米分辨率）并缓存到本地。"
        "⚠ 默认不要调用：坡度、坡向、曲率、代价、分类等分析工具本身就能接受 bbox 直接计算，"
        "只有在用户明确要求「用真实 DEM / 真实高程数据」「下载 SRTM」或已提供 dem_path 时才调用本工具，"
        "之后把返回的 dem_path 传给分析工具。"
        "首次调用需联网（10–30 秒），相同范围后续直接命中缓存。",
        {"bbox": BBOX_PARAM},
        ["bbox"],
    ),
    "compute_slope": _tool(
        "compute_slope",
        "计算指定范围的坡度栅格（单位：度，0° 为水平面，90° 为垂直）。"
        "坡度是通行性评估、路径规划和地貌分类最基础的地形因子。"
        "当用户询问「哪里陡」「坡度多少」「能不能走」时使用。",
        {
            "bbox": BBOX_PARAM,
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "output_format": FMT_PARAM,
        },
        ["bbox"],
    ),
    "compute_aspect": _tool(
        "compute_aspect",
        "计算坡向栅格（单位：度，0° 为正北，顺时针增大，90° 为东）。"
        "用于判断阴坡/阳坡、日照条件、冰雪消融与植被分布。"
        "当用户询问「朝向哪边」「阴坡阳坡」时使用。",
        {
            "bbox": BBOX_PARAM,
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "output_format": FMT_PARAM,
        },
        ["bbox"],
    ),
    "compute_curvature": _tool(
        "compute_curvature",
        "计算曲率栅格（单位：1/m，正值表示凸起如山脊，负值表示凹陷如沟谷）。"
        "用于区分山脊与沟谷、判断汇流与水土流失。"
        "当用户询问「哪里是山脊」「哪里是沟谷」时可配合本工具。",
        {
            "bbox": BBOX_PARAM,
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "output_format": FMT_PARAM,
        },
        ["bbox"],
    ),
    "compute_cost_surface": _tool(
        "compute_cost_surface",
        "构建通行代价栅格：综合坡度、曲率、山脊谷地、等高线密度等因子，"
        "给出每个位置通行的相对难易程度。"
        "如果同时传入 start_point 和 end_point，会生成方向性代价场，"
        "使后续路径倾向沿等高线绕行而非直上直下。"
        "当用户询问「哪里好走」「通行难度」时使用。",
        {
            "bbox": BBOX_PARAM,
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "start_point": POINT_PARAM("起点 [经度, 纬度]。与 end_point 同时传入才启用方向性代价"),
            "end_point": POINT_PARAM("终点 [经度, 纬度]。与 start_point 同时传入才启用方向性代价"),
            "output_format": FMT_PARAM,
        },
        ["bbox"],
    ),
    "plan_route": _tool(
        "plan_route",
        "在通行代价栅格上规划两点之间的越野路径（Dijkstra 8 邻域最短路 + 方向性代价场）。"
        "返回路径长度、累计爬升/下降、绕行系数、最大坡度与可达性。"
        "当用户要求「规划路线」「找一条从 A 到 B 的路」时使用。"
        "注意：起终点必须落在 bbox 范围内。",
        {
            "bbox": BBOX_PARAM,
            "start_point": POINT_PARAM("起点 [经度, 纬度]，必须在 bbox 范围内"),
            "end_point": POINT_PARAM("终点 [经度, 纬度]，必须在 bbox 范围内"),
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "output_format": {
                "type": "string",
                "enum": ["geojson", "czml", "kml", "json"],
                "default": "geojson",
                "description": "路径导出格式",
            },
        },
        ["bbox", "start_point", "end_point"],
    ),
    "classify_terrain_rules": _tool(
        "classify_terrain_rules",
        "用地形形态规则对区域做 8 类地貌分类（基于坡度、曲率、TPI 的判据）。"
        "8 类为：平地、山顶、山脊、陡坡、缓坡、山谷、洼地、陡崖。"
        "速度最快。**区域跨度 > 0.5°（约 50 km）的大范围筛查必须用这个**；"
        "更小的范围用 classify_geomorphons。",
        {
            "bbox": BBOX_PARAM,
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "output_format": FMT_PARAM,
        },
        ["bbox"],
    ),
    "classify_geomorphons": _tool(
        "classify_geomorphons",
        "用 Geomorphons 算法（Jasiewicz & Stepinski 2013）对区域做 8 类地貌分类。"
        "该方法通过八方向视线分析判别局部地形形态，是地形形态学的经典算法，"
        "精度与速度均衡。适合区域跨度 ≤ 0.5°（约 50 km）的常规范围；"
        "更大范围请用 classify_terrain_rules。",
        {
            "bbox": BBOX_PARAM,
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "output_format": FMT_PARAM,
        },
        ["bbox"],
    ),
    "classify_terrain_onnx": _tool(
        "classify_terrain_onnx",
        "用 ONNX CNN 模型对区域做 8 类地貌分类（以 CNN 蒸馏 Geomorphons 判定）。"
        "⚠ 性能约束：该实现为逐像元滑窗推理，resolution 上限为 128；"
        "128×128 约需 25 秒。更大范围请改用 classify_geomorphons（256×256 约 3.3 秒）。"
        "工具会在超限时返回错误并提示替代方案。",
        {
            "bbox": BBOX_PARAM,
            "resolution": {
                "type": "integer",
                "minimum": 64,
                "maximum": 128,
                "default": 128,
                "description": "栅格分辨率。受滑窗推理限制，上限为 128。超过将返回错误",
            },
            "dem_path": DEM_PARAM,
            "output_format": FMT_PARAM,
        },
        ["bbox"],
    ),
    "zonal_statistics": _tool(
        "zonal_statistics",
        "对地形指标做分级统计并给出业务结论。最适合回答「有多少面积可以通行」"
        "这类比例问题。对坡度指标会额外给出车辆可通行面积占比"
        "（以坡度 ≤ 15° 为判据）。",
        {
            "bbox": BBOX_PARAM,
            "metric": {
                "type": "string",
                "enum": ["slope", "aspect", "curvature", "cost", "elevation"],
                "default": "slope",
                "description": "要统计的指标。slope=坡度(度)，aspect=坡向(度)，"
                              "curvature=曲率(1/m)，cost=通行代价，elevation=高程(m)",
            },
            "resolution": RES_PARAM,
            "dem_path": DEM_PARAM,
            "breaks": {
                "type": "array",
                "items": {"type": "number"},
                "description": "分级断点（升序）。不传则按指标取默认值："
                               "坡度为 [0,5,10,15,25,90]，高程按分位数，"
                               "其余指标按等间距取 5 档。断点必须覆盖指标的"
                               "全部取值范围，否则区间外的像元不计入任何一档。",
            },
        },
        ["bbox"],
    ),
    "query_tabular": _tool(
        "query_tabular",
        "对**结构化数据表**做条件查询与统计（自然语言转 SQL）。"
        "当问题是在「一批记录」里做筛选 / 计数 / 分组统计时用它 —— "
        "例如「哪些地名在四川」「多工具类的题目有多少条」「海拔超过 3000 米的点位有哪些」。"
        "注意与空间计算工具的分工：本工具查的是**属性表**（一行一条记录：点位、台账、清单）；"
        "如果要算坡度 / 坡向 / 路径 / 地貌，或要统计某片**区域**的地形分布，"
        "那是 compute_* 和 zonal_statistics 的活，不要用本工具。",
        {
            "question": {
                "type": "string",
                "description": "用户的自然语言问题，会由模型翻译成 SQL 后执行。"
                               "示例：「哪些地名在四川」「单工具类的题目有多少条」",
            },
            "table": {
                "type": "string",
                "description": "指定要查的表名（如 gazetteer / eval_cases）。"
                               "不确定时不传，由模型根据可用表清单自行判断。",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "default": 50,
                "description": "返回行数上限，默认 50。问「有多少条」这类计数问题时无所谓；"
                               "问「有哪些」时若结果很多可适当调高。",
            },
            "sql": {
                "type": "string",
                "description": "直接给一条 SELECT 语句跳过自然语言翻译。"
                               "仅在用户明确要求按某个条件精确筛选、或人工调试时使用；"
                               "普通情况下不要填这个字段。只允许 SELECT，"
                               "且只能引用已登记的表。",
            },
        },
        ["question"],
    ),
}
