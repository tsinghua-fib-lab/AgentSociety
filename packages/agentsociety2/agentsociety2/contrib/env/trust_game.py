"""
Trust Game Environment
Environment for Trust Game based on AgentSociety2
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"

logger = logging.getLogger(__name__)


# Response models
class SubmitInvestmentResponse(BaseModel):
    """Response model for submit_investment() function"""

    trustor_name: str = Field(..., description="Trustor name")
    investment: int = Field(..., description="Investment amount")
    status: str = Field(..., description="Status: 'success' if submitted successfully")
    message: str = Field(
        default="", description="Human-readable message about the submission"
    )


class SubmitReturnResponse(BaseModel):
    """Response model for submit_return() function"""

    trustee_name: str = Field(..., description="Trustee name")
    return_amount: int = Field(..., description="Return amount")
    status: str = Field(..., description="Status: 'success' if submitted successfully")
    message: str = Field(
        default="", description="Human-readable message about the return"
    )


class GetPairDataResponse(BaseModel):
    """Response model for get_pair_data() function"""

    trustor_name: str = Field(..., description="Trustor name")
    trustee_name: str = Field(..., description="Trustee name")
    sent_amount: int = Field(..., description="Amount sent by trustor")
    received_amount: float = Field(..., description="Amount received by trustee")
    returned_amount: int = Field(..., description="Amount returned by trustee")
    trustor_payoff: float = Field(..., description="Trustor payoff")
    trustee_payoff: float = Field(..., description="Trustee payoff")


class GetPendingInvestmentResponse(BaseModel):
    """Response model for get_pending_investment() function"""

    trustor_name: str = Field(..., description="Trustor name")
    investment: int | None = Field(
        None, description="Pending investment amount, None if not submitted yet"
    )
    received_amount: float | None = Field(
        None,
        description="Amount that trustee would receive (investment * multiplication_factor)",
    )


class TrustGameEnv(EnvBase):
    """Environment for Trust Game based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("round_number", "INTEGER", nullable=False),
        ColumnDef("last_round", "JSON"),
        ColumnDef("pending_investments", "JSON", nullable=False),
        ColumnDef("pending_returns", "JSON", nullable=False),
        ColumnDef("partner_mapping", "JSON", nullable=False),
        ColumnDef("num_pairs", "INTEGER", nullable=False),
        ColumnDef("initial_funds", "INTEGER", nullable=False),
        ColumnDef("multiplication_factor", "INTEGER", nullable=False),
    ]

    def __init__(
        self,
        num_pairs: int = 4,
        initial_funds: int = 10,
        multiplication_factor: int = 3,
    ):
        """Initialize environment

        :param num_pairs: Number of Trustor-Trustee pairs (default: 4)
        :param initial_funds: Initial coins per Trustor per round (default: 10)
        :param multiplication_factor: Investment multiplication factor (default: 3)
        """
        super().__init__()

        self.num_pairs = num_pairs
        self.initial_funds = initial_funds
        self.multiplication_factor = multiplication_factor

        self.round_number = 0
        self.round_history: list[dict] = []
        self.partner_mapping: dict[
            str, str
        ] = {}  # trustor_name -> trustee_name, trustee_name -> trustor_name

        # Pending decisions for current round
        self._pending_investments: dict[str, int] = {}  # trustor_name -> investment
        self._pending_returns: dict[str, int] = {}  # trustee_name -> return_amount

        self._lock = asyncio.Lock()
        self._step_counter: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json``（原子写）。"""
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
                    "partner_mapping": dict(self.partner_mapping),
                    "pending_investments": dict(self._pending_investments),
                    "pending_returns": dict(self._pending_returns),
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复（含已算出的 partner_mapping）。"""
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        d = json.loads(state_path.read_text(encoding="utf-8"))
        self.round_number = int(d.get("round_number", 0))
        self.round_history = list(d.get("round_history", []))
        self.partner_mapping = dict(d.get("partner_mapping", {}))
        self._pending_investments = dict(d.get("pending_investments", {}))
        self._pending_returns = dict(d.get("pending_returns", {}))
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """Return AI-readable initialization guidance for this environment module"""
        description = f"""{cls.__name__}: Trust Game environment module.

**Description:** Manages a Trust Game where Trustors send coins to Trustees, which are multiplied, and Trustees return some coins back.

**Initialization Parameters:**
- num_pairs (int): Number of Trustor-Trustee pairs (default: 4)
- initial_funds (int): Initial coins per Trustor per round (default: 10)
- multiplication_factor (int): Investment multiplication factor (default: 3)

**Example initialization config:**
```json
{{
  "num_pairs": 4,
  "initial_funds": 10,
  "multiplication_factor": 3
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return (
            "Trust Game environment for trustor-trustee transfer and return decisions."
        )

    def set_partner_mapping(self, partner_mapping: dict[str, str]):
        """Set partner mapping (trustor_name -> trustee_name, trustee_name -> trustor_name)"""
        self.partner_mapping = partner_mapping

    def _auto_setup_partner_mapping(self, agent_name: str | None = None) -> None:
        """Auto-setup partner mapping based on agent name convention.

        Convention: Agent-{id}_Trustor_G{n} pairs with Agent-{id'}_Trustee_G{n}
        where both have the same game number G{n}.

        :param agent_name: Optional agent name (not used, kept for compatibility)
        """
        if self.partner_mapping:
            return  # Already set up

        # Build partner mapping for ALL game numbers at once
        self.partner_mapping = {}

        # Create mapping for all games (G1 to G{num_pairs})
        for game_num in range(1, self.num_pairs + 1):
            # Trustor with G{game_num} pairs with Trustee with G{game_num}
            # Agent IDs: Trustors are 1..num_pairs, Trustees are num_pairs+1..2*num_pairs
            trustor_name = f"Agent-{game_num}_Trustor_G{game_num}"
            trustee_name = f"Agent-{game_num + self.num_pairs}_Trustee_G{game_num}"
            self.partner_mapping[trustor_name] = trustee_name
            self.partner_mapping[trustee_name] = trustor_name

        logger.info(f"Auto-setup partner_mapping for all games: {self.partner_mapping}")

    @tool(readonly=False)
    async def submit_investment(
        self, trustor_name: str, investment: int
    ) -> SubmitInvestmentResponse:
        """
        Submit investment decision for a trustor.

        :param trustor_name: The trustor's full name (format: "Agent-{id}_Trustor_G{game_num}")
        :param Example: "Agent-1_Trustor_G1", "Agent-2_Trustor_G2"
        :param investment: The investment amount (0 to initial_funds)

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Auto-setup partner mapping if not set
            if not self.partner_mapping:
                self._auto_setup_partner_mapping(trustor_name)

            if (
                trustor_name not in self.partner_mapping
                or "_Trustor_" not in trustor_name
            ):
                raise ValueError(f"Unknown trustor: {trustor_name}")
            if type(investment) is not int or not 0 <= investment <= self.initial_funds:
                raise ValueError(
                    "Investment must be an integer between zero and initial_funds"
                )
            if (
                trustor_name in self._pending_investments
                and self._pending_investments[trustor_name] != investment
            ):
                raise ValueError("An investment cannot change before the round settles")
            self._pending_investments[trustor_name] = investment

            return SubmitInvestmentResponse(
                trustor_name=trustor_name,
                investment=investment,
                status="success",
                message=f"Investment of {investment} coins submitted successfully. Wait for your partner (trustee) to respond.",
            )

    @tool(readonly=False)
    async def submit_return(
        self, trustee_name: str, return_amount: int
    ) -> SubmitReturnResponse:
        """
        Submit return decision for a trustee.

        :param trustee_name: The trustee's full name (format: "Agent-{id}_Trustee_G{game_num}")
        :param Example: "Agent-5_Trustee_G1", "Agent-6_Trustee_G2"
        :param IMPORTANT: Use the exact trustee name, NOT the agent ID number!
        :param return_amount: The return amount (0 to received_amount)

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Auto-setup partner mapping if not set
            if not self.partner_mapping:
                self._auto_setup_partner_mapping(trustee_name)

            if (
                trustee_name not in self.partner_mapping
                or "_Trustee_" not in trustee_name
            ):
                raise ValueError(f"Unknown trustee: {trustee_name}")
            trustor = self.partner_mapping[trustee_name]
            investment = self._pending_investments.get(trustor)
            if investment is None:
                raise ValueError(
                    "Wait for the partner's investment before submitting a return"
                )
            received = investment * self.multiplication_factor
            if type(return_amount) is not int or not 0 <= return_amount <= received:
                raise ValueError(
                    "Return must be an integer between zero and the received amount"
                )
            self._pending_returns[trustee_name] = return_amount

            return SubmitReturnResponse(
                trustee_name=trustee_name,
                return_amount=return_amount,
                status="success",
                message=f"Return of {return_amount} coins submitted successfully. The round will execute when all submissions are complete.",
            )

    @tool(readonly=True)
    async def get_pair_data(self, trustor_name: str) -> GetPairDataResponse:
        """
        Get data for a specific trustor-trustee pair from the last round.

        :param trustor_name: The trustor's full name (format: "Agent-{id}_Trustor_G{game_num}")
        :param Example: "Agent-1_Trustor_G1", "Agent-3_Trustor_G2"

        :returns: Response containing pair data from the last round.
        """
        async with self._lock:
            if not self.round_history:
                raise ValueError("No round history available")

            last_round = self.round_history[-1]
            trustee_name = self.partner_mapping.get(trustor_name)
            if not trustee_name:
                raise ValueError(f"No trustee found for trustor {trustor_name}")

            sent_amount = last_round["trustor_investments"].get(trustor_name, 0)
            received_amount = sent_amount * self.multiplication_factor
            returned_amount = last_round["trustee_returns"].get(trustee_name, 0)
            trustor_payoff = last_round["payoffs"].get(trustor_name, 0.0)
            trustee_payoff = last_round["payoffs"].get(trustee_name, 0.0)

            return GetPairDataResponse(
                trustor_name=trustor_name,
                trustee_name=trustee_name,
                sent_amount=sent_amount,
                received_amount=received_amount,
                returned_amount=returned_amount,
                trustor_payoff=trustor_payoff,
                trustee_payoff=trustee_payoff,
            )

    @tool(readonly=True)
    async def get_trustee_data(self, trustee_name: str) -> GetPairDataResponse:
        """
        Get data for a specific trustee-trustor pair from the last round (trustee perspective).
        This is a convenience method for trustees who know their own name but need to find their partner's data.

        :param trustee_name: The trustee's full name (format: "Agent-{id}_Trustee_G{game_num}")
        :param Example: "Agent-2_Trustee_G1", "Agent-4_Trustee_G2"

        :returns: Response containing pair data from the last round.
        """
        async with self._lock:
            if not self.round_history:
                raise ValueError("No round history available")

            # Find the corresponding trustor for this trustee
            trustor_name = self.partner_mapping.get(trustee_name)
            if not trustor_name:
                raise ValueError(f"No trustor found for trustee {trustee_name}")

            last_round = self.round_history[-1]
            sent_amount = last_round["trustor_investments"].get(trustor_name, 0)
            received_amount = sent_amount * self.multiplication_factor
            returned_amount = last_round["trustee_returns"].get(trustee_name, 0)
            trustor_payoff = last_round["payoffs"].get(trustor_name, 0.0)
            trustee_payoff = last_round["payoffs"].get(trustee_name, 0.0)

            return GetPairDataResponse(
                trustor_name=trustor_name,
                trustee_name=trustee_name,
                sent_amount=sent_amount,
                received_amount=received_amount,
                returned_amount=returned_amount,
                trustor_payoff=trustor_payoff,
                trustee_payoff=trustee_payoff,
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

    @tool(readonly=True)
    async def get_pending_investment(
        self, trustor_name: str
    ) -> GetPendingInvestmentResponse:
        """
        Get pending investment for a trustor in the current round.
        This allows trustees to check if their partner trustor has submitted an investment.

        :param trustor_name: The trustor's name

        :returns: Response containing pending investment amount and calculated received amount.
        """
        async with self._lock:
            investment = self._pending_investments.get(trustor_name)
            if investment is not None:
                received_amount = investment * self.multiplication_factor
            else:
                received_amount = None

            return GetPendingInvestmentResponse(
                trustor_name=trustor_name,
                investment=investment,
                received_amount=received_amount,
            )

    @tool(readonly=True)
    async def get_game_info(self) -> dict:
        """
        Get general information about the trust game setup.
        This tool does not require agent_id and can be called anytime.

        :returns: A dictionary containing game setup info: num_pairs, initial_funds, multiplication_factor, current_round, and all agent pairings.
        """
        async with self._lock:
            # Auto-setup partner mapping if not set
            if not self.partner_mapping:
                self._auto_setup_partner_mapping(None)

            # Build agent pairings list
            pairs = []
            for game_num in range(1, self.num_pairs + 1):
                trustor_name = f"Agent-{game_num}_Trustor_G{game_num}"
                trustee_name = f"Agent-{game_num + self.num_pairs}_Trustee_G{game_num}"
                pairs.append(
                    {
                        "game_num": game_num,
                        "trustor": trustor_name,
                        "trustee": trustee_name,
                    }
                )

            return {
                "game_type": "TrustGame",
                "num_pairs": self.num_pairs,
                "initial_funds": self.initial_funds,
                "multiplication_factor": self.multiplication_factor,
                "current_round": self.round_number + 1,
                "total_rounds_completed": self.round_number,
                "agent_pairs": pairs,
                "rules": {
                    "trustor_action": f"Send 0 to {self.initial_funds} coins to trustee",
                    "trustee_action": "Return 0 to received_amount coins to trustor",
                    "multiplication": f"Sent amount is multiplied by {self.multiplication_factor}x",
                    "trustor_payoff": "initial_funds - sent + returned",
                    "trustee_payoff": "received_amount - returned",
                },
            }

    @tool(readonly=True, kind="observe")
    async def get_trust_game_status(self, agent_id: int) -> dict:
        """
        Get the current trust game status for a specific agent.
        This is an observe tool that is automatically called during <observe>.

        :param agent_id: The agent's ID

        :returns: A dictionary containing the agent's role, current round, partner info, and game history.
        """
        async with self._lock:
            # Auto-setup partner mapping if not set
            if not self.partner_mapping:
                logger.info(
                    f"[get_trust_game_status] partner_mapping is empty, calling _auto_setup_partner_mapping for agent_id={agent_id}"
                )
                self._auto_setup_partner_mapping(f"Agent-{agent_id}_Trustor_G1")
                logger.info(
                    f"[get_trust_game_status] after _auto_setup_partner_mapping, partner_mapping={self.partner_mapping}"
                )

            # Find agent info from partner_mapping
            agent_name = None
            agent_role = None
            partner_name = None

            logger.info(
                f"[get_trust_game_status] Searching for agent_id={agent_id} in partner_mapping keys: {list(self.partner_mapping.keys())}"
            )

            for name in self.partner_mapping:
                # Check if this name matches the agent_id
                if f"Agent-{agent_id}_" in name:
                    agent_name = name
                    if "_Trustor_" in name:
                        agent_role = "trustor"
                    elif "_Trustee_" in name:
                        agent_role = "trustee"
                    partner_name = self.partner_mapping.get(name)
                    break

            if not agent_name:
                return {
                    "agent_id": agent_id,
                    "error": "Agent not found in partner mapping",
                    "round_number": self.round_number,
                    "num_pairs": self.num_pairs,
                    "initial_funds": self.initial_funds,
                    "multiplication_factor": self.multiplication_factor,
                }

            # Get last round data for this agent
            last_round_data = None
            if self.round_history:
                last_round = self.round_history[-1]
                if agent_name in last_round.get("trustor_investments", {}):
                    investment = last_round["trustor_investments"][agent_name]
                    returned = last_round["trustee_returns"].get(partner_name, 0)
                    my_payoff = last_round["payoffs"].get(agent_name, 0)
                    last_round_data = {
                        "my_investment": investment,
                        "partner_returned": returned,
                        "my_payoff": my_payoff,
                    }
                elif agent_name in last_round.get("trustee_returns", {}):
                    my_return = last_round["trustee_returns"][agent_name]
                    trustor_investment = last_round["trustor_investments"].get(
                        partner_name, 0
                    )
                    received = trustor_investment * self.multiplication_factor
                    my_payoff = last_round["payoffs"].get(agent_name, 0)
                    last_round_data = {
                        "partner_investment": trustor_investment,
                        "my_received": received,
                        "my_return": my_return,
                        "my_payoff": my_payoff,
                    }

            # Get pending submissions for current round
            pending_my = None
            pending_partner = None
            if agent_role == "trustor":
                pending_my = self._pending_investments.get(agent_name)
                if partner_name:
                    pending_partner = self._pending_returns.get(partner_name)
            else:  # trustee
                pending_my = self._pending_returns.get(agent_name)
                if partner_name:
                    pending_partner = self._pending_investments.get(partner_name)

            return {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "role": agent_role,
                "partner_name": partner_name,
                "round_number": self.round_number + 1,  # Current round (1-indexed)
                "total_rounds": "multiple",  # Unknown total rounds
                "initial_funds": self.initial_funds,
                "multiplication_factor": self.multiplication_factor,
                "last_round": last_round_data,
                "pending_my_submission": pending_my,
                "pending_partner_submission": pending_partner,
                "total_rounds_completed": self.round_number,
            }

    async def init(self, start_datetime: datetime):
        """Initialize the environment"""
        await super().init(start_datetime)
        self.round_number = 0
        self.round_history.clear()
        self._pending_investments.clear()
        self._pending_returns.clear()
        self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        Executes a round if all trustors and trustees have submitted their decisions.

        :param tick: The number of ticks of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t
            last_round = self.round_history[-1] if self.round_history else None

            # Both phases must finish; an absent return is not a zero decision.
            if (
                len(self._pending_investments) == self.num_pairs
                and len(self._pending_returns) == self.num_pairs
            ):
                self.round_number += 1
                valid_investments = dict(self._pending_investments)
                trustee_received = {
                    self.partner_mapping[name]: amount * self.multiplication_factor
                    for name, amount in valid_investments.items()
                }
                validated_returns = dict(self._pending_returns)

                # Calculate payoffs
                payoffs = {}
                for trustor_name, investment in valid_investments.items():
                    trustee_name = self.partner_mapping.get(trustor_name)
                    if trustee_name:
                        returned = validated_returns.get(trustee_name, 0)
                        trustor_payoff = self.initial_funds - investment + returned
                        trustee_payoff = (
                            trustee_received.get(trustee_name, 0) - returned
                        )
                        payoffs[trustor_name] = trustor_payoff
                        payoffs[trustee_name] = trustee_payoff

                # Build round summary
                round_summary = {
                    "round": self.round_number,
                    "trustor_investments": valid_investments.copy(),
                    "trustee_returns": validated_returns,
                    "payoffs": payoffs,
                }

                self.round_history.append(round_summary)
                last_round = round_summary

                # Clear pending decisions for next round
                self._pending_investments.clear()
                self._pending_returns.clear()

            round_number = self.round_number
            pending_investments = self._pending_investments.copy()
            pending_returns = self._pending_returns.copy()
            partner_mapping = self.partner_mapping.copy()

        await self._write_env_state(
            step=self._step_counter,
            t=t,
            round_number=round_number,
            last_round=last_round,
            pending_investments=pending_investments,
            pending_returns=pending_returns,
            partner_mapping=partner_mapping,
            num_pairs=self.num_pairs,
            initial_funds=self.initial_funds,
            multiplication_factor=self.multiplication_factor,
        )
        self._step_counter += 1


__all__ = ["TrustGameEnv"]
