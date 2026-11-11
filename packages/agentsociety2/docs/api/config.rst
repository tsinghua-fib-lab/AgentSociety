配置模块
========

先查看实验配置模型，再按需查阅全局模型配置。环境变量说明见 :doc:`/installation`，可运行配置示例见 :doc:`/cli`。

自动生成内容中的密钥值为文档构建占位符；运行时请按安装说明设置自己的服务配置。

实验配置模型
------------

.. autoclass:: agentsociety2.society.models.InitConfig
   :members:

.. autoclass:: agentsociety2.society.models.AgentConfig
   :members:

.. autoclass:: agentsociety2.society.models.EnvModuleConfig
   :members:

.. autoclass:: agentsociety2.society.models.StepsConfig
   :members:

步骤与路由配置
--------------

.. autoclass:: agentsociety2.society.models.CodeGenRouterConfig
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.society.models.RunStep
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.society.models.AskStep
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.society.models.InterveneStep
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.society.models.QuestionnaireStep
   :no-members:
   :no-special-members:

.. autoclass:: agentsociety2.society.models.QuestionItem
   :no-members:
   :no-special-members:

LLM Router
----------

.. autoclass:: agentsociety2.config.llm_dispatcher.ThinkingSettings
   :no-members:
   :no-special-members:

.. autofunction:: agentsociety2.config.config.get_llm_router

.. autofunction:: agentsociety2.config.config.get_llm_router_and_model

Config 类
---------

.. autoclass:: agentsociety2.config.config.Config
   :members:
   :undoc-members:

工具函数
--------

.. autofunction:: agentsociety2.config.config.extract_json

.. autofunction:: agentsociety2.config.config.get_llm_thinking
