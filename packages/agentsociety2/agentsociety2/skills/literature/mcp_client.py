"""Academic literature search MCP client.

Connects to a LiteLLM MCP gateway (Streamable HTTP) and invokes literature-only
tools. Other tools exposed by the same gateway are ignored.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agentsociety2.logger import get_logger

logger = get_logger()

LiteratureMcpTool = Literal["search", "status", "ingest"]

LITERATURE_TOOL_BY_KIND: dict[LiteratureMcpTool, str] = {
    "search": "literature_search",
    "status": "literature_status",
    "ingest": "literature_ingest_text",
}

LITERATURE_MCP_TOOL_SUFFIXES: tuple[str, ...] = tuple(LITERATURE_TOOL_BY_KIND.values())


def is_literature_mcp_tool(name: str) -> bool:
    """Return whether an MCP tool name belongs to the literature search service.

    :param name: Tool name returned by the gateway (may include a ``Server-`` prefix).
    :returns: ``True`` if the name matches a literature tool suffix.
    """
    return any(
        name == suffix or name.endswith(f"-{suffix}")
        for suffix in LITERATURE_MCP_TOOL_SUFFIXES
    )


def normalize_literature_mcp_url(mcp_url: str) -> str:
    """Normalize and validate the literature MCP gateway URL.

    :param mcp_url: Raw URL from ``LITERATURE_SEARCH_MCP_URL``.
    :returns: Normalized URL with a trailing slash after ``/mcp/``.
    :raises ValueError: If the URL is empty or not an MCP gateway path.
    """
    url = mcp_url.strip()
    if not url:
        raise ValueError("LITERATURE_SEARCH_MCP_URL is empty")
    if url.endswith("/mcp"):
        return f"{url}/"
    if "/mcp/" not in url:
        raise ValueError(
            "LITERATURE_SEARCH_MCP_URL must be an MCP gateway URL, "
            "e.g. https://llmapi.fiblab.net/mcp/"
        )
    return url


def resolve_literature_tool_name(
    tool_names: list[str],
    *,
    kind: LiteratureMcpTool,
) -> str:
    """Pick the gateway tool name for a literature operation kind.

    :param tool_names: Tool names from ``list_tools`` (may include non-literature tools).
    :param kind: Logical operation: ``search``, ``status``, or ``ingest``.
    :returns: Resolved tool name to pass to ``call_tool``.
    :raises ValueError: If no matching literature tool is present.
    """
    preferred = LITERATURE_TOOL_BY_KIND[kind]
    for name in tool_names:
        if not is_literature_mcp_tool(name):
            continue
        if name == preferred or name.endswith(f"-{preferred}"):
            return name
    literature_only = [n for n in tool_names if is_literature_mcp_tool(n)]
    raise ValueError(
        f"Literature MCP tool {preferred!r} not found. "
        f"Literature tools visible: {literature_only}"
    )


async def list_literature_mcp_tools(*, mcp_url: str, api_key: str) -> list[str]:
    """List literature MCP tool names available on the gateway.

    :param mcp_url: MCP gateway URL.
    :param api_key: Bearer token (``sk-...``).
    :returns: Names of tools recognized as literature tools.
    """
    url = normalize_literature_mcp_url(mcp_url)
    headers = _auth_headers(api_key)

    async with (
        httpx2.AsyncClient(
            headers=headers, timeout=httpx2.Timeout(30, read=300)
        ) as client,
        streamable_http_client(url, http_client=client) as (read, write),
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [
                tool.name for tool in tools.tools if is_literature_mcp_tool(tool.name)
            ]


async def call_literature_mcp_tool(
    *,
    mcp_url: str,
    api_key: str,
    kind: LiteratureMcpTool,
    arguments: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Call a literature MCP tool and parse JSON from the text content.

    :param mcp_url: MCP gateway URL.
    :param api_key: Bearer token (``sk-...``).
    :param kind: Tool kind: ``search``, ``status``, or ``ingest``.
    :param arguments: Tool arguments dict (default empty).
    :param timeout: Request timeout in seconds.
    :returns: Parsed JSON object from the tool response.
    :raises RuntimeError: If the tool reports an error.
    :raises ValueError: If the response is empty or not JSON.
    """
    tools = await list_literature_mcp_tools(mcp_url=mcp_url, api_key=api_key)
    tool_name = resolve_literature_tool_name(tools, kind=kind)
    url = normalize_literature_mcp_url(mcp_url)
    headers = _auth_headers(api_key)
    payload = arguments or {}
    timeout_seconds = float(timeout)

    async with (
        httpx2.AsyncClient(headers=headers, timeout=timeout_seconds) as client,
        streamable_http_client(url, http_client=client) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool_name, arguments=payload)
        message = _extract_tool_json(result) if result.content else {"error": "unknown"}

    # Raise after the AnyIO-backed MCP contexts have closed. Raising inside them
    # wraps the application error in an ExceptionGroup in MCP 2.x.
    if result.is_error:
        raise RuntimeError(f"MCP tool error: {message}")
    return message


async def call_literature_search_mcp(
    *,
    mcp_url: str,
    api_key: str,
    arguments: dict[str, Any],
    timeout: int = 120,
) -> dict[str, Any]:
    """Invoke the literature search MCP tool.

    :param mcp_url: MCP gateway URL.
    :param api_key: Bearer token (``sk-...``).
    :param arguments: Search payload (``query``, ``limit``, filters, etc.).
    :param timeout: Request timeout in seconds.
    :returns: Parsed search result JSON from the gateway.
    """
    logger.debug(
        "Academic literature MCP search at %s", normalize_literature_mcp_url(mcp_url)
    )
    return await call_literature_mcp_tool(
        mcp_url=mcp_url,
        api_key=api_key,
        kind="search",
        arguments=arguments,
        timeout=timeout,
    )


async def call_literature_status_mcp(
    *,
    mcp_url: str,
    api_key: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """Invoke the literature status MCP tool (health and data sources).

    :param mcp_url: MCP gateway URL.
    :param api_key: Bearer token (``sk-...``).
    :param timeout: Request timeout in seconds.
    :returns: Parsed status JSON (includes ``sources`` when available).
    """
    return await call_literature_mcp_tool(
        mcp_url=mcp_url,
        api_key=api_key,
        kind="status",
        arguments={},
        timeout=timeout,
    )


def mcp_gateway_origin(mcp_url: str) -> str:
    """Return the gateway origin (scheme + host) for REST helper endpoints.

    :param mcp_url: MCP gateway URL.
    :returns: Origin such as ``https://llmapi.fiblab.net``.
    """
    normalized = normalize_literature_mcp_url(mcp_url)
    parsed = urlparse(normalized)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _auth_headers(api_key: str) -> dict[str, str]:
    """Build an optional bearer authentication header.

    :param api_key: Raw API key, which may contain surrounding whitespace.
    :returns: Authorization headers, or an empty mapping for a blank key.
    """
    key = api_key.strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _extract_tool_json(result: Any) -> dict[str, Any]:
    """Extract the first JSON object from an MCP tool result.

    :param result: MCP call result containing text content blocks.
    :returns: Parsed JSON object.
    :raises ValueError: If the result has no text or contains no JSON object.
    :raises json.JSONDecodeError: If JSON-looking content is malformed.
    """
    texts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    if not texts:
        raise ValueError("MCP tool returned empty content")

    raw = texts[0].strip()
    if raw.startswith("{"):
        return json.loads(raw)

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"MCP tool returned non-JSON payload: {raw[:200]}")
