"""实验数据模型

用于实验配置与执行的 Pydantic 模型。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Agent ``kwargs`` keys split into the static runtime config record.
#: Shared by the CLI, experiment-config checks, and agent tooling.
AGENT_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "max_react_turns",
        "enable_memory",
        "enable_todo_list",
        "idle_skip_enabled",
        "disabled_skill_ids",
        "default_activated_skill_ids",
        "extra_skill_paths",
    }
)


def split_agent_kwargs(agent_id: int, kwargs: dict) -> tuple[dict, dict]:
    """Build workspace records from flat or explicitly nested agent settings."""
    fields = dict(kwargs)
    profile = fields.pop("profile", {})
    config = fields.pop("config", {})
    if not isinstance(profile, dict) or not isinstance(config, dict):
        raise ValueError("Agent profile and config must be objects")
    if any(int(record.get("id", agent_id)) != agent_id for record in (fields, profile)):
        raise ValueError(f"agent_id ({agent_id}) and profile/kwargs.id must match")
    flat_config = {key: fields.pop(key) for key in AGENT_CONFIG_KEYS if key in fields}
    return {**fields, **profile, "id": agent_id}, {**flat_config, **config}


class ExperimentConfig(BaseModel):
    """实验配置模型

    单次实验运行的基础配置。
    """

    model_config = ConfigDict(extra="allow")

    hypothesis_id: str = Field(..., description="Hypothesis ID (e.g., '1', '2')")
    experiment_id: str = Field(..., description="Experiment ID (e.g., '1', '2')")
    run_id: str = Field(default="run", description="Run ID (default: 'run')")

    agent_classes: list[str] = Field(
        default_factory=list, description="List of agent class types to use"
    )
    env_modules: list[str] = Field(
        default_factory=list, description="List of environment module types to use"
    )

    user_instructions: str | None = Field(
        None, description="Additional user instructions for configuration"
    )


class ExperimentStatus(BaseModel):
    """实验执行状态模型

    表示一次运行中或已完成实验的当前状态。
    """

    model_config = ConfigDict(extra="allow")

    hypothesis_id: str = Field(..., description="Hypothesis ID")
    experiment_id: str = Field(..., description="Experiment ID")
    run_id: str = Field(..., description="Run ID")

    status: str = Field(
        ..., description="Status: starting, running, completed, failed, stopped"
    )
    pid: int | None = Field(None, description="Process ID if running")

    start_time: str | None = Field(None, description="Start time (ISO format)")
    end_time: str | None = Field(None, description="End time (ISO format)")

    stdout_log: str | None = Field(None, description="Path to stdout log file")
    stderr_log: str | None = Field(None, description="Path to stderr log file")

    is_running: bool = Field(
        default=False, description="Whether the process is currently running"
    )


class ExperimentInfo(BaseModel):
    """实验信息

    实验配置与状态的摘要。
    """

    model_config = ConfigDict(extra="allow")

    hypothesis_id: str
    experiment_id: str
    run_id: str = "run"

    has_init: bool = Field(
        default=False, description="Whether init configuration exists"
    )
    has_run: bool = Field(default=False, description="Whether run directory exists")

    status: str | None = Field(None, description="Current status")
    pid: int | None = Field(None, description="Process ID if running")
    is_running: bool = Field(default=False, description="Whether process is running")
