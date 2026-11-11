"""面向数据集驱动导出与分析的回放元数据定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ReplayDatasetKind = Literal[
    "entity_snapshot",
    "entity_static",
    "env_snapshot",
    "event_stream",
    "metric_series",
]

DATASET_CATALOG_TABLE = "replay_dataset_catalog"
COLUMN_CATALOG_TABLE = "replay_column_catalog"
AGENT_PROFILE_DATASET_ID = "core.agent_profile"
AGENT_PROFILE_TABLE_NAME = "core_agent_profile"
AGENT_PROFILE_DATASET_CAPABILITY = "agent_profile"

# Society-owned timeline markers so replay UI has steps even before env
# modules finish writing per-tick agent/env snapshots.
SIMULATION_TIMELINE_DATASET_ID = "core.simulation_timeline"
SIMULATION_TIMELINE_TABLE_NAME = "core_simulation_timeline"
SIMULATION_TIMELINE_CAPABILITY = "simulation_timeline"

# Society-owned per-agent step failure records: a partially-failed tick
# otherwise leaves the failed agents' workspaces a step behind with no
# trace of what happened (the tick-level RuntimeError only surfaces in
# logs). One row per (step, agent) failure.
STEP_FAILURE_DATASET_ID = "core.step_failures"
STEP_FAILURE_TABLE_NAME = "core_step_failures"
STEP_FAILURE_CAPABILITY = "step_failures"


@dataclass
class ReplayDatasetSpec:
    """回放数据集的语义元数据（底层为 JSONL 表分片集合）。"""

    dataset_id: str
    table_name: str
    module_name: str
    kind: ReplayDatasetKind
    title: str = ""
    description: str = ""
    entity_key: str | None = None
    step_key: str | None = None
    time_key: str | None = None
    default_order: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    version: int = 1
