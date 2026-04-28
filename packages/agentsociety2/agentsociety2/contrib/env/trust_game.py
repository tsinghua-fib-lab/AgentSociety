"""
Trust Game Environment
Environment for Trust Game based on V2 framework
"""
import asyncio
import logging
from datetime import datetime
from typing import ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage import ColumnDef

logger = logging.getLogger(__name__)


# Response models
class SubmitInvestmentResponse(BaseModel):
    """Response model for submit_investment() function"""

    trustor_name: str = Field(..., description="Trustor name")
    investment: int = Field(..., description="Investment amount")
    status: str = Field(..., description="Status: 'submitted'")


class SubmitReturnResponse(BaseModel):
    """Response model for submit_return() function"""

    trustee_name: str = Field(..., description="Trustee name")
    return_amount: int = Field(..., description="Return amount")
    status: str = Field(..., description="Status: 'submitted' or 'round_executed'")


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
    investment: Optional[int] = Field(None, description="Pending investment amount, None if not submitted yet")
    received_amount: Optional[float] = Field(None, description="Amount that trustee would receive (investment * multiplication_factor)")


class TrustGameEnv(EnvBase):
    """Environment for Trust Game based on V2 framework"""

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
        
        Args:
            num_pairs: Number of Trustor-Trustee pairs (default: 4)
            initial_funds: Initial coins per Trustor per round (default: 10)
            multiplication_factor: Investment multiplication factor (default: 3)
        """
        super().__init__()

        self.num_pairs = num_pairs
        self.initial_funds = initial_funds
        self.multiplication_factor = multiplication_factor

        self.round_number = 0
        self.round_history: List[dict] = []
        self.partner_mapping: Dict[str, str] = {}  # trustor_name -> trustee_name, trustee_name -> trustor_name
        
        # Pending decisions for current round
        self._pending_investments: Dict[str, int] = {}  # trustor_name -> investment
        self._pending_returns: Dict[str, int] = {}  # trustee_name -> return_amount
        
        self._lock = asyncio.Lock()
        self._step_counter: int = 0

    @classmethod
    def mcp_description(cls) -> str:
        """Return a description text for MCP environment module candidate list"""
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

    @property
    def description(self):
        """Description of the environment module"""
        return f"""You are a Trust Game environment module specialized in managing trustor-trustee bilateral transactions.

**Game Overview:** {self.num_pairs} trustor-trustee pairs play for multiple rounds of strategic trust and return.

**Game Rules:**
- Trustors and trustees are paired (e.g., Trustor-1 paired with Trustee-1)
- Each round: Trustor sends 0-{self.initial_funds} coins
- Sent coins are multiplied by {self.multiplication_factor}x before reaching trustee
- Trustee receives multiplied amount and chooses how much to return (0 to received amount)
- Payoffs:
  * Trustor: {self.initial_funds} - investment + return
  * Trustee: received amount - return
- Past round data visible to both partners
- Goal: Maximize cumulative payoff over rounds

**Your Role Depends on Your Name:**
- **If you are a Trustor** (name contains "Trustor"): You send coins
- **If you are a Trustee** (name contains "Trustee"): You receive multiplied coins and decide returns

**Available Operations (you MUST use these within your plan):**

**For Trustors:**
1. **submit_investment(trustor_name, investment)**: Send coins
   - trustor_name: Your full name (e.g., "Agent-1_Trustor_G1")
   - investment: 0 to {self.initial_funds} coins
   - You MUST submit exactly once per round
   - **IMPORTANT: After submitting, call the 'done' tool to end your step!**

2. **get_pair_data(trustor_name)**: View partner's last round actions
   - Returns: Sent amount, received amount, return amount, both payoffs
   - Use to build trust or adjust strategy

3. **get_round_history()**: View all past rounds

**For Trustees:**
1. **submit_return(trustee_name, return_amount)**: Return coins to trustor
   - trustee_name: Your full name (e.g., "Agent-5_Trustee_G1")
   - return_amount: 0 to received amount
   - You MUST submit within the round to maximize partner's payoff (or minimize if not trusting)
   - **IMPORTANT: After submitting, call the 'done' tool to end your step!**

2. **get_trustee_data(trustee_name)**: View your partner's investment and last actions
   - Returns: Investment sent, received, both payoffs
   - Use to decide fair returns

3. **get_round_history()**: View all past rounds

**WORKFLOW FOR EACH STEP:**
1. Observe the current game state
2. Make your decision (investment or return)
3. Submit your decision using the appropriate tool
4. **Call 'done' tool to finish your step** - This is mandatory!

**CRITICAL CONSTRAINTS:**
- Trustor MUST call submit_investment within your plan - this signals the round should execute
- Trustee MUST call submit_return within your plan to respond to trustor's investment
- Both must use their FULL NAME in function calls (e.g., "Agent-1_Trustor_G1", not just "1")
- If trustor submits but trustee doesn't, trustee's return defaults to 0
"""

    def set_partner_mapping(self, partner_mapping: Dict[str, str]):
        """Set partner mapping (trustor_name -> trustee_name, trustee_name -> trustor_name)"""
        self.partner_mapping = partner_mapping

    def _auto_setup_partner_mapping(self, agent_name: Optional[str] = None) -> None:
        """Auto-setup partner mapping based on agent name convention.

        Convention: Agent-{id}_Trustor_G{n} pairs with Agent-{id'}_Trustee_G{n}
        where both have the same game number G{n}.

        Args:
            agent_name: Optional agent name (not used, kept for compatibility)
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

        Args:
            trustor_name: The trustor's full name (format: "Agent-{id}_Trustor_G{game_num}")
                         Example: "Agent-1_Trustor_G1", "Agent-2_Trustor_G2"
            investment: The investment amount (0 to initial_funds)

        Returns:
            Response containing submission status.
        """
        async with self._lock:
            # Auto-setup partner mapping if not set
            if not self.partner_mapping:
                self._auto_setup_partner_mapping(trustor_name)

            # Normalize trustor_name: try to find matching name in partner_mapping
            normalized_name = trustor_name

            if trustor_name in self.partner_mapping:
                # Direct match - use as is
                normalized_name = trustor_name
            elif trustor_name.isdigit():
                # If given a bare ID like "1", search for matching full name
                for mapped_name in self.partner_mapping.keys():
                    if "_Trustor_" in mapped_name and mapped_name.startswith(f"Agent-{trustor_name}_"):
                        normalized_name = mapped_name
                        break
            else:
                # Try to extract agent ID from name and find correct name
                # Handle cases like "Agent-2_Trustor_G1" -> should be "Agent-2_Trustor_G2"
                import re
                match = re.match(r"Agent-(\d+)_Trustor_G\d+", trustor_name)
                if match:
                    agent_id = match.group(1)
                    # Find the correct name for this agent ID
                    for mapped_name in self.partner_mapping.keys():
                        if "_Trustor_" in mapped_name and mapped_name.startswith(f"Agent-{agent_id}_"):
                            normalized_name = mapped_name
                            logger.info(f"Normalized trustor name from '{trustor_name}' to '{normalized_name}'")
                            break

            # Validate investment
            if (
                not isinstance(investment, int)
                or investment < 0
                or investment > self.initial_funds
            ):
                investment = 0

            self._pending_investments[normalized_name] = investment

            return SubmitInvestmentResponse(
                trustor_name=normalized_name,
                investment=investment,
                status="submitted",
            )

    @tool(readonly=False)
    async def submit_return(
        self, trustee_name: str, return_amount: int
    ) -> SubmitReturnResponse:
        """
        Submit return decision for a trustee.

        Args:
            trustee_name: The trustee's full name (format: "Agent-{id}_Trustee_G{game_num}")
                         Example: "Agent-5_Trustee_G1", "Agent-6_Trustee_G2"
                         IMPORTANT: Use the exact trustee name, NOT the agent ID number!
            return_amount: The return amount (0 to received_amount)

        Returns:
            Response containing submission status.
        """
        async with self._lock:
            # Auto-setup partner mapping if not set
            if not self.partner_mapping:
                self._auto_setup_partner_mapping(trustee_name)

            # Normalize trustee_name: try to find matching name in partner_mapping
            normalized_name = trustee_name

            if trustee_name in self.partner_mapping:
                # Direct match - use as is
                normalized_name = trustee_name
            elif trustee_name.isdigit():
                # If given a bare ID like "5", search for matching full name
                for mapped_name in self.partner_mapping.keys():
                    if "_Trustee_" in mapped_name and mapped_name.startswith(f"Agent-{trustee_name}_"):
                        normalized_name = mapped_name
                        break
            elif trustee_name.startswith("agent"):
                # Handle lowercase variations like "agent_5"
                for mapped_name in self.partner_mapping.keys():
                    if "_Trustee_" in mapped_name and mapped_name.lower().replace("_", "").replace("-", "") == trustee_name.lower().replace("_", "").replace("-", ""):
                        normalized_name = mapped_name
                        break
            else:
                # Try to extract agent ID from name and find correct name
                # Handle cases like "Agent-3_Trustee_G3" -> should be "Agent-7_Trustee_G3"
                import re
                match = re.match(r"Agent-(\d+)_Trustee_G\d+", trustee_name)
                if match:
                    agent_id = match.group(1)
                    # Find the correct name for this agent ID
                    for mapped_name in self.partner_mapping.keys():
                        if "_Trustee_" in mapped_name and mapped_name.startswith(f"Agent-{agent_id}_"):
                            normalized_name = mapped_name
                            logger.info(f"Normalized trustee name from '{trustee_name}' to '{normalized_name}'")
                            break

            # Validate return amount (will be validated against received amount in step)
            if not isinstance(return_amount, int) or return_amount < 0:
                return_amount = 0

            self._pending_returns[normalized_name] = return_amount

            return SubmitReturnResponse(
                trustee_name=normalized_name,
                return_amount=return_amount,
                status="submitted",
            )

    @tool(readonly=True)
    async def get_pair_data(self, trustor_name: str) -> GetPairDataResponse:
        """
        Get data for a specific trustor-trustee pair from the last round.

        Args:
            trustor_name: The trustor's full name (format: "Agent-{id}_Trustor_G{game_num}")
                         Example: "Agent-1_Trustor_G1", "Agent-3_Trustor_G2"

        Returns:
            Response containing pair data from the last round.
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

        Args:
            trustee_name: The trustee's full name (format: "Agent-{id}_Trustee_G{game_num}")
                         Example: "Agent-2_Trustee_G1", "Agent-4_Trustee_G2"

        Returns:
            Response containing pair data from the last round.
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
    async def get_round_history(self, round_num: Optional[int] = None) -> List[dict]:
        """
        Get round history.

        Args:
            round_num: Optional round number. If None, returns all rounds.

        Returns:
            List of round summaries.
        """
        async with self._lock:
            if round_num is not None:
                return [
                    r for r in self.round_history if r.get("round") == round_num
                ]
            return self.round_history.copy()

    @tool(readonly=True)
    async def get_pending_investment(self, trustor_name: str) -> GetPendingInvestmentResponse:
        """
        Get pending investment for a trustor in the current round.
        This allows trustees to check if their partner trustor has submitted an investment.

        Args:
            trustor_name: The trustor's name

        Returns:
            Response containing pending investment amount and calculated received amount.
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

        Returns:
            A dictionary containing game setup info: num_pairs, initial_funds,
            multiplication_factor, current_round, and all agent pairings.
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
                pairs.append({
                    "game_num": game_num,
                    "trustor": trustor_name,
                    "trustee": trustee_name,
                })

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

        Args:
            agent_id: The agent's ID

        Returns:
            A dictionary containing the agent's role, current round, partner info, and game history.
        """
        async with self._lock:
            # Auto-setup partner mapping if not set
            if not self.partner_mapping:
                logger.info(f"[get_trust_game_status] partner_mapping is empty, calling _auto_setup_partner_mapping for agent_id={agent_id}")
                self._auto_setup_partner_mapping(f"Agent-{agent_id}_Trustor_G1")
                logger.info(f"[get_trust_game_status] after _auto_setup_partner_mapping, partner_mapping={self.partner_mapping}")

            # Find agent info from partner_mapping
            agent_name = None
            agent_role = None
            partner_name = None

            logger.info(f"[get_trust_game_status] Searching for agent_id={agent_id} in partner_mapping keys: {list(self.partner_mapping.keys())}")

            for name in self.partner_mapping.keys():
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
                    trustor_investment = last_round["trustor_investments"].get(partner_name, 0)
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
        
        Args:
            tick: The number of ticks of this simulation step.
            t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t
            last_round = self.round_history[-1] if self.round_history else None
            
            # Check if we have enough submissions to execute a round
            # Need all trustors' investments; if trustees haven't submitted returns yet, default to 0
            if len(self._pending_investments) >= self.num_pairs:
                # Execute the round
                self.round_number += 1

                # Calculate received amounts for trustees
                trustee_received = {}
                # 仅保留有效的trustor_name（在partner_mapping中存在的）
                valid_investments = {}
                for trustor_name, investment in self._pending_investments.items():
                    trustee_name = self.partner_mapping.get(trustor_name)
                    if trustee_name:
                        trustee_received[trustee_name] = (
                            investment * self.multiplication_factor
                        )
                        valid_investments[trustor_name] = investment

                # Validate returns against received amounts
                # If a trustee hasn't submitted a return, default to 0 (no return)
                validated_returns = {}
                for trustee_name in trustee_received.keys():
                    if trustee_name in self._pending_returns:
                        return_amount = self._pending_returns[trustee_name]
                        received = trustee_received.get(trustee_name, 0)
                        if isinstance(return_amount, int) and 0 <= return_amount <= received:
                            validated_returns[trustee_name] = return_amount
                        else:
                            validated_returns[trustee_name] = 0
                    else:
                        # Trustee hasn't submitted, default to 0
                        validated_returns[trustee_name] = 0

                # Calculate payoffs
                payoffs = {}
                for trustor_name, investment in valid_investments.items():
                    trustee_name = self.partner_mapping.get(trustor_name)
                    if trustee_name:
                        returned = validated_returns.get(trustee_name, 0)
                        trustor_payoff = (
                            self.initial_funds - investment + returned
                        )
                        trustee_payoff = trustee_received.get(trustee_name, 0) - returned
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

    def _dump_state(self) -> dict:
        """Serialize state"""
        return {
            "num_pairs": self.num_pairs,
            "initial_funds": self.initial_funds,
            "multiplication_factor": self.multiplication_factor,
            "round_number": self.round_number,
            "round_history": self.round_history,
            "partner_mapping": self.partner_mapping,
            "pending_investments": self._pending_investments,
            "pending_returns": self._pending_returns,
            "step_counter": self._step_counter,
        }

    def _load_state(self, state: dict):
        """Deserialize state"""
        self.num_pairs = state.get("num_pairs", 4)
        self.initial_funds = state.get("initial_funds", 10)
        self.multiplication_factor = state.get("multiplication_factor", 3)
        self.round_number = state.get("round_number", 0)
        self.round_history = state.get("round_history", [])
        self.partner_mapping = state.get("partner_mapping", {})
        self._pending_investments = state.get("pending_investments", {})
        self._pending_returns = state.get("pending_returns", {})
        self._step_counter = state.get("step_counter", 0)


__all__ = ["TrustGameEnv"]
