环境模块
========

本页用于查环境基类、路由器与代理接口。工具的只读属性、并发声明和持久化约定见 :doc:`/env_modules`；执行后端的限制见 :doc:`/codegen_execution`。

RouterBase
----------

.. autoclass:: agentsociety2.env.router_base.RouterBase
   :members:
   :undoc-members:
   :show-inheritance:

EnvBase
-------

.. autoclass:: agentsociety2.env.base.EnvBase
   :members:
   :undoc-members:
   :show-inheritance:

工具装饰器
----------

.. autofunction:: agentsociety2.env.base.tool

TokenUsageStats
---------------

.. autoclass:: agentsociety2.env.router_base.TokenUsageStats
   :members:
   :undoc-members:

CacheStats
----------

.. autoclass:: agentsociety2.env.router_codegen.CacheStats
   :members:
   :undoc-members:

内置路由器
----------

ReActRouter
~~~~~~~~~~~

.. autoclass:: agentsociety2.env.router_react.ReActRouter
   :members:
   :undoc-members:
   :show-inheritance:

PlanExecuteRouter
~~~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.env.router_plan_execute.PlanExecuteRouter
   :members:
   :undoc-members:
   :show-inheritance:

CodeGenRouter
~~~~~~~~~~~~~

.. autoclass:: agentsociety2.env.router_codegen.CodeGenRouter
   :members:
   :undoc-members:
   :show-inheritance:

TwoTierReActRouter
~~~~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.env.router_two_tier_react.TwoTierReActRouter
   :members:
   :undoc-members:
   :show-inheritance:

TwoTierPlanExecuteRouter
~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.env.router_two_tier_plan_execute.TwoTierPlanExecuteRouter
   :members:
   :undoc-members:
   :show-inheritance:

SearchToolRouter
~~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.env.router_search_tool.SearchToolRouter
   :members:
   :undoc-members:
   :show-inheritance:

环境路由 Actor
--------------

生产环境下环境路由跑在一个专用的 Ray actor 里（由 ``get_env_router_actor_class`` 动态创建），
agent 通过 ``EnvRouterProxy`` 句柄与之交互。

EnvRouterProxy
~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.env.env_router_proxy.EnvRouterProxy
   :members:
   :undoc-members:

.. autofunction:: agentsociety2.env.env_router_actor.get_env_router_actor_class

各路由器的选择与权衡见 :doc:`/architecture`。
