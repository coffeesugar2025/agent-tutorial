"""性能用例：首 token 延迟 / 端到端 P95 / 并发下工具错误率（总纲 5.9 / 7.2）。"""
from locust import HttpUser, task, between


class AgentUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def chat_sync(self):
        self.client.post("/v1/chat/sync", json={"message": "星野 Pro 用 FULL100 券后多少钱",
                                                "user_id": "u_1001", "thread_id": "perf"},
                         name="chat.sync")

    @task(2)
    def rag_query(self):
        self.client.post("/v2/rag/query", json={"question": "退货政策", "mode": "hybrid"},
                         name="rag.query")

    @task(1)
    def capabilities(self):
        self.client.get("/v3/capabilities", name="capabilities")

    @task(1)
    def stability(self):
        self.client.post("/v3/evals/stability", json={"k": 2}, name="evals.stability")
