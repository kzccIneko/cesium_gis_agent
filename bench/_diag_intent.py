"""诊断：为什么「跳转到阿尔卑斯山」会走地形分析。

只调意图分类这一段（不跑整个图），几秒钟出结果。
"""
import sys
import os

sys.path.insert(0, "backend")

from app.agent.nodes.planner import (  # noqa: E402
    classify_intent,
    _force_analysis,
    _has_geo_signal,
    build_view_context,
)
from app.agent.llm import build_client  # noqa: E402

VIEW = {
    "bbox": [109.00, 18.49, 111.00, 19.50],
    "center": [110.0, 19.0],
    "area_km2": 45000.0,
    "is_global": False,
}

CASES = [
    "跳转到五指山",
    "跳转到阿尔卑斯山",
    "我想看看五指山",
    "跳到阿尔卑斯山",
    "去阿尔卑斯山",
    "定位到阿尔卑斯山",
    "飞到珠穆朗玛峰",
    "跳转到这个地方",
    "算一下当前视野的坡度",
]


def main():
    llm = build_client()
    for q in CASES:
        state = {
            "query": q,
            "bbox": None,
            "session_id": "diag",
            "view_context": dict(VIEW),
            "messages": [{"role": "user", "content": q}],
        }
        forced = _force_analysis(q)
        geo = _has_geo_signal(q)
        cls = None if forced else classify_intent(state, llm)
        intent = "analysis(强制)" if forced else (
            cls.get("intent") if cls else f"分类失败→按地理信号兜底({geo})"
        )
        print(f"{q:22s} | force={forced} | geo={geo} | -> {intent}")
        if cls:
            print(f"{'':22s} | reply={str(cls.get('reply'))[:60]!r}")
            print(f"{'':22s} | actions={cls.get('actions')}")


if __name__ == "__main__":
    main()
