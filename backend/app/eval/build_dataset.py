"""构造 GeoAgent 中文地理空间任务评测集（100 条）。

为什么用脚本生成而不是手写 JSON：

1. bbox 的 [west, south, east, north] 顺序极易写错，手写 100 条必然出错。
   这里所有 bbox 都来自 REGIONS 常量表，由 validate_dataset() 统一校验。
2. 同一语义要覆盖多种中文表述（"坡度多少"/"哪里陡"/"能不能走"），
   用模板 × 地名实例化比手写更可控、也更易扩充。
3. 生成结果落盘为 dataset.json，评测脚本只读 JSON，保证"数据"与"代码"分离，
   评测结果可复现（换模型跑同一份数据）。

三类样本（与 IMPROVEMENT_PLAN.md 第五节同源）：
    单工具 40 / 多工具串联 40 / 越界拒答 20
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

# ── 地名 → 真实经纬度包围盒 [west, south, east, north] ──────────────
# 全部为国内真实地理范围，便于人工核对与面试讲解。
REGIONS: Dict[str, List[float]] = {
    "成都周边": [103.5, 30.2, 104.5, 31.0],
    "都江堰": [103.4, 30.9, 103.8, 31.2],
    "四姑娘山": [102.8, 30.9, 103.2, 31.2],
    "贡嘎山": [101.6, 29.4, 102.0, 29.8],
    "峨眉山": [103.2, 29.4, 103.5, 29.7],
    "雅安": [102.8, 29.8, 103.2, 30.2],
    "西安": [108.7, 34.0, 109.2, 34.5],
    "秦岭": [107.5, 33.5, 108.5, 34.2],
    "兰州": [103.5, 35.9, 104.0, 36.3],
    "昆明": [102.4, 24.8, 102.9, 25.3],
    "玉龙雪山": [100.1, 27.0, 100.3, 27.2],
    "拉萨": [90.8, 29.5, 91.3, 30.0],
    "珠峰": [86.8, 27.9, 87.0, 28.1],
    "张家界": [110.3, 29.2, 110.6, 29.5],
    "泰山": [117.0, 36.2, 117.3, 36.4],
    "黄山": [118.1, 30.1, 118.3, 30.3],
    "三峡": [110.0, 30.8, 111.0, 31.2],
    "横断山": [99.0, 28.0, 100.5, 29.5],
    "塔克拉玛干": [83.0, 38.5, 85.0, 40.0],
    "锡林郭勒草原": [116.0, 43.0, 117.5, 44.0],
}

# 工具层定义的合法工具名（与 backend/app/tools/registry.py 保持一致）
VALID_TOOLS = {
    "get_dem_metadata", "download_srtm", "compute_slope", "compute_aspect",
    "compute_curvature", "compute_cost_surface", "plan_route",
    "classify_terrain_rules", "classify_geomorphons", "classify_terrain_onnx",
    "zonal_statistics",
}


def _bbox_text(bbox: List[float]) -> str:
    """把 bbox 转成中文口语表述，用于 query 文本。"""
    w, s, e, n = bbox
    return f"经度 {w} 到 {e}、纬度 {s} 到 {n}"


# ── 单工具模板 ────────────────────────────────────────────────────
# 每项：(工具名, query 模板列表)。{r}=地名，{b}=bbox 文本
SINGLE_TEMPLATES: List[Tuple[str, List[str]]] = [
    ("compute_slope", [
        "计算{r}的坡度",
        "{r}这一带的坡度是多少",
        "帮我算一下{r}范围内每个位置的坡度",
        "{r}哪里比较陡",
        "分析{r}的坡度分布",
        "我想知道{r}的地形陡不陡，给个坡度图",
        "{r}的坡度情况怎么样",
        "算{r}的坡度栅格",
    ]),
    ("compute_aspect", [
        "计算{r}的坡向",
        "{r}的山坡主要朝向哪边",
        "{r}哪些是阴坡哪些是阳坡",
        "分析{r}的坡向分布",
        "{r}的朝向情况如何",
    ]),
    ("compute_curvature", [
        "计算{r}的曲率",
        "{r}哪里是山脊",
        "{r}哪里是沟谷",
        "分析{r}的曲率，区分山脊和沟谷",
    ]),
    ("compute_cost_surface", [
        "计算{r}的通行代价",
        "{r}哪里好走",
        "分析{r}的通行难度",
        "{r}的越野通行性怎么样",
        "生成{r}的通行代价栅格",
    ]),
    ("classify_terrain_rules", [
        "用规则法对{r}做地貌分类",
        "{r}的地貌类型有哪些，快速筛查一下",
        "对{r}用地形规则做地貌分类",
    ]),
    ("classify_geomorphons", [
        "用 Geomorphons 算法对{r}做地貌分类",
        "{r}的地貌怎么分类",
        "对{r}做地貌分类，用精度高一点的方法",
        "{r}属于什么地貌类型",
    ]),
    ("classify_terrain_onnx", [
        "用 ONNX 模型对{r}做地貌分类",
        "{r}用深度学习模型分类地貌",
        "调用 CNN 模型对{r}做地貌分类",
    ]),
    ("zonal_statistics", [
        "统计{r}的坡度分级情况",
        "{r}有多少面积可以通行",
        "统计{r}多少比例的坡度在15度以下",
        "{r}的高程分布怎么统计",
        "对{r}的坡度做分区统计",
    ]),
    ("get_dem_metadata", [
        "检查一下这个 DEM 文件能不能用：{d}",
        "读取 DEM 元信息：{d}",
        "看看 {d} 这个 DEM 的坐标系和分辨率",
    ]),
]

# 单工具样本使用的地名序列（保证 40 条且覆盖多个区域）
SINGLE_REGION_ROTATION = [
    "成都周边", "四姑娘山", "秦岭", "贡嘎山", "张家界", "黄山", "泰山",
    "雅安", "峨眉山", "都江堰", "三峡", "横断山", "玉龙雪山", "拉萨",
    "珠峰", "西安", "兰州", "昆明", "锡林郭勒草原", "塔克拉玛干",
]

DEM_SAMPLE_PATHS = [
    "data/dem/srtm_chengdu.tif",
    "data/dem/srtm_qinling.tif",
    "data/dem/gdem_kunming.tif",
]

# ── 多工具串联模板 ─────────────────────────────────────────────────
# 每项：(工具序列, query 模板列表)
MULTI_TEMPLATES: List[Tuple[List[str], List[str]]] = [
    (["download_srtm", "compute_slope"], [
        "下载{r}的真实高程数据并计算坡度",
        "我没有{r}的 DEM 文件，先下数据再算坡度",
        "获取{r}的 SRTM 数据然后算坡度",
        "{r}的坡度，用真实 DEM 数据算",
        "先下载{r}高程数据，再分析那里的坡度",
    ]),
    (["compute_slope", "zonal_statistics"], [
        "算{r}的坡度，然后统计有多少面积车辆能走",
        "{r}的坡度分布如何，能通行的面积占多少",
        "计算{r}坡度并做分区统计",
        "{r}有多少地方坡度在15度以下",
        "分析{r}的坡度，给出可通行面积比例",
        "统计{r}的坡度分级占比",
    ]),
    (["compute_slope", "compute_cost_surface", "plan_route"], [
        "从 A 到 B 规划一条坡度小于15度的路线，范围是{r}",
        "{r}内帮我找一条越野路线，要避开陡坡",
        "规划{r}内的通行路径，尽量走缓坡",
        "{r}从西边到东边怎么走最省力",
        "在{r}找一条适合车辆通行的路线",
        "{r}内两点之间的最优越野路径",
        "帮我规划{r}的穿越路线，考虑坡度代价",
        "{r}里从山脚到山顶怎么走",
        "设计一条{r}的徒步路线，绕开陡崖",
    ]),
    (["download_srtm", "compute_slope", "classify_geomorphons"], [
        "下载{r}的 DEM，算坡度，再做地貌分类",
        "{r}没数据，先下高程再用地貌分类",
        "获取{r}真实地形数据并分类地貌类型",
        "{r}的地貌分析，用真实 DEM 数据",
        "下载{r}高程数据，分析坡度并分类地貌",
    ]),
    (["download_srtm", "compute_cost_surface", "plan_route"], [
        "下载{r}高程数据并规划一条越野路线",
        "{r}没有 DEM，先下数据再规划路径",
        "获取{r}的地形数据，然后找一条好走的路",
        "{r}的通行路线规划，需要真实高程",
        "下载{r}数据，构建代价场并规划路径",
    ]),
    (["compute_slope", "classify_terrain_rules"], [
        "算{r}的坡度，然后用地貌规则分类",
        "{r}先算坡度再判断地貌类型",
        "分析{r}坡度并做地貌分类",
        "{r}的坡度算出来后分类地形",
        "计算{r}坡度，再做地形形态分类",
    ]),
    (["download_srtm", "compute_slope", "zonal_statistics"], [
        "下载{r}的高程数据，算坡度，再统计可通行面积",
        "{r}没有 DEM，先下数据算坡度再统计通行比例",
        "获取{r}真实地形，计算坡度并统计有多少能走",
        "{r}的坡度统计，需要真实 DEM 数据",
        "下载{r}数据，算坡度并给出车辆可通行面积占比",
    ]),
]

MULTI_REGION_ROTATION = [
    "四姑娘山", "秦岭", "贡嘎山", "横断山", "三峡", "张家界",
    "峨眉山", "玉龙雪山", "黄山", "泰山", "雅安", "都江堰",
    "成都周边", "拉萨", "珠峰", "西安", "兰州", "昆明",
    "锡林郭勒草原", "塔克拉玛干",
]

# ── 越界 / 拒答样本 ────────────────────────────────────────────────
# 这些请求超出 GeoAgent 能力范围，正确行为是拒答（不调用任何工具）
OUT_OF_SCOPE_QUERIES = [
    "明天成都天气怎么样",
    "预测下周北京的降雨量",
    "分析一下火星表面的地形",
    "帮我看看今天A股大盘走势",
    "把这段英文翻译成法语",
    "用 Python 写一个快速排序",
    "推荐几本机器学习入门书",
    "感冒了应该吃什么药",
    "这份合同有没有法律风险",
    "帮我订一张去上海的机票",
    "计算圆的面积公式是什么",
    "讲一下二战的历史背景",
    "这首歌叫什么名字",
    "怎么做红烧肉",
    "帮我算一下个人所得税",
    "分析月球背面的地貌类型",
    "预测明年房价走势",
    "帮我写一封辞职信",
    "这个bug怎么修，我的代码跑不起来了",
    "金星表面的坡度是多少",
]


def build() -> List[Dict[str, Any]]:
    """生成完整评测集。"""
    cases: List[Dict[str, Any]] = []

    # ---- 类别 1：单工具 40 条 ----
    idx = 0
    for tool, templates in SINGLE_TEMPLATES:
        for tpl in templates:
            region = SINGLE_REGION_ROTATION[idx % len(SINGLE_REGION_ROTATION)]
            idx += 1
            bbox = REGIONS[region]
            if "{d}" in tpl:
                dem = DEM_SAMPLE_PATHS[idx % len(DEM_SAMPLE_PATHS)]
                query = tpl.format(d=dem)
                expected_params: Dict[str, Any] = {"dem_path": dem}
            else:
                query = tpl.format(r=region)
                expected_params = {"bbox": bbox}
                # 30% 的样本改用坐标表述，考察模型对纯数字 bbox 的理解
                if idx % 3 == 0:
                    query = tpl.format(r=_bbox_text(bbox))
            cases.append({
                "id": f"single_{len(cases) + 1:03d}",
                "category": "single_tool",
                "query": query,
                "expected_tools": [tool],
                "expected_params": expected_params,
                "must_refuse": False,
                "region": region if "{d}" not in tpl else None,
            })

    # ---- 类别 2：多工具串联 40 条 ----
    midx = 0
    for tools, templates in MULTI_TEMPLATES:
        for tpl in templates:
            region = MULTI_REGION_ROTATION[midx % len(MULTI_REGION_ROTATION)]
            midx += 1
            bbox = REGIONS[region]
            cases.append({
                "id": f"multi_{len(cases) - 39:03d}",
                "category": "multi_tool",
                "query": tpl.format(r=region),
                "expected_tools": tools,
                "expected_params": {"bbox": bbox},
                "must_refuse": False,
                "region": region,
            })

    # ---- 类别 3：越界拒答 20 条 ----
    for i, q in enumerate(OUT_OF_SCOPE_QUERIES, 1):
        cases.append({
            "id": f"refuse_{i:03d}",
            "category": "out_of_scope",
            "query": q,
            "expected_tools": [],
            "expected_params": {},
            "must_refuse": True,
            "region": None,
        })

    return cases


def validate(cases: List[Dict[str, Any]]) -> List[str]:
    """校验评测集，返回问题列表（空列表表示全部合法）。

    校验项：
        1. 工具名必须在 VALID_TOOLS 中
        2. bbox 必须是 4 元数组且 west<east、south<north
        3. 数量必须为 100，且三类分别为 40/40/20
        4. id 不可重复
    """
    problems: List[str] = []

    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        problems.append(f"存在重复 id：共 {len(ids)} 条，去重后 {len(set(ids))} 条")

    for c in cases:
        for t in c["expected_tools"]:
            if t not in VALID_TOOLS:
                problems.append(f"{c['id']}: 非法工具名 {t!r}")
        bbox = c["expected_params"].get("bbox")
        if bbox is not None:
            if not (isinstance(bbox, list) and len(bbox) == 4):
                problems.append(f"{c['id']}: bbox 必须是 4 元数组，实际 {bbox!r}")
                continue
            w, s, e, n = bbox
            if not (w < e):
                problems.append(f"{c['id']}: bbox 经度顺序错误 west={w} east={e}")
            if not (s < n):
                problems.append(f"{c['id']}: bbox 纬度顺序错误 south={s} north={n}")

    counts: Dict[str, int] = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    expect = {"single_tool": 40, "multi_tool": 40, "out_of_scope": 20}
    for k, v in expect.items():
        if counts.get(k) != v:
            problems.append(f"类别 {k} 数量应为 {v}，实际 {counts.get(k, 0)}")

    return problems


def main() -> None:
    cases = build()
    problems = validate(cases)
    if problems:
        print("评测集校验未通过：")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)

    out = os.path.join(os.path.dirname(__file__), "dataset.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    counts: Dict[str, int] = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    print(f"已生成 {len(cases)} 条评测集 → {out}")
    print("类别分布：", counts)


if __name__ == "__main__":
    main()
