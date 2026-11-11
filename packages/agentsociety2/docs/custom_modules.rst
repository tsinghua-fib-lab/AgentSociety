自定义模块
==============

AgentSociety 2 支持创建和注册自定义智能体和环境模块，允许您使用自己的模拟组件扩展平台。

概述
--------

自定义模块系统允许您：

* 创建具有专门行为的自定义智能体类
* 创建具有特定领域工具的自定义环境模块
* 通过 API 自动发现和注册模块
* 使用自动生成的测试脚本测试自定义模块
* 通过注册表接入现有 AgentSociety 仿真
* 通过扩展技能 ``agentsociety-create-env-module`` 的 Progressive Disclosure workflow 持久化需求、设计和验证产物

AI 助手生成 Python 模块后，需要扫描、验证并检查状态恢复，再通过标准工具接口接入路由器。

目录结构
-------------------

自定义模块放置在工作区内的 ``custom/`` 目录中::

   workspace/
   ├── custom/                    # User-created directory
   │   ├── agents/                # Custom agent classes
   │   │   └── my_agent.py
   │   └── envs/                  # Custom environment modules
   │       └── my_env.py
   └── .agentsociety/             # Auto-generated configuration
       ├── agent_classes/
       ├── env_modules/
       └── custom_env_skill/
           └── runs/

创建自定义智能体
-------------------------

所有自定义智能体必须继承 ``AgentBase``。智能体是 workspace 绑定的无状态 record：状态在
``restore()`` 里恢复、在 ``to_workspace()`` 里写回；详见 :doc:`agents`。

.. code-block:: python

   from pathlib import Path
   from agentsociety2.agent.base import AgentBase
   from datetime import datetime
   from typing import Any

   class MyAgent(AgentBase):
       """My custom Agent"""

       @classmethod
       def description(cls) -> str:
           return "MyAgent: A custom agent for specific tasks"

       async def restore(self, workspace_path: Path, service_proxy: Any) -> None:
           """恢复 workspace / 服务 / 技能，再追加自定义状态。"""
           await super().restore(workspace_path, service_proxy)
           import json
           state_file = self.workspace_root_path() / "state/custom.json"
           self._custom_state = json.loads(state_file.read_text()) if state_file.exists() else {}

       async def ask(self, message: str, readonly: bool = True, *, t=None) -> str:
           """Respond to questions from the environment"""
           prompt = f"Question: {message}\nPlease answer:"
           response = await self.acompletion([{"role": "user", "content": prompt}])
           return response.choices[0].message.content or ""

       async def step(self, tick: int, t: datetime) -> str:
           """Execute one simulation step"""
           self._current_time = t
           return f"Agent {self.id} executing step {tick}"

       async def to_workspace(self, workspace_path: Path) -> None:
           """把动态状态写回 workspace（AGENT.json 等）。"""
           import json
           from agentsociety2.storage.workspace_state import atomic_write_text
           atomic_write_text(
               self.workspace_root_path() / "state/custom.json",
               json.dumps(self._custom_state, ensure_ascii=False),
           )
           self.persist_agent_json(tick=None, t=self._current_time)

必需方法
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Method
     - Description
   * - ``description()``
     - 返回模块简短描述（类方法，默认取类 docstring 首行，可不覆盖；可选覆盖
       ``init_description()`` 提供更完整的初始化指引）
   * - ``ask()``
     - 回答环境的问题（必须实现）
   * - ``step()``
     - 执行一个模拟步骤（必须实现）
   * - ``to_workspace()``
     - 把动态状态写回 workspace（必须实现）
   * - ``restore()``
     - 在 ``await super().restore(...)`` 之后恢复自定义状态（推荐覆盖）

创建自定义环境
------------------------------

自定义环境必须继承 ``EnvBase`` 并使用 ``@tool`` 装饰器注册方法：

.. code-block:: python

   from agentsociety2.env import EnvBase, tool
   from datetime import datetime

   class MyEnv(EnvBase):
       """My custom environment"""

       def __init__(self, config=None):
           super().__init__()
           # Initialize your environment state

       @classmethod
       def description(cls) -> str:
           return "MyEnv: A custom environment"

       @tool(readonly=True, kind="observe")
       async def get_state(self, agent_id: int) -> dict:
           """Get current environment state (observation tool)"""
           return {"agent_id": agent_id, "state": "normal"}

       @tool(readonly=False)
       async def do_action(self, agent_id: int, action: str) -> dict:
           """Perform an action (modification tool)"""
           return {"agent_id": agent_id, "action": action, "result": "success"}

       async def step(self, tick: int, t: datetime):
           """Environment step"""
           self.t = t

       async def to_workspace(self, workspace_path=None) -> None:
           """把动态状态写入 workspace；覆盖此方法可支持 resume，详见 :doc:`env_modules`。"""
           if workspace_path is not None:
               self._bind_workspace(workspace_path)

       async def restore(self, workspace_path) -> bool:
           """从 workspace 恢复动态状态；resume 时调用，默认返回 False。"""
           self._bind_workspace(workspace_path)
           return False

现实兼容约束
~~~~~~~~~~~~~~~~~~~

生成的自定义环境模块仍然必须遵循当前仓库的真实兼容约束：

* 文件必须位于 ``custom/envs/*.py``
* 类定义必须直接位于该文件中，不能只做 re-export
* 注册 key 继续使用 ``class_name``
* 至少存在一个合法 ``@tool``
* ``step()`` 必须存在
* 构造参数应与实验配置中的 ``kwargs`` 一致；示例可使用无参构造以便检查
* 若模块需要观察能力，应提供 ``@tool(readonly=True, kind='observe')`` 观察工具
* 建议提供信息完整的 ``description()`` （或直接写好类 docstring 首行）；未覆盖时会显示基类默认描述
* 若模块带动态内存态且希望支持中断续跑，应覆盖 ``to_workspace`` 和 ``restore``。使用
  ``--resume`` 时，模块应能从 ``state/ENV_STATE.json`` 恢复状态（见 :doc:`env_modules` 的「状态持久化与 resume」）。

.. note::

   扫描器会跳过路径中包含 ``examples/`` 的文件（示例仅供参考，不参与注册）。

@tool 装饰器
~~~~~~~~~~~~~~~~~~~

``@tool`` 装饰器将方法注册为智能体可访问的工具：

.. list-table::
   :header-rows: 1

   * - Parameter
     - Description
   * - ``readonly=True``
     - 工具不修改环境状态
   * - ``readonly=False``
     - 工具可以修改环境状态
   * - ``kind="observe"``
     - 观察工具（单个 ``agent_id`` 参数，readonly=True）
   * - ``kind="statistics"``
     - 统计工具（无参数，readonly=True）
   * - ``kind=None``
     - 常规工具（任何参数，可以只读或读写）

注册自定义模块
---------------------------

创建自定义模块后，使用 API 注册它们：

**扫描并注册**

.. code-block:: bash

   curl -X POST http://localhost:8001/api/v1/custom/scan \
     -H "Content-Type: application/json" \
     -d '{"workspace_path": "/path/to/workspace"}'

**列出已注册的模块**

.. code-block:: bash

   curl "http://localhost:8001/api/v1/custom/list?workspace_path=/path/to/workspace"

**测试自定义模块**

.. code-block:: bash

   curl -X POST http://localhost:8001/api/v1/custom/test \
     -H "Content-Type: application/json" \
     -d '{"workspace_path": "/path/to/workspace"}'

**生成自定义环境（扩展技能）**

自定义环境的生成流程不走后端 HTTP，而是由扩展内置的 Claude Code 技能
``agentsociety-create-env-module`` 驱动：经 intake → clarify → design → generate →
validate 五个 stage（``stages/``）推进，并由 ``scripts/validate.py`` 做 scanner /
tester / registry 端到端校验。运行产物（需求、设计、``validation_report.json`` 等）落在工作区的 ``.agentsociety/custom_env_skill/runs/<run_id>/`` 下。

API 端点
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Endpoint
     - Method
     - Description
   * - ``/api/v1/custom/scan``
     - POST
     - 扫描并注册自定义模块
   * - ``/api/v1/custom/test``
     - POST
     - 测试自定义模块
   * - ``/api/v1/custom/clean``
     - POST
     - 清理自定义模块配置
   * - ``/api/v1/custom/list``
     - GET
     - 列出已注册的自定义模块
   * - ``/api/v1/custom/status``
     - GET
     - 获取模块状态概述
   * - ``/api/v1/custom/classes``
     - GET
     - 列出可用的 Agent 与环境模块类（含 ``has_prefill`` 标记）
   * - ``/api/v1/custom/rescan``
     - POST
     - 清除内存中的旧自定义模块并重新扫描工作区

示例
--------

示例智能体和环境可在 ``custom/`` 目录中找到：

* ``custom/agents/examples/simple_agent.py`` - 基本智能体示例
* ``custom/agents/examples/advanced_agent.py`` - 具有记忆和情绪的智能体
* ``custom/envs/examples/simple_env.py`` - 计数器环境
* ``custom/envs/examples/advanced_env.py`` - 资源管理环境

这些示例演示了创建自定义模块的最佳实践。

配置
-------------

设置 ``WORKSPACE_PATH`` 环境变量以指向您的工作区：

.. code-block:: bash

   export WORKSPACE_PATH=/path/to/workspace

或添加到您的 ``.env`` 文件：

.. code-block:: ini

   WORKSPACE_PATH=/path/to/workspace

此设置告诉系统在哪里找到 ``custom/`` 目录。

最佳实践
--------------

**命名约定**

* 智能体类名应以 ``Agent`` 结尾
* 环境类名应以 ``Env`` 结尾
* 文件名应使用小写字母和下划线：``my_agent.py``

**错误处理**

* 返回有意义的错误消息
* 对关键路径保留必要日志，便于复盘与定位问题

**状态管理**

* 使用 ``restore()`` 从 workspace 恢复状态，使用 ``to_workspace()`` 写回动态状态
* 自定义 Agent 覆盖 ``restore()`` 时应先调用 ``await super().restore(...)``，以绑定 workspace、技能运行时和服务句柄
* 在回放中记录重要的状态更改
* 保持状态可序列化（JSON 兼容）

**工具设计**

* 对只读观察使用 ``kind="observe"``
* 对聚合数据使用 ``kind="statistics"``
* 对操作使用 ``kind=None`` 和 ``readonly=False``
* 生成后优先通过技能 run 产物（``.agentsociety/custom_env_skill/runs/<run_id>/``）中的 ``validation_report.json`` 定位失败原因
