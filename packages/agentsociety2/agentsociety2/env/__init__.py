"""环境模块 - 提供 Agent 与模拟环境交互的基础设施。

本模块包含两个核心概念：

**EnvBase** — 环境模块基类：

- 定义 Agent 可执行的操作（通过 ``@tool`` 装饰器）
- 管理环境状态
- 提供 ``observe()`` 方法供 Agent 感知环境

**RouterBase** — 路由器基类：

- 将 Agent 的自然语言指令转换为工具调用
- 支持多种路由策略（ReAct、PlanExecute、CodeGen 等）

路由器实现：

- ``ReActRouter``: ReAct 范式（推理-行动循环）
- ``PlanExecuteRouter``: 计划-执行范式
- ``CodeGenRouter``: 代码生成范式
- ``TwoTierReActRouter``: 两层 ReAct 路由
- ``TwoTierPlanExecuteRouter``: 两层计划执行路由
- ``SearchToolRouter``: 搜索工具路由

工具装饰器 ``@tool`` ：

- ``readonly=True``: 只读工具，不修改环境状态
- ``readonly=False``: 可修改环境状态的工具
- ``kind="observe"``: 观察类工具（自动调用）
- ``kind="statistics"``: 统计类工具

使用示例::

    from agentsociety2.env import EnvBase, tool

    class MyEnv(EnvBase):
        @tool(readonly=True, kind="observe")
        def get_location(self, agent_id: int) -> str:
            return self._locations.get(agent_id, "unknown")

        @tool(readonly=False)
        def move(self, agent_id: int, location: str) -> str:
            self._locations[agent_id] = location
            return f"Moved to {location}"
"""

from .base import (
    EnvBase,
    tool,
)
from .benchmark import EnvRouterBenchmarkData
from .env_router_proxy import EnvRouterProxy, create_env_router_proxy
from .router_base import RouterBase
from .router_codegen import CodeGenRouter
from .router_plan_execute import PlanExecuteRouter
from .router_react import ReActRouter
from .router_search_tool import SearchToolRouter
from .router_two_tier_plan_execute import TwoTierPlanExecuteRouter
from .router_two_tier_react import TwoTierReActRouter

__all__ = [
    "CodeGenRouter",
    "EnvBase",
    "EnvRouterBenchmarkData",
    "EnvRouterProxy",
    "PlanExecuteRouter",
    "ReActRouter",
    "RouterBase",
    "SearchToolRouter",
    "TwoTierPlanExecuteRouter",
    "TwoTierReActRouter",
    "create_env_router_proxy",
    "tool",
]
