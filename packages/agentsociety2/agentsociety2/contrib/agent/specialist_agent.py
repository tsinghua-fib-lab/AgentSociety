"""Onboarding demo agent: domain specialist with a deterministic ask()."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agentsociety2.agent.base import AgentBase


class SpecialistAgent(AgentBase):
    """Demo agent that answers from its configured specialty (no LLM)."""

    @classmethod
    def description(cls) -> str:
        return "Onboarding demo agent that answers from a configured specialty."

    @classmethod
    def init_description(cls) -> str:
        return """SpecialistAgent: onboarding demo agent.

**Profile / config:**
- specialty (str): domain of expertise (also accepted in profile)

**Example:**
```json
{
  "id": 1,
  "profile": {"id": 1, "name": "Dr. Climate", "specialty": "climate science"},
  "config": {"specialty": "climate science"}
}
```
"""

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        AgentBase.create(workspace_path, profile, config)

    async def to_workspace(self, workspace_path: Path) -> None:
        self.persist_agent_json(tick=None, t=self._current_time)

    async def step(self, tick: int, t: datetime) -> str:
        return "ok"

    async def ask(
        self, message: str, *, readonly: bool = True, t: datetime | None = None
    ) -> str:
        specialty = (self._config or {}).get("specialty") or (self._profile or {}).get(
            "specialty", "general knowledge"
        )
        return (
            f"I am {self.name}, specializing in {specialty}. "
            f"Regarding your question: {message}"
        )
