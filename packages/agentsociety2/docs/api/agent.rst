Agent 模块
==========

本页用于查智能体生命周期、工作区与交互方法。构造流程和可运行示例见 :doc:`/agents`；新增人物行为时，先判断是否只需编写 :doc:`/agent_skills`。

记忆存储与配置类型见 :doc:`memory`；技能注册与运行时见 :doc:`skills`。

.. py:module:: agentsociety2.agent.base

核心类
------

AgentBase
~~~~~~~~~

.. autoclass:: agentsociety2.agent.base.AgentBase
   :members:
   :undoc-members:
   :show-inheritance:

PersonAgent
~~~~~~~~~~~

.. autoclass:: agentsociety2.agent.person.PersonAgent
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__

``AgentBase`` 直接拥有 workspace 绑定、技能运行时、ReAct 工具循环、TODO 状态、trace 与
``AGENT.json`` 持久化等通用能力。``PersonAgent`` 是其上的薄编排器，只实现面向人物的行为逻辑。智能体不再通过 ``__init__`` 传参构造，而是经 ``AgentBase.create()`` 写一次 workspace、再经
``await AgentBase.from_workspace(path, service_proxy)`` 重建（详见 :doc:`/agents`）。

如果只是扩展人物行为，优先新增或修改 Agent Skill（见 :doc:`/agent_skills`，API 参考见
:doc:`/api/skills`）；只有需要改变智能体生命周期、状态机或外部系统调用方式时，才继承
``AgentBase`` / ``PersonAgent`` 创建新类。

工具结果与工作区访问
--------------------

.. autoclass:: agentsociety2.agent.base.react.ReactDecision
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.agent.base.react.ReactToolResult
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.agent.base.workspace_fs.WorkspaceFS
   :no-members:
   :no-special-members:
