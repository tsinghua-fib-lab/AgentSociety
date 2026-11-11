智能体记忆
==========

本页介绍 ``agentsociety2.agent`` 公开导出的记忆存储、配置与结果类型。一般使用 ``PersonAgent`` 时由智能体管理记忆；需要接入自定义存储流程时再使用这些接口。工作区生命周期见 :doc:`/agents`。

存储与检索
----------

.. autoclass:: agentsociety2.agent.memory.AgentMemoryStore
   :members: ensure, read_memory_md, append_episodes, recent, search, read_ids, range
   :no-special-members:

配置与结果
----------

.. autoclass:: agentsociety2.agent.memory.MemoryConsolidationConfig
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.agent.memory_runtime.MemoryRuntimeConfig
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.agent.memory.MemoryExtractionResult
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.agent.memory.MemoryConsolidationResult
   :no-members:
   :no-special-members:

.. autodata:: agentsociety2.agent.memory.MemoryEpisodeType
   :annotation:

运行时集成
----------

.. autoclass:: agentsociety2.agent.memory_runtime.PersonMemoryRuntime
   :no-members:
   :no-special-members:
