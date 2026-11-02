"""
Prisoner's Dilemma Game Environment
Environment for Prisoner's Dilemma game based on AgentSociety2
"""

import asyncio
import json
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

# 本模块自选的 workspace 布局：<workspace_root>/state/ENV_STATE.json。
_STATE_REL = "state/ENV_STATE.json"


# Response models
class SubmitActionResponse(BaseModel):
    """Response model for submit_action() function"""

    agent_name: str = Field(..., description="Agent name")
    action: str = Field(..., description="Action (Yes/No)")
    status: str = Field(..., description="Status: 'submitted' or 'round_executed'")


class GetPayoffMatrixResponse(BaseModel):
    """Response model for get_payoff_matrix() function"""

    payoff_cc: int = Field(..., description="Payoff when both cooperate")
    payoff_cd: int = Field(
        ..., description="Payoff when cooperate but opponent defects"
    )
    payoff_dc: int = Field(
        ..., description="Payoff when defect but opponent cooperates"
    )
    payoff_dd: int = Field(..., description="Payoff when both defect")


class PrisonersDilemmaEnv(EnvBase):
    """Environment for Prisoner's Dilemma game based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("round_number", "INTEGER", nullable=False),
        ColumnDef("last_round", "JSON"),
        ColumnDef("pending_actions", "JSON", nullable=False),
        ColumnDef("payoff_cc", "INTEGER", nullable=False),
        ColumnDef("payoff_cd", "INTEGER", nullable=False),
        ColumnDef("payoff_dc", "INTEGER", nullable=False),
        ColumnDef("payoff_dd", "INTEGER", nullable=False),
    ]

    def __init__(
        self,
        payoff_cc: int = 3,
        payoff_cd: int = 0,
        payoff_dc: int = 5,
        payoff_dd: int = 1,
    ):
        """Initialize environment

        :param payoff_cc: Payoff when both cooperate (default: 3)
        :param payoff_cd: Payoff when cooperate but opponent defects (default: 0)
        :param payoff_dc: Payoff when defect but opponent cooperates (default: 5)
        :param payoff_dd: Payoff when both defect (default: 1)
        """
        super().__init__()

        self.payoff_cc = payoff_cc
        self.payoff_cd = payoff_cd
        self.payoff_dc = payoff_dc
        self.payoff_dd = payoff_dd

        self.round_number = 0
        self.round_history: list[dict] = []

        # Pending actions for current round (agent_name -> action)
        self._pending_actions: dict[str, str] = {}

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
                    "pending_actions": dict(self._pending_actions),
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。

        晚于 ``init()`` （会重置回合状态）执行，故 checkpoint 覆盖重置；
        ``_lock`` 由 ``__init__`` 重建，不从盘读取。
        """
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        data = json.loads(state_path.read_text(encoding="utf-8"))
        self.round_number = int(data.get("round_number", 0))
        self.round_history = list(data.get("round_history", []))
        self._pending_actions = dict(data.get("pending_actions", {}))
        self._step_counter = int(data.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """Return AI-readable initialization guidance for this environment module"""
        description = f"""{cls.__name__}: Prisoner's Dilemma game environment module.

**Description:** Manages a Prisoner's Dilemma game where two agents simultaneously choose to cooperate (Yes) or defect (No), with payoffs determined by the payoff matrix.

**Initialization Parameters:**
- payoff_cc (int): Payoff when both cooperate (default: 3)
- payoff_cd (int): Payoff when cooperate but opponent defects (default: 0)
- payoff_dc (int): Payoff when defect but opponent cooperates (default: 5)
- payoff_dd (int): Payoff when both defect (default: 1)

**Example initialization config:**
```json
{{
  "payoff_cc": 3,
  "payoff_cd": 0,
  "payoff_dc": 5,
  "payoff_dd": 1
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Prisoner's Dilemma game environment for simultaneous cooperation/defection decisions."

    def _calculate_payoff(self, action1: str, action2: str) -> tuple[int, int]:
        """Calculate payoffs based on actions"""
        action1 = action1.capitalize()
        action2 = action2.capitalize()

        if action1 == "Yes" and action2 == "Yes":
            return self.payoff_cc, self.payoff_cc
        elif action1 == "Yes" and action2 == "No":
            return self.payoff_cd, self.payoff_dc
        elif action1 == "No" and action2 == "Yes":
            return self.payoff_dc, self.payoff_cd
        else:  # Both No
            return self.payoff_dd, self.payoff_dd

    @tool(readonly=False)
    async def submit_action(self, agent_name: str, action: str) -> SubmitActionResponse:
        """
        Submit action decision for an agent.

        :param agent_name: The agent's name ("Agent A" or "Agent B")
        :param action: The action ("Yes" or "No")

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Normalize and validate action
            action = action.capitalize()
            if action not in ["Yes", "No"]:
                action = "No"

            self._pending_actions[agent_name] = action

            return SubmitActionResponse(
                agent_name=agent_name,
                action=action,
                status="submitted",
            )

    @tool(readonly=True, kind="statistics")
    async def get_payoff_matrix(self) -> GetPayoffMatrixResponse:
        """
        Get the payoff matrix.

        :returns: Response containing all payoff values.
        """
        async with self._lock:
            return GetPayoffMatrixResponse(
                payoff_cc=self.payoff_cc,
                payoff_cd=self.payoff_cd,
                payoff_dc=self.payoff_dc,
                payoff_dd=self.payoff_dd,
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
        self._pending_actions.clear()
        self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        Executes a round if at least one agent has submitted their action.
        If only one agent submitted, the other agent defaults to 'No' (defect).

        :param tick: The number of ticks of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t
            last_round = self.round_history[-1] if self.round_history else None

            # Check if we have at least one agent's action to execute a round
            # (Other agents default to 'No' if they haven't submitted)
            if len(self._pending_actions) >= 1:
                # Execute the round
                self.round_number += 1

                # Get actions (assuming Agent A and Agent B)
                agent_names = list(self._pending_actions.keys())

                # Handle cases where one or both agents have submitted
                if len(agent_names) >= 1:
                    # Get first agent's action (or use default)
                    agent_a_name = agent_names[0]
                    agent_a_action = self._pending_actions[agent_a_name]

                    # Get second agent's action or default to "No" (defect)
                    if len(agent_names) >= 2:
                        agent_b_name = agent_names[1]
                        agent_b_action = self._pending_actions[agent_b_name]
                    else:
                        # Only one agent submitted, the other defaults to "No" (defect)
                        agent_b_name = "Agent-B"  # Placeholder name
                        agent_b_action = "No"

                    # Calculate payoffs
                    payoff_a, payoff_b = self._calculate_payoff(
                        agent_a_action, agent_b_action
                    )

                    # Build round summary
                    round_summary = {
                        "round": self.round_number,
                        "agent_a_name": agent_a_name,
                        "agent_a_action": agent_a_action,
                        "agent_b_name": agent_b_name,
                        "agent_b_action": agent_b_action,
                        "agent_a_payoff": payoff_a,
                        "agent_b_payoff": payoff_b,
                    }

                    self.round_history.append(round_summary)
                    last_round = round_summary

                    # Clear pending actions for next round
                    self._pending_actions.clear()

            round_number = self.round_number
            pending_actions = self._pending_actions.copy()

        await self._write_env_state(
            step=self._step_counter,
            t=t,
            round_number=round_number,
            last_round=last_round,
            pending_actions=pending_actions,
            payoff_cc=self.payoff_cc,
            payoff_cd=self.payoff_cd,
            payoff_dc=self.payoff_dc,
            payoff_dd=self.payoff_dd,
        )
        self._step_counter += 1


__all__ = ["PrisonersDilemmaEnv"]
