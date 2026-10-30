"""``agent.base`` 包——通用 agent 运行时基类。

中文:提供 ``AgentBase``(所有 agent 的基类)与 ReAct 数据类。
English: Provides ``AgentBase`` (the base class for all agents) plus the
ReAct dataclasses.

再导出:

- :class:`AgentBase`(``from agentsociety2.agent.base import AgentBase``)。
- :class:`ReactDecision` 与 :class:`ReactToolResult`(来自 ``react``)。
"""

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "AgentBase",
    "ReactDecision",
    "ReactToolResult",
    "ReactTurn",
    "TodoStateStore",
]

# 仅在访问公开对象时加载其实现；轻量上下文导入不启动整个 SDK。
_EXPORT_MODULES = {
    "AgentBase": "agentsociety2.agent.base.agent",
    "ReactDecision": "agentsociety2.agent.base.react",
    "ReactToolResult": "agentsociety2.agent.base.react",
    "ReactTurn": "agentsociety2.agent.base.react",
    "TodoStateStore": "agentsociety2.agent.base.todo",
}

if TYPE_CHECKING:
    from agentsociety2.agent.base.agent import AgentBase
    from agentsociety2.agent.base.react import (
        ReactDecision,
        ReactToolResult,
        ReactTurn,
    )
    from agentsociety2.agent.base.todo import TodoStateStore


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
