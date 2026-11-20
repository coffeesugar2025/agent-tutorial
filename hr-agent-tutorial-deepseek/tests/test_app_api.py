"""综合项目后端 API 验收测试。

运行：``python -m pytest tests/test_app_api.py -q``
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backend import main as backend  # noqa: E402
from common.data import policy_document  # noqa: E402


@pytest.fixture()
def client():
    """每个用例从空状态开始，避免审批 / 幂等键互相污染。"""
    backend.reset_state()
    with TestClient(backend.app) as test_client:
        yield test_client
    backend.reset_state()


def _chat(client: TestClient, message: str, employee_id: str, session_id: str | None = None) -> dict:
    body = {"message": message, "employee_id": employee_id}
    if session_id:
        body["session_id"] = session_id
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 健康检查 / 课程 / 文档
# ---------------------------------------------------------------------------
def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
    assert body["llm_mode"] == "mock"
    assert body["chapters"] == 18
    assert body["kb_chunks"] > 0


def test_course_and_docs(client: TestClient) -> None:
    response = client.get("/api/course")
    assert response.status_code == 200
    course = response.json()
    assert course["title"] == "HR Agent 实战教程"
    assert isinstance(course["parts"], list)

    slugs: list[str] = []
    for part in course["parts"]:
        assert part["id"].startswith("part-")
        assert part["title"]
        assert part["chapters"]
        orders = [chapter["order"] for chapter in part["chapters"]]
        assert orders == sorted(orders)
        for chapter in part["chapters"]:
            assert chapter["slug"] and not chapter["slug"].startswith("_")
            assert chapter["title"]
            assert chapter["minutes"] > 0
            assert chapter["difficulty"]
            assert "summary" in chapter
            slugs.append(chapter["slug"])

    if slugs:
        detail = client.get(f"/api/docs/{slugs[0]}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["slug"] == slugs[0]
        assert payload["markdown"].lstrip().startswith("---")
        meta = payload["meta"]
        for key in ("order", "minutes", "difficulty", "part", "prerequisites", "summary"):
            assert key in meta

    # 以下划线开头的内部文档不进入课程，也不能按 slug 访问
    assert client.get("/api/docs/_APP_API").status_code == 404
    missing = client.get("/api/docs/no-such-chapter")
    assert missing.status_code == 404
    assert "未找到章节" in missing.json()["detail"]


# ---------------------------------------------------------------------------
# 假期余额
# ---------------------------------------------------------------------------
def test_leave_balance_and_session(client: TestClient) -> None:
    chat = _chat(client, "我还有几天年假？", "E1001", "s_test_balance")
    assert chat["intent"] == "leave_balance"
    assert chat["status"] == "completed"
    assert "13" in chat["reply"]
    assert "15" in chat["reply"]  # 年度额度
    assert chat["citations"] == []
    assert [step["type"] for step in chat["steps"]] == ["llm", "tool", "final"]
    assert chat["steps"][1]["title"] == "get_leave_balance"
    assert chat["steps"][1]["data"]["annual_remaining"] == 13
    assert len(chat["suggestions"]) == 2
    assert chat["usage"]["total_tokens"] > 0
    assert chat["usage"]["total_tokens"] == (
        chat["usage"]["prompt_tokens"] + chat["usage"]["completion_tokens"]
    )
    assert chat["memory"]["employee"]["id"] == "E1001"

    session = client.get(f"/api/sessions/{chat['session_id']}")
    assert session.status_code == 200
    payload = session.json()
    assert payload["session_id"] == chat["session_id"]
    assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
    assert payload["approval"] is None
    assert payload["memory"]["employee"]["name"] == "张伟"
    assert payload["memory"]["facts"]


# ---------------------------------------------------------------------------
# 制度引用：必须来自召回片段且为 active 版本
# ---------------------------------------------------------------------------
def test_policy_citations_are_grounded(client: TestClient) -> None:
    chat = _chat(client, "年假没休完可以结转到什么时候？", "E1001")
    assert chat["intent"] == "leave_policy"
    assert chat["status"] == "completed"
    assert "3 月 31 日" in chat["reply"]
    assert chat["citations"], "制度类回答必须带引用"
    for citation in chat["citations"]:
        assert citation["status"] == "active"
        assert citation["doc_id"]
        assert citation["title"]
        assert citation["version"]
        assert citation["heading"]
        assert 0 < citation["score"] <= 1
        document = policy_document(citation["doc_id"])
        assert document is not None
        snippet = citation["snippet"].rstrip("……").strip()
        assert snippet[:80] in document["content"]
    assert any(citation["doc_id"] == "leave-2025" for citation in chat["citations"])
    assert [step["type"] for step in chat["steps"]].count("retrieval") == 1


def test_out_of_scope_escalates(client: TestClient) -> None:
    chat = _chat(client, "今天天气怎么样？", "E1001")
    assert chat["intent"] == "out_of_scope"
    assert chat["status"] == "escalated"
    assert "转人工" in chat["reply"]


def test_policy_refuses_when_no_evidence(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = backend.get_runtime()
    # 模拟召回为空：Agent 必须拒答并转人工，而不是靠模型记忆编造制度。
    monkeypatch.setattr(runtime.agent.toolbox.rag, "search", lambda *args, **kwargs: [])
    chat = _chat(client, "年假没休完可以结转到什么时候？", "E1001")
    assert chat["status"] == "escalated"
    assert chat["citations"] == []
    assert "没有找到" in chat["reply"]
    assert "转人工" in chat["reply"]


# ---------------------------------------------------------------------------
# 请假申请：写操作 + 幂等
# ---------------------------------------------------------------------------
def test_apply_leave_is_idempotent(client: TestClient) -> None:
    session_id = "s_test_apply"
    first = _chat(
        client,
        "帮我提交 2026-12-01 到 2026-12-03 的 3 天年假申请",
        "E1001",
        session_id,
    )
    assert first["intent"] == "apply_leave"
    assert first["status"] == "completed"
    assert "已提交" in first["reply"]
    tool_titles = [step["title"] for step in first["steps"] if step["type"] == "tool"]
    assert tool_titles == ["check_leave_eligibility", "submit_leave_request"]

    second = _chat(
        client,
        "帮我提交 2026-12-01 到 2026-12-03 的 3 天年假申请",
        "E1001",
        session_id,
    )
    first_id = re.search(r"LV\d+", first["reply"])
    second_id = re.search(r"LV\d+", second["reply"])
    assert first_id and second_id
    assert first_id.group() == second_id.group()
    assert "幂等" in second["reply"]


# ---------------------------------------------------------------------------
# 候选人：权限 / 脱敏
# ---------------------------------------------------------------------------
def test_candidate_search_and_pii_masking(client: TestClient) -> None:
    search = _chat(client, "帮我找会 Vue3 的前端候选人", "E1010")
    assert search["intent"] == "candidate_search"
    assert "张蕾" in search["reply"]
    assert search["steps"][1]["data"]["candidate_ids"] == ["C002"]

    detail = _chat(client, "王浩现在到哪一步了？", "E1010")
    assert detail["intent"] == "candidate_query"
    assert "Offer" in detail["reply"]
    assert "13700001003" not in detail["reply"]
    assert "wanghao@example.com" not in detail["reply"]
    assert "137****1003" in detail["reply"]


# ---------------------------------------------------------------------------
# 敏感操作：pending → approve → 执行；执行前不得有副作用
# ---------------------------------------------------------------------------
def test_salary_adjust_requires_approval_then_executes(client: TestClient) -> None:
    chat = _chat(client, "把张伟的薪资调整到 P6-1", "E1004", "s_test_salary")
    assert chat["intent"] == "salary_adjust"
    assert chat["status"] == "pending_approval"
    approval = chat["approval"]
    assert approval is not None
    assert approval["action"] == "adjust_salary"
    assert approval["risk"] == "high"
    assert approval["status"] == "pending"
    assert approval["requested_by"] == "E1004"
    assert approval["payload"]["employee_id"] == "E1001"
    assert approval["payload"]["new_band"] == "P6-1"
    assert "审批" in chat["reply"]

    store = backend.get_runtime().store
    assert store.get_salary_band("E1001") == "P5-2", "审批前不得修改薪资"

    approved = client.post(
        f"/api/approvals/{approval['id']}",
        json={"decision": "approve", "comment": "已核对编制与带宽", "approver": "E2004"},
    )
    assert approved.status_code == 200
    result = approved.json()
    assert result["status"] == "approved"
    assert "P6-1" in result["result"]
    assert result["audit_id"].startswith("au_")
    assert store.get_salary_band("E1001") == "P6-1"
    assert store.verify_audit_chain() is True
    assert any(event["action"] == "adjust_salary" for event in store.audit_events())

    repeated = client.post(
        f"/api/approvals/{approval['id']}",
        json={"decision": "approve", "approver": "E2004"},
    )
    assert repeated.status_code == 400
    assert "不能重复审批" in repeated.json()["detail"]


def test_interview_approval_and_reject(client: TestClient) -> None:
    chat = _chat(client, "安排王浩 2026-12-05 14:00 面试", "E1010", "s_test_interview")
    assert chat["status"] == "pending_approval"
    approval = chat["approval"]
    assert approval["action"] == "schedule_interview"
    store = backend.get_runtime().store
    assert store.interviews == {}, "审批前不得创建面试日程"

    rejected = client.post(
        f"/api/approvals/{approval['id']}",
        json={"decision": "reject", "comment": "面试官时间冲突", "approver": "E2004"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert store.interviews == {}
    assert store.verify_audit_chain() is True

    # 再发起一次并批准，验证执行路径
    again = _chat(client, "安排王浩 2026-12-05 15:00 面试", "E1010", "s_test_interview_2")
    approved = client.post(
        f"/api/approvals/{again['approval']['id']}",
        json={"decision": "approve", "approver": "E2004"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert len(store.interviews) == 1
    assert store.verify_audit_chain() is True


# ---------------------------------------------------------------------------
# 越权 / 参数错误 / 资源不存在
# ---------------------------------------------------------------------------
def test_permission_boundaries(client: TestClient) -> None:
    candidate = _chat(client, "帮我找会 Vue3 的前端候选人", "E1001")
    assert candidate["status"] == "escalated"
    assert "权限" in candidate["reply"]

    salary = _chat(client, "把张伟的薪资调整到 P6-1", "E1001")
    assert salary["status"] == "escalated"
    assert salary["approval"] is None

    # 非 HR 不能审批：先合法创建一张审批单，再用普通员工身份审批
    created = _chat(client, "把张伟的薪资调整到 P6-1", "E1004")
    denied = client.post(
        f"/api/approvals/{created['approval']['id']}",
        json={"decision": "approve", "approver": "E1001"},
    )
    assert denied.status_code == 400
    assert "没有权限" in denied.json()["detail"]


def test_errors_and_404(client: TestClient) -> None:
    assert client.get("/api/sessions/no-such-session").status_code == 404
    assert client.post("/api/approvals/ap_nope", json={"decision": "approve", "approver": "E2004"}).status_code == 404
    assert client.get("/api/docs/no-such-slug").status_code == 404
    assert client.get("/api/no-such-api").status_code == 404
    assert client.get("/api/no-such-api").json()["detail"] == "接口不存在"

    empty = client.post("/api/chat", json={"message": "  ", "employee_id": "E1001"})
    assert empty.status_code == 400
    assert "消息不能为空" in empty.json()["detail"]

    unknown = client.post("/api/chat", json={"message": "你好", "employee_id": "E9999"})
    assert unknown.status_code == 400
    assert "员工不存在" in unknown.json()["detail"]

    bad_kb = client.get("/api/kb/search", params={"q": ""})
    assert bad_kb.status_code == 400
    assert client.get("/api/kb/search", params={"q": "zzzzzz"}).json()["results"] == []


# ---------------------------------------------------------------------------
# 知识库检索：字段 / 排序 / 归档过滤
# ---------------------------------------------------------------------------
def test_kb_search(client: TestClient) -> None:
    response = client.get("/api/kb/search", params={"q": "年假", "top_k": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "年假"
    assert payload["results"]
    scores = [item["score"] for item in payload["results"]]
    assert scores == sorted(scores, reverse=True)
    for item in payload["results"]:
        assert set(item) == {
            "doc_id",
            "title",
            "version",
            "heading",
            "snippet",
            "score",
            "status",
        }
        assert item["status"] == "active"

    archived = client.get(
        "/api/kb/search", params={"q": "年假", "top_k": 10, "include_archived": True}
    ).json()["results"]
    assert any(item["doc_id"] == "leave-2024" and item["status"] == "archived" for item in archived)


# ---------------------------------------------------------------------------
# 场景 / CORS / 会话窗口
# ---------------------------------------------------------------------------
def test_scenarios(client: TestClient) -> None:
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert len(scenarios) == 8
    ids = {item["id"] for item in scenarios}
    for required in (
        "leave-balance",
        "leave-carryover",
        "leave-apply",
        "candidate-vue",
        "interview-wanghao",
        "salary-zhangwei",
        "remote-2027-draft",
        "out-of-scope-weather",
    ):
        assert required in ids
    for item in scenarios:
        assert set(item) == {"id", "label", "message", "employee_id", "risk"}
        assert item["risk"] in {"low", "medium", "high"}


def test_cors_allows_vite_dev_server(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_session_keeps_last_20_messages(client: TestClient) -> None:
    session_id = "s_test_window"
    for _ in range(12):
        _chat(client, "我还有几天年假？", "E1001", session_id)
    session = client.get(f"/api/sessions/{session_id}").json()
    assert len(session["messages"]) == 20
    assert session["messages"][-1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# 演示重置：让审批场景可以反复演示
# ---------------------------------------------------------------------------
def test_demo_reset_restores_salary_scenario(client: TestClient) -> None:
    session_id = "s_reset_salary"
    first = _chat(client, "把张伟的薪资调整到 P6-1", "E1004", session_id)
    approved = client.post(
        f"/api/approvals/{first['approval']['id']}",
        json={"decision": "approve", "approver": "E2004"},
    )
    assert approved.status_code == 200
    store = backend.get_runtime().store
    assert store.get_salary_band("E1001") == "P6-1"
    assert store.verify_audit_chain() is True

    # 未重置时重复申请会被业务校验拦住（避免制造重复变更）
    repeated = _chat(client, "把张伟的薪资调整到 P6-1", "E1004", session_id)
    assert repeated["status"] == "error"

    # 连续两次重置都必须可用，且回到种子状态
    for _ in range(2):
        reset = client.post("/api/demo/reset")
        assert reset.status_code == 200
        body = reset.json()
        assert body["status"] == "ok"
        assert body["reset_at"].endswith("+08:00")

        store = backend.get_runtime().store
        assert store.get_salary_band("E1001") == "P5-2"
        assert store.salary_overrides == {}
        assert store.approvals == {}
        assert store.leave_requests == {}
        assert store.audit_events() == []
        assert store.verify_audit_chain() is True
        assert client.get(f"/api/sessions/{session_id}").status_code == 404

        replay = _chat(client, "把张伟的薪资调整到 P6-1", "E1004", session_id)
        assert replay["status"] == "pending_approval"
        assert replay["approval"]["action"] == "adjust_salary"
        assert replay["approval"]["payload"]["new_band"] == "P6-1"


# ---------------------------------------------------------------------------
# 评测：20 条、确定性、快
# ---------------------------------------------------------------------------
def test_eval_run_is_deterministic_and_fast(client: TestClient) -> None:
    started = time.perf_counter()
    response = client.post("/api/eval/run")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < 5.0, f"评测耗时 {elapsed:.2f}s，超过 5 秒预算"

    payload = response.json()
    summary = payload["summary"]
    assert summary["total"] == 20
    assert 18 <= summary["passed"] <= 20
    assert summary["success_rate"] == round(summary["passed"] / 20, 3)
    assert summary["tool_accuracy"] >= 0.9
    assert summary["citation_accuracy"] >= 0.9
    assert summary["total_tokens"] > 0
    assert summary["p95_latency_ms"] >= 0

    assert payload["baseline"] == {
        "success_rate": 0.85,
        "tool_accuracy": 0.90,
        "p95_latency_ms": 95,
    }
    cases = payload["cases"]
    assert [case["id"] for case in cases] == [f"G{index:02d}" for index in range(1, 21)]
    for case in cases:
        assert case["latency_ms"] >= 0
        assert case["tokens"] >= 0
        assert isinstance(case["failures"], list)
        assert case["passed"] is (not case["failures"])

    second = client.post("/api/eval/run").json()
    assert [(case["id"], case["passed"]) for case in second["cases"]] == [
        (case["id"], case["passed"]) for case in cases
    ]
