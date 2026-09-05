"""领域级结果校验规则 —— reflector 的「确定性」部分。

为什么规则要独立于 LLM：

大模型擅长语义判断，不擅长数值边界检查。让它判断"坡度 92.3° 是否正常"
既慢又不可靠，而这是纯算术。因此把**可判定的部分全部下沉到代码**，
LLM 只负责代码判不了的部分（结果是否真的回答了问题、量级是否符合地理常识）。

6 类规则（与项目计划一致）：

    1. path_length_sanity     路径长度合理性
    2. slope_range            坡度取值范围 [0, 90]
    3. classification_nonempty 分类结果非空且非单一类别
    4. endpoints_in_bbox      起终点落在 bbox 内
    5. crs_consistency        地理参考一致性（bbox 对齐 + 像元尺寸合理）
    6. tile_alignment         栅格瓦片对齐（shape 与 resolution 匹配）

另加 2 条数据质量规则：
    7. valid_data_ratio       有效数据占比
    8. dem_source_authenticity DEM 数据源真实性（合成数据不得用于真实结论）

第 8 条是本项目特有的诚实性约束：系统在没有真实 DEM 时会退化为合成地形，
若不校验，Agent 会拿合成地形给出看似专业的真实地理结论 —— 这是最危险的失败模式。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 规则级别
LEVEL_ERROR = "error"    # 必须重试
LEVEL_WARN = "warn"      # 可用，但要在回答中提示用户
LEVEL_INFO = "info"      # 仅记录

# 判定阈值（集中定义，便于调参与在文档中引用）
MAX_DETOUR_RATIO_ERROR = 20.0    # 绕行系数超过此值判定异常
MAX_DETOUR_RATIO_WARN = 5.0      # 超过此值提示用户
MIN_PATH_NODES = 2
SLOPE_MAX_DEG = 90.0
SLOPE_MIN_DEG = 0.0
MIN_VALID_RATIO = 0.5            # 有效像元占比下限
MIN_DISTINCT_CLASSES = 2         # 分类至少要有 2 个类别
MAX_DOMINANT_RATIO = 0.995       # 单一类别占比上限
MIN_CELL_SIZE_M = 0.5            # 像元尺寸合理下限（米）
MAX_CELL_SIZE_M = 20_000.0       # 像元尺寸合理上限（米）

# 分类类工具
CLASSIFY_TOOLS = {
    "classify_terrain_rules",
    "classify_geomorphons",
    "classify_terrain_onnx",
}
# 会返回 statistics.shape 的栅格类工具
RASTER_METRIC_TOOLS = {
    "compute_slope",
    "compute_aspect",
    "compute_curvature",
    "compute_cost_surface",
}


@dataclass
class RuleResult:
    """单条规则的判定结果。"""

    rule: str
    passed: bool
    level: str                       # error / warn / info
    message: str
    suggestion: Optional[Dict[str, Any]] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "level": self.level,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class RuleReport:
    """一次校验的完整报告。"""

    results: List[RuleResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed or r.level != LEVEL_ERROR for r in self.results)

    @property
    def errors(self) -> List[RuleResult]:
        return [r for r in self.results if not r.passed and r.level == LEVEL_ERROR]

    @property
    def warnings(self) -> List[RuleResult]:
        return [r for r in self.results if not r.passed and r.level == LEVEL_WARN]

    def add(self, result: Optional[RuleResult]) -> None:
        if result is not None:
            self.results.append(result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": [r.to_dict() for r in self.errors],
            "warnings": [r.to_dict() for r in self.warnings],
            "all": [r.to_dict() for r in self.results],
        }

    def format_for_prompt(self) -> str:
        """渲染成给 LLM 看的文本报告。"""
        if not self.results:
            return "（本次调用没有适用的确定性规则）"
        lines = []
        for r in self.results:
            flag = "PASS" if r.passed else r.level.upper()
            lines.append(f"- [{flag}] {r.rule}: {r.message}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def _get(d: Any, *keys: str, default=None):
    """安全取嵌套字段。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _bbox_of(data: Dict[str, Any], arguments: Dict[str, Any]) -> Optional[List[float]]:
    return data.get("bbox") or arguments.get("bbox")


def _validate_bbox(bbox: Any) -> Optional[List[float]]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点球面距离（米）——用于独立校验工具返回的距离是否自洽。"""
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


# --------------------------------------------------------------------------
# 规则 1 · 路径长度合理性
# --------------------------------------------------------------------------

def rule_path_length_sanity(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    if tool != "plan_route":
        return None

    distance = data.get("distance_m")
    straight = data.get("straight_line_m")
    detour = data.get("detour_ratio")
    nodes = data.get("node_count")

    if nodes is not None and nodes < MIN_PATH_NODES:
        return RuleResult(
            rule="path_length_sanity",
            passed=False,
            level=LEVEL_ERROR,
            message=f"路径节点数仅 {nodes}（< {MIN_PATH_NODES}），路径退化，可能起终点重合或栅格分辨率过低",
            suggestion={"resolution": 256},
        )

    if distance is None or straight is None or straight <= 0:
        return None

    # 独立重算直线距离，验证工具自洽性（工具返回值可能因投影处理出错）
    start, end = arguments.get("start_point"), arguments.get("end_point")
    if (
        isinstance(start, (list, tuple)) and len(start) == 2
        and isinstance(end, (list, tuple)) and len(end) == 2
    ):
        try:
            expect = _haversine_m(
                float(start[0]), float(start[1]), float(end[0]), float(end[1])
            )
            if expect > 0:
                drift = abs(straight - expect) / expect
                if drift > 0.25:
                    return RuleResult(
                        rule="path_length_sanity",
                        passed=False,
                        level=LEVEL_ERROR,
                        message=(
                            f"工具返回的直线距离 {straight:.0f} m 与球面距离独立复算值 "
                            f"{expect:.0f} m 偏差 {drift * 100:.0f}%，距离计算不可信"
                        ),
                        suggestion=None,
                    )
        except (TypeError, ValueError):
            pass

    if distance < straight * 0.98:
        return RuleResult(
            rule="path_length_sanity",
            passed=False,
            level=LEVEL_ERROR,
            message=f"路径长度 {distance:.0f} m 小于直线距离 {straight:.0f} m，物理上不可能",
            suggestion=None,
        )

    ratio = detour if detour is not None else (distance / straight if straight else 0)
    if ratio > MAX_DETOUR_RATIO_ERROR:
        return RuleResult(
            rule="path_length_sanity",
            passed=False,
            level=LEVEL_ERROR,
            message=f"绕行系数 {ratio:.2f} 异常（阈值 {MAX_DETOUR_RATIO_ERROR}），可能存在大片不可通行区域",
            suggestion={"resolution": 256},
        )
    if ratio > MAX_DETOUR_RATIO_WARN:
        return RuleResult(
            rule="path_length_sanity",
            passed=False,
            level=LEVEL_WARN,
            message=f"绕行系数 {ratio:.2f} 偏高，路径绕行明显，可能受地形阻隔",
            suggestion=None,
        )

    return RuleResult(
        rule="path_length_sanity",
        passed=True,
        level=LEVEL_INFO,
        message=f"路径长度 {distance:.0f} m，绕行系数 {ratio:.2f}，在合理范围",
    )


# --------------------------------------------------------------------------
# 规则 2 · 坡度取值范围
# --------------------------------------------------------------------------

def rule_slope_range(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    if tool != "compute_slope":
        return None
    stats = data.get("statistics") or {}
    mn, mx = stats.get("min"), stats.get("max")
    if mn is None or mx is None:
        return None

    if mx > SLOPE_MAX_DEG or mn < SLOPE_MIN_DEG:
        return RuleResult(
            rule="slope_range",
            passed=False,
            level=LEVEL_ERROR,
            message=f"坡度范围 [{mn}, {mx}] 超出合法区间 [0, 90] 度，栅格计算有误",
            suggestion=None,
        )
    if mx > 80:
        return RuleResult(
            rule="slope_range",
            passed=False,
            level=LEVEL_WARN,
            message=f"最大坡度 {mx} 度接近垂直，请确认 DEM 数据质量",
            suggestion=None,
        )
    return RuleResult(
        rule="slope_range",
        passed=True,
        level=LEVEL_INFO,
        message=f"坡度范围 [{mn}, {mx}] 度，在合法区间内",
    )


def rule_aspect_range(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    """坡向必须在 [0, 360)。顺带做的，因为同样是可判定的边界检查。"""
    if tool != "compute_aspect":
        return None
    stats = data.get("statistics") or {}
    mn, mx = stats.get("min"), stats.get("max")
    if mn is None or mx is None:
        return None
    if mn < 0 or mx > 360:
        return RuleResult(
            rule="aspect_range",
            passed=False,
            level=LEVEL_ERROR,
            message=f"坡向范围 [{mn}, {mx}] 超出 [0, 360) 度",
            suggestion=None,
        )
    return RuleResult(
        rule="aspect_range", passed=True, level=LEVEL_INFO,
        message=f"坡向范围 [{mn}, {mx}] 度，合法",
    )


# --------------------------------------------------------------------------
# 规则 3 · 分类结果非空
# --------------------------------------------------------------------------

def rule_classification_nonempty(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    if tool not in CLASSIFY_TOOLS:
        return None
    dist = data.get("distribution") or {}
    distinct = dist.get("distinct_classes")
    dominant = dist.get("dominant_ratio")

    if distinct is None:
        return None

    if distinct < MIN_DISTINCT_CLASSES:
        return RuleResult(
            rule="classification_nonempty",
            passed=False,
            level=LEVEL_ERROR,
            message=f"分类结果仅 {distinct} 个类别，地形形态无区分度，可能全为 nodata 或区域过小",
            suggestion={"resolution": 256},
        )
    if dominant is not None and dominant > MAX_DOMINANT_RATIO:
        return RuleResult(
            rule="classification_nonempty",
            passed=False,
            level=LEVEL_WARN,
            message=f"主导类别占比 {dominant:.4f}，分类高度单一，结果参考价值有限",
            suggestion=None,
        )
    return RuleResult(
        rule="classification_nonempty",
        passed=True,
        level=LEVEL_INFO,
        message=f"分类得到 {distinct} 个类别，主导占比 {dominant if dominant is not None else float('nan'):.4f}",
    )


# --------------------------------------------------------------------------
# 规则 4 · 起终点在 bbox 内
# --------------------------------------------------------------------------

def rule_endpoints_in_bbox(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    if tool != "plan_route":
        return None
    bbox = _validate_bbox(_bbox_of(data, arguments))
    start, end = arguments.get("start_point"), arguments.get("end_point")
    if not bbox or not isinstance(start, (list, tuple)) or not isinstance(end, (list, tuple)):
        return None
    if len(start) != 2 or len(end) != 2:
        return None

    w, s, e, n = bbox
    try:
        pts = {
            "start_point": (float(start[0]), float(start[1])),
            "end_point": (float(end[0]), float(end[1])),
        }
    except (TypeError, ValueError):
        return None

    outside = [
        name for name, (lon, lat) in pts.items()
        if not (w <= lon <= e and s <= lat <= n)
    ]
    if outside:
        # 自动给出修正：把越界点夹取到 bbox 内部（留 1% 边距，避免落在边界像元上）
        suggestion = dict(arguments)
        mx, my = (e - w) * 0.01, (n - s) * 0.01
        for name in outside:
            lon, lat = pts[name]
            suggestion[name] = [
                min(max(lon, w + mx), e - mx),
                min(max(lat, s + my), n - my),
            ]
        return RuleResult(
            rule="endpoints_in_bbox",
            passed=False,
            level=LEVEL_ERROR,
            message=f"{', '.join(outside)} 落在 bbox {bbox} 之外",
            suggestion=suggestion,
        )
    return RuleResult(
        rule="endpoints_in_bbox", passed=True, level=LEVEL_INFO,
        message="起终点均在研究区范围内",
    )


# --------------------------------------------------------------------------
# 规则 5 · 地理参考一致性
# --------------------------------------------------------------------------

def rule_crs_consistency(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    crs = data.get("crs") or data.get("epsg")
    if crs is not None:
        crs_str = str(crs).upper().replace("_", ":")
        if "4326" not in crs_str and "WGS84" not in crs_str:
            return RuleResult(
                rule="crs_consistency",
                passed=False,
                level=LEVEL_ERROR,
                message=f"坐标系为 {crs}，Agent 全流程约定 WGS84 (EPSG:4326)，混用会导致距离与面积错误",
                suggestion=None,
            )

    # 无显式 CRS 时，用「请求 bbox 与结果 bbox 一致」+「像元尺寸合理」间接验证
    arg_bbox = _validate_bbox(arguments.get("bbox"))
    data_bbox = _validate_bbox(data.get("bbox"))
    if arg_bbox and data_bbox:
        if any(abs(a - b) > 1e-6 for a, b in zip(arg_bbox, data_bbox)):
            return RuleResult(
                rule="crs_consistency",
                passed=False,
                level=LEVEL_ERROR,
                message=f"请求 bbox {arg_bbox} 与结果 bbox {data_bbox} 不一致，结果可能来自缓存的其它区域",
                suggestion=dict(arguments, bbox=arg_bbox),
            )

    cell = data.get("cell_size_m")
    if cell is not None:
        try:
            cell_f = float(cell)
        except (TypeError, ValueError):
            cell_f = None
        if cell_f is not None and not (MIN_CELL_SIZE_M <= cell_f <= MAX_CELL_SIZE_M):
            return RuleResult(
                rule="crs_consistency",
                passed=False,
                level=LEVEL_ERROR,
                message=f"像元尺寸 {cell_f} m 超出合理范围 [{MIN_CELL_SIZE_M}, {MAX_CELL_SIZE_M}] m，地理参考可能有误",
                suggestion=None,
            )
    return None


# --------------------------------------------------------------------------
# 规则 4b · bbox 顺序合法性（参数类规则）
# --------------------------------------------------------------------------

def rule_bbox_order(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    """校验 bbox 顺序，并自动修正两种高频错误：经纬颠倒、边界反置。

    大模型输出 bbox 时最常见的两个错误：
        - 写成 [minLat, minLon, maxLat, maxLon]（纬度在前）
        - 西大于东 / 南大于北（边界反置）
    两者都可自动修正，不需要重问模型。
    """
    raw = arguments.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        a, b, c, d = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None

    fixed = None
    note = ""

    # 情形 1：纬度在前（|a|,|c| <= 90 而 |b|,|d| > 90 则不成立，需更谨慎）
    if abs(a) <= 90 and abs(c) <= 90 and (abs(b) > 90 or abs(d) > 90):
        fixed = [b, a, d, c]
        note = "bbox 为纬度在前，已交换为 [minLon, minLat, maxLon, maxLat]"
    else:
        w, s, e, n = a, b, c, d
        swapped = False
        if w > e:
            w, e = e, w
            swapped = True
        if s > n:
            s, n = n, s
            swapped = True
        if swapped:
            fixed = [w, s, e, n]
            note = "bbox 边界反置，已重新排序为 [西, 南, 东, 北]"

    if fixed is None:
        return None

    suggestion = dict(arguments)
    suggestion["bbox"] = fixed
    return RuleResult(
        rule="bbox_order",
        passed=False,
        level=LEVEL_ERROR,
        message=f"{note}：{list(raw)} → {fixed}",
        suggestion=suggestion,
    )


# --------------------------------------------------------------------------
# 规则 6 · 栅格瓦片对齐
# --------------------------------------------------------------------------

def rule_tile_alignment(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    if tool not in RASTER_METRIC_TOOLS:
        return None
    stats = data.get("statistics") or {}
    shape = stats.get("shape")
    res = data.get("resolution") or arguments.get("resolution")
    if not shape or not res:
        return None
    try:
        h, w = int(shape[0]), int(shape[1])
        res_i = int(res)
    except (TypeError, ValueError, IndexError):
        return None
    if h != res_i or w != res_i:
        return RuleResult(
            rule="tile_alignment",
            passed=False,
            level=LEVEL_ERROR,
            message=f"输出栅格 {h}×{w} 与请求分辨率 {res_i}×{res_i} 不一致，瓦片未对齐",
            suggestion=dict(arguments, resolution=res_i),
        )
    return RuleResult(
        rule="tile_alignment", passed=True, level=LEVEL_INFO,
        message=f"栅格 {h}×{w} 与分辨率 {res_i} 对齐",
    )


# --------------------------------------------------------------------------
# 规则 7 · 有效数据占比
# --------------------------------------------------------------------------

def rule_valid_data_ratio(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    ratio = data.get("valid_ratio")
    if ratio is None:
        stats = data.get("statistics") or {}
        ratio = stats.get("valid_ratio")
    if ratio is None:
        return None
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return None
    if r < MIN_VALID_RATIO:
        return RuleResult(
            rule="valid_data_ratio",
            passed=False,
            level=LEVEL_ERROR,
            message=f"有效像元仅占 {r:.2%}（阈值 {MIN_VALID_RATIO:.0%}），结果不具代表性",
            suggestion=None,
        )
    if r < 0.95:
        return RuleResult(
            rule="valid_data_ratio",
            passed=False,
            level=LEVEL_WARN,
            message=f"有效像元占比 {r:.2%}，存在 {1 - r:.2%} 的无效区域（nodata）",
            suggestion=None,
        )
    return None


# --------------------------------------------------------------------------
# 规则 8 · DEM 数据源真实性（本项目的关键诚实性约束）
# --------------------------------------------------------------------------

def rule_dem_source_authenticity(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> Optional[RuleResult]:
    source = data.get("dem_source")
    if source is None:
        return None
    if str(source).lower() in ("synthetic", "synth", "simulated", "random"):
        return RuleResult(
            rule="dem_source_authenticity",
            passed=False,
            level=LEVEL_WARN,
            message=(
                "当前结果基于合成地形，不是真实高程数据。"
                "可用于流程验证，但不得作为真实地理结论回答用户。"
                "如需真实结果，应先调用 download_srtm 或传入 dem_path。"
            ),
            suggestion=None,
        )
    return None


# --------------------------------------------------------------------------
# 注册表
# --------------------------------------------------------------------------

RULES: List[Callable[[str, Dict[str, Any], Dict[str, Any]], Optional[RuleResult]]] = [
    rule_path_length_sanity,
    rule_slope_range,
    rule_aspect_range,
    rule_classification_nonempty,
    rule_endpoints_in_bbox,
    rule_bbox_order,
    rule_crs_consistency,
    rule_tile_alignment,
    rule_valid_data_ratio,
    rule_dem_source_authenticity,
]

# 只依赖 arguments、不依赖结果 data 的规则。
# 工具调用失败时仍然可以运行 —— 这才有能力在重试前修正参数，
# 否则 Agent 会用同样的错误参数重试 N 次再放弃。
ARGUMENT_RULES: List[
    Callable[[str, Dict[str, Any], Dict[str, Any]], Optional[RuleResult]]
] = [
    rule_endpoints_in_bbox,
    rule_bbox_order,
]


def _run_rules(
    rules: List[Callable[[str, Dict[str, Any], Dict[str, Any]], Optional[RuleResult]]],
    tool: str,
    arguments: Dict[str, Any],
    data: Dict[str, Any],
) -> RuleReport:
    report = RuleReport()
    for rule in rules:
        try:
            report.add(rule(tool, arguments, data or {}))
        except Exception as exc:  # 规则自身出错不应中断 Agent
            report.add(
                RuleResult(
                    rule=getattr(rule, "__name__", "unknown"),
                    passed=False,
                    level=LEVEL_WARN,
                    message=f"规则执行异常：{exc}",
                )
            )
    return report


def check_result(
    tool: str, arguments: Dict[str, Any], data: Dict[str, Any]
) -> RuleReport:
    """对一次**成功**的工具调用执行全部适用规则。

    Args:
        tool: 工具名
        arguments: 调用参数
        data: 工具返回的 data 字段

    Returns:
        RuleReport
    """
    return _run_rules(RULES, tool, arguments, data)


def check_arguments(tool: str, arguments: Dict[str, Any]) -> RuleReport:
    """对一次**失败**的工具调用仅执行参数类规则。

    目的：在重试前找出"参数本身就能修好"的错误（起终点越界、bbox 顺序错误），
    避免用同样的错误参数反复重试直到耗尽次数。

    Returns:
        RuleReport
    """
    return _run_rules(ARGUMENT_RULES, tool, arguments, {})


def collect_warnings(data: Dict[str, Any]) -> List[str]:
    """提取工具自身返回的 warnings 字段。"""
    w = (data or {}).get("warnings")
    if isinstance(w, list):
        return [str(x) for x in w]
    return []
