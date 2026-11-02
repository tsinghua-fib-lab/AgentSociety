"""
Public Goods Game Environment
Environment for Public Goods Game based on AgentSociety2
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
class SubmitContributionResponse(BaseModel):
    """Response model for submit_contribution() function"""

    agent_name: str = Field(..., description="Agent name")
    contribution: int = Field(..., description="Contribution amount")
    status: str = Field(..., description="Status: 'submitted' or 'round_executed'")


class GetRoundResultResponse(BaseModel):
    """Response model for get_round_result() function"""

    round: int = Field(..., description="Round number")
    total_contribution: int = Field(..., description="Total contribution")
    public_pool_gain: float = Field(..., description="Public pool gain")
    gain_per_agent: float = Field(..., description="Gain per agent")
    contributions: dict[str, int] = Field(
        ..., description="Contributions by agent name"
    )
    payoffs: dict[str, float] = Field(..., description="Payoffs by agent name")


class PublicGoodsEnv(EnvBase):
    """Environment for Public Goods Game based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("round_number", "INTEGER", nullable=False),
        ColumnDef("last_round", "JSON"),
        ColumnDef("pending_contributions", "JSON", nullable=False),
        ColumnDef("submitted_agents", "JSON", nullable=False),
        ColumnDef("num_agents", "INTEGER", nullable=False),
        ColumnDef("initial_endowment", "INTEGER", nullable=False),
        ColumnDef("public_pool_multiplier", "REAL", nullable=False),
    ]

    def __init__(
        self,
        num_agents: int = 4,
        initial_endowment: int = 20,
        public_pool_multiplier: float = 1.6,
    ):
        """Initialize environment

        :param num_agents: Number of agents (default: 4)
        :param initial_endowment: Initial coins per agent per round (default: 20)
        :param public_pool_multiplier: Multiplier for public pool contributions (default: 1.6)
        """
        super().__init__()

        self.num_agents = num_agents
        self.initial_endowment = initial_endowment
        self.public_pool_multiplier = public_pool_multiplier

        self.round_number = 0
        self.round_history: list[dict] = []

        # Pending contributions for current round (agent_name -> contribution)
        self._pending_contributions: dict[str, int] = {}

        # Track which agents have submitted in current round
        self._agents_submitted_in_current_round: set = set()

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
                    "round_number": self.round_number,
                    "round_history": list(self.round_history),
                    "pending_contributions": dict(self._pending_contributions),
                    "agents_submitted": sorted(self._agents_submitted_in_current_round),
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。晚于 ``init()`` 执行，覆盖重置。"""
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        d = json.loads(state_path.read_text(encoding="utf-8"))
        self.round_number = int(d.get("round_number", 0))
        self.round_history = list(d.get("round_history", []))
        self._pending_contributions = dict(d.get("pending_contributions", {}))
        self._agents_submitted_in_current_round = set(d.get("agents_submitted", []))
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """Return AI-readable initialization guidance for this environment module"""
        description = f"""{cls.__name__}: Public Goods Game environment module.

**Description:** Manages a Public Goods Game where agents contribute to a public fund. Contributions are multiplied and divided equally among all players.

**Initialization Parameters:**
- num_agents (int): Number of agents (default: 4)
- initial_endowment (int): Initial coins per agent per round (default: 20)
- public_pool_multiplier (float): Multiplier for public pool contributions (default: 1.6)

**Example initialization config:**
```json
{{
  "num_agents": 4,
  "initial_endowment": 20,
  "public_pool_multiplier": 1.6
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Public Goods game environment for contribution and collective payoff decisions."

    @tool(readonly=False)
    async def submit_contribution(
        self, agent_name: str, contribution: int
    ) -> SubmitContributionResponse:
        """
        Submit contribution decision for an agent in the Public Goods Game.

        Game Context: This is a Public Goods Game where agents contribute to a public fund.
        Each round, agents receive coins and can contribute 0 to their endowment to the public fund.
        The total public fund is multiplied and divided equally among all players.
        Each agent's round gain = (coins not contributed) + (share of multiplied public fund).

        :param agent_name: The agent's name (should be in format "Agent-{id}", e.g., "Agent-1")
        :param contribution: The contribution amount (0 to initial_endowment)

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Validate contribution
            if (
                not isinstance(contribution, int)
                or contribution < 0
                or contribution > self.initial_endowment
            ):
                contribution = 0

            # Store pending contribution (allows re-submission in same round, last one wins)
            self._pending_contributions[agent_name] = contribution
            # Mark this agent as submitted in current round
            self._agents_submitted_in_current_round.add(agent_name)

            # Note: Round execution is deferred to step() to ensure atomicity
            status = "submitted"

            return SubmitContributionResponse(
                agent_name=agent_name,
                contribution=contribution,
                status=status,
            )

    @tool(readonly=True)
    async def get_round_history(self, round_num: int | None = None) -> list[dict]:
        """
        Get round history for the Public Goods Game.

        Game Context: This is a Public Goods Game where agents contribute to a public fund.
        Each round summary contains: round number, total contribution, public pool gain, and payoffs for each agent.
        History helps agents understand past contributions and outcomes to make better decisions.

        :param round_num: Optional round number. If None, returns all rounds.

        :returns: List of round summaries. Each summary contains: - round: Round number - total_contribution: Total coins contributed by all agents - public_pool_gain: Total public fund after multiplication - payoffs: Dictionary mapping agent names to their round gains
        """
        async with self._lock:
            if round_num is not None:
                return [r for r in self.round_history if r.get("round") == round_num]
            return self.round_history.copy()

    async def init(self, start_datetime: datetime):
        """Initialize the environment"""
        await super().init(start_datetime)
        # Reset environment state for a new game
        self.round_number = 0
        self.round_history.clear()
        self._pending_contributions.clear()
        self._agents_submitted_in_current_round.clear()
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

            # Execute the round if all agents have submitted
            if len(self._agents_submitted_in_current_round) >= self.num_agents:
                # Execute the round
                self.round_number += 1

                # Calculate total contribution and gains
                total_contribution = sum(self._pending_contributions.values())
                public_pool_gain = total_contribution * self.public_pool_multiplier
                gain_per_agent = public_pool_gain / self.num_agents

                # Calculate payoffs for each agent
                payoffs = {}
                for agent_name, contribution in self._pending_contributions.items():
                    private_savings = self.initial_endowment - contribution
                    total_gain = private_savings + gain_per_agent
                    payoffs[agent_name] = total_gain

                # Build round summary
                round_summary = {
                    "round": self.round_number,
                    "total_contribution": total_contribution,
                    "public_pool_gain": public_pool_gain,
                    "contributions": self._pending_contributions.copy(),  # Store individual contributions
                    "payoffs": payoffs,
                }

                self.round_history.append(round_summary)
                last_round = round_summary

                # Clear pending contributions for next round
                self._pending_contributions.clear()
                self._agents_submitted_in_current_round.clear()

            round_number = self.round_number
            pending_contributions = self._pending_contributions.copy()
            submitted_agents = sorted(self._agents_submitted_in_current_round)

        await self._write_env_state(
            step=self._step_counter,
            t=t,
            round_number=round_number,
            last_round=last_round,
            pending_contributions=pending_contributions,
            submitted_agents=submitted_agents,
            num_agents=self.num_agents,
            initial_endowment=self.initial_endowment,
            public_pool_multiplier=self.public_pool_multiplier,
        )
        self._step_counter += 1


__all__ = ["PublicGoodsEnv"]
