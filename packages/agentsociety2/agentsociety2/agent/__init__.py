"""Agent subsystem.

中文：导出当前主线 Agent API。
English: Exports the current Agent API.
"""

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "AgentBase",
    "AgentMemoryStore",
    "MemoryConsolidationConfig",
    "MemoryConsolidationResult",
    "MemoryEpisodeType",
    "MemoryExtractionResult",
    "MemoryRuntimeConfig",
    "PersonAgent",
    "PersonMemoryRuntime",
    "ReactDecision",
    "ReactToolResult",
]

# 仅在访问公开对象时加载其实现；轻量上下文导入不启动整个 SDK。
_EXPORT_MODULES = {
    "AgentBase": "agentsociety2.agent.base",
    "ReactDecision": "agentsociety2.agent.base",
    "ReactToolResult": "agentsociety2.agent.base",
    "AgentMemoryStore": "agentsociety2.agent.memory",
    "MemoryConsolidationConfig": "agentsociety2.agent.memory",
    "MemoryConsolidationResult": "agentsociety2.agent.memory",
    "MemoryEpisodeType": "agentsociety2.agent.memory",
    "MemoryExtractionResult": "agentsociety2.agent.memory",
    "MemoryRuntimeConfig": "agentsociety2.agent.memory_runtime",
    "PersonMemoryRuntime": "agentsociety2.agent.memory_runtime",
    "PersonAgent": "agentsociety2.agent.person",
}

if TYPE_CHECKING:
    from agentsociety2.agent.base import AgentBase, ReactDecision, ReactToolResult
    from agentsociety2.agent.memory import (
        AgentMemoryStore,
        MemoryConsolidationConfig,
        MemoryConsolidationResult,
        MemoryEpisodeType,
        MemoryExtractionResult,
    )
    from agentsociety2.agent.memory_runtime import (
        MemoryRuntimeConfig,
        PersonMemoryRuntime,
    )
    from agentsociety2.agent.person import (
        PersonAgent,
    )


def __getattr__(name: str):
    """按需解析公开导出，并缓存对象以保持导入身份一致。

    :param name: 公开导出名称。
    :returns: 对应实现模块中的对象。
    :raises AttributeError: 名称不属于公开导出。
    """
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """列出已有属性及尚未加载的公开导出。"""
    return sorted(set(globals()) | set(__all__))
