"""
Commons Tragedy Game Agent
Agent for Tragedy of the Commons game based on AgentSociety2
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class CommonsTragedyAgent(AgentBase):
    """Agent for Tragedy of the Commons game based on AgentSociety2"""

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this agent class.
        Includes parameter descriptions.
        """
        description = f"""{cls.__name__}: Agent for Tragedy of the Commons game.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters (workspace contract):**
- id (int): The unique identifier for the agent.
- name (str): The name of the agent.

**Game Rules:**
This agent participates in a 10-round Tragedy of the Commons game where multiple players extract resources from a shared pool. Each player chooses an extraction amount (1-10 units) per round. Each unit extracted gives 1 point, but the shared pool is depletable. If total extraction exceeds the remaining pool, extractions are limited to available resources.

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
    ) -> "CommonsTragedyAgent":
        """Reconstruct a ready CommonsTragedyAgent from its workspace."""
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
        self.max_extraction = 10

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
        # Build prompt from profile dict
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
        """Execute one step - make extraction decision and submit to environment"""
        if self._env is None:
            return f"[{self.name}] Environment not initialized"
        self._step_count += 1

        try:
            # Step 1: Get current pool resources from environment
            _, pool_response = await self.ask_env(
                {},
                "Please call get_pool_resources() to get the current pool resources.",
                readonly=True,
                template_mode=True,
            )
            self._logger.debug(
                f"[{self.name}] Pool resources response: {pool_response}"
            )

            # Parse pool resources from response
            current_pool_resources = self._parse_pool_resources(pool_response)

            # Step 2: Get round history from environment
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

            # Step 3: Decide extraction amount using LLM
            extraction, explanation = await self._decide_extraction(
                current_round, current_pool_resources, all_agent_names
            )

            # Step 4: Submit extraction to environment
            submit_result, submit_response = await self.ask_env(
                {
                    "variables": {
                        "agent_name": self.name,
                        "requested_extraction": extraction,
                    }
                },
                "Please call submit_extraction() using agent_name and requested_extraction from ctx['variables'] to submit my extraction decision.",
                readonly=False,
                template_mode=True,
            )
            self._ensure_env_ask_ok(
                submit_result, submit_response, op="submit_extraction"
            )
            self._logger.info(
                f"[{self.name}] Round {current_round}: Submitted extraction={extraction}, "
                f"explanation={explanation[:50]}..."
            )

            return f"[{self.name}] Round {current_round}: Submitted extraction {extraction}"

        except Exception as e:
            error_message = f"Step execution failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] {error_message}")
            return f"[{self.name}] [ERROR] {error_message}"

    def _build_history_string(self, all_agent_names: list) -> str:
        """Build history string"""
        if not self.history:
            return "No previous rounds have been played."

        history_lines = []
        history_lines.append("History of previous rounds:")

        for round_summary in self.history:
            r = round_summary["round"]
            pool_before = round_summary["pool_before_round"]
            extractions = round_summary["extractions"]
            pool_after = round_summary["pool_after_round"]
            payoffs = round_summary["payoffs"]

            history_lines.append(f"Round {r}:")
            history_lines.append(f"  Pool at start of round {r}: {pool_before} units.")

            extraction_details = [
                f"{name} extracted {extractions.get(name, 0)} units"
                for name in all_agent_names
            ]
            history_lines.append("  " + ", ".join(extraction_details) + ".")

            history_lines.append(
                f"  Pool remaining after round {r}: {pool_after} units."
            )

            payoff_details = [
                f"{name} gained {payoffs.get(name, 0)} points"
                for name in all_agent_names
            ]
            history_lines.append("  " + ", ".join(payoff_details) + ".")

        return "\n".join(history_lines)

    def update_history(self, round_summary: dict):
        """Update history record"""
        self.history.append(round_summary)

    def _build_profile_string(self) -> str:
        """Build profile string from profile dict"""
        if isinstance(self._profile, dict):
            name = self._profile.get("name", f"Agent {self.id}")
            # Build complete game rules description matching baseline
            return (
                f"You are a rational decision maker named {name}. "
                f"You are participating in a Tragedy of the Commons game. "
                f"Your goal is to maximize your personal resource extraction over 10 rounds of the game. "
                f"There are 10 rounds in total. In each round, all players simultaneously choose an integer amount to extract from a shared common resource pool. "
                f"The extraction amount must be between 1 and {self.max_extraction} (inclusive). "
                f"For each unit you extract, you gain 1 point. "
                f"The resource pool is depletable. If the total extraction of all players in a round exceeds the remaining resource pool, players can only extract the remaining amount available in the pool. "
                f"The remaining resources in the pool are reduced by the total actual extraction of all players at the end of each round. "
                f"You can remember all past behaviors of other players and the state of the resource pool. Other players also know this information. "
                f"Make your decisions wisely based on the current resource pool size and past extraction behaviors."
            )
        elif isinstance(self._profile, str):
            return self._profile
        else:
            # Fallback: build profile with game rules even if profile is not dict
            return (
                f"You are a rational decision maker named {self._name}. "
                f"You are participating in a Tragedy of the Commons game. "
                f"Your goal is to maximize your personal resource extraction over 10 rounds of the game. "
                f"There are 10 rounds in total. In each round, all players simultaneously choose an integer amount to extract from a shared common resource pool. "
                f"The extraction amount must be between 1 and {self.max_extraction} (inclusive). "
                f"For each unit you extract, you gain 1 point. "
                f"The resource pool is depletable. If the total extraction of all players in a round exceeds the remaining resource pool, players can only extract the remaining amount available in the pool. "
                f"The remaining resources in the pool are reduced by the total actual extraction of all players at the end of each round. "
                f"You can remember all past behaviors of other players and the state of the resource pool. Other players also know this information. "
                f"Make your decisions wisely based on the current resource pool size and past extraction behaviors."
            )

    def _parse_pool_resources(self, response: str) -> int:
        """Parse current pool resources from environment response"""
        # Try to extract from JSON-like response
        try:
            # Look for JSON in the response
            json_match = re.search(r"\{[^}]+\}", response)
            if json_match:
                data = json.loads(json_match.group(0))
                if isinstance(data, dict):
                    return data.get("current_pool_resources", 100)
        except (json.JSONDecodeError, ValueError, KeyError):
            import logging

            logging.getLogger(__name__).debug(
                "Failed to parse pool resources from JSON", exc_info=True
            )

        # Fallback: try to extract number from text
        numbers = re.findall(r"\d+", response)
        if numbers:
            return int(numbers[0])

        # Default fallback
        return 100

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
            extractions = round_summary.get("extractions", {})
            agent_names.update(extractions.keys())

        # If no history, return default names
        if not agent_names:
            # Try to infer from payoffs
            for round_summary in self.history:
                payoffs = round_summary.get("payoffs", {})
                agent_names.update(payoffs.keys())

        # Always include self
        agent_names.add(self.name)

        # Return sorted list for consistency
        return sorted(agent_names)

    async def _decide_extraction(
        self, round_num: int, current_pool_resources: int, all_agent_names: list
    ) -> tuple[int, str]:
        """Decide extraction amount - extracted from act method logic"""
        # Build history string
        history_str = self._build_history_string(all_agent_names)

        # Build prompt
        profile_str = self._build_profile_string()
        prompt = (
            f"{profile_str}\n"
            f"Current Game State:\n"
            f"This is round {round_num} of 10.\n"
            f"The current public resource pool has {current_pool_resources} units before any extractions in this round.\n\n"
            f"{history_str}\n\n"
            "***CRITICAL INSTRUCTION***: Based ONLY on the rules and history, determine your extraction amount.\n"
            f"Your decision must be an integer between 1 and {self.max_extraction} (inclusive).\n"
            "YOU MUST FOLLOW THIS OUTPUT FORMAT EXACTLY:\n"
            "\n"
            "<output>\n"
            "  <extraction>INTEGER</extraction>\n"
            "  <explanation>Your 1-2 sentence reasoning here.</explanation>\n"
            "</output>"
            "\n"
            "IMPORTANT: Do not write any additional text before or after the XML structure. Your entire output must consist of exactly the XML format shown above."
        )

        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}], stream=False
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

            # Extract extraction using regex
            extraction_match = re.search(
                r"<extraction>\s*(10|[1-9])\s*</extraction>", content, re.IGNORECASE
            )
            if extraction_match:
                parsed_extraction = int(extraction_match.group(1))
                if 1 <= parsed_extraction <= self.max_extraction:
                    extraction = parsed_extraction
                else:
                    self._logger.warning(
                        f"[{self.name}] [WARNING] Extraction value out of range: {parsed_extraction}, using default 1"
                    )
                    extraction = 1

                # Extract explanation
                explanation_match = re.search(
                    r"<explanation>(.*?)</explanation>",
                    content,
                    re.DOTALL | re.IGNORECASE,
                )
                if explanation_match:
                    explanation = explanation_match.group(1).strip()
                else:
                    explanation = (
                        f"Selected '{extraction}' but no explanation provided in XML"
                    )

                self._logger.info(
                    f"[{self.name}] [SUCCESS] Final parsed (XML): extraction={extraction}, explanation={explanation[:50]}..."
                )
            else:
                # Fallback: try single-line matching
                self._logger.warning(
                    f"[{self.name}] [WARNING] XML parsing failed, attempting single-line matching..."
                )
                lines = content.strip().split("\n")
                first_line = lines[0].strip()

                match = re.search(r"\b(10|[1-9])\b", first_line)
                if match:
                    parsed_extraction = int(match.group(0))
                    if 1 <= parsed_extraction <= self.max_extraction:
                        extraction = parsed_extraction
                    else:
                        extraction = 1
                    explanation = (
                        " ".join(lines[1:]).strip()
                        or "Single-line match successful, no detailed explanation"
                    )
                    self._logger.info(
                        f"[{self.name}] [FALLBACK] Single-line match successful: extraction={extraction}"
                    )
                else:
                    # Final fallback: search entire response
                    keyword_match = re.search(r"\b(10|[1-9])\b", content)
                    if keyword_match:
                        parsed_extraction = int(keyword_match.group(1))
                        if 1 <= parsed_extraction <= self.max_extraction:
                            extraction = parsed_extraction
                        else:
                            extraction = 1
                        explanation = f"Extracted keyword from response: {extraction}"
                        self._logger.info(
                            f"[{self.name}] [KEYWORD] Keyword match successful: extraction={extraction}"
                        )
                    else:
                        raise ValueError(
                            f"Failed to parse valid extraction, content:\n{content[:200]}"
                        )

        except Exception as e:
            error_message = f"Parsing/call failed: {type(e).__name__} - {e!s}"
            self._logger.error(f"[{self.name}] [ERROR] {error_message}")

            extraction = 1
            explanation = (
                f"[CRITICAL FAILURE] {error_message}, using default selection: 1"
            )

        self._logger.debug(f"[{self.name}] [DEBUG] Final selection: {extraction}")
        return extraction, explanation
