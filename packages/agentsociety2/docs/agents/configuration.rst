智能体配置与构造
================

.. _agents-configuration-2:

类继承层次
----------

当前智能体体系的类继承关系：

.. code-block:: text

   AgentBase (ABC)          # agent/base/agent.py — 所有智能体的基类
     └── PersonAgent        # agent/person.py — 面向人物仿真的默认智能体（薄编排器）

* ``AgentBase`` **直接拥有** 所有通用能力：workspace 绑定、技能运行时（``AgentSkillRuntime``）、
  ReAct 工具循环、LLM 调用、TODO 状态、trace、``AGENT.json`` 持久化。它**没有 mixin、没有多继承**。
* ``PersonAgent`` 只实现面向人物的逻辑（memory、person prompt、daily-guidance 等行为），其余全部继承自基类。
* ``contrib/agent/`` 下提供若干实验性 Agent（如博弈论场景），核心框架只依赖 ``AgentBase`` 和 ``PersonAgent``。


.. _agents-configuration-1:

构造模型（workspace 绑定的无状态 record）
-----------------------------------------

智能体通过 workspace 入口构造。``AgentBase`` 提供两个类方法入口 + 一个无参
``__init__``：

.. list-table::
   :widths: 32 68
   :header-rows: 1

   * - 入口
     - 说明
   * - ``AgentBase.create(workspace_path, profile, config)``
     - **静态写一次**：把 ``config.json`` + 初始 ``AGENT.json`` + 标准空目录写入 workspace。**不返回** agent 实例。
   * - ``await AgentBase.from_workspace(workspace_path, service_proxy)``
     - 重建 ready agent：``agent = cls()``（无参）→ ``await agent.restore(ws, proxy)`` → 返回。
   * - ``AgentBase.__init__(self)``
     - 无参。只设置空 slot，不做任何 profile 解析、不要求 id。真正初始化发生在 ``restore()``。

跨 tick 的动态状态全部落在 workspace；``step()`` 每次都从 workspace 重建上下文，因此 agent 本身是**无状态的 record**，可以被 Ray Task 当作数据流式调度到任意 worker（见 :doc:`/architecture`）。

绝大多数研究者并不直接调 ``create`` / ``from_workspace``，而是通过 ``AgentSociety`` + ``InitConfig``
声明 agent，由编排器在实验启动时批量创建（见下方 :ref:`agent-config` 与 :doc:`/cli`）。下面仅展示底层契约，便于理解与扩展：

.. code-block:: python

   from pathlib import Path
   from agentsociety2 import PersonAgent
   from agentsociety2.agent.service_proxy import ServiceProxy

   workspace = Path("run/agents/agent_0001")

   # 1) 写一次 workspace（config.json + 初始 AGENT.json）
   PersonAgent.create(
       workspace,
       profile={"id": 1, "name": "Alice", "age": 28, "bio": "A software engineer."},
       config={},
   )

   # 2) 重建 ready agent（需要 ServiceProxy 注入 env/llm/trace/replay）
   agent = await PersonAgent.from_workspace(workspace, service_proxy)


.. _agents-configuration-0:

服务注入：ServiceProxy
----------------------

``from_workspace`` 内部调用 ``_bind_services(service_proxy)``，把一个共享服务容器注入 agent：

.. list-table::
   :widths: 28 72
   :header-rows: 1

   * - slot
     - 来源 / 用途
   * - ``self._service_proxy``
     - 原始容器，持有 ``env`` / ``llm`` / ``trace`` / ``replay`` 句柄。
   * - ``self._env``
     - 环境 router（``RouterBase``），经 ``ask_env`` 访问。
   * - ``self._dispatcher``
     - 默认 LLM dispatcher（``service_proxy.llm.default``）。
   * - ``self._model_name``
     - 默认 LLM 模型名。

``ServiceProxy`` 把 env / LLM clients / trace / replay 收口为单一对象，是 Ray Task 并行执行的关键。
LLM client 只携带连接参数，worker 在本地事件循环中按需创建 litellm Router。

.. _agent-config:

.. _agents-configuration-3:

智能体配置（AgentConfig）
-------------------------

实验级的智能体配置由 :class:`~agentsociety2.society.models.AgentConfig` 描述，字段如下：

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - 字段
     - 说明
   * - ``agent_id`` (int)
     - 智能体唯一标识符。
   * - ``agent_type`` (str)
     - 智能体类型（注册表中的类名，如 ``PersonAgent``）。
   * - ``kwargs`` (dict)
     - 传给该 agent 的所有初始化参数，包含 ``profile`` 等。

它出现在 ``InitConfig.agents`` 列表里，由 CLI 的 ``--config`` JSON 提供。模型 / LLM 的选择走全局
``config``，见 :doc:`/installation` 的环境变量与 :doc:`/api/config`。

画像、运行参数与动态状态
------------------------

``profile`` 描述仿真参与者，例如标识、姓名和背景；``config`` 保存该智能体的静态运行参数。实验配置中的 ``AgentConfig.kwargs`` 是编排器创建工作区时使用的输入，具体字段应与所选智能体类匹配。

动态状态在运行后由 workspace 保存。恢复已有实验时，检查 ``AGENT.json`` 与状态文件；修改初始配置后需要明确是启动新实验，还是继续原实验，避免误以为恢复操作会重新应用所有初始值。
