"""
Volunteer's Dilemma Game Environment
Environment for Volunteer's Dilemma game based on AgentSociety2
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
class SubmitChoiceResponse(BaseModel):
    """Response model for submit_choice() function"""

    agent_name: str = Field(..., description="Agent name")
    choice: str = Field(..., description="Choice (Volunteer/Stand by)")
    status: str = Field(..., description="Status: 'submitted' or 'round_executed'")


class VolunteerDilemmaEnv(EnvBase):
    """Environment for Volunteer's Dilemma game based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("round_number", "INTEGER", nullable=False),
        ColumnDef("last_round", "JSON"),
        ColumnDef("pending_choices", "JSON", nullable=False),
        ColumnDef("num_agents", "INTEGER", nullable=False),
        ColumnDef("benefit_b", "INTEGER", nullable=False),
        ColumnDef("cost_c", "INTEGER", nullable=False),
    ]

    def __init__(
        self,
        num_agents: int = 4,
        benefit_b: int = 100,
        cost_c: int = 40,
    ):
        """Initialize environment

        :param num_agents: Number of agents (default: 4)
        :param benefit_b: Benefit for everyone if someone volunteers (default: 100)
        :param cost_c: Cost for a volunteer (default: 40)
        """
        super().__init__()

        self.num_agents = num_agents
        self.benefit_b = benefit_b
        self.cost_c = cost_c

        self.round_number = 0
        self.round_history: list[dict] = []

        # Pending choices for current round (agent_name -> choice)
        self._pending_choices: dict[str, str] = {}

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
                    "pending_choices": dict(self._pending_choices),
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
        self.round_number = int(d.get("round_number", 0))
        self.round_history = list(d.get("round_history", []))
        self._pending_choices = dict(d.get("pending_choices", {}))
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """Return AI-readable initialization guidance for this environment module"""
        description = f"""{cls.__name__}: Volunteer's Dilemma game environment module.

**Description:** Manages a Volunteer's Dilemma game where agents choose to volunteer or stand by. If at least one agent volunteers, all agents receive benefit, but volunteers pay a cost.

**Initialization Parameters:**
- num_agents (int): Number of agents (default: 4)
- benefit_b (int): Benefit for everyone if someone volunteers (default: 100)
- cost_c (int): Cost for a volunteer (default: 40)

**Example initialization config:**
```json
{{
  "num_agents": 4,
  "benefit_b": 100,
  "cost_c": 40
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Volunteer's Dilemma game environment for group volunteer decisions."

    @tool(readonly=False)
    async def submit_choice(self, agent_name: str, choice: str) -> SubmitChoiceResponse:
        """
        Submit choice decision for an agent.

        :param agent_name: The agent's name
        :param choice: The choice ("Volunteer" or "Stand by")

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Validate choice
            if choice in ["Volunteer", "Stand by"]:
                validated_choice = choice
            else:
                validated_choice = "Stand by"

            self._pending_choices[agent_name] = validated_choice

            # 记录提交日志用于调试
            import sys

            print(
                f"[ENV DEBUG] {agent_name} submitted: {validated_choice} (pending: {len(self._pending_choices)}/{self.num_agents})",
                file=sys.stderr,
            )

            return SubmitChoiceResponse(
                agent_name=agent_name,
                choice=validated_choice,
                status="submitted",
            )

    @tool(readonly=True)
    async def get_round_history(self, round_num: int | None = None) -> list[dict]:
        """
        Get round history.

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
        self.round_number = 0
        self.round_history.clear()
        self._pending_choices.clear()
        self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        Executes a round if all agents have submitted their choices.

        :param tick: The number of ticks of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t
            last_round = self.round_history[-1] if self.round_history else None

            # Check if we have enough submissions to execute a round
            if len(self._pending_choices) >= self.num_agents:
                # Execute the round
                self.round_number += 1

                # Calculate number of volunteers
                num_volunteers = sum(
                    1
                    for choice in self._pending_choices.values()
                    if choice == "Volunteer"
                )
                is_someone_volunteering = num_volunteers > 0

                # Calculate payoffs for each agent
                payoffs = {}
                for agent_name, choice in self._pending_choices.items():
                    if is_someone_volunteering:
                        if choice == "Volunteer":
                            payoff = self.benefit_b - self.cost_c
                        else:  # "Stand by"
                            payoff = self.benefit_b
                    else:  # No one volunteered
                        payoff = 0
                    payoffs[agent_name] = float(payoff)

                # Build round summary with debug info
                round_summary = {
                    "round": self.round_number,
                    "choices": self._pending_choices.copy(),
                    "num_volunteers": num_volunteers,
                    "is_someone_volunteering": is_someone_volunteering,
                    "payoffs": payoffs,
                    "num_agents_submitted": len(self._pending_choices),
                    "benefit_b": self.benefit_b,
                    "cost_c": self.cost_c,
                }

                self.round_history.append(round_summary)
                last_round = round_summary

                # Clear pending choices for next round
                self._pending_choices.clear()

            round_number = self.round_number
            pending_choices = self._pending_choices.copy()

        await self._write_env_state(
            step=self._step_counter,
            t=t,
            round_number=round_number,
            last_round=last_round,
            pending_choices=pending_choices,
            num_agents=self.num_agents,
            benefit_b=self.benefit_b,
            cost_c=self.cost_c,
        )
        self._step_counter += 1


__all__ = ["VolunteerDilemmaEnv"]
