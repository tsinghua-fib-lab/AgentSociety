"""AgentSociety 2 - 现代化的 LLM-native 智能体仿真平台。

本包提供构建和仿真 LLM 驱动智能体的工具，用于社会科学研究。

主要组件
--------

**Agent 模块**:
- ``AgentBase``: 智能体抽象基类
- ``PersonAgent``: skills-first 智能体

**Env 模块**:
- ``EnvBase``: 环境模块基类
- ``RouterBase``: 路由器基类
- ``ReActRouter``: ReAct 范式路由器
- ``PlanExecuteRouter``: 计划-执行路由器
- ``CodeGenRouter``: 代码生成路由器
- ``TwoTierReActRouter``: 两层 ReAct 路由器
- ``TwoTierPlanExecuteRouter``: 两层计划执行路由器
- ``SearchToolRouter``: 搜索工具路由器
- ``tool``: 工具装饰器

**Society 模块**:
- ``AgentSociety``: 主模拟编排器（位于 ``agentsociety2.society``）
- ``AgentSocietyHelper``: 模拟编排助手（顶层 re-export）

**Storage 模块**:
- ``ReplayWriter``: 环境回放数据写入器

使用示例::

    from agentsociety2 import AgentBase, PersonAgent, EnvBase, tool
    from agentsociety2.society import AgentSociety

    # 定义自定义环境
    class MyEnv(EnvBase):
        @tool(readonly=True)
        def get_status(self) -> str:
            return "ok"

    # 定义自定义智能体
    class MyAgent(AgentBase):
        async def step(self, tick: int, t) -> str:
            return "done"
        # ... 其他抽象方法
"""

from __future__ import annotations

import os
from importlib import import_module
from typing import TYPE_CHECKING

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

__version__ = "2.9.3"

__all__ = [
    "AgentBase",
    "AgentSocietyHelper",
    "CodeGenRouter",
    "EnvBase",
    "PersonAgent",
    "PlanExecuteRouter",
    "ReActRouter",
    "ReplayWriter",
    "RouterBase",
    "SearchToolRouter",
    "TwoTierPlanExecuteRouter",
    "TwoTierReActRouter",
    "tool",
]

# 仅在访问公开对象时加载其实现；轻量上下文导入不启动整个 SDK。
_EXPORT_MODULES = {
    "AgentBase": "agentsociety2.agent",
    "PersonAgent": "agentsociety2.agent",
    "CodeGenRouter": "agentsociety2.env",
    "EnvBase": "agentsociety2.env",
    "PlanExecuteRouter": "agentsociety2.env",
    "ReActRouter": "agentsociety2.env",
    "RouterBase": "agentsociety2.env",
    "SearchToolRouter": "agentsociety2.env",
    "TwoTierPlanExecuteRouter": "agentsociety2.env",
    "TwoTierReActRouter": "agentsociety2.env",
    "tool": "agentsociety2.env",
    "AgentSocietyHelper": "agentsociety2.society",
    "ReplayWriter": "agentsociety2.storage",
}

if TYPE_CHECKING:
    from .agent import AgentBase, PersonAgent
    from .env import (
        CodeGenRouter,
        EnvBase,
        PlanExecuteRouter,
        ReActRouter,
        RouterBase,
        SearchToolRouter,
        TwoTierPlanExecuteRouter,
        TwoTierReActRouter,
        tool,
    )
    from .society import AgentSocietyHelper
    from .storage import ReplayWriter


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
