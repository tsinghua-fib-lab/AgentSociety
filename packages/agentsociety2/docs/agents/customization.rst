编写自定义智能体
================

.. _agents-customization-13:

自定义智能体
~~~~~~~~~~~~

.. note::

   扩展 ``PersonAgent`` 的认知能力，优先使用 Agent Skills（见 :doc:`/agent_skills`）。只有需要完全不同的智能体架构时，才创建自定义智能体类。

要创建自定义智能体，继承 ``AgentBase`` 并实现抽象方法，覆盖 ``restore`` 追加业务状态。不要重写
``__init__``；状态在 ``restore`` 里设。

.. _agents-customization-12:

AgentBase 抽象 / 推荐覆盖的方法
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: 40 60
   :header-rows: 1

   * - 方法
     - 说明
   * - ``ask(self, message, readonly=True, *, t=None)``
     - **必须实现**。通过 agent 的推理流程回答外部问题。
   * - ``step(self, tick, t)``
     - **必须实现**。执行一个仿真步。
   * - ``to_workspace(self, workspace_path)``
     - **必须实现**。把当前动态状态写回 workspace。
   * - ``restore(self, workspace_path, service_proxy)``
     - 推荐覆盖：在 ``await super().restore(...)`` 之后追加业务状态恢复。
   * - ``build_react_messages(...)``
     - 复用基类 ``run_react_loop`` 时**必须覆盖**：构造 ReAct 提示词（chat messages）。
   * - ``build_agent_json(*, tick, t)``
     - 推荐覆盖：扩展 ``AGENT.json`` 字段（先 ``data = super().build_agent_json(...)`` 再追加）。
   * - ``dispatch_react_tool(action, args, *, readonly=False)``
     - 推荐覆盖：增加工具前缀（如 ``memory_*`` / ``todo_*``），未命中转发给 ``super()``。

最小子类示例：

.. code-block:: python

   from datetime import datetime
   from pathlib import Path
   from typing import Any

   from agentsociety2.agent.base import AgentBase


   class MinimalAgent(AgentBase):
       """最小子类：自定义状态 + 复用基类 ReAct 循环。"""

       async def restore(self, workspace_path: Path, service_proxy: Any) -> None:
           await super().restore(workspace_path, service_proxy)  # 先恢复 workspace / 服务 / 技能
           import json
           state_file = self.workspace_root_path() / "state/custom.json"
           data = json.loads(state_file.read_text()) if state_file.exists() else {}
           self._custom_counter = int(data.get("counter", 0))

       def build_react_messages(self, *, tick, t, observations, question=None,
                                readonly=False, skill_hooks=None):
           system = f"You are agent {self.name} (id={self.id}). tick={tick}, t={t.isoformat()}."
           user = question or "Decide next action."
           return [{"role": "system", "content": system},
                   {"role": "user", "content": user}]

       async def to_workspace(self, workspace_path: Path) -> None:
           import json
           from agentsociety2.storage.workspace_state import atomic_write_text
           atomic_write_text(
               self.workspace_root_path() / "state/custom.json",
               json.dumps({"counter": self._custom_counter}),
           )
           self.persist_agent_json(tick=None, t=self._current_time)

       async def ask(self, message: str, readonly: bool = True, *, t=None) -> str:
           current = t or self._current_time or datetime.now()
           return await self.run_react_loop(tick=0, t=current, observations=[], question=message, readonly=readonly)

       async def step(self, tick: int, t: datetime) -> str:
           self._current_time = t
           self._custom_counter += 1
           return await self.run_react_loop(tick=tick, t=t)

子类可直接调用的基类公开 API 还包括：``run_react_loop``、``acompletion``、``run_lifecycle_hooks``、
``discover_skill_sources``、``persist_agent_json``、``trace_span``、``ask_env``、``get_profile``、
``skill_runtime``，以及 ``self.id`` / ``self.name`` / ``self.logger`` 等属性。完整清单见
:doc:`/api/agent` 与源码 ``agent/base/README.md``。
