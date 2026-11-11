"""学术文献检索 MCP 客户端。

连接 LiteLLM MCP 网关（Streamable HTTP）并只调用文献相关工具，
忽略同一网关暴露的其他工具。
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
    """判断某个 MCP 工具名是否属于文献检索服务。

    :param name: 网关返回的工具名（可能带 ``Server-`` 前缀）。
    :returns: 与某个文献工具后缀匹配时返回 ``True`` 。
    """
    return any(
        name == suffix or name.endswith(f"-{suffix}")
        for suffix in LITERATURE_MCP_TOOL_SUFFIXES
    )


def normalize_literature_mcp_url(mcp_url: str) -> str:
    """规范化并校验文献 MCP 网关 URL。

    :param mcp_url: ``LITERATURE_SEARCH_MCP_URL`` 中的原始 URL。
    :returns: 规范化后的 URL，保证 ``/mcp/`` 以斜杠结尾。
    :raises ValueError: URL 为空或不是 MCP 网关路径时抛出。
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
    """为指定的文献操作类型选出网关工具名。

    :param tool_names: ``list_tools`` 返回的工具名列表（可能包含非文献工具）。
    :param kind: 逻辑操作类型：``search`` 、``status`` 或 ``ingest`` 。
    :returns: 解析出的、可传给 ``call_tool`` 的工具名。
    :raises ValueError: 找不到匹配的文献工具时抛出。
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
    """列出网关上可用的文献 MCP 工具名。

    :param mcp_url: MCP 网关 URL。
    :param api_key: Bearer 令牌（``sk-...`` ）。
    :returns: 被识别为文献工具的工具名列表。
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
    """调用文献 MCP 工具并从文本内容中解析 JSON。

    :param mcp_url: MCP 网关 URL。
    :param api_key: Bearer 令牌（``sk-...`` ）。
    :param kind: 工具类型：``search`` 、``status`` 或 ``ingest`` 。
    :param arguments: 工具参数字典（默认为空）。
    :param timeout: 请求超时时间（秒）。
    :returns: 从工具响应解析出的 JSON 对象。
    :raises RuntimeError: 工具报告错误时抛出。
    :raises ValueError: 响应为空或不是 JSON 时抛出。
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

    # 在 transport 退出后提取并抛应用错误,避免 AnyIO 将其包装成 ExceptionGroup
    # (含 _extract_tool_json 对畸形内容抛出的 ValueError——提取也放在上下文外)。
    if result.is_error:
        message = _extract_tool_json(result) if result.content else {"error": "unknown"}
        raise RuntimeError(f"MCP tool error: {message}")
    return _extract_tool_json(result)


async def call_literature_search_mcp(
    *,
    mcp_url: str,
    api_key: str,
    arguments: dict[str, Any],
    timeout: int = 120,
) -> dict[str, Any]:
    """调用文献检索 MCP 工具。

    :param mcp_url: MCP 网关 URL。
    :param api_key: Bearer 令牌（``sk-...`` ）。
    :param arguments: 检索请求参数（``query`` 、``limit`` 、过滤器等）。
    :param timeout: 请求超时时间（秒）。
    :returns: 从网关解析出的检索结果 JSON。
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
    """调用文献状态 MCP 工具（健康状态与数据源）。

    :param mcp_url: MCP 网关 URL。
    :param api_key: Bearer 令牌（``sk-...`` ）。
    :param timeout: 请求超时时间（秒）。
    :returns: 解析出的状态 JSON（可用时包含 ``sources`` ）。
    """
    return await call_literature_mcp_tool(
        mcp_url=mcp_url,
        api_key=api_key,
        kind="status",
        arguments={},
        timeout=timeout,
    )


def mcp_gateway_origin(mcp_url: str) -> str:
    """返回网关 origin（协议 + 主机），供 REST 辅助端点使用。

    :param mcp_url: MCP 网关 URL。
    :returns: 形如 ``https://llmapi.fiblab.net`` 的 origin。
    """
    normalized = normalize_literature_mcp_url(mcp_url)
    parsed = urlparse(normalized)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _auth_headers(api_key: str) -> dict[str, str]:
    """构造可选的 Bearer 认证头。

    :param api_key: 原始 API key，可能含首尾空白字符。
    :returns: Authorization 请求头；key 为空时返回空映射。
    """
    key = api_key.strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _extract_tool_json(result: Any) -> dict[str, Any]:
    """从 MCP 工具结果中提取第一个 JSON 对象。

    :param result: 包含文本内容块的 MCP 调用结果。
    :returns: 解析后的 JSON 对象。
    :raises ValueError: 结果不含文本或不包含 JSON 对象时抛出。
    :raises json.JSONDecodeError: 类 JSON 内容格式非法时抛出。
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
