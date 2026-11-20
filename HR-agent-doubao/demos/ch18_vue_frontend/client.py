"""第 18 章（客户端）：不开浏览器也能验证 SSE 事件流。

跑法：
  终端 A：python ch18_vue_frontend/server.py
  终端 B：python ch18_vue_frontend/client.py

它做的事和浏览器里 EventSource 完全一样：连上 /chat，逐行读 `event:` / `data:`，
所以这一章在**没有网络、没有浏览器**的环境里也能验收。
"""

import json, sys, urllib.request

URL = "http://127.0.0.1:8765/chat"

req = urllib.request.Request(URL, headers={"Accept": "text/event-stream"})
print(f"连接 {URL} …\n")

event = None
with urllib.request.urlopen(req, timeout=30) as resp:
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
            if event == "tool_start":
                print(f"  [{event}] {payload['name']}({json.dumps(payload['input'], ensure_ascii=False)})")
            elif event == "tool_end":
                print(f"  [{event}] {payload['output']}")
            elif event == "answer":
                print(f"  [{event}] {payload['text']}")
            else:
                print(f"  [{event}] {payload.get('msg')}")
            if event == "done":
                break

print("\n事件流结束。浏览器里那张 Vue 页面，用的就是这一串数据。")
