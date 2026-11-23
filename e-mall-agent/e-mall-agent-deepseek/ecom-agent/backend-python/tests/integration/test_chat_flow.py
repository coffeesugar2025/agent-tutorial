"""对话链路集成测试：登录 → 建会话 → SSE 事件序列 → 落库 → 越权隔离。

全部使用 Mock LLM + hash embedding + 内存向量，不依赖任何外部服务。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.infra.db import session_scope
from app.infra.models import SysUser
from app.security.auth import hash_password

PASSWORD = "Passw0rd!"


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _create_user(roles: str = "USER,ADMIN,OPS") -> tuple[int, str]:
    username = f"u_{uuid.uuid4().hex[:10]}"
    with session_scope() as db:
        row = SysUser(
            username=username,
            password_hash=hash_password(PASSWORD),
            display_name="测试用户",
            roles=roles,
            status=1,
        )
        db.add(row)
        db.flush()
        return int(row.id), username


def _login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    return {"Authorization": f"Bearer {body['data']['token']}"}


def _collect_events(
    client: TestClient, headers: dict[str, str], session_id: int, message: str, client_msg_id: str | None = None
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    """读取 SSE 流，返回 (事件名序列, 按事件名分组的数据)。"""
    payload = {"sessionId": session_id, "message": message}
    if client_msg_id:
        payload["clientMsgId"] = client_msg_id

    events: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    with client.stream("POST", "/api/v1/chat/stream", json=payload, headers=headers) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        name: str | None = None
        for line in stream.iter_lines():
            if line.startswith("event: "):
                name = line[len("event: ") :].strip()
                events.append(name)
            elif line.startswith("data: ") and name:
                grouped.setdefault(name, []).append(json.loads(line[len("data: ") :]))
    return events, grouped


def test_chat_stream_event_sequence(client: TestClient):
    _, username = _create_user()
    headers = _login(client, username)

    resp = client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = resp.json()["data"]["id"]

    events, grouped = _collect_events(client, headers, session_id, "帮我推荐 5000 以内的拍照手机")

    assert events, "没有任何 SSE 事件"
    assert events[0] == "meta", f"首个事件必须是 meta，实际 {events[0]}"
    assert "agent" in events
    assert "tool_call" in events, "导购场景应触发商品检索工具"
    assert "tool_result" in events
    assert "delta" in events
    assert "usage" in events
    assert events[-1] == "done", f"最后一个事件必须是 done，实际 {events[-1]}"
    assert "error" not in events

    meta = grouped["meta"][0]
    assert meta["sessionId"] == session_id
    assert meta["messageId"] > 0
    assert meta["traceId"]

    answer = "".join(item.get("text", "") for item in grouped["delta"])
    assert answer.strip(), "最终回答不能为空"

    done = grouped["done"][0]
    assert done["finishReason"] == "stop"
    assert done["messageId"] == meta["messageId"]


def test_chat_persists_messages(client: TestClient):
    _, username = _create_user()
    headers = _login(client, username)
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["data"]["id"]

    _collect_events(client, headers, session_id, "帮我推荐一款耳机")

    resp = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
    messages = resp.json()["data"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"].strip(), "助手消息必须写入正文"
    assert messages[1]["agentType"] in ("SHOPPING", "SERVICE", "OPS")


def test_chat_client_msg_id_is_idempotent(client: TestClient):
    """同一 clientMsgId 重复提交不能重复产生一次完整回答。"""
    _, username = _create_user()
    headers = _login(client, username)
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["data"]["id"]

    first, _ = _collect_events(client, headers, session_id, "推荐一款笔记本", client_msg_id="dup-1")
    assert "tool_call" in first or "delta" in first

    second, grouped = _collect_events(client, headers, session_id, "推荐一款笔记本", client_msg_id="dup-1")
    assert second[0] == "meta"
    assert second[-1] == "done"
    # 幂等命中时不会真正调用工具
    assert "tool_call" not in second
    assert "重复" in "".join(item.get("text", "") for item in grouped.get("delta", []))


def test_chat_requires_auth(client: TestClient):
    resp = client.post("/api/v1/chat/stream", json={"sessionId": 1, "message": "hi"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_session_isolation_between_users(client: TestClient):
    """另一个用户不能读到别人的会话与消息。"""
    _, owner = _create_user()
    owner_headers = _login(client, owner)
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=owner_headers).json()["data"]["id"]

    _, other = _create_user(roles="USER")
    other_headers = _login(client, other)

    assert client.get(f"/api/v1/chat/sessions/{session_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=other_headers).status_code == 404
    assert client.delete(f"/api/v1/chat/sessions/{session_id}", headers=other_headers).status_code == 404


def test_admin_overview_records_trace(client: TestClient):
    _, username = _create_user()
    headers = _login(client, username)
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["data"]["id"]
    _collect_events(client, headers, session_id, "你好")

    resp = client.get("/api/v1/admin/overview?days=7", headers=headers)
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["totalSessions"] >= 1
    assert body["data"]["totalMessages"] >= 2
    assert 0.0 <= body["data"]["successRate"] <= 1.0


def test_health_and_capabilities(client: TestClient):
    health = client.get("/health").json()
    assert health["status"] in ("UP", "DEGRADED")
    assert "mysql" in health["components"]

    caps = client.get("/api/v1/meta/capabilities").json()["data"]
    assert caps["backend"] == "python"
    assert caps["features"]["hybridRag"] is True
