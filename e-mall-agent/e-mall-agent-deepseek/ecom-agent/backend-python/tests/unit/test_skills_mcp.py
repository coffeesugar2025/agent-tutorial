"""Skill 渐进式披露与 MCP 网关单元测试（含无 SDK / 无目录的降级路径）。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp import server as mcp_server
from app.skills.loader import SkillError, SkillLoader, SkillNotFound, get_loader, list_skills

pytestmark = pytest.mark.unit


def test_skill_metadata_is_layer_one_only():
    loader = get_loader()
    metas = {meta.name: meta for meta in loader.discover()}

    assert {"refund-policy", "product-compare"} <= set(metas)
    refund = metas["refund-policy"]
    assert refund.description
    assert "search_knowledge" in refund.allowed_tools
    assert refund.max_steps == 6
    assert refund.path is not None and refund.path.name == "refund-policy"

    skill = loader.get("refund-policy")
    assert skill.body_loaded is False
    assert skill.body == ""
    assert len(list_skills()) >= 2


def test_skill_body_loads_on_demand_without_frontmatter():
    loader = get_loader()
    body = loader.load_body("refund-policy")

    assert "七天无理由" in body or "退款" in body
    assert not body.startswith("---")

    skill = loader.get("product-compare", load_body=True)
    assert skill.body_loaded is True
    assert "对比" in skill.body
    assert skill.to_dict(include_body=True)["body"] == skill.body


def test_skill_matching_by_triggers():
    loader = get_loader()

    assert [meta.name for meta in loader.match("退款运费谁承担")] == ["refund-policy"]
    assert [meta.name for meta in loader.match("帮我对比这两款手机，预算 5000")] == ["product-compare"]
    assert loader.match("今天的天气如何") == []


def test_skill_not_found_and_path_traversal_blocked():
    loader = get_loader()

    with pytest.raises(SkillNotFound):
        loader.get("missing-skill")
    with pytest.raises(SkillError):
        loader.read_resource("refund-policy", "../../etc/passwd")
    with pytest.raises(SkillError):
        loader.read_resource("refund-policy", "resources/not-exists.md")


def test_loader_degrades_when_root_missing(tmp_path):
    loader = SkillLoader(tmp_path / "no-such-dir")

    assert loader.discover() == []
    assert loader.list_skills() == []
    assert loader.index_block() == ""
    assert loader.prompt_block(include_body=True) == ""
    with pytest.raises(SkillNotFound):
        loader.load_body("anything")


def test_skill_prompt_block_respects_budget():
    loader = get_loader()

    index = loader.index_block()
    assert "refund-policy" in index

    block = loader.prompt_block(["refund-policy"], include_body=True, max_chars=600)
    assert "refund-policy" in block
    assert len(block) <= 1400  # 超预算时只保留描述并提示按需加载


def test_mcp_tool_descriptors_and_annotations():
    payload = mcp_server.tools_payload()

    assert payload["server"] == mcp_server.SERVER_NAME
    assert payload["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert payload["toolCount"] == len(payload["tools"]) >= 10

    by_name = {tool["name"]: tool for tool in payload["tools"]}
    assert by_name["search_products"]["annotations"]["readOnlyHint"] is True
    assert by_name["create_refund_request"]["annotations"]["destructiveHint"] is True
    assert by_name["create_refund_request"]["annotations"]["readOnlyHint"] is False
    assert by_name["search_products"]["inputSchema"]["type"] == "object"


def test_mcp_call_blocks_write_and_rejects_unknown_tool():
    write_result = asyncio.run(
        mcp_server.call_tool("create_refund_request", {"orderNo": "SO202611230001"})
    )
    assert write_result["isError"] is True
    assert "风险级别" in write_result["content"][0]["text"]

    unknown = asyncio.run(mcp_server.call_tool("no_such_tool", {}))
    assert unknown["isError"] is True
    assert "未注册" in unknown["content"][0]["text"]


def test_mcp_read_tool_executes():
    result = asyncio.run(mcp_server.call_tool("search_products", {"query": "手机", "topK": 3}))

    assert result["isError"] is False
    assert result["structuredContent"]["ok"] is True
    assert result["structuredContent"]["tool"] == "search_products"
    assert result["content"][0]["text"]


def test_mcp_payload_degrades_without_sdk(monkeypatch):
    monkeypatch.setattr(mcp_server, "sdk_available", lambda: False)

    payload = mcp_server.tools_payload()

    assert payload["sdkAvailable"] is False
    assert payload["degraded"] is True
    assert payload["transport"] == "http-json"
    assert payload["toolCount"] >= 10


def test_mcp_router_serves_json_tools_and_rejects_write():
    app = FastAPI()
    assert mcp_server.mount(app) is True
    client = TestClient(app, raise_server_exceptions=False)

    listing = client.get("/mcp/tools")
    assert listing.status_code == 200
    assert listing.json()["toolCount"] >= 10
    assert client.get("/mcp/info").json()["server"] == mcp_server.SERVER_NAME
    assert client.get("/mcp/health").json()["status"] == "UP"

    write_call = client.post(
        "/mcp/tools/create_refund_request/call",
        json={"arguments": {"orderNo": "SO202611230001"}},
    )
    assert write_call.status_code == 200
    assert write_call.json()["isError"] is True
