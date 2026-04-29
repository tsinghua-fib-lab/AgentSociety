"""Agent模块 - 提供智能体核心类和基础设施。

核心组件
========

**AgentBase**
    智能体抽象基类，定义基本接口。

**PersonAgent**
    技能优先型Agent实现，支持独立工作区和渐进式技能发现。

配置管理
========

**AgentConfig**
    统一配置管理，整合模型、循环、上下文、持久化、并发等所有配置。

    >>> from agentsociety2.agent import AgentConfig
    >>> config = AgentConfig()  # 使用默认值
    >>> config.model.context_window  # 200000

持久化
======

**Checkpoint** - 检查点管理，支持崩溃恢复
**WriteAheadLog** - 预写日志，确保精确恢复
**WorkspaceCleaner** - 工作区清理
**SessionRecovery** - 会话恢复上下文构建

并发控制
========

**ParallelExecutor** - 并行工具执行器
**RateLimiter** - 令牌桶限流器
**TaskManager** - 后台任务管理器
"""

from .base import AgentBase
from .person import PersonAgent
from .config import (
    AgentConfig,
    ModelConfig,
    LoopConfig,
    ContextConfig,
    PersistenceConfig,
    ConcurrencyConfig,
    LoopDetectionConfig,
    StateConfig,
    ALLOWED_ENV_VARS,
)
from .prompt_builder import PromptBuilder, PromptCacheManager, ToolTableBuilder
from .persistence import (
    Checkpoint,
    WriteAheadLog,
    WorkspaceCleaner,
    SessionRecovery,
    IntentStatus,
)
from .concurrent import (
    Priority,
    PrioritizedTask,
    PriorityScheduler,
    ParallelExecutor,
    RateLimiter,
    TaskManager,
    DeadlockDetector,
)
from .context import AgentMemory

__all__ = [
    # 核心类
    "AgentBase",
    "PersonAgent",
    # 配置
    "AgentConfig",
    "ModelConfig",
    "LoopConfig",
    "ContextConfig",
    "PersistenceConfig",
    "ConcurrencyConfig",
    "LoopDetectionConfig",
    "StateConfig",
    "ALLOWED_ENV_VARS",
    # Prompt
    "PromptBuilder",
    "PromptCacheManager",
    "ToolTableBuilder",
    # 持久化
    "Checkpoint",
    "WriteAheadLog",
    "WorkspaceCleaner",
    "SessionRecovery",
    "IntentStatus",
    # 并发
    "Priority",
    "PrioritizedTask",
    "PriorityScheduler",
    "ParallelExecutor",
    "RateLimiter",
    "TaskManager",
    "DeadlockDetector",
    # 上下文
    "AgentMemory",
]
