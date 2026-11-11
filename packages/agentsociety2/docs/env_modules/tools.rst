创建环境模块与工具
==================

.. _env-modules-tools-6:

创建自定义模块
--------------

.. _env-modules-tools-5:

继承 EnvBase
~~~~~~~~~~~~

要创建自定义环境模块，请继承 ``EnvBase`` 并实现必需的方法：

.. _env-modules-tools-4:

需要实现的方法
^^^^^^^^^^^^^^

创建自定义环境模块时，必须实现：

1. **async def step(self, tick: int, t: datetime) -> None**

   执行一个模拟步骤。在 AgentSociety 模拟期间自动调用。使用此方法更新时间相关的状态。

   参数:
       tick: 此步骤的持续时间（秒）
       t: 此步骤开始时的模拟日期时间；全部智能体与环境推进后，编排器再将时钟增加 tick

2. **使用 @tool 装饰的工具**

   使用 ``@tool`` 装饰器将方法公开为智能体的可调用函数。

   .. code-block:: python

      from datetime import datetime
      from agentsociety2.env import EnvBase, tool

      class MyModule(EnvBase):
          def __init__(self):
              super().__init__()
              self._values: dict[int, int] = {}

          @tool(readonly=True, kind="observe")
          def get_value(self, agent_id: int) -> str:
              """Get a value for an agent."""
              return f"Value for agent {agent_id}"

          @tool(readonly=False)
          def set_value(self, agent_id: int, value: int) -> str:
              """Set a value for an agent."""
              self._values[agent_id] = value
              return f"Set value for agent {agent_id}"

          async def step(self, tick: int, t: datetime) -> None:
              self.t = t

.. _env-modules-tools-3:

参考实现
^^^^^^^^

有关完整的参考实现，请参阅：

* ``SimpleSocialSpace`` - 社交互动模块
* ``PublicGoodsEnv`` - 公共物品博弈模块
* ``PrisonersDilemmaEnv`` - 囚徒困境模块

.. _env-modules-tools-2:

@tool 装饰器
~~~~~~~~~~~~

``@tool`` 装饰器将方法标记为可被智能体调用：

.. code-block:: python

   from agentsociety2.env import tool

   @tool(readonly=True, kind="observe")
   def get_status(self, agent_id: int) -> str:
       """Get the status of an agent."""
       return f"Agent {agent_id} status"

``readonly=True`` 表示查询，``readonly=False`` 表示可能修改状态。``kind`` 控制工具是否参与自动观察或统计收集：

* ``observe``：只读，除 ``self`` 外最多一个参数，用于按智能体收集观察。
* ``statistics``：只读，除 ``self`` 外没有参数，用于收集整体统计。
* 未设置 ``kind``：常规工具，可以只读或读写，由路由器按请求调用。

工具的类型注解和 docstring 用于生成调用说明。返回值应包含足够的信息，让智能体能够判断操作结果；缺少输入或操作失败时给出明确原因。

.. _env-modules-tools-1:

并发安全
~~~~~~~~

环境模块可覆盖类方法 ``is_concurrency_safe() -> bool``（默认 ``False``）：

* 返回 ``True``：工具只触达 per-agent / 已自带锁保护的状态，可与其它 ask 并行执行。
* 当**挂载的全部模块**都返回 ``True`` 时：

  * CLI / ``EnvRouterProxy`` 创建的 Ray actor 使用
    ``AGENTSOCIETY_ENV_ACTOR_MAX_CONCURRENCY`` （默认 ``64``）作为 ``max_concurrency``；
  * ``CodeGenRouter`` 跳过全局 ``_execute_lock``，改依赖各模块本地锁。
* 任一模块不安全时，actor 退回 ``max_concurrency=1``，保证串行正确性。

.. _env-modules-tools-0:

工具类型
--------

* **observe**: 单参数观察（需要 readonly=True）
* **statistics**: 聚合查询（无参数，需要 readonly=True）
* **regular**: 任何其他工具（可以是只读或读写）

有关工具类型的更多详情，请参阅 :doc:`/concepts`。

.. _env-modules-tools-9:

注册模块
--------

环境模块没有 ``register_module`` 之类的注册方法，只能在构造 router 时通过
``env_modules`` 参数挂载：

.. code-block:: python

   from agentsociety2.env import CodeGenRouter

   router = CodeGenRouter(env_modules=[MyModule()])

   # Or mount multiple modules at once
   router = CodeGenRouter(env_modules=[MyModule(), MyOtherModule()])

.. _env-modules-tools-8:

完整示例
--------

.. code-block:: python

   from typing import Dict
   from pathlib import Path
   from datetime import datetime
   from agentsociety2.env import EnvBase, tool, CodeGenRouter
   from agentsociety2 import PersonAgent
   from agentsociety2.society import AgentSociety

   class WeatherEnvironment(EnvBase):
       """A simple weather environment module."""

       def __init__(self):
           super().__init__()
           self._weather = "sunny"
           self._temperature = 25
           self._agent_locations: Dict[int, str] = {}

       @tool(readonly=True, kind="observe")
       def get_weather(self, agent_id: int) -> str:
           """Get the current weather for an agent's location."""
           location = self._agent_locations.get(agent_id, "unknown")
           return f"The weather in {location} is {self._weather} with {self._temperature}°C."

       @tool(readonly=False)
       def change_weather(self, weather: str, temperature: int) -> str:
           """Change the weather conditions."""
           self._weather = weather
           self._temperature = temperature
           return f"Weather changed to {weather} at {temperature}°C."

       async def step(self, tick: int, t: datetime) -> None:
           """Update environment state for one simulation step."""
           self.t = t
           # Update time-dependent state here if needed

   # Use the custom module（agent 以 spec 声明，不实例化）
   env_router = CodeGenRouter(env_modules=[WeatherEnvironment()])

   agent_specs = [{"id": 1, "profile": {"name": "Bob"}, "config": {}}]

   society = AgentSociety(
       agent_specs=agent_specs,
       agent_class_name="PersonAgent",
       env_router=env_router,
       start_t=datetime.now(),
       run_dir=Path("run"),
   )
   await society.init()

.. note::

   生产环境下环境路由跑在一个专用的 Ray actor 里（``EnvRouterProxy``），所有 agent 共享一份环境状态；也可在进程内直接用 ``CodeGenRouter``。除默认的 ``CodeGenRouter`` 外还有
   ``ReActRouter`` / ``PlanExecuteRouter`` / ``TwoTierReActRouter`` / ``TwoTierPlanExecuteRouter``
   / ``SearchToolRouter`` 可选（见 :doc:`/architecture`）。

.. _env-modules-tools-7:

示例
----

请参阅 ``agentsociety2.contrib.env`` 中的内置环境类（类名以当前代码为准）：

* ``SimpleSocialSpace`` — 社交互动
* ``WeatherEnvironment`` — 天气查询 / 干预（onboarding 见 ``examples/basics/02_custom_env_module.py``）
* ``PublicGoodsEnv`` — 公共物品博弈
* ``PrisonersDilemmaEnv`` — 囚徒困境
* ``TrustGameEnv`` — 信任博弈
