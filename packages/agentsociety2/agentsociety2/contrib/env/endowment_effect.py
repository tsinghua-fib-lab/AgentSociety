"""
Endowment Effect Experiment Environment
Environment for Endowment Effect experiment based on AgentSociety2
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
class SubmitWTAWTPResponse(BaseModel):
    """Response model for submit_wta_wtp() function"""

    agent_id: int = Field(..., description="Agent ID")
    item: str = Field(..., description="Item name")
    wta: float = Field(..., description="Willingness to Accept price")
    wtp: float = Field(..., description="Willingness to Pay price")
    status: str = Field(..., description="Status: 'submitted' or 'completed'")


class GetMyEvaluationsResponse(BaseModel):
    """Response model for get_my_evaluations() function"""

    agent_id: int = Field(..., description="Agent ID")
    evaluations: dict[str, dict[str, float]] = Field(
        ..., description="Dictionary of item -> {'wta': float, 'wtp': float}"
    )
    completed_items: list[str] = Field(..., description="List of completed items")
    remaining_items: list[str] = Field(..., description="List of remaining items")


class EndowmentEffectEnv(EnvBase):
    """Environment for Endowment Effect experiment based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    # Valid items for the experiment
    VALID_ITEMS: ClassVar[list[str]] = ["pen", "plate", "glass", "doll"]
    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("evaluations", "JSON", nullable=False),
        ColumnDef("completed_items", "INTEGER", nullable=False),
    ]

    def __init__(self, agent_ids: list[int]):
        """
        Initialize the Endowment Effect environment.

        :param agent_ids: List of agent IDs participating in the experiment
        """
        super().__init__()

        self.agent_ids = agent_ids
        self.num_agents = len(agent_ids)

        # Store evaluations: {agent_id: {item: {"wta": float, "wtp": float}}}
        self._evaluations: dict[int, dict[str, dict[str, float]]] = {
            agent_id: {} for agent_id in agent_ids
        }

        self._lock = asyncio.Lock()
        self._step_counter: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。int 键 dict 用 dump 形式。"""
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "evaluations": dump_int_map(self._evaluations),
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
        self._evaluations = {
            aid: dict(v) for aid, v in load_int_map(d.get("evaluations")).items()
        }
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions and JSON schemas for data models.
        """
        description = f"""{cls.__name__}: Endowment Effect experiment environment module.

**Description:** Manages an Endowment Effect experiment where agents evaluate their willingness to accept (WTA) and willingness to pay (WTP) for different items.

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
        return "Endowment Effect experiment environment for collecting WTA and WTP evaluations."

    @tool(readonly=False)
    async def submit_wta_wtp(
        self, agent_id: int, item: str, wta: float, wtp: float
    ) -> SubmitWTAWTPResponse:
        """
        Submit WTA and WTP evaluation for an item.

        :param agent_id: The agent's ID
        :param item: The item name (must be one of: "pen", "plate", "glass", "doll")
        :param wta: Willingness to Accept price (non-negative number)
        :param wtp: Willingness to Pay price (non-negative number)

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Validate agent_id
            if agent_id not in self.agent_ids:
                raise ValueError(
                    f"Agent ID {agent_id} is not in the experiment. Valid IDs: {self.agent_ids}"
                )

            # Validate and normalize item name
            item = item.lower().strip()
            if item not in self.VALID_ITEMS:
                raise ValueError(
                    f"Invalid item '{item}'. Valid items are: {self.VALID_ITEMS}"
                )

            # Validate WTA and WTP (must be non-negative)
            if wta < 0:
                wta = 0.0
            if wtp < 0:
                wtp = 0.0

            # Store the evaluation
            if agent_id not in self._evaluations:
                self._evaluations[agent_id] = {}

            self._evaluations[agent_id][item] = {
                "wta": float(wta),
                "wtp": float(wtp),
            }

            # Check if all items are completed
            completed = len(self._evaluations[agent_id])
            all_completed = completed == len(self.VALID_ITEMS)

            status = "completed" if all_completed else "submitted"

            return SubmitWTAWTPResponse(
                agent_id=agent_id,
                item=item,
                wta=float(wta),
                wtp=float(wtp),
                status=status,
            )

    @tool(readonly=True, kind="observe")
    async def get_my_evaluations(self, agent_id: int) -> GetMyEvaluationsResponse:
        """
        Get evaluations submitted by a specific agent.

        :param agent_id: The agent's ID

        :returns: Response containing current evaluations, completed items, and remaining items.
        """
        async with self._lock:
            if agent_id not in self.agent_ids:
                raise ValueError(
                    f"Agent ID {agent_id} is not in the experiment. Valid IDs: {self.agent_ids}"
                )

            evaluations = self._evaluations.get(agent_id, {}).copy()
            completed_items = list(evaluations.keys())
            remaining_items = [
                item for item in self.VALID_ITEMS if item not in completed_items
            ]

            return GetMyEvaluationsResponse(
                agent_id=agent_id,
                evaluations=evaluations,
                completed_items=completed_items,
                remaining_items=remaining_items,
            )

    @tool(readonly=True, kind="statistics")
    async def get_all_evaluations(self) -> dict[int, dict[str, dict[str, float]]]:
        """
        Get all agents' evaluations.

        :returns: Dictionary of all evaluations: {agent_id: {item: {"wta": float, "wtp": float}}}
        """
        async with self._lock:
            # Return a deep copy to prevent external modifications
            return {
                agent_id: {item: eval_data.copy() for item, eval_data in items.items()}
                for agent_id, items in self._evaluations.items()
            }

    async def init(self, start_datetime: datetime):
        """
        Initialize the environment module.
        """
        await super().init(start_datetime)
        async with self._lock:
            self._evaluations = {agent_id: {} for agent_id in self.agent_ids}
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
                    "evaluations": {
                        item: eval_data.copy()
                        for item, eval_data in self._evaluations[agent_id].items()
                    },
                    "completed_items": len(self._evaluations[agent_id]),
                }
                for agent_id in self.agent_ids
            ]

        await self._write_agent_state_batch(
            step=self._step_counter,
            t=t,
            records=records,
        )
        self._step_counter += 1

    def get_results(self) -> dict[int, dict[str, dict[str, float]]]:
        """
        Get all evaluation results (synchronous method for result extraction).

        :returns: Dictionary of all evaluations: {agent_id: {item: {"wta": float, "wtp": float}}}
        """
        return {
            agent_id: {item: eval_data.copy() for item, eval_data in items.items()}
            for agent_id, items in self._evaluations.items()
        }


__all__ = ["EndowmentEffectEnv"]
