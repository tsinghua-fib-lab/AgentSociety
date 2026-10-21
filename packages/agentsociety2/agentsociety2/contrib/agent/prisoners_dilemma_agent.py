"""
Prisoner's Dilemma Game Agent
Agent for Prisoner's Dilemma game based on AgentSociety2
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class PrisonersDilemmaAgent(AgentBase):
    """Agent for Prisoner's Dilemma game based on AgentSociety2"""

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this agent class.
        Includes parameter descriptions.
        """
        description = f"""{cls.__name__}: Agent for Prisoner's Dilemma game.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters (workspace contract):**
- id (int): The unique identifier for the agent.
- name (str): The name of the agent.

**Game Rules:**
This agent participates in a 10-round Prisoner's Dilemma game where two players simultaneously choose to cooperate (Yes) or defect (No). The payoff matrix is:
- Both cooperate: 3 points each
- One cooperates, one defects: 0 points (cooperator), 5 points (defector)
- Both defect: 1 point each

**Example initialization config:**
```json
{{
  "id": 1,
  "profile": {{"name": "Agent A"}},
  "config": {{}}
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
    ) -> "PrisonersDilemmaAgent":
        """Reconstruct a ready PrisonersDilemmaAgent from its workspace."""
        agent = cls()
        await agent._restore(workspace_path, service_proxy)
        return agent

    async def _restore(self, workspace_path: Path, service_proxy: Any) -> None:
        """Restore game-agent state from AGENT.json (no super() — game agents
        don't use the skill/workspace runtime that AgentBase._restore binds)."""
        workspace_path = Path(workspace_path)
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {"name": meta.get("name")})
        self._name = meta.get("name") or f"Agent_{self._id}"
        self._config = {}
        self._bind_services(service_proxy)
        self._step_count = int(meta.get("step_count", 0))
        # custom attributes
        self.history = list(meta.get("history", []))

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
        """Execute one step - make action decision and submit to environment"""
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

            # Extract opponent name from history if available
            opponent_name = self._extract_opponent_name()

            # Step 2: Decide action using LLM
            action, explanation = await self._decide_action(
                current_round, opponent_name
            )

            # Step 3: Submit action to environment
            submit_result, submit_response = await self.ask_env(
                {
                    "variables": {
                        "agent_name": self.name,
                        "action": action,
                    }
                },
                "Please call submit_action() using agent_name and action from ctx['variables'] to submit my action decision.",
                readonly=False,
                template_mode=True,
            )
            self._ensure_env_ask_ok(submit_result, submit_response, op="submit_action")
            self._logger.info(
                f"[{self.name}] Round {current_round}: Submitted action={action}, "
                f"explanation={explanation[:50]}..."
            )

            return f"[{self.name}] Round {current_round}: Submitted action {action}"

        except Exception as e:
            error_message = f"Step execution failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] {error_message}")
            return f"[{self.name}] [ERROR] {error_message}"

    async def _decide_action(
        self, round_num: int, opponent_name: str
    ) -> tuple[str, str]:
        """Decide action using LLM - determine cooperate or defect"""
        # Build history string
        history_str = self._build_history_string(opponent_name)

        # Build prompt
        profile_str = self._build_profile_string()
        prompt = (
            f"{profile_str}\n"
            f"This is round {round_num}.\n"
            f"{history_str}\n"
            "***CRITICAL INSTRUCTION***: Based ONLY on the rules and history, determine your action.\n"
            "Your decision must be either **Yes (Cooperate)** or **No (Defect/Betray)**.\n"
            "YOU MUST FOLLOW THIS OUTPUT FORMAT EXACTLY:\n"
            "\n"
            "<output>\n"
            "  <action>Yes or No</action>\n"
            "  <explanation>Your 1-2 sentence reasoning here.</explanation>\n"
            "</output>"
            "\n"
            "IMPORTANT: Do not write any additional text before or after the XML structure. Your entire output must consist of exactly the XML format shown above."
        )

        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}],
                stream=False,
                max_retries=5,
                max_delay=90.0,
            )

            if not response or not response.choices or len(response.choices) == 0:
                raise ValueError("LLM returned empty response")

            choice = response.choices[0]
            if not hasattr(choice, "message") or not choice.message:
                raise ValueError("LLM returned empty response")

            content = choice.message.content or ""  # type: ignore
            self._logger.debug(f"[{self.name}] [DEBUG] 原始响应: {content}")

            if not content or content.isspace():
                raise ValueError("LLM返回空响应")

            # Extract Action using regex
            action_match = re.search(
                r"<action>\s*(Yes|No)\s*</action>", content, re.IGNORECASE
            )
            if action_match:
                action = action_match.group(1).capitalize()

                # Extract Explanation
                explanation_match = re.search(
                    r"<explanation>(.*?)</explanation>",
                    content,
                    re.DOTALL | re.IGNORECASE,
                )
                if explanation_match:
                    explanation = explanation_match.group(1).strip()
                else:
                    explanation = f"选择了 '{action}'，但未在 XML 中提供解释"

                self._logger.info(
                    f"[{self.name}] [SUCCESS] 最终解析 (XML): action={action}, explanation={explanation[:50]}..."
                )
            else:
                # Fallback: single-line matching
                self._logger.warning(
                    f"[{self.name}] [WARNING] XML 解析失败，尝试单行匹配..."
                )
                lines = content.strip().split("\n")
                first_line = lines[0].strip()

                match = re.search(r"^\s*(yes|no)\s*[.!]?$", first_line, re.IGNORECASE)

                if match:
                    action = match.group(1).capitalize()
                    explanation = (
                        " ".join(lines[1:]).strip() or "单行匹配成功，无详细解释"
                    )
                    self._logger.info(
                        f"[{self.name}] [FALLBACK] 单行匹配成功: action={action}"
                    )
                else:
                    # Final fallback: keyword search
                    keyword_match = re.search(r"\b(yes|no)\b", content, re.IGNORECASE)
                    if keyword_match:
                        action = keyword_match.group(1).capitalize()
                        explanation = f"从响应中提取关键词：{action}"
                        self._logger.info(
                            f"[{self.name}] [KEYWORD] 关键词匹配成功: action={action}"
                        )
                    else:
                        raise ValueError(f"无法解析有效动作，内容:\n{content[:200]}")

        except Exception as e:
            error_message = f"解析/调用失败: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] [ERROR] {error_message}")
            raise RuntimeError(
                f"[{self.name}] LLM decision failed: {error_message}"
            ) from e

        self._logger.debug(f"[{self.name}] [DEBUG] 最终选择: {action}")
        return action, explanation

    def _build_profile_string(self) -> str:
        """Build profile string from profile dict"""
        if isinstance(self._profile, dict):
            # Build complete game rules description matching baseline
            return (
                "You are a rational decision-maker. You are playing a game that is played in multiple rounds with another player. "
                "The game consists of 10 rounds, and you are allowed to remember the past actions of your opponent. "
                "In each round, both of you will simultaneously choose one of two actions: Yes (Cooperate) or No (Defect/Betray). "
                "Your goal is to maximize your benefits. "
                "The following is the payoff matrix that determines your benefits: "
                "- If both choose Yes: You get 3 points, your opponent gets 3 points "
                "- If you choose Yes and your opponent chooses No: You get 0 points, your opponent gets 5 points "
                "- If you choose No and your opponent chooses Yes: You get 5 points, your opponent gets 0 points "
                "- If both choose No: You get 1 point, your opponent gets 1 point "
                "Remember this matrix and make decisions to maximize your total points. You must output 1-2 sentences to explain your decision."
            )
        elif isinstance(self._profile, str):
            return self._profile
        else:
            # Fallback: build profile with game rules even if profile is not dict
            return (
                "You are a rational decision-maker. You are playing a game that is played in multiple rounds with another player. "
                "The game consists of 10 rounds, and you are allowed to remember the past actions of your opponent. "
                "In each round, both of you will simultaneously choose one of two actions: Yes (Cooperate) or No (Defect/Betray). "
                "Your goal is to maximize your benefits. "
                "The following is the payoff matrix that determines your benefits: "
                "- If both choose Yes: You get 3 points, your opponent gets 3 points "
                "- If you choose Yes and your opponent chooses No: You get 0 points, your opponent gets 5 points "
                "- If you choose No and your opponent chooses Yes: You get 5 points, your opponent gets 0 points "
                "- If both choose No: You get 1 point, your opponent gets 1 point "
                "Remember this matrix and make decisions to maximize your total points. You must output 1-2 sentences to explain your decision."
            )

    def _parse_round_history(self, env_result: Any, response: str) -> list:
        """Parse round history from environment response"""
        rounds = self._extract_env_list_result(env_result, response, "round_history")
        return [round_data for round_data in rounds if isinstance(round_data, dict)]

    def _sync_history(self, round_history: list):
        """Sync local history with environment round history"""
        # Update local history from environment round history
        # Convert environment format to local format: (my_action, opponent_action)
        self.history = []
        for round_data in round_history:
            agent_a_action = round_data.get("agent_a_action", "")
            agent_b_action = round_data.get("agent_b_action", "")

            # Determine which action is mine based on agent name
            if agent_a_action and agent_b_action:
                # For now, assume we're Agent A (will be determined by actual agent name)
                # This will be fixed when we extract opponent name properly
                if self.name == "Agent A":
                    self.history.append((agent_a_action, agent_b_action))
                else:
                    self.history.append((agent_b_action, agent_a_action))

    def _extract_opponent_name(self) -> str:
        """Extract opponent name from history"""
        # For Prisoner's Dilemma, there's only one opponent
        # Check if we're Agent A or Agent B
        if self.name == "Agent A":
            return "Agent B"
        else:
            return "Agent A"

    def _build_history_string(self, opponent_name: str) -> str:
        """Build history string"""
        if not self.history:
            return "No previous rounds have been played."

        history_str = "History:\n"
        for i, (my_action, opponent_action) in enumerate(self.history):
            formatted_my_action = my_action.capitalize()
            formatted_opponent_action = opponent_action.capitalize()
            history_str += f"Round {i + 1}: Your choice={formatted_my_action}, {opponent_name}'s choice={formatted_opponent_action}\n"

        return history_str
