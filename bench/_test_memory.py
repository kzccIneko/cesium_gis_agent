"""多轮对话联调：验证上下文记忆与指代消解。

复现用户报的场景：
  1. 问完五指山之后说「跳转到这个地方」—— 以前答"请提供具体地名"
  2. 「跳转到阿尔卑斯山」—— 以前要先跑几分钟地形分析
"""
import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:8000/api/v1/agent/chat"
SESSION = "mem-test-" + str(int(time.time()))

# 模拟前端上报的视野（海南附近）
VIEW = {
    "bbox": [109.00, 18.49, 111.00, 19.50],
    "center": [110.0, 19.0],
    "area_km2": 45000.0,
    "is_global": False,
}


def ask(q, view=VIEW, session=SESSION):
    payload = {"query": q, "session_id": session, "view_context": view}
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    d = json.load(urllib.request.urlopen(req, timeout=900))
    dt = time.perf_counter() - t0
    print("=" * 74)
    print(f"问：{q}   （{dt:.1f}s）")
    print(f"  意图={d.get('intent')}  拒答={d.get('refused')}  步数={len(d.get('steps') or [])}"
          f"  轮数={d.get('session_turns')}")
    if d.get("memory_notes"):
        for n in d["memory_notes"]:
            print(f"  记忆：{n}")
    if d.get("resolved_query"):
        print(f"  补全：{d['resolved_query']}")
    if d.get("actions"):
        print(f"  动作：{json.dumps(d['actions'], ensure_ascii=False)}")
    print(f"  回答：{(d.get('answer') or '').replace(chr(10), ' ')[:170]}")
    return d


if __name__ == "__main__":
    cases = sys.argv[1:] or [
        "我想看看五指山",
        "跳转到这个地方",
        "跳转到阿尔卑斯山",
        "跳转到这个地方",
        "这里是什么地方",
    ]
    for q in cases:
        try:
            ask(q)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {q} 失败：{type(exc).__name__}: {exc}")
