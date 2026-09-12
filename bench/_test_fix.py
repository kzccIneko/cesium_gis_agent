"""验证意图分流修复：分析题不能被误判，非分析题仍要正确。"""
import json
import urllib.request

VIEW = {
    "bbox": [118.53, 21.38, 122.62, 25.83],
    "center": [120.575, 23.605],
    "area_km2": 205170,
    "is_global": False,
}


def ask(q):
    payload = {"query": q, "session_id": "t_fix", "view_context": VIEW}
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/agent/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    d = json.load(urllib.request.urlopen(req, timeout=600))
    tools = [s.get("tool") for s in (d.get("steps") or [])]
    print(f"意图={d.get('intent'):9s} 工具={tools} | {q}")


CASES_ANALYSIS = [
    "四姑娘山这一带的坡度是多少",
    "贡嘎山哪里比较陡",
    "泰山的坡度情况怎么样",
    "分析张家界的坡度分布",
]
CASES_OTHER = [
    "什么是坡度",
    "这里是什么国家/地区",
    "你有什么功能模块",
    "为跳转到海南省区域",
]

if __name__ == "__main__":
    print("--- 这些必须是 analysis（要调工具）---")
    for q in CASES_ANALYSIS:
        ask(q)
    print("\n--- 这些不能是 analysis ---")
    for q in CASES_OTHER:
        ask(q)
