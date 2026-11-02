"""
Global Information Environment
This environment provides global information to the agent.
"""

import asyncio
import json
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import (
    EnvBase,
    tool,
)
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"


class GetGlobalInformationResponse(BaseModel):
    """Response model for get() function"""

    global_information: str = Field(..., description="The global information")


class SetGlobalInformationResponse(BaseModel):
    """Response model for set() function"""

    old_information: str = Field(..., description="The old information")
    new_information: str = Field(..., description="The new information")


class GlobalInformationEnv(EnvBase):
    @classmethod
    def is_concurrency_safe(cls) -> bool:
        # Already self-protected by an internal asyncio.Lock around its single
        # shared field (_global_information), so concurrent tool calls are safe.
        return True

    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("global_information", "TEXT", nullable=False),
    ]

    def __init__(self):
        """
        Initialize the Global Information Environment.
        """
        super().__init__()
        self._default_global_information = (
            "It's a normal day without any special events."
        )
        self._global_information = self._default_global_information
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
                    "global_information": self._global_information,
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
        self._global_information = str(
            d.get("global_information", self._default_global_information)
        )
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions.
        """
        description = f"""{cls.__name__}: Global information environment module.

**Description:** Provides global information to the agent like weather, global news, etc.

**Initialization Parameters (excluding llm):**
No additional parameters required. This module only requires the llm parameter.

**Example initialization config:**
```json
{{}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Global information environment for shared simulation-wide key-value context."

    @tool(readonly=True, kind="observe")
    async def get(self) -> GetGlobalInformationResponse:
        """
        Get the global information.

        :returns: The global information.
        """
        async with self._lock:
            return GetGlobalInformationResponse(
                global_information=self._global_information
            )

    @tool(readonly=False)
    async def set(self, prompt: str) -> SetGlobalInformationResponse:
        """
        Set the global information.

        :param prompt: The global information.

        :returns: The global information.
        """
        async with self._lock:
            old_information = self._global_information
            self._global_information = prompt
        return SetGlobalInformationResponse(
            old_information=old_information,
            new_information=prompt,
        )

    async def init(self, start_datetime: datetime):
        await super().init(start_datetime)
        async with self._lock:
            self._global_information = self._default_global_information
            self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t
            global_information = self._global_information

        await self._write_env_state(
            step=self._step_counter,
            t=t,
            global_information=global_information,
        )
        self._step_counter += 1
