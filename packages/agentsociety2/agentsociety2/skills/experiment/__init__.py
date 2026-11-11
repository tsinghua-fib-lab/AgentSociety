"""实验执行技能

提供实验执行与结果管理能力。
"""

from .claude_integration import (
    format_module_suggestion_message,
    generate_hypothesis_config,
    get_experiment_template,
    suggest_modules_for_topic,
    validate_experiment_ready,
)
from .init_tool import ExperimentConfigTool
from .models import ExperimentConfig, ExperimentInfo, ExperimentStatus
from .module_discovery import (
    get_available_agent_modules,
    get_available_env_modules,
    get_module_selection_guidance,
    get_modules_summary,
    validate_hypothesis_modules,
    validate_module_selection,
)
from .runner import (
    get_experiment_status,
    list_experiments,
    start_experiment,
    stop_experiment,
)

__all__ = [
    "ExperimentConfig",
    "ExperimentConfigTool",
    "ExperimentInfo",
    "ExperimentStatus",
    "format_module_suggestion_message",
    "generate_hypothesis_config",
    "get_available_agent_modules",
    # Module discovery
    "get_available_env_modules",
    "get_experiment_status",
    "get_experiment_template",
    "get_module_selection_guidance",
    "get_modules_summary",
    "list_experiments",
    "start_experiment",
    "stop_experiment",
    # Claude Code integration
    "suggest_modules_for_topic",
    "validate_experiment_ready",
    "validate_hypothesis_modules",
    "validate_module_selection",
]
