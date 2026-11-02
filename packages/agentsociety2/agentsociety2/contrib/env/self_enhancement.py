"""
Self-Enhancement Experiment Environment
Environment for Self-Enhancement (SE) experiment based on AgentSociety2
"""

import asyncio
import json
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.env.base import dump_int_map, load_int_map
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"


# Response models for tool functions
class SubmitRankingResponse(BaseModel):
    """Response model for submit_ranking() function"""

    agent_id: int = Field(..., description="Agent ID")
    dimension: str = Field(..., description="Dimension name")
    percentile: int = Field(..., description="Percentile ranking (0-100)")
    status: str = Field(..., description="Status: 'submitted' or 'completed'")


class GetRankingsResponse(BaseModel):
    """Response model for get_my_rankings() function"""

    agent_id: int = Field(..., description="Agent ID")
    rankings: dict[str, int] = Field(
        ..., description="Dictionary of dimension -> percentile"
    )
    completed_dimensions: list[str] = Field(
        ..., description="List of completed dimensions"
    )
    remaining_dimensions: list[str] = Field(
        ..., description="List of remaining dimensions"
    )


# Valid dimensions for SE experiment
VALID_DIMENSIONS = [
    "INTELLIGENCE",
    "COOPERATION",
    "APPEARANCE",
    "MORALITY",
    "SOCIABILITY",
    "HEALTH",
    "HONESTY",
    "GENEROSITY",
]


class SelfEnhancementEnv(EnvBase):
    """Environment for Self-Enhancement (SE) experiment based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("rankings", "JSON", nullable=False),
        ColumnDef("completed_dimensions", "INTEGER", nullable=False),
    ]

    def __init__(
        self,
        agent_ids: list[int],
    ):
        """
        Initialize the Self-Enhancement environment.

        :param agent_ids: List of agent IDs participating in the experiment
        """
        super().__init__()

        self.agent_ids = agent_ids
        self.num_agents = len(agent_ids)

        # Store rankings: agent_id -> dimension -> percentile
        self._rankings: dict[int, dict[str, int]] = {
            agent_id: {} for agent_id in agent_ids
        }

        self._lock = asyncio.Lock()
        self._step_counter: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。"""
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "rankings": dump_int_map(self._rankings),
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。"""
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        d = json.loads(state_path.read_text(encoding="utf-8"))
        self._rankings = {
            aid: dict(v) for aid, v in load_int_map(d.get("rankings")).items()
        }
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions and JSON schemas for data models.
        """
        description = f"""{cls.__name__}: Self-Enhancement experiment environment module.

**Description:** Manages a Self-Enhancement experiment where agents evaluate their percentile rankings (0-100) across 8 dimensions relative to Tsinghua University student population.

**Initialization Parameters (excluding llm):**
- agent_ids (List[int]): List of agent IDs participating in the experiment

**Example initialization config:**
```json
{{
  "agent_ids": [101, 102, 103]
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return (
            "Self-Enhancement experiment environment for self-evaluation assessments."
        )

    @tool(readonly=False)
    async def submit_ranking(
        self, agent_id: int, dimension: str, percentile: int
    ) -> SubmitRankingResponse:
        """
        Submit percentile ranking for a dimension.

        :param agent_id: The agent's ID
        :param dimension: The dimension name (must be one of: INTELLIGENCE, COOPERATION, APPEARANCE, MORALITY, SOCIABILITY, HEALTH, HONESTY, GENEROSITY)
        :param percentile: The percentile ranking (0-100, integer)

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Validate agent_id
            if agent_id not in self.agent_ids:
                raise ValueError(f"Agent ID {agent_id} is not in the experiment")

            # Validate dimension
            dimension_upper = dimension.upper()
            if dimension_upper not in VALID_DIMENSIONS:
                raise ValueError(
                    f"Invalid dimension: {dimension}. Must be one of: {', '.join(VALID_DIMENSIONS)}"
                )

            # Validate percentile
            if not isinstance(percentile, int):
                raise ValueError(
                    f"Percentile must be an integer, got {type(percentile).__name__}"
                )
            percentile = max(0, min(100, percentile))  # Clamp to 0-100

            # Check if already submitted
            if dimension_upper in self._rankings[agent_id]:
                raise ValueError(
                    f"Ranking for dimension {dimension_upper} has already been submitted. "
                    f"Current ranking: {self._rankings[agent_id][dimension_upper]}"
                )

            # Store the ranking
            self._rankings[agent_id][dimension_upper] = percentile

            # Check if all dimensions are completed
            completed = len(self._rankings[agent_id])
            all_completed = completed == len(VALID_DIMENSIONS)

            status = "completed" if all_completed else "submitted"

            # Debug log
            import sys

            print(
                f"[ENV DEBUG] Agent {agent_id} submitted {dimension_upper}: {percentile} "
                f"({completed}/{len(VALID_DIMENSIONS)} completed)",
                file=sys.stderr,
            )

            return SubmitRankingResponse(
                agent_id=agent_id,
                dimension=dimension_upper,
                percentile=percentile,
                status=status,
            )

    @tool(readonly=True)
    async def get_my_rankings(self, agent_id: int) -> GetRankingsResponse:
        """
        Get rankings for a specific agent.

        :param agent_id: The agent's ID

        :returns: Response containing current rankings, completed dimensions, and remaining dimensions.
        """
        async with self._lock:
            if agent_id not in self.agent_ids:
                raise ValueError(f"Agent ID {agent_id} is not in the experiment")

            rankings = self._rankings[agent_id].copy()
            completed_dimensions = list(rankings.keys())
            remaining_dimensions = [
                dim for dim in VALID_DIMENSIONS if dim not in completed_dimensions
            ]

            return GetRankingsResponse(
                agent_id=agent_id,
                rankings=rankings,
                completed_dimensions=completed_dimensions,
                remaining_dimensions=remaining_dimensions,
            )

    @tool(readonly=True, kind="statistics")
    async def get_all_rankings(self) -> dict[int, dict[str, int]]:
        """
        Get all rankings for all agents (statistics function).

        :returns: Dictionary mapping agent_id to their rankings dictionary.
        """
        async with self._lock:
            return {
                agent_id: rankings.copy()
                for agent_id, rankings in self._rankings.items()
            }

    async def init(self, start_datetime: datetime):
        """
        Initialize the environment module.
        """
        await super().init(start_datetime)
        async with self._lock:
            self._rankings = {agent_id: {} for agent_id in self.agent_ids}
            self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks (1 tick = 1 second) of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.current_datetime = t
            records = [
                {
                    "agent_id": agent_id,
                    "rankings": self._rankings[agent_id].copy(),
                    "completed_dimensions": len(self._rankings[agent_id]),
                }
                for agent_id in self.agent_ids
            ]

        await self._write_agent_state_batch(
            step=self._step_counter,
            t=t,
            records=records,
        )
        self._step_counter += 1

    def get_results(self) -> dict[int, dict[str, int]]:
        """
        Get all rankings results (synchronous method for result extraction).

        :returns: Dictionary mapping agent_id to their rankings dictionary.
        """
        return {
            agent_id: rankings.copy() for agent_id, rankings in self._rankings.items()
        }


__all__ = ["VALID_DIMENSIONS", "SelfEnhancementEnv"]
