"""模块注册中心（agent/env 的集中注册与惰性发现）。"""

from __future__ import annotations

import inspect
import os
from importlib import import_module
from pathlib import Path
from typing import Any, Self

from agentsociety2.agent.base import AgentBase
from agentsociety2.backend.path_security import resolve_workspace_root
from agentsociety2.env.base import EnvBase
from agentsociety2.logger import get_logger

logger = get_logger()


class ModuleRegistry:
    """agent 与环境模块的集中注册中心（单例）。

    支持两类来源：

    - 内置模块：来自 ``agentsociety2.contrib`` 与内置 agent（例如 PersonAgent）
    - 自定义模块：来自 workspace 的 ``custom/`` 目录

    默认启用惰性加载：只有在第一次访问 registry 内容时才触发发现与注册。
    """

    _instance: ModuleRegistry | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._env_modules: dict[str, type[EnvBase]] = {}
        self._agent_modules: dict[str, type[AgentBase]] = {}
        self._workspace_path: Path | None = None

        # Lazy loading flags
        self._builtin_loaded: bool = False
        self._custom_loaded: bool = False
        self._lazy_enabled: bool = True  # Can be disabled to force eager loading

        logger.info("ModuleRegistry initialized (lazy loading enabled)")

    def _ensure_builtin_loaded(self) -> None:
        """确保内置模块已加载（惰性加载触发点）。"""
        if not self._lazy_enabled:
            return
        if self._builtin_loaded:
            return

        modules = import_module("agentsociety2.registry.modules")
        modules.discover_and_register_builtin_modules(self)
        self._builtin_loaded = True

    def _ensure_custom_loaded(self) -> None:
        """确保自定义模块已加载（惰性加载触发点）。"""
        if not self._lazy_enabled:
            return
        if self._custom_loaded:
            return

        workspace_path = self._resolve_workspace_path()
        if workspace_path is None:
            # No workspace set, nothing to load
            self._custom_loaded = True
            return

        modules = import_module("agentsociety2.registry.modules")
        modules.scan_and_register_custom_modules(workspace_path, self)
        self._custom_loaded = True

    def _ensure_loaded(self) -> None:
        """确保内置与自定义模块都已加载（惰性加载触发点）。"""
        self._ensure_builtin_loaded()
        self._ensure_custom_loaded()

    @property
    def env_modules(self) -> dict[str, type[EnvBase]]:
        """返回已注册环境模块映射，并在访问时触发惰性加载。"""
        self._ensure_loaded()
        return self._env_modules.copy()

    @property
    def agent_modules(self) -> dict[str, type[AgentBase]]:
        """返回已注册 agent 映射，并在访问时触发惰性加载。"""
        self._ensure_loaded()
        return self._agent_modules.copy()

    def register_env_module(
        self, module_type: str, module_class: type[EnvBase], is_custom: bool = False
    ) -> None:
        """注册环境模块。

        :param module_type: type identifier（例如 ``simple_social_space``）。
        :param module_class: 环境模块类。
        :param is_custom: 是否为自定义模块。
        """
        if module_type in self._env_modules and not is_custom:
            logger.debug(f"Env module '{module_type}' already registered, skipping")
            return

        self._env_modules[module_type] = module_class
        logger.debug(f"Registered env module: {module_type} -> {module_class.__name__}")

    def register_agent_module(
        self, agent_type: str, agent_class: type[AgentBase], is_custom: bool = False
    ) -> None:
        """注册 agent。

        :param agent_type: type identifier（例如 ``person_agent``）。
        :param agent_class: agent 类。
        :param is_custom: 是否为自定义 agent。
        """
        if agent_type in self._agent_modules and not is_custom:
            logger.debug(f"Agent '{agent_type}' already registered, skipping")
            return

        self._agent_modules[agent_type] = agent_class
        logger.debug(f"Registered agent: {agent_type} -> {agent_class.__name__}")

    def get_env_module(self, module_type: str) -> type[EnvBase] | None:
        """按 type 获取环境模块类（会触发惰性加载）。

        :param module_type: type identifier。
        :returns: 环境模块类；未找到返回 ``None``。
        """
        self._ensure_loaded()
        return self._env_modules.get(module_type)

    def get_agent_module(self, agent_type: str) -> type[AgentBase] | None:
        """按 type 获取 agent 类（会触发惰性加载）。

        :param agent_type: type identifier。
        :returns: agent 类；未找到返回 ``None``。
        """
        self._ensure_loaded()
        return self._agent_modules.get(agent_type)

    def list_env_modules(self) -> list[tuple[str, type[EnvBase]]]:
        """返回已注册环境模块列表，并在访问时触发惰性加载。"""
        self._ensure_loaded()
        return list(self._env_modules.items())

    def list_agent_modules(self) -> list[tuple[str, type[AgentBase]]]:
        """返回已注册 agent 列表，并在访问时触发惰性加载。"""
        self._ensure_loaded()
        return list(self._agent_modules.items())

    def set_workspace(self, workspace_path: Path) -> None:
        """设置 workspace 路径（用于 custom 模块发现）。

        :param workspace_path: workspace 目录。
        """
        self._workspace_path = resolve_workspace_root(str(workspace_path))
        # Reset custom loaded flag so modules will be discovered on next access
        self._custom_loaded = False
        logger.debug(f"Registry workspace set to: {self._workspace_path}")

    def _resolve_workspace_path(self) -> Path | None:
        """返回用于 custom 模块发现的 workspace 路径；若无法推断则返回 ``None``。"""

        if self._workspace_path is not None:
            return self._workspace_path

        env_workspace = os.getenv("WORKSPACE_PATH")
        if env_workspace:
            self._workspace_path = resolve_workspace_root(env_workspace)
            logger.debug(
                f"Registry workspace inferred from WORKSPACE_PATH: {self._workspace_path}"
            )
            return self._workspace_path

        cwd = Path.cwd().resolve()
        candidates = [cwd, *cwd.parents]
        for candidate in candidates:
            if (candidate / "custom" / "envs").exists() or (
                candidate / "custom" / "agents"
            ).exists():
                self._workspace_path = candidate
                logger.debug(
                    f"Registry workspace inferred from cwd: {self._workspace_path}"
                )
                return self._workspace_path

        return None

    def load_builtin_modules(self) -> None:
        """主动加载内置模块（禁用惰性等待）。"""
        self._ensure_builtin_loaded()

    def load_custom_modules(self) -> None:
        """主动加载自定义模块（禁用惰性等待）。"""
        self._ensure_custom_loaded()

    def load_all_modules(self) -> None:
        """主动加载全部模块（内置 + 自定义）。"""
        self._ensure_loaded()

    def clear_custom_modules(self) -> None:
        """清除 registry 中所有 custom 模块。"""
        to_remove = [
            mt
            for mt, mc in self._env_modules.items()
            if getattr(mc, "_is_custom", False)
        ]
        for mt in to_remove:
            del self._env_modules[mt]

        to_remove = [
            at
            for at, ac in self._agent_modules.items()
            if getattr(ac, "_is_custom", False)
        ]
        for at in to_remove:
            del self._agent_modules[at]

        # Reset custom loaded flag so modules will be re-discovered on next access
        self._custom_loaded = False

        logger.info(f"Cleared {len(to_remove)} custom modules")

    def get_module_info(self, module_type: str, kind: str) -> dict[str, Any]:
        """获取模块信息（会触发惰性加载）。

        :param module_type: type identifier。
        :param kind: ``env_module`` 或 ``agent``。
        :returns: 模块信息字典（含参数签名、描述、是否 custom 等）。
        """
        self._ensure_builtin_loaded()

        if kind == "env_module":
            cls = self.get_env_module(module_type)
        else:
            cls = self.get_agent_module(module_type)

        if cls is None:
            return {
                "success": False,
                "error": f"Module '{module_type}' not found",
            }

        # Try to get AI-facing descriptions
        description = ""
        init_description = ""
        try:
            description = cls.description()
        except Exception:
            description = f"{cls.__name__}"
        try:
            init_description = cls.init_description()
        except Exception:
            init_description = ""

        # Get constructor signature
        params = {}
        try:
            sig = inspect.signature(cls.__init__)
            for name, param in list(sig.parameters.items())[1:]:  # Skip 'self'
                params[name] = {
                    "annotation": (
                        str(param.annotation)
                        if param.annotation != inspect.Parameter.empty
                        else "Any"
                    ),
                    "default": (
                        str(param.default)
                        if param.default != inspect.Parameter.empty
                        else None
                    ),
                    "kind": str(param.kind),
                }
        except Exception:
            logger.debug("Failed to inspect signature for tool", exc_info=True)

        return {
            "success": True,
            "type": module_type,
            "class_name": cls.__name__,
            "description": description,
            "init_description": init_description,
            "parameters": params,
            "is_custom": getattr(cls, "_is_custom", False),
        }


# Global registry instance
_registry: ModuleRegistry | None = None


def get_registry() -> ModuleRegistry:
    """:returns: 全局 :class:`~agentsociety2.registry.base.ModuleRegistry` 单例。"""
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry
