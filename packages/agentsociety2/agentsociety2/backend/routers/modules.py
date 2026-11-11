"""查询可用的智能体类和环境模块。

为配置编辑器提供内置模块与工作区自定义模块的元数据。模块发现与注册由 :class:`agentsociety2.registry.ModuleRegistry` 提供；HTTP 路径和参数见运行中后端的 Swagger 文档。"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agentsociety2.backend.path_security import resolve_workspace_root
from agentsociety2.logger import get_logger
from agentsociety2.registry import (
    get_registered_agent_modules,
    get_registered_env_modules,
    get_registry,
    scan_and_register_custom_modules,
)

logger = get_logger()

router = APIRouter(prefix="/api/v1/modules", tags=["modules"])


def _get_workspace_path() -> str:
    """从环境变量获取工作区路径"""
    workspace_path = os.getenv("WORKSPACE_PATH")
    if not workspace_path:
        raise HTTPException(
            status_code=400,
            detail="WORKSPACE_PATH environment variable not set",
        )
    return workspace_path


def _load_custom_modules_if_needed() -> None:
    """已配置工作区时加载自定义模块"""
    try:
        workspace_path = os.getenv("WORKSPACE_PATH")
        if workspace_path:
            registry = get_registry()
            # Only scan if not already loaded
            if not registry._custom_loaded:
                scan_and_register_custom_modules(
                    resolve_workspace_root(workspace_path), registry
                )
    except Exception as e:
        logger.warning(f"Failed to load custom modules: {e}")


@router.get("/agent_classes")
async def get_agent_classes(
    include_custom: bool = Query(True, description="是否包含自定义模块"),
) -> dict[str, Any]:
    """获取所有可用的Agent类列表

    返回系统中所有已注册的Agent类，包括内置和自定义模块。

    :param include_custom: 是否包含自定义模块，默认True

    :returns: Dict[str, Any]: 包含Agent类信息的响应： - success: 是否成功 - agents: Agent类字典，键为类型名，值为： - type: 类型名 - ``class_name``: 类名 - description: 描述 - ``is_custom``: 是否为自定义模块 - count: Agent类总数
    :raises HTTPException: 500 - 获取Agent类失败
    """
    try:
        _ = get_registry()  # 确保注册表已初始化

        # 加载自定义模块（如果需要）
        if include_custom:
            _load_custom_modules_if_needed()

        # 获取所有已注册的 Agent 类
        agents = {}
        for agent_type, agent_class in get_registered_agent_modules():
            try:
                description = agent_class.description()
            except Exception:
                description = f"{agent_class.__name__}: {agent_class.__doc__ or 'No description available'}"
            try:
                init_description = agent_class.init_description()
            except Exception:
                init_description = ""

            agents[agent_type] = {
                "type": agent_type,
                "class_name": agent_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(agent_class, "_is_custom", False),
            }

        return {
            "success": True,
            "agents": agents,
            "count": len(agents),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get agent classes: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get agent classes: {e!s}"
        ) from None


@router.get("/env_module_classes")
async def get_env_module_classes(
    include_custom: bool = Query(True, description="是否包含自定义模块"),
) -> dict[str, Any]:
    """获取所有可用的环境模块类列表

    返回系统中所有已注册的环境模块类，包括内置和自定义模块。

    :param include_custom: 是否包含自定义模块，默认True

    :returns: Dict[str, Any]: 包含环境模块类信息的响应： - success: 是否成功 - modules: 环境模块类字典，键为类型名，值为： - type: 类型名 - ``class_name``: 类名 - description: 描述 - ``is_custom``: 是否为自定义模块 - count: 模块类总数
    :raises HTTPException: 500 - 获取环境模块类失败
    """
    try:
        _ = get_registry()  # 确保注册表已初始化

        # 加载自定义模块（如果需要）
        if include_custom:
            _load_custom_modules_if_needed()

        # 获取所有已注册的 Environment 模块类
        env_modules = {}
        for module_type, env_class in get_registered_env_modules():
            try:
                description = env_class.description()
            except Exception:
                description = f"{env_class.__name__}: {env_class.__doc__ or 'No description available'}"
            try:
                init_description = env_class.init_description()
            except Exception:
                init_description = ""

            env_modules[module_type] = {
                "type": module_type,
                "class_name": env_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(env_class, "_is_custom", False),
            }

        return {
            "success": True,
            "modules": env_modules,
            "count": len(env_modules),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get env module classes: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get env module classes: {e!s}"
        ) from None


@router.get("/all")
async def get_all_modules(
    include_custom: bool = Query(True, description="是否包含自定义模块"),
) -> dict[str, Any]:
    """获取所有可用的模块类

    一次性返回所有Agent类和环境模块类，减少请求次数。

    :param include_custom: 是否包含自定义模块，默认True

    :returns: Dict[str, Any]: 包含所有模块信息的响应： - success: 是否成功 - agents: Agent类字典 - ``agent_count``: Agent类数量 - ``env_modules``: 环境模块类字典 - ``env_module_count``: 环境模块类数量
    :raises HTTPException: 500 - 获取模块失败
    """
    try:
        _ = get_registry()  # 确保注册表已初始化

        # 加载自定义模块（如果需要）
        if include_custom:
            _load_custom_modules_if_needed()

        # 获取 Agent 类
        agents = {}
        for agent_type, agent_class in get_registered_agent_modules():
            try:
                description = agent_class.description()
            except Exception:
                description = f"{agent_class.__name__}: {agent_class.__doc__ or 'No description available'}"
            try:
                init_description = agent_class.init_description()
            except Exception:
                init_description = ""

            agents[agent_type] = {
                "type": agent_type,
                "class_name": agent_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(agent_class, "_is_custom", False),
            }

        # 获取 Environment 模块类
        env_modules = {}
        for module_type, env_class in get_registered_env_modules():
            try:
                description = env_class.description()
            except Exception:
                description = f"{env_class.__name__}: {env_class.__doc__ or 'No description available'}"
            try:
                init_description = env_class.init_description()
            except Exception:
                init_description = ""

            env_modules[module_type] = {
                "type": module_type,
                "class_name": env_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(env_class, "_is_custom", False),
            }

        return {
            "success": True,
            "agents": agents,
            "agent_count": len(agents),
            "env_modules": env_modules,
            "env_module_count": len(env_modules),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get all modules: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get all modules: {e!s}"
        ) from None
