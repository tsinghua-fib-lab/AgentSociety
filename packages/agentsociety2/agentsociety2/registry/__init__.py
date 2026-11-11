"""模块注册中心 - 提供 Agent 类和环境模块的集中注册管理。

本模块支持：

- 内置模块（来自 contrib 目录）
- 自定义模块（来自 custom 目录）

主要功能
--------

- **ModuleRegistry**: 模块注册中心类
- **get_registry**: 获取全局注册中心实例
- **get_registered_env_modules**: 获取已注册的环境模块列表
- **get_registered_agent_modules**: 获取已注册的 Agent 模块列表
- **get_env_module_class**: 根据名称获取环境模块类
- **get_agent_module_class**: 根据名称获取 Agent 模块类
- **list_all_modules**: 列出所有已注册模块
- **reload_modules**: 重新加载所有模块
- **scan_and_register_custom_modules**: 扫描并注册自定义模块
- **discover_and_register_builtin_modules**: 发现并注册内置模块

实现延迟加载 - 模块只在首次访问时才被发现。
"""

from agentsociety2.registry.base import ModuleRegistry, get_registry
from agentsociety2.registry.models import (
    AgentInitConfig,
    AskRequest,
    CreateInstanceRequest,
    EnvModuleInitConfig,
    InterventionRequest,
)
from agentsociety2.registry.modules import (
    discover_and_register_builtin_modules,
    get_agent_module_class,
    get_env_module_class,
    get_registered_agent_modules,
    get_registered_env_modules,
    list_all_modules,
    register_scanned_custom_modules,
    reload_modules,
    scan_and_register_custom_modules,
)

__all__ = [
    "AgentInitConfig",
    "AskRequest",
    "CreateInstanceRequest",
    # Models
    "EnvModuleInitConfig",
    "InterventionRequest",
    # Registry
    "ModuleRegistry",
    "discover_and_register_builtin_modules",
    "get_agent_module_class",
    "get_env_module_class",
    "get_registered_agent_modules",
    "get_registered_env_modules",
    "get_registry",
    "list_all_modules",
    "register_scanned_custom_modules",
    "reload_modules",
    "scan_and_register_custom_modules",
]
