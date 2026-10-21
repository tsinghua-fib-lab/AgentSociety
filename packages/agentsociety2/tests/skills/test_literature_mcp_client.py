"""Tests for literature MCP client helpers."""

import pytest

from agentsociety2.skills.literature.mcp_client import (
    is_literature_mcp_tool,
    mcp_gateway_origin,
    normalize_literature_mcp_url,
    resolve_literature_tool_name,
)


def test_normalize_gateway_mcp_trailing_slash():
    assert (
        normalize_literature_mcp_url("https://llmapi.fiblab.net/mcp")
        == "https://llmapi.fiblab.net/mcp/"
    )


def test_normalize_rejects_non_mcp_url():
    with pytest.raises(ValueError):
        normalize_literature_mcp_url("https://llmapi.fiblab.net/")


def test_mcp_gateway_origin():
    assert (
        mcp_gateway_origin("https://llmapi.fiblab.net/mcp/")
        == "https://llmapi.fiblab.net"
    )


def test_is_literature_mcp_tool_filters_gateway_tools():
    assert is_literature_mcp_tool("Literature_Search-literature_search")
    assert not is_literature_mcp_tool("Mirothinker_WebSearch-run_research_task")


def test_resolve_search_tool_ignores_other_tools():
    names = [
        "Mirothinker_WebSearch-check_status",
        "Literature_Search-literature_search",
        "Literature_Search-literature_status",
    ]
    assert resolve_literature_tool_name(names, kind="search") == (
        "Literature_Search-literature_search"
    )


def test_resolve_status_tool_name():
    names = ["literature_status", "literature_search", "literature_ingest_text"]
    assert resolve_literature_tool_name(names, kind="status") == "literature_status"


def test_resolve_tool_name_missing_raises():
    with pytest.raises(ValueError):
        resolve_literature_tool_name(["other_tool"], kind="search")


@pytest.mark.parametrize("is_error", [False, True])
async def test_mcp2_transport_auth_and_tool_errors(monkeypatch, is_error):
    """Exercise real MCP sessions over mocked HTTP, including wire error flags."""
    import json

    import httpx2

    from agentsociety2.skills.literature import mcp_client

    requests = []
    async_client = httpx2.AsyncClient

    def respond(request):
        assert request.headers["authorization"] == "Bearer test-key"
        message = json.loads(request.content)
        method = message["method"]
        requests.append(method)
        if "id" not in message:
            return httpx2.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "literature_search",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }
        elif method == "tools/call":
            assert message["params"]["arguments"] == {"query": "society"}
            result = {
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "isError": is_error,
            }
        else:
            raise AssertionError(method)
        return httpx2.Response(
            200,
            json={"jsonrpc": "2.0", "id": message["id"], "result": result},
        )

    def make_client(**kwargs):
        return async_client(transport=httpx2.MockTransport(respond), **kwargs)

    monkeypatch.setattr(mcp_client.httpx2, "AsyncClient", make_client)
    call = mcp_client.call_literature_mcp_tool(
        mcp_url="https://gateway.test/mcp/",
        api_key="test-key",
        kind="search",
        arguments={"query": "society"},
    )
    if is_error:
        with pytest.raises(RuntimeError, match="MCP tool error"):
            await call
    else:
        assert await call == {"ok": True}
    assert "tools/list" in requests
    assert "tools/call" in requests
