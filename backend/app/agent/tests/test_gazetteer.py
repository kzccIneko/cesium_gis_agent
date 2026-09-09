"""地名词典测试。

重点验证三件事：
1. 评测集 20 个地名全部命中且 bbox 与标准答案一致（这是它的核心用途）
2. 最长匹配生效，短别名不会抢走长地名
3. 纯坐标类查询不会误命中（否则会把正确的坐标请求带偏）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agent.gazetteer import Gazetteer  # noqa: E402


@pytest.fixture(scope="module")
def gz(tmp_path_factory) -> Gazetteer:
    """用临时库，避免污染真实 .data/geoagent.sqlite。"""
    db = tmp_path_factory.mktemp("gz") / "test.sqlite"
    return Gazetteer(str(db))


def test_seed_loaded(gz: Gazetteer) -> None:
    st = gz.stats()
    assert st["entries"] >= 60
    assert st["by_source"].get("eval") == 20
    assert st["aliases"] > st["entries"]  # 有别名


def test_eval_regions_match_expected_bbox(gz: Gazetteer) -> None:
    """逐条核对评测集里的标准答案，错一个都不行。"""
    expected = {
        "成都周边": [103.5, 30.2, 104.5, 31.0],
        "四姑娘山": [102.8, 30.9, 103.2, 31.2],
        "贡嘎山": [101.6, 29.4, 102.0, 29.8],
        "峨眉山": [103.2, 29.4, 103.5, 29.7],
        "张家界": [110.3, 29.2, 110.6, 29.5],
        "泰山": [117.0, 36.2, 117.3, 36.4],
        "玉龙雪山": [100.1, 27.0, 100.3, 27.2],
        "珠峰": [86.8, 27.9, 87.0, 28.1],
        "秦岭": [107.5, 33.5, 108.5, 34.2],
        "横断山": [99.0, 28.0, 100.5, 29.5],
        "三峡": [110.0, 30.8, 111.0, 31.2],
        "都江堰": [103.4, 30.9, 103.8, 31.2],
        "雅安": [102.8, 29.8, 103.2, 30.2],
        "拉萨": [90.8, 29.5, 91.3, 30.0],
        "西安": [108.7, 34.0, 109.2, 34.5],
        "兰州": [103.5, 35.9, 104.0, 36.3],
        "昆明": [102.4, 24.8, 102.9, 25.3],
        "黄山": [118.1, 30.1, 118.3, 30.3],
        "塔克拉玛干": [83.0, 38.5, 85.0, 40.0],
        "锡林郭勒草原": [116.0, 43.0, 117.5, 44.0],
    }
    for name, bbox in expected.items():
        got = gz.resolve_bbox(name)
        assert got == bbox, f"{name}: 期望 {bbox}，实际 {got}"


def test_lookup_inside_sentence(gz: Gazetteer) -> None:
    hits = gz.lookup("分析四姑娘山一带的坡度")
    assert hits and hits[0].name == "四姑娘山"
    assert hits[0].bbox == [102.8, 30.9, 103.2, 31.2]


def test_longest_match_wins(gz: Gazetteer) -> None:
    """'成都周边' 不能被别名 '成都' 抢走；'横断山区' 要归到 '横断山'。"""
    assert gz.lookup("计算成都周边的坡度")[0].name == "成都周边"
    assert gz.lookup("横断山区的地貌")[0].name == "横断山"
    assert gz.lookup("塔克拉玛干沙漠通行性")[0].name == "塔克拉玛干"


def test_alias_lookup(gz: Gazetteer) -> None:
    assert gz.resolve_bbox("珠穆朗玛峰的坡度") == [86.8, 27.9, 87.0, 28.1]
    assert gz.resolve_bbox("锡林郭勒好走吗") == [116.0, 43.0, 117.5, 44.0]


def test_no_false_positive_on_coordinates(gz: Gazetteer) -> None:
    """纯经纬度查询不该被词典改写 —— 否则会把本来正确的答案带偏。"""
    for q in (
        "帮我算一下经度 107.5 到 108.5、纬度 33.5 到 34.2范围的坡度",
        "计算经度 103.2 到 103.5、纬度 29.4 到 29.7的坡向",
        "分析经度 99.0 到 100.5、纬度 28.0 到 29.5的坡向分布",
    ):
        assert gz.lookup(q) == [], f"误命中：{q}"


def test_annotate_appends_hint(gz: Gazetteer) -> None:
    out = gz.annotate("计算成都周边的坡度")
    assert out.startswith("计算成都周边的坡度")
    assert "[地名词典]" in out
    assert "[103.5, 30.2, 104.5, 31.0]" in out
    assert "西经, 南纬, 东经, 北纬" in out


def test_annotate_noop_without_match(gz: Gazetteer) -> None:
    q = "计算经度 103.2 到 103.5、纬度 29.4 到 29.7的坡向"
    assert gz.annotate(q) == q


def test_upsert_and_reload(gz: Gazetteer) -> None:
    before = len(gz)
    gz.upsert("测试山", 100.0, 30.0, 100.5, 30.5, kind="mountain")
    assert len(gz) == before + 1
    assert gz.resolve_bbox("测试山") == [100.0, 30.0, 100.5, 30.5]


def test_query_does_not_mutate_user_text(gz: Gazetteer) -> None:
    """annotate 返回新字符串，不改入参，避免调用方被隐式修改。"""
    q = "泰山的坡度"
    gz.annotate(q)
    assert q == "泰山的坡度"
