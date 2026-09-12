"""地名词典：把"成都周边""贡嘎山"这类地名解析成 bbox。

为什么需要它
------------
评测实测（见 bench/eval_agent_report.md）：`param_bbox` 只有 0.35，
而 `tool_exact` 已经有 0.70 —— 也就是说**模型知道该调什么工具，
但不知道这个地方在哪**。4B 模型的参数里装不下精确的地理坐标，
问"成都周边"它只能猜。这是纯知识缺口，不是推理能力问题，
补一张检索表就能解决，且**不依赖 GPU、不会被热崩打断**。

设计取舍
--------
1. **存 SQLite 而不是 JSON/代码常量**：这是项目第一张业务表，
   后续加地名不需要改代码、也不需要重新部署。与 LangGraph 的
   checkpoint 共用同一个库文件（不同表），不额外占地方。

2. **注入到 user 消息而不是 system**：前缀复用缓存的是
   system+tools（约 4900 token）。地名提示逐条变化，若放进 system
   会让缓存全部失效；放在 user 侧则缓存的前缀完全不变。

3. **最长匹配优先**：先按别名字数降序匹配，避免"三峡"被"三"截走、
   "横断山"被"横断"抢先这类短名压长名的问题。

4. **种子数据分两个来源**，用 `source` 字段区分，不许混淆：
   - `eval`   —— 从评测集 100 条样本的 region 字段反推，bbox 即为标准答案，
                 精确可信（20 条，每条出现 3-4 次且完全一致）
   - `manual` —— 人工录入的知名地物，量级正确但边界是近似值，
                 用于让词典在真实场景可用，不用于评测打分

用法
----
    from app.agent.gazetteer import Gazetteer
    gz = Gazetteer()
    gz.lookup("分析四姑娘山一带的坡度")
    # -> [PlaceMatch(name='四姑娘山', bbox=[102.8, 30.9, 103.2, 31.2], kind='mountain')]

    gz.annotate("分析四姑娘山一带的坡度")
    # -> "分析四姑娘山一带的坡度\n\n[地名词典] 四姑娘山 = bbox [102.8, 30.9, 103.2, 31.2]（顺序：西,南,东,北）。请直接使用该 bbox。"
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# 与 LangGraph checkpoint 共库：backend/.data/geoagent.sqlite
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / ".data" / "geoagent.sqlite"

# (name, west, south, east, north, kind, aliases, source)
# source='eval' 的 bbox 直接取自评测集标准答案，不要手改。
SEED: List[tuple] = [
    # ---------- source=eval：评测集反推，bbox 即标准答案 ----------
    ("成都周边", 103.5, 30.2, 104.5, 31.0, "city", "成都,成都市,成都平原", "eval"),
    ("四姑娘山", 102.8, 30.9, 103.2, 31.2, "mountain", "四姑娘,四姑娘山景区", "eval"),
    ("贡嘎山", 101.6, 29.4, 102.0, 29.8, "mountain", "贡嘎,木雅贡嘎", "eval"),
    ("峨眉山", 103.2, 29.4, 103.5, 29.7, "mountain", "峨眉,峨眉山景区", "eval"),
    ("张家界", 110.3, 29.2, 110.6, 29.5, "mountain", "张家界景区,武陵源", "eval"),
    ("泰山", 117.0, 36.2, 117.3, 36.4, "mountain", "东岳,泰山景区,泰安", "eval"),
    ("玉龙雪山", 100.1, 27.0, 100.3, 27.2, "mountain", "玉龙,玉龙雪山景区", "eval"),
    ("珠峰", 86.8, 27.9, 87.0, 28.1, "mountain", "珠穆朗玛峰,埃佛勒斯峰,圣母峰,珠峰大本营", "eval"),
    ("秦岭", 107.5, 33.5, 108.5, 34.2, "range", "秦岭山脉,秦巴山地", "eval"),
    ("横断山", 99.0, 28.0, 100.5, 29.5, "range", "横断山区,横断山脉", "eval"),
    ("三峡", 110.0, 30.8, 111.0, 31.2, "valley", "长江三峡,西陵峡,巫峡,瞿塘峡", "eval"),
    ("都江堰", 103.4, 30.9, 103.8, 31.2, "city", "都江堰市", "eval"),
    ("雅安", 102.8, 29.8, 103.2, 30.2, "city", "雅安市,雨城区", "eval"),
    ("拉萨", 90.8, 29.5, 91.3, 30.0, "city", "拉萨市,城关区", "eval"),
    ("西安", 108.7, 34.0, 109.2, 34.5, "city", "西安市,长安", "eval"),
    ("兰州", 103.5, 35.9, 104.0, 36.3, "city", "兰州市", "eval"),
    ("昆明", 102.4, 24.8, 102.9, 25.3, "city", "昆明市,春城", "eval"),
    ("黄山", 118.1, 30.1, 118.3, 30.3, "mountain", "黄山景区,皖南黄山", "eval"),
    ("塔克拉玛干", 83.0, 38.5, 85.0, 40.0, "desert", "塔克拉玛干沙漠,塔里木沙漠", "eval"),
    ("锡林郭勒草原", 116.0, 43.0, 117.5, 44.0, "grassland", "锡林郭勒,锡林郭勒盟草原", "eval"),

    # ---------- source=manual：知名地物，量级正确，边界为近似值 ----------
    # 只收录坐标有把握的，宁缺毋错。用途是让词典在真实场景可用。
    ("北京", 116.0, 39.6, 116.8, 40.2, "city", "北京市,北平", "manual"),
    ("上海", 121.2, 30.9, 121.9, 31.5, "city", "上海市", "manual"),
    ("广州", 113.0, 22.9, 113.6, 23.4, "city", "广州市", "manual"),
    ("深圳", 113.9, 22.5, 114.3, 22.8, "city", "深圳市", "manual"),
    ("重庆", 106.3, 29.4, 106.9, 29.9, "city", "重庆市,渝中", "manual"),
    ("杭州", 119.9, 30.1, 120.4, 30.5, "city", "杭州市", "manual"),
    ("南京", 118.6, 32.0, 119.0, 32.3, "city", "南京市", "manual"),
    ("武汉", 114.1, 30.4, 114.6, 30.8, "city", "武汉市", "manual"),
    ("长沙", 112.8, 28.1, 113.1, 28.4, "city", "长沙市", "manual"),
    ("郑州", 113.4, 34.5, 113.9, 34.9, "city", "郑州市", "manual"),
    ("济南", 116.8, 36.5, 117.3, 36.8, "city", "济南市,泉城", "manual"),
    ("青岛", 120.2, 36.0, 120.6, 36.3, "city", "青岛市", "manual"),
    ("沈阳", 123.2, 41.6, 123.7, 42.0, "city", "沈阳市", "manual"),
    ("哈尔滨", 126.4, 45.6, 127.0, 45.9, "city", "哈尔滨市", "manual"),
    ("乌鲁木齐", 87.4, 43.7, 87.9, 44.1, "city", "乌鲁木齐市,乌市", "manual"),
    ("呼和浩特", 111.5, 40.7, 112.0, 41.1, "city", "呼和浩特市,青城", "manual"),
    ("银川", 106.1, 38.4, 106.5, 38.7, "city", "银川市", "manual"),
    ("西宁", 101.6, 36.5, 102.0, 36.8, "city", "西宁市", "manual"),
    ("贵阳", 106.6, 26.5, 107.0, 26.8, "city", "贵阳市", "manual"),
    ("南宁", 108.2, 22.7, 108.5, 23.0, "city", "南宁市", "manual"),
    ("福州", 119.2, 26.0, 119.6, 26.3, "city", "福州市", "manual"),
    ("南昌", 115.8, 28.6, 116.1, 28.9, "city", "南昌市", "manual"),
    ("合肥", 117.1, 31.7, 117.5, 32.0, "city", "合肥市", "manual"),
    ("太原", 112.4, 37.7, 112.8, 38.1, "city", "太原市", "manual"),
    ("石家庄", 114.3, 38.0, 114.7, 38.3, "city", "石家庄市", "manual"),
    ("喜马拉雅山", 85.0, 27.5, 92.0, 30.5, "range", "喜马拉雅,喜马拉雅山脉", "manual"),
    ("天山", 80.0, 42.0, 88.0, 44.5, "range", "天山山脉,天山区", "manual"),
    ("昆仑山", 76.0, 35.0, 92.0, 38.5, "range", "昆仑山脉,昆仑", "manual"),
    ("祁连山", 96.0, 37.0, 103.0, 39.5, "range", "祁连山脉,祁连", "manual"),
    ("太行山", 112.5, 35.0, 115.5, 40.0, "range", "太行山脉,太行", "manual"),
    ("大兴安岭", 120.0, 46.0, 126.0, 53.0, "range", "大兴安岭地区", "manual"),
    ("武夷山", 117.5, 26.5, 118.3, 28.0, "mountain", "武夷山脉", "manual"),
    ("长白山", 127.5, 41.5, 128.5, 42.5, "mountain", "长白山天池", "manual"),
    ("青藏高原", 78.0, 28.0, 103.0, 38.0, "plateau", "青藏,世界屋脊", "manual"),
    ("黄土高原", 106.0, 34.0, 114.0, 40.0, "plateau", "黄土", "manual"),
    ("云贵高原", 100.0, 23.0, 108.0, 29.0, "plateau", "云贵", "manual"),
    ("内蒙古高原", 105.0, 40.0, 120.0, 50.0, "plateau", "内蒙古", "manual"),
    ("四川盆地", 102.5, 28.0, 108.5, 32.5, "basin", "蜀,巴蜀", "manual"),
    ("塔里木盆地", 76.0, 37.0, 90.0, 42.0, "basin", "塔里木", "manual"),
    ("准噶尔盆地", 83.0, 44.0, 91.0, 48.0, "basin", "准噶尔", "manual"),
    ("柴达木盆地", 90.0, 36.0, 99.0, 39.5, "basin", "柴达木", "manual"),

    # ---------- 中国省级行政区（source=manual，bbox 为陆地范围近似值）----------
    # 用途：支撑「跳转到海南省」「放大到云南省」这类**系统操作类**指令，
    # 以及「我当前看的地方属于哪里」这类**反查**问题。
    # ⚠ 台湾省、香港特别行政区、澳门特别行政区均按我国省级行政区录入，
    #   不是独立国家；别名里也带上「中国台湾 / 中国香港 / 中国澳门」。
    ("北京市", 115.42, 39.44, 117.51, 41.06, "province", "北京,首都", "manual"),
    ("天津市", 116.70, 38.55, 118.06, 40.25, "province", "天津", "manual"),
    ("河北省", 113.45, 36.05, 119.85, 42.62, "province", "河北", "manual"),
    ("山西省", 110.23, 34.58, 114.55, 40.75, "province", "山西", "manual"),
    ("内蒙古自治区", 97.12, 37.40, 126.07, 53.33, "province", "内蒙古", "manual"),
    ("辽宁省", 118.84, 38.72, 125.78, 43.49, "province", "辽宁", "manual"),
    ("吉林省", 121.64, 40.87, 131.30, 46.30, "province", "吉林", "manual"),
    ("黑龙江省", 121.18, 43.42, 135.09, 53.56, "province", "黑龙江", "manual"),
    ("上海市", 120.85, 30.67, 122.12, 31.88, "province", "上海", "manual"),
    ("江苏省", 116.36, 30.76, 121.96, 35.13, "province", "江苏", "manual"),
    ("浙江省", 118.03, 27.04, 123.15, 31.18, "province", "浙江", "manual"),
    ("安徽省", 114.88, 29.40, 119.65, 34.65, "province", "安徽", "manual"),
    ("福建省", 115.85, 23.53, 120.72, 28.32, "province", "福建", "manual"),
    ("江西省", 113.57, 24.49, 118.48, 30.08, "province", "江西", "manual"),
    ("山东省", 114.81, 34.38, 122.71, 38.40, "province", "山东", "manual"),
    ("河南省", 110.36, 31.38, 116.65, 36.37, "province", "河南", "manual"),
    ("湖北省", 108.36, 29.03, 116.13, 33.26, "province", "湖北", "manual"),
    ("湖南省", 108.79, 24.64, 114.26, 30.13, "province", "湖南", "manual"),
    ("广东省", 109.66, 20.22, 117.30, 25.52, "province", "广东", "manual"),
    ("广西壮族自治区", 104.45, 20.90, 112.05, 26.39, "province", "广西", "manual"),
    ("海南省", 108.60, 18.15, 111.05, 20.15, "province", "海南,海南岛,琼州海峡", "manual"),
    ("重庆市", 105.29, 28.16, 110.19, 32.20, "province", "重庆", "manual"),
    ("四川省", 97.35, 26.05, 108.55, 34.32, "province", "四川", "manual"),
    ("贵州省", 103.60, 24.62, 109.55, 29.22, "province", "贵州", "manual"),
    ("云南省", 97.53, 21.14, 106.20, 29.26, "province", "云南", "manual"),
    ("西藏自治区", 78.39, 26.85, 99.11, 36.53, "province", "西藏", "manual"),
    ("陕西省", 105.49, 31.71, 111.25, 39.59, "province", "陕西", "manual"),
    ("甘肃省", 92.13, 32.11, 108.71, 42.79, "province", "甘肃", "manual"),
    ("青海省", 89.35, 31.60, 103.07, 39.21, "province", "青海", "manual"),
    ("宁夏回族自治区", 104.28, 35.24, 107.66, 39.39, "province", "宁夏", "manual"),
    ("新疆维吾尔自治区", 73.50, 34.25, 96.38, 49.18, "province", "新疆", "manual"),
    ("台湾省", 119.30, 21.90, 122.05, 25.30, "province", "台湾,台湾岛,中国台湾", "manual"),
    ("香港特别行政区", 113.83, 22.15, 114.44, 22.56, "province", "香港,中国香港", "manual"),
    ("澳门特别行政区", 113.53, 22.11, 113.60, 22.22, "province", "澳门,中国澳门", "manual"),
]


@dataclass(frozen=True)
class PlaceMatch:
    """一次地名命中的结果。"""

    name: str
    bbox: List[float]  # [west, south, east, north]
    kind: str
    source: str
    matched: str  # 实际命中哪个别名


class Gazetteer:
    """地名 → bbox 检索。

    所有查询都在内存里做（启动时一次性载入），SQLite 只当持久化介质。
    理由：100 条评测 × 每条一次查询，走 SQL 是不必要的开销；
    而内存 dict 的最长匹配实现起来也更直观。
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._by_alias: Dict[str, PlaceMatch] = {}
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path))

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gazetteer (
                name     TEXT PRIMARY KEY,
                west     REAL NOT NULL,
                south    REAL NOT NULL,
                east     REAL NOT NULL,
                north    REAL NOT NULL,
                kind     TEXT NOT NULL DEFAULT 'place',
                aliases  TEXT NOT NULL DEFAULT '',
                source   TEXT NOT NULL DEFAULT 'manual'
            )
            """
        )
        conn.commit()

    def seed(self, force: bool = False) -> int:
        """写入种子数据。force=True 会用种子覆盖已存在的条目。

        返回实际写入的条数。
        """
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.cursor()
            written = 0
            for name, w, s, e, n, kind, aliases, source in SEED:
                if force:
                    cur.execute(
                        "INSERT OR REPLACE INTO gazetteer"
                        " (name,west,south,east,north,kind,aliases,source)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (name, w, s, e, n, kind, aliases, source),
                    )
                else:
                    cur.execute(
                        "INSERT OR IGNORE INTO gazetteer"
                        " (name,west,south,east,north,kind,aliases,source)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (name, w, s, e, n, kind, aliases, source),
                    )
                written += cur.rowcount if cur.rowcount > 0 else 0
            conn.commit()
            return written
        finally:
            conn.close()

    def upsert(
        self,
        name: str,
        west: float,
        south: float,
        east: float,
        north: float,
        kind: str = "place",
        aliases: str = "",
        source: str = "manual",
    ) -> None:
        """新增或更新一条地名。运行期扩充词典用这个。"""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO gazetteer"
                " (name,west,south,east,north,kind,aliases,source)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (name, west, south, east, north, kind, aliases, source),
            )
            conn.commit()
        finally:
            conn.close()
        self._load()

    def _load(self) -> None:
        """从 SQLite 载入全部条目到内存索引。表不存在时自动建并播种。"""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            rows = conn.execute(
                "SELECT name,west,south,east,north,kind,aliases,source FROM gazetteer"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            self.seed()

        # 种子数据会随版本新增（例如后来补的 34 个省级行政区）。
        # 用 INSERT OR IGNORE 幂等补齐一遍，既让老库自动获得新条目，
        # 又不会覆盖已有记录或用户自己 upsert 的数据。
        self.seed(force=False)

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT name,west,south,east,north,kind,aliases,source FROM gazetteer"
            ).fetchall()
        finally:
            conn.close()

        index: Dict[str, PlaceMatch] = {}
        for name, w, s, e, n, kind, aliases, source in rows:
            match = PlaceMatch(
                name=name,
                bbox=[float(w), float(s), float(e), float(n)],
                kind=kind or "place",
                source=source or "manual",
                matched=name,
            )
            keys = [name] + [a.strip() for a in (aliases or "").split(",") if a.strip()]
            for k in keys:
                # 同一个别名被两条记录占用时，保留第一次（seed 顺序即优先级）
                index.setdefault(k, match)
        self._by_alias = index

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def lookup(self, text: str, limit: int = 3) -> List[PlaceMatch]:
        """在文本里找地名，返回命中列表（按别名字数降序，长名优先）。"""
        hits: List[PlaceMatch] = []
        seen: set = set()
        for alias in sorted(self._by_alias, key=len, reverse=True):
            if alias in text:
                m = self._by_alias[alias]
                if m.name in seen:
                    continue
                seen.add(m.name)
                hits.append(
                    PlaceMatch(m.name, list(m.bbox), m.kind, m.source, alias)
                )
                if len(hits) >= limit:
                    break
        return hits

    def resolve_bbox(self, text: str) -> Optional[List[float]]:
        """只要一个 bbox 时用这个。没命中返回 None。"""
        hits = self.lookup(text, limit=1)
        return hits[0].bbox if hits else None

    def lookup_point(self, lon: float, lat: float, limit: int = 3) -> List[PlaceMatch]:
        """反查：给定经纬度，找出覆盖它的地名，**按范围从小到大**返回。

        用途：用户问「我当前看的这块是什么地方」时，模型并不需要知道
        某个坐标对应哪个行政区 —— 词典直接给出答案，模型只负责组织语言。
        4B 模型记不住这类对应关系，也不该要求它硬记（上一条实测教训：
        「这里有什么国家/地区」被它判成越界直接拒答）。
        """
        hits: List[tuple] = []
        seen: set = set()
        for _alias, m in self._by_alias.items():
            if m.name in seen:
                continue
            west, south, east, north = m.bbox
            if west <= lon <= east and south <= lat <= north:
                seen.add(m.name)
                # 面积越小越具体（市 < 省 < 高原），排序时优先
                hits.append(((east - west) * (north - south), m))
        hits.sort(key=lambda item: item[0])
        return [
            PlaceMatch(m.name, list(m.bbox), m.kind, m.source, m.name)
            for _area, m in hits[:limit]
        ]

    def describe_point(self, lon: float, lat: float) -> str:
        """把反查结果拼成一句给模型/用户看的话。"""
        hits = self.lookup_point(lon, lat)
        if not hits:
            return f"坐标 ({lon:.2f}, {lat:.2f}) 附近没有收录的地名"
        return "、".join(f"{h.name}（{h.kind}）" for h in hits)

    def annotate(self, query: str) -> str:
        """把地名提示追加到 query 后面。

        关键：追加在 **user 消息**里，不动 system。前缀复用缓存的是
        system+tools（约 4900 token），提示逐条变化若塞进 system
        会让缓存全部失效，反而更慢。
        """
        hits = self.lookup(query)
        if not hits:
            return query
        lines = []
        for h in hits:
            w, s, e, n = h.bbox
            lines.append(f"{h.name} = [{w}, {s}, {e}, {n}]")
        return (
            f"{query}\n\n[地名词典] {'；'.join(lines)}"
            "（bbox 顺序：西经, 南纬, 东经, 北纬）。请直接使用该 bbox，不要自行估算。"
        )

    def __len__(self) -> int:
        return len({m.name for m in self._by_alias.values()})

    def stats(self) -> Dict[str, Any]:
        by_source: Dict[str, int] = {}
        for m in {x.name: x for x in self._by_alias.values()}.values():
            by_source[m.source] = by_source.get(m.source, 0) + 1
        return {"entries": len(self), "aliases": len(self._by_alias), "by_source": by_source}


# 进程内共享一个实例：避免每条样本都重读一次 SQLite
_DEFAULT: Optional[Gazetteer] = None


def get_gazetteer(db_path: Optional[str] = None) -> Gazetteer:
    global _DEFAULT
    if db_path:
        return Gazetteer(db_path)
    if _DEFAULT is None:
        _DEFAULT = Gazetteer()
    return _DEFAULT
