Registry 模块
=============

注册表负责发现类、查询构造参数和扫描自定义模块。先查询当前环境返回的标识符，再写入实验配置；操作示例见 :doc:`/module_and_parameter_management`。

ModuleRegistry
--------------

.. autoclass:: agentsociety2.registry.ModuleRegistry
   :members:
   :undoc-members:
   :show-inheritance:

工具函数
--------

.. autofunction:: agentsociety2.registry.get_registry

注册函数
--------

.. autofunction:: agentsociety2.registry.get_registered_env_modules

.. autofunction:: agentsociety2.registry.get_registered_agent_modules

.. autofunction:: agentsociety2.registry.get_env_module_class

.. autofunction:: agentsociety2.registry.get_agent_module_class

.. autofunction:: agentsociety2.registry.list_all_modules

.. autofunction:: agentsociety2.registry.reload_modules

.. autofunction:: agentsociety2.registry.scan_and_register_custom_modules

.. autofunction:: agentsociety2.registry.discover_and_register_builtin_modules

请求/响应模型
-------------

.. autoclass:: agentsociety2.registry.EnvModuleInitConfig
   :members:
   :undoc-members:

.. autoclass:: agentsociety2.registry.AgentInitConfig
   :members:
   :undoc-members:

.. autoclass:: agentsociety2.registry.CreateInstanceRequest
   :members:
   :undoc-members:

.. autoclass:: agentsociety2.registry.AskRequest
   :members:
   :undoc-members:

.. autoclass:: agentsociety2.registry.InterventionRequest
   :members:
   :undoc-members:
