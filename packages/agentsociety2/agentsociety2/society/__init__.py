"""社会模拟模块 - 提供多 Agent 模拟的核心编排功能。

本模块包含：

**AgentSociety** — 主模拟编排器：

- 管理 Agent 和 Environment 的生命周期
- 执行模拟步骤（tick-by-tick）
- 协调 Agent 与环境的交互
- 管理环境 replay writer，并协调 agent workspace 生命周期

**AgentSocietyHelper** — 计划执行助手：

- 处理外部问题和干预
- 提供便捷的 ask/intervene 接口

**配置模型**：

- ``InitConfig``: 初始化配置（Agent、Env、LLM 配置等）
- ``StepsConfig``: 步骤配置（Ask/Intervene/Run 操作序列）
- ``AgentConfig``: Agent 配置
- ``EnvModuleConfig``: 环境模块配置

使用示例::

    from agentsociety2.society import AgentSociety, InitConfig, StepsConfig

    # 加载配置
    config = InitConfig.from_file("config.json")
    steps = StepsConfig.from_file("steps.yaml")

    # 创建并运行模拟
    society = AgentSociety(config)
    await society.run(steps)
"""

from .helper import AgentSocietyHelper
from .models import (
    AgentConfig,
    AskStep,
    EnvModuleConfig,
    InitConfig,
    InterveneStep,
    QuestionItem,
    QuestionnaireStep,
    RunStep,
    StepsConfig,
    StepUnion,
)
from .questionnaire import (
    AgentQuestionnaireResult,
    Questionnaire,
    QuestionnaireAnswer,
    QuestionnaireResponse,
)
from .society import AgentSociety

__all__ = [
    "AgentConfig",
    "AgentQuestionnaireResult",
    "AgentSociety",
    "AgentSocietyHelper",
    "AskStep",
    "EnvModuleConfig",
    "InitConfig",
    "InterveneStep",
    "QuestionItem",
    "Questionnaire",
    "QuestionnaireAnswer",
    "QuestionnaireResponse",
    "QuestionnaireStep",
    "RunStep",
    "StepUnion",
    "StepsConfig",
]
