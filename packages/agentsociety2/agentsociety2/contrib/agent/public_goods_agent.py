"""
Public Goods Game Agent
Agent for Public Goods Game based on AgentSociety2
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class PublicGoodsAgent(AgentBase):
    """Agent for Public Goods Game based on AgentSociety2"""

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this agent class.
        Includes parameter descriptions.
        """
        description = f"""{cls.__name__}: Agent for Public Goods Game.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters (workspace contract):**
- id (int): The unique identifier for the agent.
- name (str): The name of the agent.
- config dict keys: num_rounds (int, default 10), num_agents (int, default 4),
  initial_endowment (int, default 20), public_pool_multiplier (float, default 1.6).

**Game Rules:**
This agent participates in a multi-round Public Goods Game. Each round, players receive an endowment and can contribute 0 to all coins to a public fund. The total public fund is multiplied and equally shared among all players. Players aim to maximize cumulative coins while balancing individual benefit and collective cooperation.

**Example initialization config:**
```json
{{
  "id": 1,
  "profile": {{"name": "Agent A"}},
  "config": {{"num_rounds": 10, "num_agents": 4, "initial_endowment": 20, "public_pool_multiplier": 1.6}}
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
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: Any
    ) -> "PublicGoodsAgent":
        """Reconstruct a ready PublicGoodsAgent from its workspace."""
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
        self.history = list(meta.get("history", []))
        self.num_rounds = int(cfg.get("num_rounds", 10))
        self.num_agents = int(cfg.get("num_agents", 4))
        self.initial_endowment = int(cfg.get("initial_endowment", 20))
        self.public_pool_multiplier = float(cfg.get("public_pool_multiplier", 1.6))
        self.max_contribution = self.initial_endowment
        self.min_contribution = 0

    async def to_workspace(self, workspace_path: Path) -> None:
        """Write current dynamic state (history) back to the workspace."""
        workspace_path = Path(workspace_path)
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": self._id,
                    "name": self._name,
                    "profile": self.get_profile(),
                    "step_count": self._step_count,
                    "history": self.history,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    async def ask(self, message: str, readonly: bool = True) -> str:
        """Answer questions"""
        profile_str = self._build_profile_string()
        prompt = f"{profile_str}\n\n{message}"
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
        """Execute one step - make contribution decision and submit to environment"""
        if self._env is None:
            return f"[{self.name}] Environment not initialized"
        self._step_count += 1

        try:
            # Step 1: Get round history from environment
            history_result, history_response = await self.ask_env(
                {},
                "Please call get_round_history() and store the returned list in results['round_history'].",
                readonly=True,
                template_mode=True,
            )
            self._logger.debug(f"[{self.name}] History response: {history_response}")

            # Parse and update local history
            round_history = self._parse_round_history(history_result, history_response)
            self._sync_history(round_history)

            # Determine current round number (next round = len(history) + 1)
            current_round = len(self.history) + 1

            # Extract all agent names from history if available
            all_agent_names = self._extract_agent_names()

            # Step 2: Decide contribution amount using LLM
            contribution, explanation = await self._decide_contribution(
                current_round, all_agent_names
            )

            # Step 3: Submit contribution to environment
            submit_result, submit_response = await self.ask_env(
                {
                    "variables": {
                        "agent_name": self.name,
                        "contribution": contribution,
                    }
                },
                "Please call submit_contribution() using agent_name and contribution from ctx['variables'] to submit my contribution decision.",
                readonly=False,
                template_mode=True,
            )
            self._ensure_env_ask_ok(
                submit_result, submit_response, op="submit_contribution"
            )
            self._logger.info(
                f"[{self.name}] Round {current_round}: Submitted contribution={contribution}, "
                f"explanation={explanation[:50]}..."
            )

            return f"[{self.name}] Round {current_round}: Submitted contribution {contribution}"

        except Exception as e:
            error_message = f"Step execution failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] {error_message}")
            return f"[{self.name}] [ERROR] {error_message}"

    async def _decide_contribution(
        self, round_num: int, all_agent_names: list
    ) -> tuple[int, str]:
        """Decide contribution amount using LLM"""
        # Build history string
        history_str = self._build_history_string(all_agent_names)

        personality = str(self._profile.get("personality", "unspecified"))
        prompt = (
            f"You are {self.name}; personality: {personality}.\n"
            f"Public Goods Game, round {round_num}/{self.num_rounds}: "
            f"{self.num_agents} players each receive {self.initial_endowment} coins. "
            f"Contributions are multiplied by {self.public_pool_multiplier} and "
            "shared equally.\n"
            f"{history_str}\n"
            f"Choose an integer from {self.min_contribution} to "
            f"{self.max_contribution}. Reply only: <integer> - <one short reason>."
        )

        contribution = 0
        explanation = ""

        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}],
                stream=False,
                max_retries=5,
                max_delay=90.0,
                max_tokens=2048,
            )

            if not response or not response.choices or len(response.choices) == 0:
                raise ValueError("LLM returned empty response")

            choice = response.choices[0]
            if not hasattr(choice, "message") or not choice.message:
                raise ValueError("LLM returned empty response")

            content = choice.message.content or ""  # type: ignore
            self._logger.debug(f"[{self.name}] [DEBUG] Raw response: {content}")

            if not content or content.isspace():
                raise ValueError("LLM returned empty response")

            # Use regex to match number and explanation
            match = re.search(r"^\s*(\d+)\s*[-–—]?\s*(.*)$", content, re.DOTALL)

            if match:
                parsed_contribution = int(match.group(1))

                if (
                    self.min_contribution
                    <= parsed_contribution
                    <= self.max_contribution
                ):
                    contribution = parsed_contribution
                else:
                    self._logger.warning(
                        f"[{self.name}] [WARNING] Contribution value out of range: {parsed_contribution}, using default 0"
                    )
                    contribution = 0

                if match.group(2):
                    explanation = match.group(2).strip()
                else:
                    explanation = "No explanation provided"

                self._logger.info(
                    f"[{self.name}] [SUCCESS] Final parsed: contribution={contribution}, explanation={explanation[:50]}..."
                )
            else:
                # Fallback: search entire response for number
                keyword_match = re.search(r"\b(\d+)\b", content)
                if keyword_match:
                    parsed_contribution = int(keyword_match.group(1))
                    if (
                        self.min_contribution
                        <= parsed_contribution
                        <= self.max_contribution
                    ):
                        contribution = parsed_contribution
                    else:
                        contribution = 0
                    explanation = f"Extracted keyword from response: {contribution}"
                    self._logger.info(
                        f"[{self.name}] [KEYWORD] Keyword match successful: contribution={contribution}"
                    )
                else:
                    raise ValueError(
                        f"Failed to parse valid contribution, content:\n{content[:200]}"
                    )

        except Exception as e:
            error_message = f"Parsing/call failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] [ERROR] {error_message}")
            raise RuntimeError(
                f"[{self.name}] LLM decision failed: {error_message}"
            ) from e

        self._logger.debug(f"[{self.name}] [DEBUG] Final selection: {contribution}")
        return contribution, explanation

    def _build_history_string(self, all_agent_names: list) -> str:
        """Build history string"""
        if not self.history:
            return "No previous rounds have been played."

        history_lines = []
        history_lines.append("History of previous rounds:")

        cumulative_payoffs = {name: 0 for name in all_agent_names}

        for round_summary in self.history:
            r = round_summary["round"]
            total_contrib = round_summary["total_contribution"]
            public_gain = round_summary["public_pool_gain"]
            payoffs = round_summary["payoffs"]

            for name in all_agent_names:
                cumulative_payoffs[name] += payoffs.get(name, 0)

            history_lines.append(f"Round {r}:")
            history_lines.append(
                f"  Total contributed to public fund: {total_contrib} coins."
            )
            history_lines.append(f"  Public fund gain: {public_gain:.2f} coins.")

            payoff_details = [
                f"{name} gained {payoffs.get(name, 0):.2f} coins"
                for name in all_agent_names
            ]
            history_lines.append("  " + ", ".join(payoff_details) + ".")

            cumulative_details = [
                f"{name} has {cumulative_payoffs[name]:.2f} coins total"
                for name in all_agent_names
            ]
            history_lines.append("  Cumulative: " + ", ".join(cumulative_details) + ".")

        return "\n".join(history_lines)

    def _build_profile_string(self) -> str:
        """Build profile string with complete game rules matching baseline"""
        # Calculate example values for the profile
        total_contribution = self.num_agents * self.initial_endowment
        public_gain = total_contribution * self.public_pool_multiplier
        per_player_gain = public_gain / self.num_agents

        return (
            f"You are {self._name}, a participant in a {self.num_rounds}-round Public Goods Game.\n"
            f"Your goal is to maximize your personal cumulative coins.\n"
            f"Rules: Each round, you receive {self.initial_endowment} coins.\n"
            f"- You can contribute 0 to {self.initial_endowment} coins to a public fund.\n"
            f"- The total public fund is multiplied by {self.public_pool_multiplier} and equally shared among all players.\n"
            f"- Your round gain = (coins not contributed) + (total public fund * {self.public_pool_multiplier} / {self.num_agents}).\n"
            f"- You know all past contributions and gains.\n\n"
            f"Strategic Note: While you can choose to contribute 0 coins (free-ride), consider that if everyone contributes, you'll all gain more.\n"
            f"For example, if all {self.num_agents} players contribute all {self.initial_endowment} coins:\n"
            f"- Total contribution: {self.num_agents} × {self.initial_endowment} = {total_contribution}\n"
            f"- Public fund gain: {total_contribution} × {self.public_pool_multiplier} = {public_gain}\n"
            f"- Each player gets: {public_gain} / {self.num_agents} = {per_player_gain} coins from the public fund\n"
            f"- Your total gain: {per_player_gain} coins (vs. {self.initial_endowment} coins if everyone free-rides)"
        )

    def _parse_round_history(self, env_result: Any, response: str) -> list:
        """Parse round history from environment response"""
        rounds = self._extract_env_list_result(env_result, response, "round_history")
        return [round_data for round_data in rounds if isinstance(round_data, dict)]

    def _sync_history(self, round_history: list):
        """Sync local history with environment history"""
        # Update local history to match environment history
        # Only add new rounds that we don't have yet
        existing_rounds = {r.get("round") for r in self.history}
        for round_data in round_history:
            round_num = round_data.get("round")
            if round_num and round_num not in existing_rounds:
                self.history.append(round_data)

    def _extract_agent_names(self) -> list:
        """Extract all agent names from history"""
        agent_names = set()
        for round_summary in self.history:
            payoffs = round_summary.get("payoffs", {})
            agent_names.update(payoffs.keys())

        # If no history, return default names
        if not agent_names:
            return [f"Agent {chr(65 + i)}" for i in range(self.num_agents)]

        return sorted(agent_names)
