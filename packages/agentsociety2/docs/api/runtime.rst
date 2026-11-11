共享服务与追踪
==============

本页补充智能体、路由与存储接口共同使用的运行时类型。系统中的连接方式见 :doc:`/architecture`；一般实验优先使用 :doc:`society` 的编排器入口。

服务容器
--------

.. autoclass:: agentsociety2.agent.service_proxy.ServiceProxy
   :members: take_token_stats
   :no-special-members:

.. autoclass:: agentsociety2.agent.service_proxy.LLMClients
   :no-members:
   :no-special-members:

LLM 连接与并发
--------------

.. py:module:: agentsociety2.config.llm_dispatcher

.. autoclass:: agentsociety2.config.llm_dispatcher.LLMClient
   :members: call, take_token_stats
   :no-special-members:

.. autoclass:: agentsociety2.config.llm_dispatcher.AdaptiveSemaphore
   :no-members:
   :no-special-members:

追踪句柄与写入
--------------

.. py:module:: agentsociety2.trace

.. autoclass:: agentsociety2.trace.TraceSpan
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.trace.sharded_writer.JsonlTraceWriter
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.trace.sharded_writer.ShardedAppendSink
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.trace.sharded_writer.TraceProxy
   :no-members:
   :no-special-members:

.. autofunction:: agentsociety2.trace.sharded_writer.build_local_sink
