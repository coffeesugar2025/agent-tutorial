"""对运行中的后端做一次端到端冒烟测试。

先启动：python app/backend/main.py
再运行：python scripts/smoke_api.py
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"
EMPLOYEE = "E1001"
HR = "E1004"
APPROVER = "E2004"


def show(label: str, data: object) -> None:
    text = json.dumps(data, ensure_ascii=False)
    print(f"PASS {label}: {text[:220]}")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=20)
    try:
        # 演示服务是有状态的：先重置，保证脚本可以重复运行。
        reset = client.post("/api/demo/reset").json()
        assert reset["status"] == "ok", reset
        show("demo reset", reset)

        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        show("health", health)

        course = client.get("/api/course").json()
        chapters = [chapter for part in course["parts"] for chapter in part["chapters"]]
        assert len(chapters) >= 16, len(chapters)
        show("course", {"parts": len(course["parts"]), "chapters": len(chapters)})

        doc = client.get("/api/docs/agent-loop").json()
        assert "Agent Loop" in doc["markdown"] and doc["meta"]["order"] == 2
        show("docs", {"slug": doc["slug"], "chars": len(doc["markdown"])})

        balance = client.post(
            "/api/chat",
            json={"session_id": "smoke-balance", "message": "我还有几天年假？", "employee_id": EMPLOYEE},
        ).json()
        assert "13" in balance["reply"], balance["reply"]
        assert any(step["type"] == "tool" for step in balance["steps"])
        show("leave balance", {"reply": balance["reply"], "steps": len(balance["steps"])})

        policy = client.post(
            "/api/chat",
            json={"session_id": "smoke-policy", "message": "年假没休完可以结转到什么时候？", "employee_id": EMPLOYEE},
        ).json()
        assert policy["citations"], policy
        assert any("2025" in item["version"] for item in policy["citations"]), policy["citations"]
        assert "3 月 31 日" in policy["reply"] or "3月31日" in policy["reply"], policy["reply"]
        show("policy citation", {"reply": policy["reply"][:80], "citation": policy["citations"][0]["doc_id"]})

        leave = client.post(
            "/api/chat",
            json={
                "session_id": "smoke-leave",
                "message": "帮我提交 2026-12-01 到 2026-12-03 的 3 天年假申请",
                "employee_id": EMPLOYEE,
            },
        ).json()
        assert leave["status"] == "completed", leave
        assert "已提交" in leave["reply"] or "申请" in leave["reply"], leave["reply"]
        show("apply leave", {"reply": leave["reply"], "status": leave["status"]})

        candidate = client.post(
            "/api/chat",
            json={"session_id": "smoke-candidate", "message": "帮我找会 Vue3 的前端候选人", "employee_id": "E1010"},
        ).json()
        assert "张蕾" in candidate["reply"], candidate["reply"]
        assert "138" not in candidate["reply"], "候选人手机号未脱敏"
        show("candidate search", {"reply": candidate["reply"][:100]})

        interview = client.post(
            "/api/chat",
            json={
                "session_id": "smoke-interview",
                "message": "安排王浩 2026-12-05 14:00 面试",
                "employee_id": "E1010",
            },
        ).json()
        assert interview["status"] == "pending_approval", interview
        approval = interview["approval"]
        assert approval and approval["action"] == "schedule_interview"
        decided = client.post(
            f"/api/approvals/{approval['id']}",
            json={"decision": "approve", "comment": "冒烟测试", "approver": APPROVER},
        ).json()
        assert decided["status"] == "approved", decided
        show("interview approval", {"approval": approval["id"], "result": decided["result"][:100]})

        salary = client.post(
            "/api/chat",
            json={
                "session_id": "smoke-salary",
                "message": "把张伟的薪资调整到 P6-1",
                "employee_id": HR,
            },
        ).json()
        assert salary["status"] == "pending_approval", salary
        rejected = client.post(
            f"/api/approvals/{salary['approval']['id']}",
            json={"decision": "reject", "comment": "预算不足", "approver": APPROVER},
        ).json()
        assert rejected["status"] == "rejected", rejected
        show("salary reject", {"status": rejected["status"], "result": rejected["result"][:100]})

        kb = client.get("/api/kb/search", params={"q": "年假", "top_k": 3}).json()
        assert kb["results"] and all(item["status"] == "active" for item in kb["results"])
        show("kb search", {"count": len(kb["results"]), "top": kb["results"][0]["doc_id"]})

        evaluation = client.post("/api/eval/run").json()
        assert evaluation["summary"]["total"] >= 20
        assert 0 <= evaluation["summary"]["success_rate"] <= 1
        show("evaluation", evaluation["summary"])

        index = client.get("/").text
        assert '<div id="app">' in index
        show("static spa", {"bytes": len(index)})

    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {type(exc).__name__}: {exc}")
        return 1
    finally:
        client.close()
    print("\n全部冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
