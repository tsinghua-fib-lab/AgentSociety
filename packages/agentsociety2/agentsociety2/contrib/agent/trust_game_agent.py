"""
Trust Game Agent
Agent for Trust Game based on AgentSociety2
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class TrustGameAgent(AgentBase):
    """Agent for Trust Game based on AgentSociety2"""

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this agent class.
        Includes parameter descriptions.
        """
        description = f"""{cls.__name__}: Agent for Trust Game.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters (workspace contract):**
- id (int): The unique identifier for the agent.
- name (str): The name of the agent.
- role (Literal["Trustor", "Trustee"]): The role of the agent.
- config dict keys: num_rounds (int, default 10), initial_funds (int, default 10),
  multiplication_factor (int, default 3), partner_name (str, default "").

**Game Rules:**
This agent participates in a multi-round Trust Game with two roles:
- **Trustor**: Starts with initial_funds coins per round, sends 0-initial_funds to Trustee. Amount is multiplied before Trustee receives it. Payoff = initial_funds - sent + returned.
- **Trustee**: Receives (sent amount × multiplication_factor) coins, returns 0-received to Trustor. Payoff = received - returned.

Both roles aim to maximize cumulative coins while considering trust and reciprocity.

**Example initialization config:**
```json
{{
  "id": 1,
  "profile": {{"name": "Trustor A"}},
  "config": {{"role": "Trustor", "num_rounds": 10, "initial_funds": 10, "multiplication_factor": 3, "partner_name": ""}}
}}
```
"""
        return description

    # ==================== Workspace 契约 ====================

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        """Create the initial agent workspace."""
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        agent_id = int(profile.get("id", 0))
        name = str(profile.get("name") or f"Agent_{agent_id}")
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": agent_id,
                    "name": name,
                    "profile": profile,
                    "step_count": 0,
                    "history": [],
                    "current_funds": int((config or {}).get("initial_funds", 10)),
                    "partner_name": str((config or {}).get("partner_name", "")),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: Any
    ) -> "TrustGameAgent":
        """Reconstruct a ready TrustGameAgent from its workspace."""
        agent = cls()
        await agent._restore(workspace_path, service_proxy)
        return agent

    async def _restore(self, workspace_path: Path, service_proxy: Any) -> None:
        """Restore game-agent state from AGENT.json + config.json (no super() —
        game agents don't use the skill/workspace runtime that
        AgentBase._restore binds)."""
        workspace_path = Path(workspace_path)
        cfg = {}
        config_path = workspace_path / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {"name": meta.get("name")})
        self._name = meta.get("name") or f"Agent_{self._id}"
        self._config = dict(cfg or {})
        self._bind_services(service_proxy)
        self._step_count = int(meta.get("step_count", 0))
        # custom attributes
        self._role = cfg.get("role", "Trustor")
        self.history = list(meta.get("history", []))
        self.num_rounds = int(cfg.get("num_rounds", 10))
        self.initial_funds = int(cfg.get("initial_funds", 10))
        self._current_funds = int(meta.get("current_funds", self.initial_funds))
        self.multiplication_factor = int(cfg.get("multiplication_factor", 3))
        partner = meta.get("partner_name") or cfg.get("partner_name", "")
        self._partner_name = str(partner)
        # Validate role
        if self._role not in ["Trustor", "Trustee"]:
            raise ValueError(
                f"Invalid role: {self._role}. Must be 'Trustor' or 'Trustee'"
            )

    async def to_workspace(self, workspace_path: Path) -> None:
        """Write current dynamic state back to the workspace."""
        workspace_path = Path(workspace_path)
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": self._id,
                    "name": self._name,
                    "role": self._role,
                    "profile": self.get_profile(),
                    "step_count": self._step_count,
                    "history": self.history,
                    "current_funds": self._current_funds,
                    "partner_name": self._partner_name,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def set_partner_name(self, partner_name: str):
        """Set partner name (called by environment)"""
        self._partner_name = partner_name

    @property
    def role(self) -> str:
        """Return agent role"""
        return self._role

    async def ask(self, message: str, readonly: bool = True) -> str:
        """Answer questions"""
        prompt = f"{self._profile}\n\n{message}"
        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}], stream=False
            )
            if response and response.choices and len(response.choices) > 0:
                choice = response.choices[0]
                if hasattr(choice, "message") and choice.message:
                    return choice.message.content or ""  # type: ignore
            return "[错误] LLM返回空响应"
        except Exception as e:
            error_message = f"LLM调用失败: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] {error_message}")
            return f"[错误] {error_message}"

    async def step(self, tick: int, t: datetime) -> str:
        """Submit a real decision in the current investment/return phase."""
        if self._env is None:
            raise RuntimeError("Trust game environment is not initialized")
        history, answer = await self.ask_env(
            {},
            "Call get_round_history() and store the list in results['round_history'].",
            readonly=True,
            template_mode=True,
        )
        self._ensure_env_ask_ok(history, answer, op="get_round_history")
        self._sync_history(history["round_history"])
        current_round = len(self.history) + 1
        partner = self._partner_name
        if not partner:
            raise ValueError("Trust game requires an explicit partner_name")
        trustor = self.name if self._role == "Trustor" else partner
        pending, answer = await self.ask_env(
            {"variables": {"trustor_name": trustor}},
            "Call get_pending_investment with ctx['variables']['trustor_name']; "
            "store the returned investment field (integer or None) in results['investment'].",
            readonly=True,
            template_mode=True,
        )
        self._ensure_env_ask_ok(pending, answer, op="get_pending_investment")
        investment = pending["investment"]
        if self._role == "Trustor":
            if investment is not None:
                return f"[{self.name}] Waiting for {partner}'s return"
            amount, _ = await self._decide_investment(current_round, partner)
            variables = {"trustor_name": self.name, "investment": amount}
            operation = "submit_investment"
        else:
            if investment is None:
                return f"[{self.name}] Waiting for {partner}'s investment"
            if type(investment) is not int or investment < 0:
                raise ValueError("Invalid pending investment")
            self._current_funds = investment * self.multiplication_factor
            amount = 0
            if self._current_funds:
                amount, _ = await self._decide_return(
                    current_round, partner, self._current_funds
                )
            variables = {"trustee_name": self.name, "return_amount": amount}
            operation = "submit_return"
        result, answer = await self.ask_env(
            {"variables": variables},
            f"Call {operation} using the named values in ctx['variables'].",
            readonly=False,
            template_mode=True,
        )
        self._ensure_env_ask_ok(result, answer, op=operation)
        return f"[{self.name}] Round {current_round}: {operation}={amount}"

    async def _decide_investment(
        self, round_num: int, partner_name: str
    ) -> tuple[int, str]:
        """Decide investment amount using LLM"""
        # Build history string
        history_str = self._build_history_string(partner_name)

        # Build prompt
        prompt = self._build_trustor_prompt(
            round_num,
            self.initial_funds,
            self.multiplication_factor,
            self.num_rounds,
            self.initial_funds,
            history_str,
        )

        investment = 0  # Default investment

        try:
            content = await self._completion_text(
                [{"role": "user", "content": prompt}]
            )
            self._logger.debug(f"[{self.name}] Raw LLM response: {content[:200]}...")

            # Parse numerical value
            investment = self._parse_amount(content, self._role, self.initial_funds)

            # Extract explanation
            explanation = self._extract_explanation(content)

            self._logger.info(
                f"[{self.name}] Decision: {investment} coins, explanation: {explanation[:50]}..."
            )

        except Exception as e:
            error_msg = f"Decision making failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] {error_msg}")
            raise RuntimeError(error_msg) from e

        return investment, explanation

    async def _decide_return(
        self, round_num: int, partner_name: str, received_amount: int
    ) -> tuple[int, str]:
        """Decide return amount using LLM"""
        # Build history string
        history_str = self._build_history_string(partner_name)

        # Build prompt
        prompt = self._build_trustee_prompt(
            round_num,
            self.initial_funds,
            self.multiplication_factor,
            self.num_rounds,
            received_amount,
            history_str,
        )

        return_amount = 0  # Default return

        try:
            content = await self._completion_text(
                [{"role": "user", "content": prompt}]
            )
            self._logger.debug(f"[{self.name}] Raw LLM response: {content[:200]}...")

            # Parse numerical value
            return_amount = self._parse_amount(content, self._role, received_amount)

            # Extract explanation
            explanation = self._extract_explanation(content)

            self._logger.info(
                f"[{self.name}] Decision: {return_amount} coins, explanation: {explanation[:50]}..."
            )

        except Exception as e:
            error_msg = f"Decision making failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] {error_msg}")
            raise RuntimeError(error_msg) from e

        return return_amount, explanation

    def update_history(self, round_summary: dict):
        """Update agent's history with current round summary"""
        self.history.append(round_summary)

    def _build_profile_string(self) -> str:
        """Build profile string with complete game rules matching baseline"""
        if isinstance(self._profile, dict):
            name = self._profile.get("name", f"Agent {self.id}")
        else:
            name = self._name

        if self._role == "Trustor":
            return (
                f"You are {name}, Trustor in a {self.num_rounds}-round Trust Game.\n"
                f"Goal: Maximize cumulative coins.\n"
                f"Rules: Start with {self.initial_funds} coins/round.\n"
                f"Send 0-{self.initial_funds} coins (×{self.multiplication_factor} for Trustee).\n"
                f"Trustee returns some coins. Your payoff: {self.initial_funds} - sent + returned.\n"
                "Consider past Trustee behavior."
            )
        else:
            return (
                f"You are {name}, Trustee in a {self.num_rounds}-round Trust Game.\n"
                f"Goal: Maximize cumulative coins.\n"
                f"Rules: Receive (sent amount)×{self.multiplication_factor} coins from Trustor.\n"
                "Return 0-received coins. Your payoff: received - returned.\n"
                "Consider past Trustor behavior."
            )

    def _parse_round_history(self, env_result: Any, response: str) -> list:
        """Parse round history from environment response"""
        rounds = self._extract_env_list_result(env_result, response, "round_history")
        return [round_data for round_data in rounds if isinstance(round_data, dict)]

    def _sync_history(self, round_history: list):
        """Sync local history with environment round history"""
        # Update local history from environment round history
        # Convert environment format to local format
        self.history = []
        for round_data in round_history:
            round_num = round_data.get("round", 0)
            trustor_investments = round_data.get("trustor_investments", {})
            trustee_returns = round_data.get("trustee_returns", {})
            payoffs = round_data.get("payoffs", {})

            if self._role == "Trustor":
                sent_amount = trustor_investments.get(self.name, 0)
                # Find partner trustee
                partner_name = self._extract_partner_name()
                if partner_name:
                    returned_amount = trustee_returns.get(partner_name, 0)
                else:
                    returned_amount = 0
                payoff = payoffs.get(self.name, 0)

                self.history.append(
                    {
                        "round": round_num,
                        "sent_amount": sent_amount,
                        "returned_amount": returned_amount,
                        "payoff": payoff,
                        "multiplication_factor": self.multiplication_factor,
                    }
                )
            else:  # Trustee
                # Find partner trustor
                partner_name = self._extract_partner_name()
                if partner_name:
                    sent_amount = trustor_investments.get(partner_name, 0)
                    received_amount = sent_amount * self.multiplication_factor
                else:
                    sent_amount = 0
                    received_amount = 0
                returned_amount = trustee_returns.get(self.name, 0)
                payoff = payoffs.get(self.name, 0)

                self.history.append(
                    {
                        "round": round_num,
                        "sent_amount": sent_amount,
                        "received_amount": received_amount,
                        "returned_amount": returned_amount,
                        "payoff": payoff,
                        "multiplication_factor": self.multiplication_factor,
                    }
                )

    def _extract_partner_name(self) -> str:
        """Extract partner name"""
        # Use stored partner name if available
        if self._partner_name:
            return self._partner_name

        # Try to extract from history by checking round data
        if self.history:
            # Partner name should be set by environment, but we can try to infer from history
            # This is a fallback - partner mapping should be set explicitly
            return ""

        return ""

    def _extract_partner_name_from_env(self) -> str:
        """Extract partner name - use stored partner name"""
        return self._partner_name

    def _build_history_string(self, partner_name: str) -> str:
        """Build history string"""
        if not self.history:
            return "No previous rounds have been played."

        history_lines = []
        history_lines.append("History of previous rounds:")

        for round_summary in self.history:
            r = round_summary["round"]

            if self._role == "Trustor":
                sent_amount = round_summary.get("sent_amount", 0)
                returned_amount = round_summary.get("returned_amount", 0)
                payoff = round_summary.get("payoff", 0)
                history_lines.append(
                    f"Round {r}: You sent {sent_amount} coins. {partner_name} returned {returned_amount} coins. Your payoff: {payoff:.2f} coins."
                )
            else:  # Trustee
                sent_amount = round_summary.get("sent_amount", 0)
                received_amount = round_summary.get("received_amount", 0)
                returned_amount = round_summary.get("returned_amount", 0)
                payoff = round_summary.get("payoff", 0)
                history_lines.append(
                    f"Round {r}: You received {received_amount} coins (from {partner_name}'s {sent_amount} coins * {round_summary.get('multiplication_factor', 3)}). You returned {returned_amount} coins. Your payoff: {payoff:.2f} coins."
                )

        return "\n".join(history_lines)

    def _build_trustor_prompt(
        self,
        round_num: int,
        initial_funds: int,
        multiplication_factor: int,
        num_rounds: int,
        current_funds: int,
        history_str: str,
    ) -> str:
        """Build prompt for Trustor"""
        return (
            f"Round {round_num} of {num_rounds}\n"
            f"Current funds: {current_funds}\n"
            f"Send 0-{initial_funds} coins to Trustee (amount × {multiplication_factor} for them)\n"
            f"Your goal: Maximize total coins (payoff = {initial_funds} - sent + returned)\n\n"
            f"{history_str}\n\n"
            "Decision format:\n"
            "Amount: [0-10]\n"
            "Explanation: [brief strategic reason]"
        )

    def _build_trustee_prompt(
        self,
        round_num: int,
        initial_funds: int,
        multiplication_factor: int,
        num_rounds: int,
        current_funds: int,
        history_str: str,
    ) -> str:
        """Build prompt for Trustee"""
        return (
            f"Round {round_num} of {num_rounds}\n"
            f"Received: {current_funds} coins (Trustor sent {current_funds / multiplication_factor})\n"
            f"Return 0-{current_funds} coins to Trustor\n"
            f"Your goal: Maximize total coins (payoff = {current_funds} - returned)\n\n"
            f"{history_str}\n\n"
            "Decision format:\n"
            f"Amount: [0-{current_funds}]\n"
            "Explanation: [brief strategic reason]"
        )

    def _parse_amount(self, content: str, role: str, max_amount: int) -> int:
        """Parse numerical amount from LLM response"""
        match = re.search(r"\b(\d+)\b", content)
        if not match:
            raise ValueError(
                f"Failed to parse valid numerical amount from response: {content[:200]}..."
            )

        parsed_val = int(match.group(0))

        # Validate amount range based on role
        if not (0 <= parsed_val <= max_amount):
            self._logger.warning(
                f"[{self._name}] Invalid {role.lower()} amount ({parsed_val}) detected, must be between 0 and {max_amount}"
            )
            return 0  # Use 0 as safe default

        return parsed_val

    def _extract_explanation(self, content: str) -> str:
        """Extract explanation from LLM response"""
        # Look for explanation after the amount
        match = re.search(r"\b\d+\b", content)
        if match:
            explanation = content[match.end() :].strip()
            return explanation if explanation else "No explanation provided"

        # If no amount found, return entire content as explanation
        return content.strip() if content.strip() else "No explanation provided"
