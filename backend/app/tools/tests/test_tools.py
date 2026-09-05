"""GeoAgent 工具层测试。

运行方式（二选一）：
    # 方式一：pytest（推荐）
    D:/VS_Code_Program/CesiumJS_Debug/earthscape/.venv/Scripts/python.exe -m pytest backend/app/tools/tests/ -v

    # 方式二：直接运行（不依赖 pytest）
    D:/VS_Code_Program/CesiumJS_Debug/earthscape/.venv/Scripts/python.exe backend/app/tools/tests/test_tools.py

测试覆盖：
    - 参数校验（bbox / resolution / 起终点越界 / 未知工具）
    - 11 个工具的正常路径
    - ONNX 分辨率守卫（性能保护）
    - 缓存命中（Week 1 的核心优化）
    - 调度层宽容性（忽略大模型多传的参数）
"""

from __future__ import annotations

import os
import sys
import time

# 保证无论从哪个目录运行都能导入 backend.app.tools
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.tools import (  # noqa: E402
    TOOL_REGISTRY,
    call_tool,
    classify_geomorphons,
    classify_terrain_onnx,
    classify_terrain_rules,
    compute_aspect,
    compute_cost_surface,
    compute_curvature,
    compute_slope,
    dispatch,
    get_dem_metadata,
    get_mcp_tools,
    get_openai_tools,
    list_tools,
    plan_route,
    terrain_cache,
    zonal_statistics,
)

# 测试用范围（成都附近一小块），全程使用合成地形，避免网络依赖
BBOX = [103.5, 30.2, 103.7, 30.4]
RES = 64


# ── 参数校验 ────────────────────────────────────────────────────────
def test_invalid_bbox_reversed():
    """west >= east 应被拒绝且标记为可重试。"""
    r = compute_slope(bbox=[104.0, 30.2, 103.5, 30.4], resolution=RES)
    assert not r["success"]
    assert r["error_type"] == "invalid_bbox"
    assert r["retryable"] is True


def test_invalid_bbox_length():
    r = compute_slope(bbox=[103.5, 30.2, 103.7], resolution=RES)
    assert not r["success"]
    assert r["error_type"] == "invalid_bbox"


def test_invalid_resolution_too_large():
    r = compute_slope(bbox=BBOX, resolution=99999)
    assert not r["success"]
    assert r["error_type"] == "invalid_resolution"


def test_unknown_tool():
    r = dispatch("no_such_tool", {})
    assert not r["success"]
    assert r["error_type"] == "out_of_capability"


def test_dispatch_ignores_extra_params():
    """大模型多传参数时应宽容处理，不报错。"""
    r = dispatch("compute_slope", {"bbox": BBOX, "resolution": RES, "bogus_param": 1})
    assert r["success"], r.get("error")
    assert r["data"].get("ignored_params") == ["bogus_param"]


# ── 地形因子 ────────────────────────────────────────────────────────
def test_compute_slope():
    r = compute_slope(bbox=BBOX, resolution=RES)
    assert r["success"], r.get("error")
    st = r["data"]["statistics"]
    # 坡度合法区间 0–90
    assert 0 <= st["min"] and st["max"] <= 90
    assert st["valid_ratio"] > 0.9
    assert r["data"]["artifact"]["path"].endswith(".geojson")
    assert os.path.exists(r["data"]["artifact"]["path"])


def test_compute_aspect():
    r = compute_aspect(bbox=BBOX, resolution=RES)
    assert r["success"], r.get("error")
    st = r["data"]["statistics"]
    assert 0 <= st["min"] and st["max"] <= 360


def test_compute_curvature():
    r = compute_curvature(bbox=BBOX, resolution=RES)
    assert r["success"], r.get("error")
    assert "statistics" in r["data"]


def test_compute_cost_surface_basic():
    """不传起终点 → 基础代价场，应给出明确提示。"""
    r = compute_cost_surface(bbox=BBOX, resolution=RES)
    assert r["success"], r.get("error")
    assert r["data"]["directional"] is False
    assert any("方向性代价" in w for w in r["data"].get("warnings", []))


def test_compute_cost_surface_directional():
    """传入起终点 → 方向性代价场。"""
    r = compute_cost_surface(
        bbox=BBOX, resolution=RES,
        start_point=[103.55, 30.25], end_point=[103.65, 30.35],
    )
    assert r["success"], r.get("error")
    assert r["data"]["directional"] is True
    assert "min_cost_dir_stats" in r["data"]


def test_cost_surface_partial_points_rejected():
    """只传起点不传终点 → 明确报错。"""
    r = compute_cost_surface(bbox=BBOX, resolution=RES, start_point=[103.55, 30.25])
    assert not r["success"]
    assert r["error_type"] == "invalid_point"


# ── 路径规划 ────────────────────────────────────────────────────────
def test_plan_route():
    r = plan_route(
        bbox=BBOX, resolution=RES,
        start_point=[103.55, 30.25], end_point=[103.65, 30.35],
    )
    assert r["success"], r.get("error")
    d = r["data"]
    assert d["distance_m"] > 0
    assert d["node_count"] >= 2
    assert d["detour_ratio"] >= 1.0
    assert d["directional_cost"] is True


def test_plan_route_point_outside_bbox():
    r = plan_route(
        bbox=BBOX, resolution=RES,
        start_point=[120.0, 30.25],   # 明显在 bbox 之外
        end_point=[103.65, 30.35],
    )
    assert not r["success"]
    assert r["error_type"] == "invalid_point"


def test_plan_route_missing_endpoint():
    """漏传终点必须返回结构化错误，而不是抛 TypeError 让 Agent 崩溃。"""
    r = plan_route(bbox=BBOX, resolution=RES, start_point=[103.55, 30.25])
    assert not r["success"]
    assert r["error_type"] == "invalid_point"


def test_plan_route_bad_point_types():
    """大模型传入非法点位格式时应优雅报错。"""
    # 字符串而非数组
    r = plan_route(
        bbox=BBOX, resolution=RES,
        start_point="103.55,30.25", end_point=[103.65, 30.35],
    )
    assert not r["success"]
    assert r["error_type"] == "invalid_point"

    # 元素个数不对
    r = plan_route(
        bbox=BBOX, resolution=RES,
        start_point=[103.55], end_point=[103.65, 30.35],
    )
    assert not r["success"]
    assert r["error_type"] == "invalid_point"

    # 经纬度越界
    r = plan_route(
        bbox=BBOX, resolution=RES,
        start_point=[999.0, 30.25], end_point=[103.65, 30.35],
    )
    assert not r["success"]
    assert r["error_type"] == "invalid_point"


# ── 地貌分类 ────────────────────────────────────────────────────────
def test_classify_rules():
    r = classify_terrain_rules(bbox=BBOX, resolution=RES)
    assert r["success"], r.get("error")
    assert r["data"]["distribution"]["total_cells"] == RES * RES
    assert len(r["data"]["legend"]) == 8


def test_classify_geomorphons():
    r = classify_geomorphons(bbox=BBOX, resolution=RES)
    assert r["success"], r.get("error")
    assert r["data"]["method"] == "geomorphons"


def test_onnx_resolution_guard():
    """分辨率超过 128 必须被拒绝并给出替代建议（性能保护）。"""
    r = classify_terrain_onnx(bbox=BBOX, resolution=256)
    assert not r["success"]
    assert r["error_type"] == "invalid_resolution"
    assert "classify_geomorphons" in r["error"]  # 应提示替代方案


def test_classify_onnx_small():
    """小范围 ONNX 分类（64×64，约 6.5 秒）。"""
    r = classify_terrain_onnx(bbox=BBOX, resolution=64)
    assert r["success"], r.get("error")
    assert r["data"]["method"] == "onnx"
    # 应提示标签来源
    assert any("伪标签" in w for w in r["data"].get("warnings", []))


def test_zonal_statistics_slope():
    r = zonal_statistics(bbox=BBOX, metric="slope", resolution=RES)
    assert r["success"], r.get("error")
    assert "passable" in r["data"]           # 坡度指标应给出可通行性结论
    assert len(r["data"]["classes"]) == 5
    total = sum(c["ratio"] for c in r["data"]["classes"])
    assert abs(total - 1.0) < 0.01           # 各级占比之和应为 1


def test_zonal_statistics_unknown_metric():
    r = zonal_statistics(bbox=BBOX, metric="nonsense", resolution=RES)
    assert not r["success"]
    assert r["error_type"] == "unknown_metric"


# ── 缓存（Week 1 核心优化）───────────────────────────────────────────
def test_cache_reuse_across_metrics():
    """连续调用不同指标工具应复用同一次地形分析结果。"""
    terrain_cache.clear()

    r1 = compute_slope(bbox=BBOX, resolution=RES)
    assert r1["data"]["cache_hit"] is False

    r2 = compute_aspect(bbox=BBOX, resolution=RES)
    assert r2["data"]["cache_hit"] is True, "同参数的不同指标应命中缓存"

    r3 = compute_curvature(bbox=BBOX, resolution=RES)
    assert r3["data"]["cache_hit"] is True

    stats = terrain_cache.stats()
    assert stats["hit_rate"] > 0.5


def test_cache_miss_on_different_resolution():
    terrain_cache.clear()
    compute_slope(bbox=BBOX, resolution=64)
    r = compute_slope(bbox=BBOX, resolution=96)
    assert r["data"]["cache_hit"] is False


# ── 元数据 / 注册表 ──────────────────────────────────────────────────
def test_get_dem_metadata_missing_file():
    r = get_dem_metadata(dem_path="/nonexistent/path/to/dem.tif")
    assert not r["success"]
    assert r["error_type"] == "dem_not_found"


def test_registry_completeness():
    """每个工具都必须有对应的函数与 schema。"""
    assert len(TOOL_REGISTRY) == 11
    for name, item in TOOL_REGISTRY.items():
        assert callable(item["fn"]), f"{name} 缺少实现函数"
        assert "function" in item["schema"], f"{name} 缺少 schema"
        assert item["schema"]["function"]["name"] == name


def test_openai_tools_format():
    tools = get_openai_tools()
    assert len(tools) == 11
    for t in tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert "name" in fn and "description" in fn and "parameters" in fn
        assert fn["parameters"]["type"] == "object"


def test_mcp_tools_format():
    """MCP 格式（Week 3 使用）：name / description / inputSchema。"""
    tools = get_mcp_tools()
    assert len(tools) == 11
    for t in tools:
        assert set(t.keys()) == {"name", "description", "inputSchema"}
        assert t["inputSchema"]["type"] == "object"


def test_list_tools():
    tools = list_tools()
    assert len(tools) == 11
    assert all("name" in t and "description" in t for t in tools)


# ── 直接运行入口（不依赖 pytest）────────────────────────────────────
if __name__ == "__main__":
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    passed, failed = 0, []
    print(f"运行 {len(tests)} 个测试\n" + "=" * 60)
    for name, fn in tests:
        t0 = time.perf_counter()
        try:
            fn()
            print(f"  ✓ {name:<45} {(time.perf_counter()-t0)*1000:7.1f} ms")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {name:<45} {exc}")
            failed.append((name, exc))
    print("=" * 60)
    print(f"通过 {passed}/{len(tests)}")
    if failed:
        print("\n失败详情：")
        for name, exc in failed:
            print(f"  {name}: {exc!r}")
        sys.exit(1)
