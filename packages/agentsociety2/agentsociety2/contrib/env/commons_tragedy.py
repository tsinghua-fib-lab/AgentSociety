"""
Commons Tragedy Game Environment
Environment for Tragedy of the Commons game based on AgentSociety2
"""

import asyncio
import json
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"


# Response models
class GetPoolResourcesResponse(BaseModel):
    """Response model for get_pool_resources() function"""

    current_pool_resources: int = Field(..., description="Current resource pool size")
    initial_pool_resources: int = Field(..., description="Initial resource pool size")


class SubmitExtractionResponse(BaseModel):
    """Response model for submit_extraction() function"""

    agent_name: str = Field(..., description="Agent name")
    requested_extraction: int = Field(..., description="Requested extraction amount")
    status: str = Field(..., description="Status: 'submitted' or 'round_executed'")


class GetRoundHistoryResponse(BaseModel):
    """Response model for get_round_history() function"""

    round: int = Field(..., description="Round number")
    pool_before_round: int = Field(..., description="Pool before round")
    extractions: dict[str, int] = Field(..., description="Extractions by agent name")
    pool_after_round: int = Field(..., description="Pool after round")
    payoffs: dict[str, int] = Field(..., description="Payoffs by agent name")


class CommonsTragedyEnv(EnvBase):
    """Environment for Tragedy of the Commons game based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("round_number", "INTEGER", nullable=False),
        ColumnDef("current_pool_resources", "INTEGER", nullable=False),
        ColumnDef("last_round", "JSON"),
        ColumnDef("pending_extractions", "JSON", nullable=False),
        ColumnDef("submitted_agents", "JSON", nullable=False),
        ColumnDef("initial_pool_resources", "INTEGER", nullable=False),
        ColumnDef("max_extraction_per_agent", "INTEGER", nullable=False),
    ]

    def __init__(
        self,
        num_agents: int = 4,
        initial_pool_resources: int = 100,
        max_extraction_per_agent: int = 10,
    ):
        """Initialize environment

        :param num_agents: Number of agents (default: 4)
        :param initial_pool_resources: Initial resource pool size (default: 100)
        :param max_extraction_per_agent: Maximum extraction per agent per round (default: 10)
        """
        super().__init__()

        self.num_agents = num_agents
        self.initial_pool_resources = initial_pool_resources
        self.max_extraction_per_agent = max_extraction_per_agent

        self.current_pool_resources = self.initial_pool_resources
        self.round_number = 0
        self.round_history: list[dict] = []

        # Pending extractions for current round (agent_name -> extraction)
        self._pending_extractions: dict[str, int] = {}

        # Track which agents have submitted in current round
        self._agents_submitted_in_current_round: set = set()

        # Track the last time we executed a round
        self._last_round_executed: int = -1

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
                    "current_pool_resources": self.current_pool_resources,
                    "round_number": self.round_number,
                    "round_history": list(self.round_history),
                    "pending_extractions": dict(self._pending_extractions),
                    "agents_submitted": sorted(self._agents_submitted_in_current_round),
                    "last_round_executed": self._last_round_executed,
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
        self.current_pool_resources = d.get(
            "current_pool_resources", self.current_pool_resources
        )
        self.round_number = int(d.get("round_number", 0))
        self.round_history = list(d.get("round_history", []))
        self._pending_extractions = dict(d.get("pending_extractions", {}))
        self._agents_submitted_in_current_round = set(d.get("agents_submitted", []))
        self._last_round_executed = int(d.get("last_round_executed", -1))
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """Return AI-readable initialization guidance for this environment module"""
        description = f"""{cls.__name__}: Commons Tragedy game environment module.

**Description:** Manages a Tragedy of the Commons game where agents extract resources from a shared pool. The pool is depletable and if total extraction exceeds available resources, allocations are proportional.

**Initialization Parameters:**
- num_agents (int): Number of agents (default: 4)
- initial_pool_resources (int): Initial resource pool size (default: 100)
- max_extraction_per_agent (int): Maximum extraction per agent per round (default: 10)

**Example initialization config:**
```json
{{
  "num_agents": 4,
  "initial_pool_resources": 100,
  "max_extraction_per_agent": 10
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Commons Tragedy game environment for shared-pool resource extraction decisions."

    @tool(readonly=True, kind="observe")
    async def get_pool_resources(self) -> GetPoolResourcesResponse:
        """
        Get current pool resources.

        Game Context: This is a Tragedy of the Commons game. You are participating with other agents
        in extracting resources from a shared pool over 10 rounds. Each unit you extract gives you 1 point.
        The pool is depletable - if total extractions exceed available resources, allocations are proportional.

        :returns: Response containing current and initial pool resources.
        """
        async with self._lock:
            return GetPoolResourcesResponse(
                current_pool_resources=self.current_pool_resources,
                initial_pool_resources=self.initial_pool_resources,
            )

    @tool(readonly=False)
    async def submit_extraction(
        self, agent_name: str, requested_extraction: int
    ) -> SubmitExtractionResponse:
        """
        Submit extraction decision for an agent.

        Game Context: This is a Tragedy of the Commons game. You are participating with other agents
        in extracting resources from a shared pool over 10 rounds. Each unit you extract gives you 1 point.
        The pool is depletable - if total extractions exceed available resources, allocations are proportional.
        Your goal is to maximize your personal resource extraction over all rounds.

        :param agent_name: The agent's name (should be in format "Agent-{id}", e.g., "Agent-1")
        :param requested_extraction: The requested extraction amount (1 to max_extraction_per_agent)

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Validate extraction amount
            if (
                not isinstance(requested_extraction, int)
                or requested_extraction < 1
                or requested_extraction > self.max_extraction_per_agent
            ):
                requested_extraction = 1

            # Store pending extraction (allows re-submission in same round, last one wins)
            # Agent name should be in format "Agent-{id}" as specified in the agent profile
            self._pending_extractions[agent_name] = requested_extraction
            # Mark this agent as submitted in current round
            self._agents_submitted_in_current_round.add(agent_name)

            # Note: Round execution is deferred to step() to ensure atomicity
            # All agents submit first, then the round is executed together
            status = "submitted"

            return SubmitExtractionResponse(
                agent_name=agent_name,
                requested_extraction=requested_extraction,
                status=status,
            )

    def _calculate_actual_extractions_sync(
        self, requested_extractions: dict, pool_before: int
    ) -> tuple[dict, int, int]:
        """Calculate actual extractions considering resource pool capacity limits"""
        actual_extractions = {agent_name: 0 for agent_name in requested_extractions}
        total_requested = sum(requested_extractions.values())
        total_actual_extracted = 0

        if total_requested > 0 and pool_before > 0:
            if total_requested > pool_before:
                # Insufficient resources, allocate proportionally
                scaling_factor = pool_before / total_requested

                for agent_name, requested in requested_extractions.items():
                    actual_extractions[agent_name] = int(requested * scaling_factor)
                    total_actual_extracted += actual_extractions[agent_name]

                # Handle remainder
                remainder = pool_before - total_actual_extracted
                if remainder > 0:
                    fractional_parts = [
                        (
                            requested_extractions[name] * scaling_factor
                            - actual_extractions[name],
                            name,
                        )
                        for name in requested_extractions
                    ]
                    fractional_parts.sort(key=lambda x: x[0], reverse=True)

                    for _ in range(int(remainder)):
                        if fractional_parts:
                            _, agent_name_to_add = fractional_parts.pop(0)
                            actual_extractions[agent_name_to_add] += 1
                            total_actual_extracted += 1
                        else:
                            break
            else:
                # Sufficient resources, use requested extractions directly
                actual_extractions = requested_extractions.copy()
                total_actual_extracted = total_requested

        remaining_pool = pool_before - total_actual_extracted
        remaining_pool = max(remaining_pool, 0)

        return actual_extractions, total_actual_extracted, remaining_pool

    @tool(readonly=True)
    async def get_round_history(self, round_num: int | None = None) -> list[dict]:
        """
        Get round history.

        Game Context: This is a Tragedy of the Commons game. You are participating with other agents
        in extracting resources from a shared pool over 10 rounds. Each unit you extract gives you 1 point.
        The pool is depletable - if total extractions exceed available resources, allocations are proportional.
        Reviewing history helps you understand past behaviors and make better decisions.

        :param round_num: Optional round number. If None, returns all rounds.

        :returns: List of round summaries.
        """
        async with self._lock:
            if round_num is not None:
                return [r for r in self.round_history if r.get("round") == round_num]
            return self.round_history.copy()

    async def init(self, start_datetime: datetime):
        """Initialize the environment"""
        await super().init(start_datetime)
        # Reset environment state for a new game
        self.current_pool_resources = self.initial_pool_resources
        self.round_number = 0
        self.round_history.clear()
        self._pending_extractions.clear()
        self._agents_submitted_in_current_round.clear()
        self._last_round_executed = -1
        self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        This method is called by the environment router after agents have submitted their decisions.
        All submissions for the current round are processed and the round is executed here,
        ensuring atomicity and consistent state for the next round.

        :param tick: The number of ticks of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t
            last_round = self.round_history[-1] if self.round_history else None

            # Execute the round if at least some agents have submitted
            # (Agents that haven't submitted will be treated as extracting 0 units)
            # This prevents deadlock when some agents are slow or fail to decide
            if len(self._pending_extractions) > 0:
                # Execute the round
                self.round_number += 1
                pool_before_this_round = self.current_pool_resources

                # Calculate actual extractions with proportional allocation
                actual_extractions, _total_extracted, remaining_pool = (
                    self._calculate_actual_extractions_sync(
                        self._pending_extractions.copy(), pool_before_this_round
                    )
                )

                self.current_pool_resources = remaining_pool

                # Build round summary
                round_summary = {
                    "round": self.round_number,
                    "pool_before_round": pool_before_this_round,
                    "extractions": actual_extractions,
                    "pool_after_round": remaining_pool,
                    "payoffs": actual_extractions.copy(),  # Extraction equals payoff
                }

                self.round_history.append(round_summary)
                last_round = round_summary

                # Clear pending extractions for next round
                self._pending_extractions.clear()
                self._agents_submitted_in_current_round.clear()

            round_number = self.round_number
            current_pool_resources = self.current_pool_resources
            pending_extractions = self._pending_extractions.copy()
            submitted_agents = sorted(self._agents_submitted_in_current_round)

        await self._write_env_state(
            step=self._step_counter,
            t=t,
            round_number=round_number,
            current_pool_resources=current_pool_resources,
            last_round=last_round,
            pending_extractions=pending_extractions,
            submitted_agents=submitted_agents,
            initial_pool_resources=self.initial_pool_resources,
            max_extraction_per_agent=self.max_extraction_per_agent,
        )
        self._step_counter += 1


__all__ = ["CommonsTragedyEnv"]
