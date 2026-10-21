"""
Volunteer's Dilemma Game Agent
Agent for Volunteer's Dilemma game based on AgentSociety2
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class VolunteerDilemmaAgent(AgentBase):
    """Agent for Volunteer's Dilemma game based on AgentSociety2"""

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this agent class.
        Includes parameter descriptions.
        """
        description = f"""{cls.__name__}: Agent for Volunteer's Dilemma Game.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters (workspace contract):**
- id (int): The unique identifier for the agent.
- name (str): The name of the agent.
- config dict keys: num_rounds (int, default 10), num_agents (int, default 4),
  benefit_b (int, default 100), cost_c (int, default 40).

**Game Rules:**
This agent participates in a multi-round Volunteer's Dilemma Game. Each round, players choose "Volunteer" or "Stand by":
- If at least one player volunteers: All players receive benefit_b coins. Each volunteer pays cost_c.
- If no one volunteers: All players receive 0 coins.
- Net payoff for volunteering: benefit_b - cost_c (e.g., 60 coins)
- Net payoff for standing by when someone volunteers: benefit_b (e.g., 100 coins)
- Net payoff when no one volunteers: 0 coins

Players aim to maximize cumulative coins while balancing personal gain and collective benefit.

**Example initialization config:**
```json
{{
  "id": 1,
  "profile": {{"name": "Agent A"}},
  "config": {{"num_rounds": 10, "num_agents": 4, "benefit_b": 100, "cost_c": 40}}
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
    ) -> "VolunteerDilemmaAgent":
        """Reconstruct a ready VolunteerDilemmaAgent from its workspace."""
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
        self.decision_options = ["Volunteer", "Stand by"]
        self.num_rounds = int(cfg.get("num_rounds", 10))
        self.num_agents = int(cfg.get("num_agents", 4))
        self.benefit_b = int(cfg.get("benefit_b", 100))
        self.cost_c = int(cfg.get("cost_c", 40))

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
        """Execute one step - make choice decision and submit to environment"""
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

            # Step 2: Decide choice using LLM
            choice, explanation = await self._decide_choice(
                current_round, all_agent_names
            )

            # Step 3: Submit choice to environment
            submit_result, submit_response = await self.ask_env(
                {
                    "variables": {
                        "agent_name": self.name,
                        "choice": choice,
                    }
                },
                "Please call submit_choice() using agent_name and choice from ctx['variables'] to submit my choice decision.",
                readonly=False,
                template_mode=True,
            )
            self._ensure_env_ask_ok(submit_result, submit_response, op="submit_choice")
            self._logger.info(
                f"[{self.name}] Round {current_round}: Submitted choice={choice}, "
                f"explanation={explanation[:50]}..."
            )

            return f"[{self.name}] Round {current_round}: Submitted choice {choice}"

        except Exception as e:
            error_message = f"Step execution failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] {error_message}")
            return f"[{self.name}] [ERROR] {error_message}"

    async def _decide_choice(
        self, round_num: int, all_agent_names: list
    ) -> tuple[str, str]:
        """Decide choice using LLM - determine whether to volunteer or stand by"""
        # Build history string
        history_str = self._build_history_string(all_agent_names)

        # Build prompt
        profile_str = self._build_profile_string()
        prompt = (
            f"{profile_str}\n"
            f"Current Game State:\n"
            f"This is round {round_num} of {self.num_rounds}.\n"
            f"{history_str}\n\n"
            "***CRITICAL DECISION INSTRUCTION***:\n"
            "Please make your decision strictly following this format:\n"
            "Decision: [Volunteer/Stand by]\n"
            "Explanation: [Brief 1-2 sentence explanation]"
        )

        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}], stream=False
            )

            if not response or not response.choices or len(response.choices) == 0:
                raise ValueError("LLM returned empty response")

            choice_obj = response.choices[0]
            if not hasattr(choice_obj, "message") or not choice_obj.message:
                raise ValueError("LLM returned empty response")

            content = choice_obj.message.content or ""  # type: ignore
            self._logger.debug(f"[{self.name}] [DEBUG] Raw response: {content}")

            if not content or content.isspace():
                raise ValueError("LLM returned empty response")

            # Use regex to match choice and explanation
            match_volunteer = re.search(r"volunteer", content, re.IGNORECASE)
            match_standby = re.search(r"stand by", content, re.IGNORECASE)

            if match_volunteer and (
                not match_standby or match_volunteer.start() < match_standby.start()
            ):
                choice = self.decision_options[0]  # 'Volunteer'
                explanation = (
                    content[match_volunteer.end() :].strip()
                    if match_volunteer.end() < len(content)
                    else ""
                )
            elif match_standby:
                choice = self.decision_options[1]  # 'Stand by'
                explanation = (
                    content[match_standby.end() :].strip()
                    if match_standby.end() < len(content)
                    else ""
                )
            else:
                raise ValueError(
                    f"Failed to parse valid choice, content:\n{content[:200]}"
                )

            # Clean explanation
            if not explanation:
                explanation = "No explanation provided"

            self._logger.info(
                f"[{self.name}] [SUCCESS] Final parsed: choice={choice}, explanation={explanation[:50]}..."
            )

        except Exception as e:
            error_message = f"Parsing/call failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] [ERROR] {error_message}")

            choice = self.decision_options[1]
            explanation = f"[CRITICAL FAILURE] {error_message}, using default selection: {self.decision_options[1]}"

        self._logger.debug(f"[{self.name}] [DEBUG] Final selection: {choice}")
        return choice, explanation

    def _parse_round_history(self, env_result: Any, response: str) -> list:
        """Parse round history from environment response"""
        rounds = self._extract_env_list_result(env_result, response, "round_history")
        return [round_data for round_data in rounds if isinstance(round_data, dict)]

    def _sync_history(self, round_history: list):
        """Sync local history with environment round history"""
        # Update local history from environment round history
        self.history = []
        for round_data in round_history:
            round_summary = {
                "round": round_data.get("round", 0),
                "choices": round_data.get("choices", {}),
                "num_volunteers": round_data.get("num_volunteers", 0),
                "payoffs": round_data.get("payoffs", {}),
            }
            self.history.append(round_summary)

    def _extract_agent_names(self) -> list:
        """Extract all agent names from history"""
        agent_names = set()
        for round_summary in self.history:
            choices = round_summary.get("choices", {})
            agent_names.update(choices.keys())
            payoffs = round_summary.get("payoffs", {})
            agent_names.update(payoffs.keys())

        # If no history, return default names
        if not agent_names:
            agent_names = {f"Agent {chr(65 + i)}" for i in range(self.num_agents)}

        return sorted(agent_names)

    def _build_profile_string(self) -> str:
        """Build profile string from profile dict with complete game rules"""
        if isinstance(self._profile, dict):
            name = self._profile.get("name", f"Agent {self.id}")
            # Build complete game rules description matching baseline
            volunteer_net_payoff = self.benefit_b - self.cost_c
            standby_success_payoff = self.benefit_b
            return (
                f"You are {name}, a participant in a {self.num_rounds}-round Volunteer's Dilemma Game.\n"
                "Your goal is to maximize your personal cumulative coins.\n"
                "Rules:\n"
                "1. Each round, choose 'Volunteer' or 'Stand by'.\n"
                f"2. If at least one player 'Volunteers': All players receive {self.benefit_b} coins. Each 'Volunteer' pays a cost of {self.cost_c} coins.\n"
                "3. If NO player 'Volunteers': All players receive 0 coins.\n"
                f"4. Your net payoff if you Volunteer: {volunteer_net_payoff} coins.\n"
                f"5. Your net payoff if you Stand by and someone else Volunteers: {standby_success_payoff} coins.\n"
                "6. Your net payoff if you Stand by and no one Volunteers: 0 coins.\n"
                "7. No communication allowed. You know all past choices and payoffs.\n"
                "Strategic Note: While standing by gives higher payoff if someone else volunteers, if everyone stands by, everyone gets 0.\n"
                "You need to balance between personal gain and collective benefit."
            )
        elif isinstance(self._profile, str):
            return self._profile
        else:
            # Fallback: build profile with game rules even if profile is not dict
            volunteer_net_payoff = self.benefit_b - self.cost_c
            standby_success_payoff = self.benefit_b
            return (
                f"You are a participant in a {self.num_rounds}-round Volunteer's Dilemma Game.\n"
                "Your goal is to maximize your personal cumulative coins.\n"
                "Rules:\n"
                "1. Each round, choose 'Volunteer' or 'Stand by'.\n"
                f"2. If at least one player 'Volunteers': All players receive {self.benefit_b} coins. Each 'Volunteer' pays a cost of {self.cost_c} coins.\n"
                "3. If NO player 'Volunteers': All players receive 0 coins.\n"
                f"4. Your net payoff if you Volunteer: {volunteer_net_payoff} coins.\n"
                f"5. Your net payoff if you Stand by and someone else Volunteers: {standby_success_payoff} coins.\n"
                "6. Your net payoff if you Stand by and no one Volunteers: 0 coins.\n"
                "7. No communication allowed. You know all past choices and payoffs.\n"
                "Strategic Note: While standing by gives higher payoff if someone else volunteers, if everyone stands by, everyone gets 0.\n"
                "You need to balance between personal gain and collective benefit."
            )

    def _build_history_string(self, all_agent_names: list) -> str:
        """Build history string"""
        if not self.history:
            return "No previous rounds have been played."

        history_lines = []
        history_lines.append("History of previous rounds:")

        cumulative_payoffs = {name: 0 for name in all_agent_names}

        for round_summary in self.history:
            r = round_summary["round"]
            choices = round_summary["choices"]
            num_volunteers = round_summary["num_volunteers"]
            payoffs = round_summary["payoffs"]

            for name in all_agent_names:
                cumulative_payoffs[name] += payoffs.get(name, 0)

            history_lines.append(f"Round {r}:")
            history_lines.append(
                f"  Choices: {', '.join([f'{name}: {choices[name]}' for name in all_agent_names])}"
            )
            history_lines.append(f"  Number of volunteers: {num_volunteers}")

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
