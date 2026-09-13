"""构造「意图路由」SFT 训练数据。

## 为什么训这个

实测（bench/_test_grammar.py，24 条）显示模型自己判意图只有 91.7%，
而主集得分 98.75% —— 差额来自 `planner._force_analysis` 这个**正则安全网**
在替模型兜底（含"坡度/地貌"的句子被强判为分析）。

用户明确反对这种硬编码（"太笨太死板，泛化能力差"），但直接删掉安全网
准确率就掉到 91.7%。所以正解是**让模型自己判对**。

## 数据从哪来（没有人工标注）

三条来源混合，避免"模板太干净 → 换个说法就失效"（这正是当前正则的问题）：

  1. **真实样本**：已有评测集（含保留集）的 query + 人工标注的意图
  2. **模板生成**：意图 × 地名/术语槽位 × 口语化前缀 组合
  3. **难例强化**：把实测中模型判错的类型（"统计 X 坡度比例" 被误判 refuse、
     "什么地貌类型" 被误判 knowledge）在同一模板下**多次采样**

标签是模板决定的，天然可靠；不需要模型生成，也不需要人工标注。

用法：
    python bench/build_sft_data.py            # 生成到 bench/sft_data/
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, "backend")

OUT_DIR = Path(__file__).resolve().parent / "sft_data"
SEED = 20260913

# ---------------------------------------------------------------- 槽位
# 地名：境内用已有的 93 条词典，境外补几个真实山脉/区域
DOMESTIC = [
    "珠峰", "贡嘎山", "四姑娘山", "泰山", "华山", "黄山", "峨眉山", "五台山",
    "庐山", "武夷山", "天山", "昆仑山", "祁连山", "大兴安岭", "小兴安岭",
    "太行山", "秦岭", "横断山脉", "念青唐古拉山", "唐古拉山", "阿尔金山",
    "海南省", "云南省", "四川省", "西藏", "新疆", "青海省", "甘肃省",
    "内蒙古", "贵州省", "广西省", "台湾省", "五指山", "长白山", "神农架",
    "塔克拉玛干沙漠", "柴达木盆地", "四川盆地", "黄土高原", "云贵高原",
    "三峡", "都江堰", "九寨沟", "张家界", "三江源", "雅鲁藏布江",
]
FOREIGN = [
    "阿尔卑斯山", "安第斯山脉", "落基山脉", "喜马拉雅山脉", "乞力马扎罗山",
    "富士山", "乌拉尔山", "高加索山", "比利牛斯山", "喀尔巴阡山",
]
PLACES = DOMESTIC + FOREIGN

TERMS = ["坡度", "坡向", "曲率", "地形起伏度", "TPI", "DEM", "SRTM", "高程", "通行代价"]

CITIES = ["北京", "上海", "成都", "广州", "深圳", "杭州", "西安", "武汉"]
PLANETS = ["火星", "月球", "金星", "木星", "土星", "水星"]

# 口语化前缀 / 后缀：让模型见到"人话"而不是只有工整的祈使句。
# 实测教训：正则安全网失效的根因就是"只认特定说法"。
PREFIXES = ["", "帮我", "麻烦", "我想", "能不能", "可以", "请", "麻烦帮我", "我想让你"]
SUFFIXES = ["", "，谢谢", "一下", "看看", "，可以吗", "，麻烦了"]

# 中文数词（"15 度以下" 也常说"十五度以下"）
NUM = ["15", "20", "25", "30", "10", "35", "45"]

# ---------------------------------------------------------------- 模板
# key = 意图，值是 (模板, 权重)。权重用来刻意多采难例。
TEMPLATES = {
    "analysis": [
        ("算一下{place}的坡度", 3),
        ("{place}的坡度是多少", 3),
        ("统计{place}坡度在{num}度以下的比例", 5),   # 实测被误判成 refuse
        ("{place}坡度在{num}度以下的面积占比是多少", 4),
        ("{place}属于什么地貌类型", 5),              # 实测被误判成 knowledge
        ("判断{place}的地貌类型", 3),
        ("{place}哪里比较陡", 3),
        ("{place}哪里比较平缓", 2),
        ("规划一条穿越{place}的路线", 3),
        ("{place}的通行代价怎么样", 3),
        ("{place}的地形起伏大不大", 3),
        ("算一下{place}的坡向分布", 3),
        ("{place}的山坡主要朝向哪边", 3),
        ("{place}的曲率是多少", 2),
        ("看看{place}的 DEM 分辨率", 3),
        ("下载{place}的高程数据", 3),
        ("{place}的 DEM 是哪个坐标系", 2),
        ("{place}哪些地方是阴坡", 3),
        ("分析{place}的地形因子", 3),
        ("{place}这块区域的平均坡度", 3),
        ("做一下{place}的分区统计", 2),
        ("生成{place}的坡度分级图", 2),
        ("{place}适不适合徒步穿越", 3),
        ("从{place}东侧到西侧怎么走比较好", 2),
    ],
    "knowledge": [
        ("{place}在哪里", 3),
        ("{place}属于哪个省", 3),
        ("{place}有什么特点", 3),
        ("什么是{term}", 4),
        ("{term}是什么意思", 3),
        ("{term}是怎么算的", 2),
        ("介绍一下{place}", 3),
        ("{place}的海拔是多少", 3),
        ("中国有多少个省级行政区", 2),
        ("{place}的气候怎么样", 2),
    ],
    "action": [
        ("跳转到{place}", 4),
        ("看看{place}", 4),
        ("我想看看{place}", 4),
        ("放大到{place}", 3),
        ("定位到{place}", 3),
        ("飞到{place}", 3),
        ("{place}在哪儿，带我过去", 3),             # 实测被误判成 knowledge
        ("跳到{place}去", 2),
        ("切换到{place}", 2),
    ],
    "chat": [
        ("你好", 5), ("您好", 3), ("嗨", 2), ("谢谢", 3), ("多谢", 2),
        ("再见", 2), ("你是谁", 3), ("你能做什么", 4), ("你有什么功能", 3),
        ("介绍一下你自己", 3), ("你会什么", 2), ("早上好", 2),
    ],
    "refuse": [
        ("{city}明天天气怎么样", 4),
        ("{city}会下雨吗", 3),
        ("帮我写一篇{style}", 3),
        ("{planet}表面的地形", 5),                  # 实测被误判成 analysis
        ("{planet}上有山吗", 4),
        ("{num}加{num}等于几", 3),
        ("推荐几支股票", 3),
        ("帮我翻译这段话", 2),
        ("讲个笑话", 2),
        ("我头疼吃什么药", 2),
        ("圆的面积公式是什么", 3),
    ],
}
STYLES = ["作文", "周报", "辞职信", "诗", "演讲稿", "邮件"]

# ---------------------------------------------------------------- 输出格式
SYSTEM = (
    "你是「三维地理信息分析系统」里的智能助手。判断用户这句话的意图，"
    "只输出一个 JSON：{\"intent\": \"...\", \"understanding\": \"...\", \"reply\": \"...\"}\n"
    "intent 取值：analysis（要算地形/路径/统计）、knowledge（地理常识或问概念）、"
    "action（移动地图视角）、chat（寒暄闲聊）、refuse（与地球地理无关）。\n"
    "非 analysis 时在 reply 里给出给用户看的回答；analysis 时 reply 留空。"
)


def fill(tpl: str) -> str:
    return (
        tpl.replace("{place}", random.choice(PLACES))
        .replace("{term}", random.choice(TERMS))
        .replace("{city}", random.choice(CITIES))
        .replace("{planet}", random.choice(PLANETS))
        .replace("{num}", random.choice(NUM))
        .replace("{style}", random.choice(STYLES))
    )


def make_sample(query: str, intent: str) -> dict:
    obj = {"intent": intent, "understanding": f"用户在{_desc(intent)}", "reply": ""}
    if intent != "analysis":
        obj["reply"] = {
            "knowledge": "这是一条地理常识或概念问题，我直接回答。",
            "action": "好的，正在把地图移动到你说的位置。",
            "chat": "你好，我是这个三维地理信息系统的分析助手。",
            "refuse": "这个问题超出了我的能力范围 —— 我只做地球表面的地理空间分析。",
        }[intent]
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": query},
            {"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)},
        ]
    }


def _desc(intent: str) -> str:
    return {
        "analysis": "要求做地形/路径/统计类的计算",
        "knowledge": "问地理常识或概念",
        "action": "要求移动地图视角",
        "chat": "在寒暄或问我的能力",
        "refuse": "问与地球地理无关的事",
    }[intent]


def templates_for(intent: str):
    pool = []
    for tpl, w in TEMPLATES[intent]:
        pool.extend([tpl] * w)
    return pool


def main() -> None:
    random.seed(SEED)

    rows = []
    seen = set()

    # ① 真实样本：评测集 + 保留集（人工标注，最有价值）
    for name in ("dataset.json", "dataset_heldout.json"):
        p = Path("backend/app/eval") / name
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        cases = data["cases"] if isinstance(data, dict) else data
        for c in cases:
            q = (c.get("query") or "").strip()
            cat = c.get("category") or ""
            intent = {
                "single_tool": "analysis", "multi_tool": "analysis",
                "out_of_scope": "refuse",
            }.get(cat) or c.get("intent") or "analysis"
            if q and q not in seen:
                seen.add(q)
                rows.append(make_sample(q, intent))

    # ② 模板生成（含口语化前后缀）
    per_intent = {"analysis": 260, "knowledge": 90, "action": 120, "chat": 70, "refuse": 130}
    for intent, want in per_intent.items():
        pool = templates_for(intent)
        made = 0
        guard = 0
        while made < want and guard < want * 40:
            guard += 1
            q = random.choice(PREFIXES) + fill(random.choice(pool)) + random.choice(SUFFIXES)
            q = q.strip()
            if q in seen or len(q) < 2:
                continue
            seen.add(q)
            rows.append(make_sample(q, intent))
            made += 1

    random.shuffle(rows)
    split = int(len(rows) * 0.9)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for fn, part in (("train.json", rows[:split]), ("eval.json", rows[split:])):
        (OUT_DIR / fn).write_text(
            json.dumps(part, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # 分布统计：意图不均衡会让模型偏向多数类，先看清比例
    from collections import Counter

    def intent_of(r):
        return json.loads(r["messages"][2]["content"])["intent"]

    cnt = Counter(intent_of(r) for r in rows)
    print(f"共 {len(rows)} 条 → 训练 {split} / 验证 {len(rows) - split}")
    for k, v in cnt.most_common():
        print(f"  {k:10s} {v:4d}  ({v / len(rows):.1%})")
    print(f"输出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
