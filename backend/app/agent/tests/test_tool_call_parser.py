"""原生 <tool_call> 解析的单元测试。

背景：llama-cpp-python 0.3.35 不解析 Qwen 的 <tool_call> 格式，
导致 Agent 永远看不到模型调用的工具。这个解析器是评测分数从 0 到可用
的关键，必须有测试锁死行为。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agent.llm import parse_native_tool_calls  # noqa: E402


def test_single_call_with_json_array_param():
    text = (
        "先取 DEM：\n<tool_call>\n<function=download_srtm>\n"
        "<parameter=bbox>\n[103.5, 30.2, 104.5, 31.0]\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    calls = parse_native_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "download_srtm"
    assert calls[0]["arguments"]["bbox"] == [103.5, 30.2, 104.5, 31.0]


def test_multiple_calls_and_params():
    text = (
        "<tool_call><function=download_srtm><parameter=bbox>[1,2,3,4]</parameter>"
        "</function></tool_call>"
        "<tool_call><function=compute_slope><parameter=bbox>[1,2,3,4]</parameter>"
        "<parameter=resolution>256</parameter></function></tool_call>"
    )
    calls = parse_native_tool_calls(text)
    assert [c["name"] for c in calls] == ["download_srtm", "compute_slope"]
    assert calls[1]["arguments"]["resolution"] == 256


def test_string_param_not_forced_to_json():
    text = (
        "<tool_call><function=compute_slope><parameter=dem_path>D:\\dem\\a.tif"
        "</parameter></function></tool_call>"
    )
    calls = parse_native_tool_calls(text)
    assert calls[0]["arguments"]["dem_path"] == "D:\\dem\\a.tif"


def test_degenerate_format_without_wrapper():
    text = "调用 <function=zonal_statistics><parameter=metric>slope</parameter></function>"
    calls = parse_native_tool_calls(text)
    assert calls[0]["name"] == "zonal_statistics"
    assert calls[0]["arguments"]["metric"] == "slope"


def test_plain_text_returns_empty():
    assert parse_native_tool_calls("坡度是两点间高差与水平距离之比。") == []
    assert parse_native_tool_calls("") == []
