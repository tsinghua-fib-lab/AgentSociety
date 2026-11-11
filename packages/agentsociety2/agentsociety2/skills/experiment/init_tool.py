"""实验配置工具

用于初始化与校验实验配置的简化工具。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentsociety2.logger import get_logger

logger = get_logger()


class ExperimentConfigTool:
    """初始化与校验实验配置的工具"""

    def __init__(
        self,
        workspace_path: str | Path,
        progress_callback: Any = None,
        tool_id: str = "",
    ):
        """初始化实验配置工具

        :param workspace_path: 工作区目录路径
        :param progress_callback: 可选的进度更新回调
        :param tool_id: 可选的工具标识符
        """
        self.workspace_path = Path(workspace_path).resolve()
        self._progress_callback = progress_callback
        self._tool_id = tool_id
        self.logger = get_logger()

    @property
    def name(self) -> str:
        return "experiment_config"

    @property
    def description(self) -> str:
        return "Initialize and validate experiment configuration"

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hypothesis_id": {"type": "string", "description": "Hypothesis ID"},
                "experiment_id": {"type": "string", "description": "Experiment ID"},
                "max_iterations": {
                    "type": "integer",
                    "description": "Max iterations for validation",
                    "default": 5,
                },
                "validate_only": {
                    "type": "boolean",
                    "description": "Only validate without modifying",
                    "default": False,
                },
            },
            "required": ["hypothesis_id", "experiment_id"],
        }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        """执行实验配置

        :param arguments: 包含 ``hypothesis_id``、``experiment_id`` 及可选参数的字典

        :returns: 含 ``success``、``content``、``error`` 字段的结果对象
        """
        hypothesis_id = arguments.get("hypothesis_id")
        experiment_id = arguments.get("experiment_id")
        validate_only = arguments.get("validate_only", False)

        from agentsociety2.skills.experiment.config import (
            get_experiment_paths,
            read_init_config,
            validate_experiment_exists,
        )

        # Validate experiment exists
        validation = validate_experiment_exists(
            self.workspace_path, hypothesis_id, experiment_id
        )

        if not validation.get("valid"):
            return _result(
                success=False,
                content=validation.get("content", ""),
                error=validation.get("error", "Validation failed"),
            )

        paths = get_experiment_paths(self.workspace_path, hypothesis_id, experiment_id)
        init_config_file = paths["init_config"]

        if validate_only:
            # Only validate existing config
            if init_config_file.exists():
                init_config = read_init_config(paths["experiment"])
                if init_config:
                    return _result(
                        success=True,
                        content=f"Experiment config is valid.\n"
                        f"Hypothesis: {hypothesis_id}\n"
                        f"Experiment: {experiment_id}\n"
                        f"Config file: {init_config_file}",
                    )
                else:
                    return _result(
                        success=False,
                        content="Config file exists but could not be parsed",
                        error="Invalid config format",
                    )
            else:
                return _result(
                    success=False,
                    content=f"No config file found at {init_config_file}",
                    error="Config not found",
                )

        # Initialize config (create basic structure)
        if init_config_file.exists():
            return _result(
                success=True,
                content=f"Experiment already initialized.\nConfig: {init_config_file}",
            )

        # Create init directory and basic config
        paths["init"].mkdir(parents=True, exist_ok=True)
        (paths["init"] / "results").mkdir(exist_ok=True)

        # Create a basic init_config.json
        basic_config = {
            "hypothesis_id": hypothesis_id,
            "experiment_id": experiment_id,
            "created_at": str(Path(__file__).stat().st_mtime),
            "status": "initialized",
        }

        init_config_file.write_text(
            json.dumps(basic_config, indent=2), encoding="utf-8"
        )

        return _result(
            success=True,
            content=f"Experiment config initialized.\n"
            f"Hypothesis: {hypothesis_id}\n"
            f"Experiment: {experiment_id}\n"
            f"Config file: {init_config_file}",
        )


def _result(success: bool, content: str, error: str | None = None) -> Any:
    """创建与 ToolResult 兼容的结果对象"""

    # Use a simple class since we can't import the original ToolResult
    class SimpleResult:
        def __init__(self, success: bool, content: str, error: str | None = None):
            self.success = success
            self.content = content
            self.error = error

    return SimpleResult(success, content, error)
