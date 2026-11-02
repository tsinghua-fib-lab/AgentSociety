"""
Reputation Game Environment (Optimized Version)
A simplified reputation game environment that supports multiple social norms and maintains agent reputations and payoffs.

This optimized version uses Pydantic for better validation and type safety.
"""

import asyncio
import json
import random
from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator

from agentsociety2.env import (
    EnvBase,
    tool,
)
from agentsociety2.env.base import dump_int_map, load_int_map
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"


# Enums for better type safety
class Reputation(int, Enum):
    """Reputation values."""

    BAD = 0
    GOOD = 1


class Action(str, Enum):
    """Action types in donation game."""

    COOPERATE = "cooperate"
    DEFECT = "defect"


class NormType(str, Enum):
    """Social norm types."""

    IMAGE_SCORE = "image_score"
    SIMPLE_STANDING = "simple_standing"
    STERN_JUDGING = "stern_judging"


class ReputationGameConfig(BaseModel):
    """Configuration for ReputationGameEnv.

    Uses Pydantic for automatic validation and JSON schema generation.
    """

    Z: int = Field(
        default=5,
        ge=1,
        description="Population size (number of agents)",
    )
    BENEFIT: int = Field(
        default=5,
        ge=0,
        description="Cooperation benefit (received by recipient)",
    )
    COST: int = Field(
        default=1,
        ge=0,
        description="Cooperation cost (paid by donor)",
    )
    norm_type: NormType = Field(
        default=NormType.STERN_JUDGING,
        description="Social norm type",
    )
    seed: int | None = Field(
        default=None,
        description="Random seed for reproducibility (None for random)",
    )

    @field_validator("norm_type", mode="before")
    @classmethod
    def validate_norm_type(cls, v):
        """Convert string to NormType enum if needed."""
        if isinstance(v, str):
            try:
                return NormType(v)
            except ValueError:
                raise ValueError(
                    f"Invalid norm_type: {v}. Must be one of {[e.value for e in NormType]}"
                ) from None
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "Z": 5,
                    "BENEFIT": 5,
                    "COST": 1,
                    "norm_type": "stern_judging",
                    "seed": 42,
                }
            ]
        }
    }


class ActionLogEntry(BaseModel):
    """Entry in the public action log."""

    donor_id: int = Field(..., description="ID of the donor agent")
    recipient_id: int = Field(..., description="ID of the recipient agent")
    action: str = Field(..., description="Action taken: 'cooperate' or 'defect'")
    donor_old_rep: str = Field(..., description="Donor's reputation before action")
    donor_new_rep: str = Field(..., description="Donor's reputation after action")
    recipient_rep: str = Field(
        ..., description="Recipient's reputation at time of action"
    )
    cost: int = Field(..., description="Cost paid by donor")
    benefit: int = Field(..., description="Benefit received by recipient")
    timestamp: str = Field(..., description="ISO format timestamp of the action")


class AgentSummary(BaseModel):
    """Summary of an agent for top agents list."""

    id: int = Field(..., description="Agent ID")
    reputation: str = Field(..., description="Current reputation: 'good' or 'bad'")
    payoff: float = Field(..., description="Cumulative payoff")
    recent_actions: list[dict] = Field(
        default_factory=list, description="Recent action log entries"
    )


# Response models for tool functions
class GetAgentReputationResponse(BaseModel):
    """Response model for get_agent_reputation() function"""

    agent_id: int = Field(..., description="The agent ID")
    reputation: str = Field(..., description="Current reputation: 'good' or 'bad'")


class GetAgentPayoffResponse(BaseModel):
    """Response model for get_agent_payoff() function"""

    agent_id: int = Field(..., description="The agent ID")
    payoff: float = Field(..., description="Cumulative payoff")


class ExecuteDonationResponse(BaseModel):
    """Response model for execute_donation() function"""

    donor_id: int = Field(..., description="The donor agent ID")
    recipient_id: int = Field(..., description="The recipient agent ID")
    action: str = Field(..., description="Action taken: 'cooperate' or 'defect'")
    cost: int = Field(..., description="Cost paid by donor")
    benefit: int = Field(..., description="Benefit received by recipient")
    donor_new_reputation: str = Field(
        ..., description="Donor's new reputation: 'good' or 'bad'"
    )


class GetTopAgentSummaryResponse(BaseModel):
    """Response model for get_top_agent_summary() function"""

    top_agents: list[dict] = Field(..., description="List of top agent summaries")
    top_k: int = Field(..., description="Number of top agents returned")


class GetPublicActionLogResponse(BaseModel):
    """Response model for get_public_action_log() function"""

    log: list[dict] = Field(..., description="List of recent action log entries")
    limit: int = Field(..., description="Number of records returned")


class GetPopulationSizeResponse(BaseModel):
    """Response model for get_population_size() function"""

    population_size: int = Field(..., description="Population size (Z)")
    Z: int = Field(..., description="Population size (Z)")


class GetGlobalStatisticsResponse(BaseModel):
    """Response model for get_global_statistics() function"""

    total_interactions: int = Field(..., description="Total number of interactions")
    cooperation_count: int = Field(..., description="Number of cooperation actions")
    defection_count: int = Field(..., description="Number of defection actions")
    cooperation_rate: float = Field(..., description="Cooperation rate (0.0 to 1.0)")


class GetReputationDistributionResponse(BaseModel):
    """Response model for get_reputation_distribution() function"""

    good_count: int = Field(..., description="Number of agents with good reputation")
    bad_count: int = Field(..., description="Number of agents with bad reputation")
    good_ratio: float = Field(..., description="Ratio of good reputation (0.0 to 1.0)")


class GetAgentHistoryResponse(BaseModel):
    """Response model for get_agent_history() function"""

    agent_id: int = Field(..., description="The agent ID")
    history: list[dict] = Field(..., description="List of recent interaction records")


class GetStrategyConvergenceAnalysisResponse(BaseModel):
    """Response model for get_strategy_convergence_analysis() function"""

    periods: list[dict] = Field(..., description="List of period statistics")
    trend: str = Field(
        ...,
        description="Trend direction: 'increasing', 'decreasing', 'stable', 'fluctuating', or 'insufficient_data'",
    )
    convergence_status: str = Field(
        ...,
        description="Convergence status: 'converged', 'not_converged', or 'insufficient_data'",
    )
    convergence_analysis: str = Field(
        ..., description="Textual analysis of convergence"
    )


class ReputationGameEnv(EnvBase):
    """Reputation Game Environment (Optimized Version).

    This environment maintains:
    1. Reputation for all agents (GOOD/BAD)
    2. Cumulative payoffs for all agents
    3. Updates reputation based on social norms
    4. Public action log for interactions

    Optimizations:
    - Uses Pydantic models for better validation
    - Uses enums for type safety
    - Automatic JSON schema generation
    - Better error handling
    """

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("reputation", "TEXT", nullable=False),
        ColumnDef("payoff", "REAL", nullable=False),
    ]
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("total_interactions", "INTEGER", nullable=False),
        ColumnDef("cooperation_count", "INTEGER", nullable=False),
        ColumnDef("defection_count", "INTEGER", nullable=False),
        ColumnDef("cooperation_rate", "REAL", nullable=False),
        ColumnDef("good_count", "INTEGER", nullable=False),
        ColumnDef("bad_count", "INTEGER", nullable=False),
        ColumnDef("good_ratio", "REAL", nullable=False),
        ColumnDef("latest_action", "JSON"),
        ColumnDef("norm_type", "TEXT", nullable=False),
        ColumnDef("benefit", "INTEGER", nullable=False),
        ColumnDef("cost", "INTEGER", nullable=False),
        ColumnDef("population_size", "INTEGER", nullable=False),
    ]

    def __init__(
        self,
        config: ReputationGameConfig | dict | None = None,
    ):
        super().__init__()

        # Handle both dict and ReputationGameConfig instances
        if config is None:
            self._config = ReputationGameConfig()
        elif isinstance(config, dict):
            try:
                self._config = ReputationGameConfig(**config)
            except Exception:
                # Fallback to default config if validation fails
                self._config = ReputationGameConfig()
        elif isinstance(config, ReputationGameConfig):
            self._config = config
        else:
            raise TypeError(
                f"config must be ReputationGameConfig or dict, got {type(config)}"
            )

        # State management
        self._reputations: dict[int, Reputation] = {}  # agent_id -> Reputation
        self._payoffs: dict[int, float] = {}  # agent_id -> cumulative payoff
        self._action_log: list[ActionLogEntry] = []  # Public action log

        # Thread safety
        self._lock = asyncio.Lock()
        self._step_counter: int = 0

        # Initialize state
        self._init_state()

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。

        Reputation(int Enum) 存 .value；ActionLogEntry(pydantic) 用 model_dump。
        """
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "reputations": {
                        k: v.value for k, v in dump_int_map(self._reputations).items()
                    },
                    "payoffs": dump_int_map(self._payoffs),
                    "action_log": [e.model_dump(mode="json") for e in self._action_log],
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
        self._reputations = {
            aid: Reputation(int(v))
            for aid, v in load_int_map(d.get("reputations")).items()
        }
        self._payoffs = {
            aid: float(v) for aid, v in load_int_map(d.get("payoffs")).items()
        }
        self._action_log = [
            ActionLogEntry.model_validate(e) for e in d.get("action_log", [])
        ]
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Uses Pydantic's automatic JSON schema generation.
        """
        # Use Pydantic's automatic schema generation
        config_schema = ReputationGameConfig.model_json_schema()

        description = f"""{cls.__name__}: Reputation game environment module.

**Description:** Provides reputation-based donation game functionalities with multiple social norms. This environment maintains agent reputations (GOOD/BAD), cumulative payoffs, and updates reputation based on social norms (image_score, simple_standing, stern_judging). Supports donation game interactions where agents can cooperate or defect, with reputation updates following the selected social norm.

**Initialization Parameters (excluding llm):**
- config (Optional[ReputationGameConfig]): Configuration object with Z, BENEFIT, COST, norm_type, and seed. If not provided, uses default values (Z=5, BENEFIT=5, COST=1, norm_type="stern_judging", seed=None).

**ReputationGameConfig JSON Schema:**
```json
{json.dumps(config_schema, indent=2)}
```

**Example initialization config:**
```json
{{
  "config": {{
    "Z": 5,
    "BENEFIT": 5,
    "COST": 1,
    "norm_type": "stern_judging",
    "seed": 42
  }}
}}
```

**Available Tools:**
- `get_agent_reputation(agent_id)`: Get the current reputation of an agent
- `get_agent_payoff(agent_id)`: Get the cumulative payoff of an agent
- `execute_donation(donor_id, recipient_id, action)`: Execute a donation decision (cooperate/defect)
- `get_top_agent_summary(top_k)`: Get summary of top agents by payoff
- `get_public_action_log(limit)`: Get public action log of recent interactions
- `get_population_size()`: Get the population size (Z)
- `get_global_statistics()`: Get global statistics (total interactions, cooperation count, defection count, cooperation rate)
- `get_reputation_distribution()`: Get current reputation distribution (good count, bad count, good ratio)
- `get_agent_history(agent_id, limit)`: Get recent interaction history for a specific agent (as donor or recipient)
- `get_strategy_convergence_analysis(num_periods)`: Analyze strategy convergence by examining cooperation rate trends over time
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Reputation game environment for donation decisions, reputations, and payoffs."

    def _init_state(self):
        """Initialize state for all agents."""
        if self._config.seed is not None:
            random.seed(self._config.seed)

        for i in range(self._config.Z):
            # Randomly initialize reputation
            self._reputations[i] = random.choice([Reputation.GOOD, Reputation.BAD])
            # Initial payoff is 0
            self._payoffs[i] = 0.0

    # Social norm implementations

    def _apply_norm_image_score(
        self, action: Action, recipient_rep: Reputation
    ) -> Reputation:
        """
        Image Score norm:
        - Cooperate -> Good reputation
        - Defect -> Bad reputation
        (Ignores recipient reputation)
        """
        return Reputation.GOOD if action == Action.COOPERATE else Reputation.BAD

    def _apply_norm_simple_standing(
        self, action: Action, recipient_rep: Reputation
    ) -> Reputation:
        """
        Simple Standing norm:
        - Cooperate with good reputation -> Good reputation
        - Cooperate with bad reputation -> Bad reputation
        - Defect -> Bad reputation
        """
        if action == Action.DEFECT:
            return Reputation.BAD
        # cooperate
        return Reputation.GOOD if recipient_rep == Reputation.GOOD else Reputation.BAD

    def _apply_norm_stern_judging(
        self, action: Action, recipient_rep: Reputation
    ) -> Reputation:
        """
        Stern Judging norm:
        - Cooperate with good reputation -> Good reputation
        - Defect with good reputation -> Bad reputation
        - Cooperate with bad reputation -> Bad reputation
        - Defect with bad reputation -> Good reputation
        """
        if recipient_rep == Reputation.GOOD:
            return Reputation.GOOD if action == Action.COOPERATE else Reputation.BAD
        else:  # recipient_rep == BAD
            return Reputation.BAD if action == Action.COOPERATE else Reputation.GOOD

    def _apply_norm(self, action: Action, recipient_rep: Reputation) -> Reputation:
        """Apply the current social norm to update reputation."""
        norm_funcs = {
            NormType.IMAGE_SCORE: self._apply_norm_image_score,
            NormType.SIMPLE_STANDING: self._apply_norm_simple_standing,
            NormType.STERN_JUDGING: self._apply_norm_stern_judging,
        }
        func = norm_funcs.get(self._config.norm_type)
        if not func:
            raise ValueError(f"Unknown norm type: {self._config.norm_type}")
        return func(action, recipient_rep)

    def _validate_agent_id(self, agent_id: int, param_name: str = "agent_id"):
        """Validate agent_id is within valid range."""
        if agent_id < 0 or agent_id >= self._config.Z:
            raise ValueError(
                f"Invalid {param_name}: {agent_id}. Must be between 0 and {self._config.Z - 1}."
            )

    def _reputation_to_str(self, rep: Reputation) -> str:
        """Convert Reputation enum to string."""
        return "good" if rep == Reputation.GOOD else "bad"

    # Environment tools

    @tool(readonly=True, kind="observe")
    async def get_agent_reputation(self, agent_id: int) -> GetAgentReputationResponse:
        """
        Get the current reputation of a specific agent by their ID.

        IMPORTANT: The agent_id parameter must exactly match the ID requested in the instruction.
        Do NOT use a different agent_id than what was specified.

        :param agent_id: The exact ID of the agent to query (must be an integer, e.g., 0, 1, 2, ...)

        :returns: Response containing agent_id and reputation. The reputation will be either "good" or "bad".
        """
        async with self._lock:
            self._validate_agent_id(agent_id)

            rep = self._reputations.get(agent_id, Reputation.GOOD)
            rep_str = self._reputation_to_str(rep)
            return GetAgentReputationResponse(agent_id=agent_id, reputation=rep_str)

    @tool(readonly=True, kind="observe")
    async def get_agent_payoff(self, agent_id: int) -> GetAgentPayoffResponse:
        """
        Get the cumulative payoff of a specific agent by their ID.

        IMPORTANT: The agent_id parameter must exactly match the ID requested in the instruction.
        Do NOT use a different agent_id than what was specified.

        :param agent_id: The exact ID of the agent to query (must be an integer, e.g., 0, 1, 2, ...)

        :returns: Response containing agent_id and payoff. The payoff is a float representing the cumulative score.
        """
        async with self._lock:
            self._validate_agent_id(agent_id)

            payoff = self._payoffs.get(agent_id, 0.0)
            return GetAgentPayoffResponse(agent_id=agent_id, payoff=payoff)

    @tool(readonly=False)
    async def execute_donation(
        self, donor_id: int, recipient_id: int, action: str
    ) -> ExecuteDonationResponse:
        """
        Execute a donation decision.

        IMPORTANT: The donor_id and recipient_id parameters must exactly match the IDs specified in the instruction.
        Do NOT use different IDs than what was requested.

        This function settles payoffs based on the decision and updates the donor's reputation
        according to the current social norm.

        :param donor_id: The exact ID of the donor agent (must be an integer, e.g., 0, 1, 2, ...)
        :param recipient_id: The exact ID of the recipient agent (must be an integer, e.g., 0, 1, 2, ...)
        :param action: "cooperate" or "defect" (must be exactly one of these two strings)

        :returns: Response containing execution results including donor_id, recipient_id, action, cost, benefit, and donor_new_reputation.
        """
        async with self._lock:
            # Validate IDs
            self._validate_agent_id(donor_id, "donor_id")
            self._validate_agent_id(recipient_id, "recipient_id")

            # Validate and convert action
            try:
                action_enum = Action(action.lower())
            except ValueError:
                raise ValueError(
                    f"Invalid action: {action}. Must be 'cooperate' or 'defect'."
                ) from None

            # Get recipient reputation
            recipient_rep = self._reputations.get(recipient_id, Reputation.GOOD)

            # Settle payoffs
            if action_enum == Action.COOPERATE:
                self._payoffs[donor_id] = (
                    self._payoffs.get(donor_id, 0.0) - self._config.COST
                )
                self._payoffs[recipient_id] = (
                    self._payoffs.get(recipient_id, 0.0) + self._config.BENEFIT
                )
                cost = self._config.COST
                benefit = self._config.BENEFIT
            else:  # defect
                cost = 0
                benefit = 0

            # Update donor reputation (according to current norm)
            old_rep = self._reputations.get(donor_id, Reputation.GOOD)
            new_rep = self._apply_norm(action_enum, recipient_rep)
            self._reputations[donor_id] = new_rep

            # Record to log using Pydantic model
            log_entry = ActionLogEntry(
                donor_id=donor_id,
                recipient_id=recipient_id,
                action=action_enum.value,
                donor_old_rep=self._reputation_to_str(old_rep),
                donor_new_rep=self._reputation_to_str(new_rep),
                recipient_rep=self._reputation_to_str(recipient_rep),
                cost=cost,
                benefit=benefit,
                timestamp=datetime.now(UTC).isoformat(),
            )
            self._action_log.append(log_entry)
            # Keep log length (last 1000 entries)
            if len(self._action_log) > 1000:
                self._action_log = self._action_log[-1000:]

            return ExecuteDonationResponse(
                donor_id=donor_id,
                recipient_id=recipient_id,
                action=action_enum.value,
                cost=cost,
                benefit=benefit,
                donor_new_reputation=self._reputation_to_str(new_rep),
            )

    @tool(readonly=True)
    async def get_top_agent_summary(self, top_k: int = 5) -> GetTopAgentSummaryResponse:
        """
        Get summary of top agents by payoff.

        This function is used to support agent learning behavior.

        :param top_k: Number of top agents to return, default 5

        :returns: Response containing top_agents list and top_k.
        """
        async with self._lock:
            # Sort by payoff
            sorted_agents = sorted(
                self._payoffs.items(), key=lambda x: x[1], reverse=True
            )[:top_k]

            top_agents = []
            for agent_id, payoff in sorted_agents:
                rep = self._reputations.get(agent_id, Reputation.GOOD)
                rep_str = self._reputation_to_str(rep)

                # Get recent actions for this agent (from log)
                recent_actions = [
                    log.model_dump()
                    for log in self._action_log[-20:]
                    if log.donor_id == agent_id
                ]

                summary = AgentSummary(
                    id=agent_id,
                    reputation=rep_str,
                    payoff=payoff,
                    recent_actions=recent_actions[:5],  # Last 5 actions
                )
                top_agents.append(summary.model_dump())

            return GetTopAgentSummaryResponse(top_agents=top_agents, top_k=top_k)

    @tool(readonly=True)
    async def get_public_action_log(
        self, limit: int = 20
    ) -> GetPublicActionLogResponse:
        """
        Get public action log.

        Returns recent interaction records for agent reasoning.

        :param limit: Number of recent records to return, default 20

        :returns: Response containing log list and limit.
        """
        async with self._lock:
            recent_logs = (
                self._action_log[-limit:]
                if len(self._action_log) > limit
                else self._action_log
            )

            # Convert Pydantic models to dicts
            log_dicts = [log.model_dump() for log in recent_logs]

            return GetPublicActionLogResponse(log=log_dicts, limit=limit)

    @tool(readonly=True, kind="statistics")
    async def get_population_size(self) -> GetPopulationSizeResponse:
        """
        Get the population size (Z) of the environment.

        This function returns the total number of agents in the simulation.

        :returns: Response containing population_size (Z).
        """
        async with self._lock:
            Z = self._config.Z
            return GetPopulationSizeResponse(population_size=Z, Z=Z)

    @tool(readonly=True, kind="statistics")
    async def get_global_statistics(self) -> GetGlobalStatisticsResponse:
        """
        Get global statistics of the environment.

        Returns overall statistics including:
        - Total number of interactions
        - Cooperation count
        - Defection count
        - Cooperation rate (η = coop_count / total_interactions)

        :returns: Response containing: - total_interactions: Total number of interactions - cooperation_count: Number of cooperation actions - defection_count: Number of defection actions - cooperation_rate: Cooperation rate (0.0 to 1.0)
        """
        async with self._lock:
            logs = self._action_log
            total = len(logs)

            coop = sum(1 for log in logs if log.action == Action.COOPERATE.value)
            defect = total - coop

            eta = coop / total if total > 0 else 0.0

            return GetGlobalStatisticsResponse(
                total_interactions=total,
                cooperation_count=coop,
                defection_count=defect,
                cooperation_rate=eta,
            )

    @tool(readonly=True, kind="statistics")
    async def get_reputation_distribution(self) -> GetReputationDistributionResponse:
        """
        Get current reputation distribution of the population.

        Returns the distribution of good and bad reputations among all agents:
        - Good reputation count
        - Bad reputation count
        - Good reputation ratio

        :returns: Response containing: - good_count: Number of agents with good reputation - bad_count: Number of agents with bad reputation - good_ratio: Ratio of good reputation (0.0 to 1.0)
        """
        async with self._lock:
            good_count = sum(
                1 for r in self._reputations.values() if r == Reputation.GOOD
            )
            bad_count = sum(
                1 for r in self._reputations.values() if r == Reputation.BAD
            )
            total = len(self._reputations)

            good_ratio = good_count / total if total > 0 else 0.0

            return GetReputationDistributionResponse(
                good_count=good_count,
                bad_count=bad_count,
                good_ratio=good_ratio,
            )

    @tool(readonly=True)
    async def get_agent_history(
        self, agent_id: int, limit: int = 50
    ) -> GetAgentHistoryResponse:
        """
        Get recent interaction history for a specific agent.

        Returns the agent's recent interactions as either donor or recipient.

        :param agent_id: The ID of the agent to query
        :param limit: Maximum number of recent interactions to return, default 50

        :returns: Response containing: - agent_id: The agent ID - history: List of recent interaction records (as donor or recipient)
        """
        async with self._lock:
            self._validate_agent_id(agent_id)

            # Get recent logs (last 1000 entries)
            logs = self._action_log[-1000:]

            # Filter logs where agent is donor or recipient
            filtered = [
                log
                for log in logs
                if log.donor_id == agent_id or log.recipient_id == agent_id
            ]

            # Get most recent interactions
            recent = filtered[-limit:] if len(filtered) > limit else filtered

            # Convert Pydantic models to dicts for return
            history_dicts = [log.model_dump() for log in recent]

            return GetAgentHistoryResponse(agent_id=agent_id, history=history_dicts)

    @tool(readonly=True)
    async def get_strategy_convergence_analysis(
        self, num_periods: int = 3
    ) -> GetStrategyConvergenceAnalysisResponse:
        """
        Analyze strategy convergence by examining cooperation rate trends over time.

        Divides the interaction history into periods and analyzes:
        - Cooperation rate in each period
        - Trend of cooperation rate (increasing, decreasing, stable)
        - Convergence status (whether cooperation rate stabilizes)
        - Reputation distribution changes

        :param num_periods: Number of time periods to divide the history into, default 3

        :returns: Response containing: - periods: List of period statistics (cooperation_rate, interaction_count) - trend: Trend direction ("increasing", "decreasing", "stable", "fluctuating") - convergence_status: Whether convergence occurred ("converged", "not_converged", "insufficient_data") - convergence_analysis: Textual analysis of convergence
        """
        async with self._lock:
            logs = self._action_log
            total_interactions = len(logs)

            if total_interactions < num_periods:
                return GetStrategyConvergenceAnalysisResponse(
                    periods=[],
                    trend="insufficient_data",
                    convergence_status="insufficient_data",
                    convergence_analysis=f"Insufficient data for analysis. Only {total_interactions} interactions recorded, need at least {num_periods}.",
                )

            # Divide logs into periods
            period_size = total_interactions // num_periods
            periods = []

            for i in range(num_periods):
                start_idx = i * period_size
                end_idx = (
                    (i + 1) * period_size if i < num_periods - 1 else total_interactions
                )
                period_logs = logs[start_idx:end_idx]

                if len(period_logs) == 0:
                    continue

                coop_count = sum(
                    1 for log in period_logs if log.action == Action.COOPERATE.value
                )
                total_count = len(period_logs)
                coop_rate = coop_count / total_count if total_count > 0 else 0.0

                periods.append(
                    {
                        "period": i + 1,
                        "start_index": start_idx,
                        "end_index": end_idx,
                        "interaction_count": total_count,
                        "cooperation_count": coop_count,
                        "cooperation_rate": coop_rate,
                    }
                )

            # Analyze trend
            if len(periods) < 2:
                trend = "insufficient_data"
            else:
                rates = [p["cooperation_rate"] for p in periods]
                # Calculate trend: compare first half vs second half
                mid = len(rates) // 2
                first_half_avg = sum(rates[:mid]) / len(rates[:mid]) if mid > 0 else 0
                second_half_avg = (
                    sum(rates[mid:]) / len(rates[mid:]) if len(rates[mid:]) > 0 else 0
                )

                diff = second_half_avg - first_half_avg
                threshold = 0.05  # 5% threshold for stability

                if abs(diff) < threshold:
                    trend = "stable"
                elif diff > threshold:
                    trend = "increasing"
                elif diff < -threshold:
                    trend = "decreasing"
                else:
                    trend = "fluctuating"

            # Determine convergence status
            if len(periods) < 2:
                convergence_status = "insufficient_data"
                convergence_analysis = "Insufficient data to determine convergence."
            else:
                # Check if last two periods are similar (converged)
                last_two_rates = [p["cooperation_rate"] for p in periods[-2:]]
                rate_diff = (
                    abs(last_two_rates[1] - last_two_rates[0])
                    if len(last_two_rates) == 2
                    else 1.0
                )
                convergence_threshold = 0.1  # 10% difference threshold

                if rate_diff < convergence_threshold:
                    convergence_status = "converged"
                    convergence_analysis = (
                        f"Strategy appears to have converged. "
                        f"Cooperation rate in last two periods: {last_two_rates[0]:.3f} → {last_two_rates[1]:.3f} "
                        f"(difference: {rate_diff:.3f} < {convergence_threshold})."
                    )
                else:
                    convergence_status = "not_converged"
                    convergence_analysis = (
                        f"Strategy has not converged yet. "
                        f"Cooperation rate in last two periods: {last_two_rates[0]:.3f} → {last_two_rates[1]:.3f} "
                        f"(difference: {rate_diff:.3f} >= {convergence_threshold})."
                    )

            return GetStrategyConvergenceAnalysisResponse(
                periods=periods,
                trend=trend,
                convergence_status=convergence_status,
                convergence_analysis=convergence_analysis,
            )

    # Lifecycle methods
    async def init(self, start_datetime: datetime):
        """Initialize the environment."""
        await super().init(start_datetime)
        async with self._lock:
            self._reputations.clear()
            self._payoffs.clear()
            self._action_log.clear()
            self._init_state()
            self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t
            # Environment does not perform automatic operations, waits for Agent to call tools
            total_interactions = len(self._action_log)
            cooperation_count = sum(
                1 for log in self._action_log if log.action == Action.COOPERATE.value
            )
            defection_count = total_interactions - cooperation_count
            cooperation_rate = (
                cooperation_count / total_interactions
                if total_interactions > 0
                else 0.0
            )
            good_count = sum(
                1
                for reputation in self._reputations.values()
                if reputation == Reputation.GOOD
            )
            bad_count = sum(
                1
                for reputation in self._reputations.values()
                if reputation == Reputation.BAD
            )
            population_size = len(self._reputations)
            good_ratio = good_count / population_size if population_size > 0 else 0.0
            latest_action = (
                self._action_log[-1].model_dump() if self._action_log else None
            )
            agent_rows = [
                {
                    "agent_id": agent_id,
                    "reputation": self._reputation_to_str(reputation),
                    "payoff": self._payoffs.get(agent_id, 0.0),
                }
                for agent_id, reputation in sorted(self._reputations.items())
            ]

        await self._write_agent_state_batch(
            step=self._step_counter,
            t=t,
            records=agent_rows,
        )
        await self._write_env_state(
            step=self._step_counter,
            t=t,
            total_interactions=total_interactions,
            cooperation_count=cooperation_count,
            defection_count=defection_count,
            cooperation_rate=cooperation_rate,
            good_count=good_count,
            bad_count=bad_count,
            good_ratio=good_ratio,
            latest_action=latest_action,
            norm_type=self._config.norm_type.value,
            benefit=self._config.BENEFIT,
            cost=self._config.COST,
            population_size=self._config.Z,
        )
        self._step_counter += 1


__all__ = [
    "Action",
    "NormType",
    "Reputation",
    "ReputationGameConfig",
    "ReputationGameEnv",
]
