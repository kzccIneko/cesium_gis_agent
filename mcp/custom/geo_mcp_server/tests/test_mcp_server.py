"""GeoMCP Server 测试。

不依赖真实 MCP 客户端（Claude Desktop / Cursor），直接在进程内驱动
FastMCP 的 list_tools / call_tool / resource / prompt 接口，
因此可以在 CI 里跑，也可以在没装任何客户端的机器上运行。

运行方式::

    python mcp/custom/geo_mcp_server/tests/test_mcp_server.py

必须用 backend 的虚拟环境（工具依赖 numpy / rasterio / onnxruntime）。

注意 sys.path 卫生：项目根目录下有个与官方 SDK 同名的 `mcp/` 目录，
一旦项目根进入 sys.path，`import mcp` 就会命中它而不是 SDK，
报错是含糊的 "No module named 'mcp.server'"。本文件开头主动清理。
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与导入
# ---------------------------------------------------------------------------

SERVER_DIR = Path(__file__).resolve().parents[1]      # geo_mcp_server/
PROJECT_ROOT = Path(__file__).resolve().parents[3]    # 项目根

# 清理可能遮蔽官方 MCP SDK 的项目根路径
for _p in list(sys.path):
    if not _p:
        continue
    try:
        if Path(_p or ".").resolve() == PROJECT_ROOT:
            sys.path.remove(_p)
    except OSError:
        pass

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

if importlib.util.find_spec("mcp.server.fastmcp") is None:
    raise SystemExit(
        "MCP Python SDK 不可用，或已被项目根目录下的 mcp/ 目录遮蔽。\n"
        "请用 backend 虚拟环境并以脚本方式运行本测试：\n"
        f"    python {Path(__file__).resolve()}"
    )

import server  # noqa: E402
from server import mcp  # noqa: E402
from tools import (  # noqa: E402
    BACKEND_ROOT,
    build_signature,
    describe_artifact,
    format_tool_result,
    get_tool_definitions,
    make_tool_function,
)

# ---------------------------------------------------------------------------
# 极简测试框架（与 tools / agent 两层保持一致，不引入 pytest）
# ---------------------------------------------------------------------------

_PASSED = 0
_FAILED = 0
_FAILURES: list = []


def _run(fn):
    global _PASSED, _FAILED
    name = fn.__name__
    try:
        fn()
        _PASSED += 1
        print(f"  PASS  {name}")
    except AssertionError as exc:
        _FAILED += 1
        _FAILURES.append((name, str(exc) or "断言失败"))
        print(f"  FAIL  {name}\n        {exc}")
    except Exception as exc:  # noqa: BLE001
        _FAILED += 1
        _FAILURES.append((name, f"{type(exc).__name__}: {exc}"))
        print(f"  ERROR {name}\n        {type(exc).__name__}: {exc}")


def test(fn):
    globals()[fn.__name__] = fn
    return fn


BBOX = [103.5, 30.2, 103.7, 30.4]
RES = 64


async def _call(name: str, arguments: dict) -> str:
    """通过 FastMCP 调用工具，返回文本内容。"""
    result = await mcp.call_tool(name, arguments)
    content = result[0] if isinstance(result, tuple) else result
    if isinstance(content, list):
        return "\n".join(getattr(c, "text", str(c)) for c in content)
    return str(content)


def call_tool_text(name: str, arguments: dict) -> str:
    return asyncio.run(_call(name, arguments))


# ---------------------------------------------------------------------------
# 1. 环境与 schema 一致性
# ---------------------------------------------------------------------------


@test
def test_backend_root_exists():
    assert BACKEND_ROOT.is_dir(), f"backend 目录不存在：{BACKEND_ROOT}"


@test
def test_tool_definitions_are_mcp_shaped():
    defs = get_tool_definitions()
    assert len(defs) == 11, f"应有 11 个工具，实际 {len(defs)}"
    for d in defs:
        assert set(d) >= {"name", "description", "inputSchema"}, d
        assert isinstance(d["inputSchema"], dict)
        assert d["inputSchema"].get("type") == "object", d["name"]


@test
def test_mcp_registers_all_tools_plus_agent():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    expected = {d["name"] for d in get_tool_definitions()}
    assert expected <= names, f"未注册：{expected - names}"
    assert "geo_agent_query" in names, "Agent 工具未注册"
    assert len(tools) == len(expected) + 1, f"工具总数应为 12，实际 {len(tools)}"


@test
def test_no_schema_drift_between_mcp_and_registry():
    """MCP 暴露的参数必须与后端工具函数签名完全一致。

    这是本层存在的首要理由：schema 单一来源。若有人在后端加了参数
    却只更新了 schemas.py 而漏了函数签名（或反之），这里会立刻暴露。
    """
    from app.tools import TOOL_REGISTRY

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name, entry in TOOL_REGISTRY.items():
        mcp_props = set(tools[name].inputSchema.get("properties") or {})
        fn_props = set(inspect.signature(entry["fn"]).parameters)
        assert mcp_props == fn_props, (
            f"{name} 参数漂移：MCP 侧 {sorted(mcp_props)}，"
            f"函数签名 {sorted(fn_props)}"
        )


@test
def test_required_params_preserved():
    """必填参数必须在 schema 里体现为 required，否则模型会漏传。"""
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert tools["plan_route"].inputSchema.get("required") == [
        "bbox",
        "start_point",
        "end_point",
    ], tools["plan_route"].inputSchema.get("required")
    assert tools["compute_slope"].inputSchema.get("required") == ["bbox"]


@test
def test_enum_values_reachable_in_schema():
    """枚举值必须出现在 schema 中，而不是只写在描述文本里。"""
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    metric = tools["zonal_statistics"].inputSchema["properties"]["metric"]
    blob = json.dumps(metric, ensure_ascii=False)
    for value in ("slope", "aspect", "curvature", "cost", "elevation"):
        assert value in blob, f"metric 枚举缺少 {value}"


@test
def test_signature_builder_marks_required():
    sig = build_signature(
        {
            "type": "object",
            "properties": {
                "bbox": {"type": "array", "items": {"type": "number"}},
                "resolution": {"type": "integer", "default": 256},
            },
            "required": ["bbox"],
        }
    )
    assert sig.parameters["bbox"].default is inspect.Parameter.empty
    assert sig.parameters["resolution"].default == 256


# ---------------------------------------------------------------------------
# 2. 结果渲染
# ---------------------------------------------------------------------------


@test
def test_describe_artifact():
    line = describe_artifact(
        {
            "artifact": {
                "format": "geojson",
                "path": "D:/out/slope.geojson",
                "feature_count": 3969,
            }
        }
    )
    assert line is not None and "D:/out/slope.geojson" in line
    assert "3969" in line and "geojson" in line
    assert describe_artifact({}) is None


@test
def test_format_success_output():
    text = format_tool_result(
        "compute_slope",
        {
            "success": True,
            "data": {
                "summary": "坡度：均值 18.8 degree",
                "statistics": {"mean": 18.8, "max": 31.6},
                "warnings": ["当前使用合成地形"],
                "artifact": {"format": "geojson", "path": "D:/o/s.geojson"},
            },
        },
    )
    assert text.startswith("✅")
    assert "产物文件" in text and "D:/o/s.geojson" in text
    assert "关键统计" in text and "18.8" in text
    assert "⚠️ 告警" in text
    # 已在顶部单独展示的字段不应在完整结果里重复出现
    assert text.count("当前使用合成地形") == 1


@test
def test_format_failure_output_is_actionable():
    text = format_tool_result(
        "plan_route",
        {
            "success": False,
            "error_type": "invalid_point",
            "error": "经度 103.0 不在分析范围 [103.5, 103.7] 内",
            "retryable": True,
        },
    )
    assert text.startswith("❌")
    assert "invalid_point" in text
    assert "103.0" in text
    assert "是" in text  # 是否可重试
    assert "geo_agent_query" in text, "失败时应引导到可自动修正的入口"


@test
def test_output_truncation():
    huge = {"success": True, "data": {"blob": "x" * 40000}}
    text = format_tool_result("t", huge, max_chars=500)
    assert len(text) < 2000, "截断未生效，会撑爆客户端上下文"
    assert "已截断" in text


@test
def test_unknown_tool_returns_failure_text_not_exception():
    """工具层承诺绝不抛异常，MCP 层必须守住这条承诺。"""
    fn = make_tool_function(
        "no_such_tool",
        "x",
        {"type": "object", "properties": {}, "required": []},
    )
    text = fn()
    assert isinstance(text, str)
    assert "❌" in text


# ---------------------------------------------------------------------------
# 3. 端到端调用
# ---------------------------------------------------------------------------


@test
def test_call_compute_slope_success():
    text = call_tool_text("compute_slope", {"bbox": BBOX, "resolution": RES})
    assert "✅" in text, text[:300]
    assert "产物文件" in text
    assert "坡度" in text
    # 合成地形必须被明确标注，否则用户会拿假数据当真
    assert "合成地形" in text, "未标注数据来源为合成地形"


@test
def test_call_plan_route_out_of_bbox_is_actionable():
    text = call_tool_text(
        "plan_route",
        {
            "bbox": BBOX,
            "resolution": RES,
            "start_point": [103.0, 30.0],
            "end_point": [103.95, 30.55],
        },
    )
    assert "❌" in text
    assert "invalid_point" in text
    assert "可重试" in text


@test
def test_call_zonal_statistics():
    text = call_tool_text(
        "zonal_statistics",
        {"bbox": BBOX, "metric": "slope", "resolution": RES},
    )
    assert "✅" in text, text[:300]


@test
def test_onnx_resolution_guard_surfaces():
    """ONNX 分类超分辨率必须被拒绝并给出替代方案，而不是跑 100 秒。"""
    text = call_tool_text(
        "classify_terrain_onnx", {"bbox": BBOX, "resolution": 256}
    )
    assert "❌" in text, text[:400]
    assert "128" in text, "应提示 128 分辨率上限"


# ---------------------------------------------------------------------------
# 4. Agent 工具
# ---------------------------------------------------------------------------


@test
def test_agent_query_rejects_bad_bbox():
    text = call_tool_text(
        "geo_agent_query", {"question": "分析坡度", "bbox": [103.5, 30.2]}
    )
    assert "❌" in text
    assert "bbox" in text


@test
def test_agent_query_end_to_end():
    text = call_tool_text(
        "geo_agent_query",
        {"question": "分析这片区域的坡度", "bbox": BBOX, "session_id": "mcp-test"},
    )
    assert "❌" not in text, text[:500]
    assert len(text) > 50
    assert "工具调用" in text


# ---------------------------------------------------------------------------
# 5. 资源与提示词
# ---------------------------------------------------------------------------


@test
def _unwrap(obj):
    """不同 mcp 版本下，装饰器有的返回原函数、有的返回包装对象。"""
    return getattr(obj, "fn", obj)


def test_resource_tools_readable():
    import server as srv

    raw = _unwrap(srv.resource_tools)()
    payload = json.loads(raw)
    assert len(payload) == 11
    assert all("inputSchema" in p for p in payload)


@test
def test_resource_capabilities_declares_data_source():
    import server as srv

    caps = json.loads(_unwrap(srv.resource_capabilities)())
    assert caps["crs"].startswith("EPSG:4326")
    assert "SRTM" in caps["dem"]["primary"]
    assert "合成地形" in caps["dem"]["fallback"]
    assert caps["known_limits"], "必须声明已知局限"


@test
def test_prompt_embeds_arguments():
    import server as srv

    text = _unwrap(srv.prompt_site_selection)(
        requirement="找可修施工便道的缓坡", bbox="103.5,30.2,103.7,30.4"
    )
    assert "103.5,30.2,103.7,30.4" in text
    assert "缓坡" in text
    assert "不要编造数值" in text


# ---------------------------------------------------------------------------
# 6. 协议卫生
# ---------------------------------------------------------------------------


@test
def test_logging_goes_to_stderr():
    """stdio 传输下 stdout 是 JSON-RPC 通道，日志写进去会破坏协议帧。"""
    import logging

    root = logging.getLogger()
    handlers = [h for h in root.handlers]
    assert handlers, "未配置日志处理器"
    bad = [
        h
        for h in handlers
        if getattr(getattr(h, "stream", None), "name", None) == "stdout"
    ]
    assert not bad, "存在写往 stdout 的日志处理器"


# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 62)
    print("GeoMCP Server 测试")
    print("=" * 62)

    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in sorted(names):
        fn = globals()[n]
        if callable(fn):
            _run(fn)

    print()
    print("=" * 62)
    print(f"通过 {_PASSED} / {_PASSED + _FAILED}")
    if _FAILURES:
        print()
        print("失败明细：")
        for name, msg in _FAILURES:
            print(f"  - {name}: {msg}")
    print("=" * 62)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
