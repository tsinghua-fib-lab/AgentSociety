"""模块自动发现与注册。

该模块负责：

- 自动发现并注册 ``contrib`` 下的内置环境模块与 agent；
- 扫描并注册 ``custom`` 下的用户自定义模块；
- 提供一组便捷函数给后端/CLI 调用（list/reload/get）。
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase
from agentsociety2.env.base import EnvBase
from agentsociety2.logger import get_logger
from agentsociety2.registry.base import ModuleRegistry, get_registry

logger = get_logger()


def _load_custom_class(
    *,
    file_path: str,
    class_name: str,
    module_prefix: str,
) -> type[Any]:
    """从 workspace 文件加载自定义类。

    :param file_path: 文件路径。
    :param class_name: 目标类名。
    :param module_prefix: 注入到 sys.modules 的模块名前缀（用于隔离）。
    :returns: 加载到的 class 对象。
    :raises ImportError: 无法构建 import spec 时抛出。
    """

    spec = importlib.util.spec_from_file_location(
        f"{module_prefix}_{class_name}",
        file_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to create spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    module_name = f"{module_prefix}_{class_name}"
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def register_scanned_custom_modules(
    scan_result: dict[str, Any],
    registry: ModuleRegistry | None = None,
) -> dict[str, Any]:
    """注册 scanner 已发现的自定义模块。

    :param scan_result: scanner 输出（包含 envs/agents/errors）。
    :param registry: 可选注册中心；为空则使用全局 registry。
    :returns: 更新后的 ``scan_result``（会追加 ``registration_errors``）。
    """

    if registry is None:
        registry = get_registry()

    registration_errors: list[str] = list(scan_result.get("registration_errors", []))

    for env_info in scan_result.get("envs", []):
        try:
            env_class = _load_custom_class(
                file_path=env_info["file_path"],
                class_name=env_info["class_name"],
                module_prefix="custom_env",
            )
            env_class._is_custom = True
            registry.register_env_module(
                env_info["class_name"],
                env_class,
                is_custom=True,
            )
        except Exception as exc:
            registration_errors.append(
                f"Env module {env_info.get('class_name')}: registration failed"
            )
            logger.warning(
                f"Failed to register custom env module {env_info.get('class_name')}: {exc}"
            )

    for agent_info in scan_result.get("agents", []):
        try:
            agent_class = _load_custom_class(
                file_path=agent_info["file_path"],
                class_name=agent_info["class_name"],
                module_prefix="custom_agent",
            )
            agent_class._is_custom = True
            registry.register_agent_module(
                agent_info["class_name"],
                agent_class,
                is_custom=True,
            )
        except Exception as exc:
            registration_errors.append(
                f"Agent {agent_info.get('class_name')}: registration failed"
            )
            logger.warning(
                f"Failed to register custom agent {agent_info.get('class_name')}: {exc}"
            )

    scan_result["registration_errors"] = registration_errors
    return scan_result


def _discover_contrib_env_modules() -> dict[str, type[EnvBase]]:
    """发现 contrib.env 下所有环境模块。

    :returns: ``{class_name: class}`` 映射。
    """
    modules = {}

    try:
        from agentsociety2.contrib import env as env_package

        # Walk through all modules in contrib.env
        for _importer, modname, _ispkg in pkgutil.walk_packages(
            env_package.__path__, env_package.__name__ + "."
        ):
            if modname.startswith("__"):
                continue

            try:
                module = importlib.import_module(modname)

                # Find EnvBase subclasses in this module
                for name, obj in vars(module).items():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, EnvBase)
                        and obj is not EnvBase
                        and obj.__module__ == modname
                    ):
                        # Use class name directly as the key
                        if name and name not in modules:
                            modules[name] = obj
                            logger.debug(f"Discovered env module: {name}")

            except Exception as e:
                logger.debug(f"Failed to import {modname}: {e}")

    except ImportError as e:
        logger.warning(f"Failed to import contrib.env: {e}")

    return modules


def _discover_contrib_agents() -> dict[str, type[AgentBase]]:
    """发现 contrib.agent 下所有 agent 类。

    :returns: ``{class_name: class}`` 映射。
    """
    agents = {}

    try:
        from agentsociety2.contrib import agent as agent_package

        # Walk through all modules in contrib.agent
        for _importer, modname, _ispkg in pkgutil.walk_packages(
            agent_package.__path__, agent_package.__name__ + "."
        ):
            if modname.startswith("__"):
                continue

            try:
                module = importlib.import_module(modname)

                # Find AgentBase subclasses in this module
                for name, obj in vars(module).items():
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, AgentBase)
                        and obj is not AgentBase
                        and obj.__module__ == modname
                    ):
                        # Use class name directly as the key
                        if name and name not in agents:
                            agents[name] = obj
                            logger.debug(f"Discovered agent: {name}")

            except Exception as e:
                logger.debug(f"Failed to import {modname}: {e}")

    except ImportError as e:
        logger.warning(f"Failed to import contrib.agent: {e}")

    return agents


def _discover_builtin_agents() -> dict[str, type[AgentBase]]:
    """发现内置 agent。"""
    agents = {}

    try:
        from agentsociety2.agent import PersonAgent

        agents["PersonAgent"] = PersonAgent
        logger.debug("Discovered built-in agent: PersonAgent")

    except ImportError as e:
        logger.warning(f"Failed to import agentsociety2.agent: {e}")

    return agents


def _class_name_to_type(class_name: str) -> str | None:
    """将类名转换为 type identifier（CamelCase -> ``snake_case``）。"""
    import re

    # Handle special cases
    if class_name == "LLMDonorAgent":
        return "llm_donor_agent"
    if class_name == "SocialMediaSpace":
        return "social_media"

    # Convert CamelCase to snake_case
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", class_name)
    snake_case = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Remove trailing "_agent" or "_env" if present
    if snake_case.endswith("_agent"):
        snake_case = snake_case[:-6] + "_agent"
    elif snake_case.endswith("_environment"):
        snake_case = snake_case[:-12]

    return snake_case


def discover_and_register_builtin_modules(
    registry: ModuleRegistry | None = None,
) -> None:
    """发现并注册所有内置模块（contrib + 内置 agent）。

    :param registry: 可选注册中心；为空则使用全局 registry。
    """
    if registry is None:
        registry = get_registry()

    # Discover and register environment modules
    env_modules = _discover_contrib_env_modules()
    for module_type, module_class in env_modules.items():
        registry.register_env_module(module_type, module_class, is_custom=False)

    # Discover and register agents
    agents = {}
    agents.update(_discover_contrib_agents())
    agents.update(_discover_builtin_agents())

    for agent_type, agent_class in agents.items():
        registry.register_agent_module(agent_type, agent_class, is_custom=False)

    logger.info(
        f"Registered {len(env_modules)} env modules and {len(agents)} agents "
        f"from built-in modules"
    )


def scan_and_register_custom_modules(
    workspace_path: Path, registry: ModuleRegistry | None = None
) -> dict[str, Any]:
    """扫描并注册 custom/ 下的自定义模块。

    :param workspace_path: workspace 路径。
    :param registry: 可选注册中心；为空则使用全局 registry。
    :returns: scan 结果（包含 envs/agents/errors）。
    """
    if registry is None:
        registry = get_registry()

    # Clear any previously registered custom modules to avoid accumulation
    # when user changes class names or module structure
    registry.clear_custom_modules()

    registry.set_workspace(workspace_path)

    from agentsociety2.backend.services.custom.scanner import CustomModuleScanner

    scanner = CustomModuleScanner(str(workspace_path))
    scan_result = scanner.scan_all()
    scan_result = register_scanned_custom_modules(scan_result, registry)

    logger.info(
        f"Registered {len(scan_result.get('envs', []))} custom env modules and "
        f"{len(scan_result.get('agents', []))} custom agents"
    )

    return scan_result


# Convenience functions


def get_registered_env_modules() -> list[tuple[str, type[EnvBase]]]:
    """:returns: 已注册环境模块列表 ``[(module_type, module_class), ...]`` 。"""
    return get_registry().list_env_modules()


def get_registered_agent_modules() -> list[tuple[str, type[AgentBase]]]:
    """:returns: 已注册 agent 列表 ``[(agent_type, agent_class), ...]`` 。"""
    return get_registry().list_agent_modules()


def get_env_module_class(module_type: str) -> type[EnvBase] | None:
    """按 type 获取环境模块类。

    :param module_type: 类型标识。
    :returns: 环境模块 class；未找到返回 ``None`` 。
    """
    return get_registry().get_env_module(module_type)


def get_agent_module_class(agent_type: str) -> type[AgentBase] | None:
    """按 type 获取 agent 类。

    :param agent_type: 类型标识。
    :returns: agent class；未找到返回 ``None`` 。
    """
    return get_registry().get_agent_module(agent_type)


def list_all_modules() -> dict[str, list[dict[str, Any]]]:
    """列出所有已注册模块（含描述与是否 custom 标记）。"""
    registry = get_registry()

    env_modules = []
    for module_type, module_class in registry.list_env_modules():
        try:
            description = module_class.description()
        except Exception:
            description = ""
        try:
            init_description = module_class.init_description()
        except Exception:
            init_description = ""
        env_modules.append(
            {
                "type": module_type,
                "class_name": module_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(module_class, "_is_custom", False),
            }
        )

    agents = []
    for agent_type, agent_class in registry.list_agent_modules():
        try:
            description = agent_class.description()
        except Exception:
            description = ""
        try:
            init_description = agent_class.init_description()
        except Exception:
            init_description = ""
        agents.append(
            {
                "type": agent_type,
                "class_name": agent_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(agent_class, "_is_custom", False),
            }
        )

    return {
        "env_modules": env_modules,
        "agents": agents,
    }


def reload_modules(workspace_path: Path | None = None) -> None:
    """清空并重新发现模块（按需加载）。

    :param workspace_path: 可选 workspace 路径（用于 custom 模块）。
    """
    registry = get_registry()

    # Clear registry
    registry._env_modules.clear()
    registry._agent_modules.clear()

    # Reset lazy loading flags
    registry._builtin_loaded = False
    registry._custom_loaded = False

    # Set workspace if provided
    if workspace_path:
        registry.set_workspace(workspace_path)

    logger.info("Module registry cleared (modules will be loaded on demand)")
