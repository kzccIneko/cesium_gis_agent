"""测试五类意图分流（用户实测反馈的那几个问题）。"""
import json
import urllib.request

VIEW = {
    "bbox": [118.53, 21.38, 122.62, 25.83],
    "center": [120.575, 23.605],
    "area_km2": 205170,
    "is_global": False,
}


def ask(q, view=VIEW):
    payload = {"query": q, "bbox": None, "session_id": "t_intent",
               "view_context": view}
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/agent/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    d = json.load(urllib.request.urlopen(req, timeout=600))
    print("=" * 72)
    print("问：", q)
    print("意图：", d.get("intent"), "| 拒答：", d.get("refused"),
          "| 工具步数：", len(d.get("steps") or []))
    print("动作：", json.dumps(d.get("actions"), ensure_ascii=False))
    print("回答：", (d.get("answer") or "").replace("\n", " ")[:320])


if __name__ == "__main__":
    for q in [
        "这里有什么国家/地区",
        "你有什么功能模块",
        "为跳转到海南省区域",
    ]:
        ask(q)
