"""第 18 章（服务端）：把 Agent 的**流式事件**推给前端。

跑法：python ch18_vue_frontend/server.py
然后浏览器打开 http://127.0.0.1:8765/ （index.html 由本服务一起提供）
不想开浏览器？另开一个终端：python ch18_vue_frontend/client.py

为什么用 SSE 而不是 WebSocket：
  · Agent 输出是单向的（服务端 → 前端），SSE 天生适合
  · 一行 `data: {...}` 就能推一个事件，前端 EventSource 三行代码接完
  · 断线自动重连；WebSocket 要自己写心跳与重连

关键：`astream_events(version="v2")` 把"模型在思考 / 正在调工具 / 工具返回了 / 最终答案"
变成一个个可订阅的事件 —— 前端才能显示"Agent 正在做什么"，而不是干等 20 秒。
"""

import json, sys, pathlib, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent
from langchain_core.tools import tool

from common import ai_text, ai_tool, get_model


@tool("get_leave_balance")
def get_leave_balance(emp_id: str) -> str:
    """查员工 2026 年年假余额。"""
    return f"{emp_id} 2026 年年假剩 7 天"


@tool("get_headcount")
def get_headcount(dept: str) -> str:
    """按部门查在职人数。"""
    return f"{dept} 在职 3 人"


TOOLS = [get_leave_balance, get_headcount]


def make_agent():
    model = get_model([
        ai_tool("get_leave_balance", {"emp_id": "E1001"}, "c1"),
        ai_tool("get_headcount", {"dept": "技术中心"}, "c2"),
        ai_text("结论：张伟 2026 年年假剩 7 天；技术中心在职 3 人。"),
    ])
    return create_agent(model, tools=TOOLS, system_prompt="查数据必须调工具，不许估算。")


ROOT = pathlib.Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # 静音，别把每个请求都打出来
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/chat"):
            self.stream_chat()
            return
        self.send_error(404)

    def stream_chat(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(tag: str, payload: dict):
            # ★ SSE 的格式非常死：`event: xxx` + `data: {...}` + 空行
            self.wfile.write(f"event: {tag}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()

        agent = make_agent()
        emit("start", {"msg": "开始处理"})
        try:
            import asyncio

            async def run():
                # ★ LangChain 1.x：事件流只有异步版 astream_events(version="v2")；
                #   同步的 stream_events 已经不支持 v2 了（会抛 NotImplementedError）。
                async for ev in agent.astream_events(
                    {"messages": [{"role": "user", "content": "技术中心多少人？张伟还有几天年假？"}]},
                    version="v2",
                ):
                    kind = ev["event"]
                    if kind == "on_chat_model_start":
                        emit("thinking", {"msg": "模型正在思考…"})
                    elif kind == "on_tool_start":
                        emit("tool_start", {"name": ev.get("name"), "input": ev["data"].get("input")})
                    elif kind == "on_tool_end":
                        emit("tool_end", {"name": ev.get("name"), "output": str(ev["data"].get("output"))})
                    elif kind == "on_chat_model_end":
                        msg = getattr(ev["data"].get("output"), "content", "") or ""
                        if msg:
                            emit("answer", {"text": msg})

            asyncio.run(run())
            emit("done", {"msg": "完成"})
        except Exception as e:
            emit("error", {"msg": f"{type(e).__name__}: {e}"})


def main():
    port = 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"服务已启动：http://127.0.0.1:{port}/")
    print("  · 浏览器打开上面这个地址（Vue3 页面会实时显示 Agent 在做什么）")
    print("  · 或在另一个终端跑 client.py，不需要浏览器也能看到同一串事件")
    print("  Ctrl+C 结束")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
