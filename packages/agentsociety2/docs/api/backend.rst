Backend API 模块
================

本页介绍后端模块与请求模型的 Python 接口。HTTP 接口的访问、Swagger 调试与请求示例见 :doc:`http`；工作区与跨域配置见 :doc:`/installation`。

FastAPI 应用
------------

.. automodule:: agentsociety2.backend.app
   :members:
   :undoc-members:

服务启动
--------

.. automodule:: agentsociety2.backend.run
   :members:

路由模块
--------

预填充参数路由
~~~~~~~~~~~~~~

.. automodule:: agentsociety2.backend.routers.prefill_params
   :members:
   :undoc-members:

实验路由
~~~~~~~~

.. automodule:: agentsociety2.backend.routers.experiments
   :members:
   :undoc-members:

回放路由
~~~~~~~~

.. automodule:: agentsociety2.backend.routers.replay
   :members:
   :undoc-members:

自定义模块路由
~~~~~~~~~~~~~~

.. automodule:: agentsociety2.backend.routers.custom
   :members:
   :undoc-members:

模块路由
~~~~~~~~

.. automodule:: agentsociety2.backend.routers.modules
   :members:
   :undoc-members:

Agent Skills 路由
~~~~~~~~~~~~~~~~~

.. automodule:: agentsociety2.backend.routers.agent_skills
   :members:
   :undoc-members:

请求/响应模型
-------------

SkillItem
~~~~~~~~~

.. autoclass:: agentsociety2.backend.routers.agent_skills.SkillItem
   :members:
   :no-index:

ListResponse
~~~~~~~~~~~~

.. autoclass:: agentsociety2.backend.routers.agent_skills.ListResponse
   :members:
   :no-index:
