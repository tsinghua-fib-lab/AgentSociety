# Code Templates

> All templates below target the current `AgentBase` contract in
> `agentsociety2.agent.base`.
>
> Source of truth:
> - `packages/agentsociety2/agentsociety2/agent/base/README.md`
> - `packages/agentsociety2/agentsociety2/agent/base/agent.py`
> - `packages/agentsociety2/agentsociety2/contrib/agent/volunteer_dilemma_agent.py` (minimal game agent)
> - `packages/agentsociety2/agentsociety2/agent/person.py` (full skill-based agent)

## Construction model — the contract every template follows

`AgentBase` is **no longer constructed positionally**. The lifecycle is:

1. `await MyAgent.create(workspace_path, profile, config)` — classmethod, writes the
   initial workspace (`config.json` + `AGENT.json` + standard dirs). **Does not return
   an instance.**
2. `await MyAgent.from_workspace(workspace_path, service_proxy)` — classmethod, does
   `agent = cls()` (arg-less) then `await agent.restore(ws, proxy)` and returns the
   ready agent. `AgentBase` provides a concrete default; subclasses inherit it.
3. `restore(self, workspace_path, service_proxy)` — the **real init hook**. The base
   implementation reads `config.json` + `AGENT.json`, binds services/workspace/skill
   runtime. Subclasses override it to add their own state **after**
   `await super().restore(...)`.
4. `to_workspace(self, workspace_path)` — write dynamic state back to the workspace.

Required abstracts (subclasses MUST implement): `to_workspace`, `ask`, `step`.
`create` / `from_workspace` have concrete base implementations; override only when you
need a custom workspace layout (see Template 1 / 2, which reimplement them because they
keep an extended `AGENT.json` and bypass the skill runtime).

Two override styles:

- **Minimal / game agents** (Template 1, 2, 3): keep a fully custom `AGENT.json`, do
  NOT call `super().restore(...)` (they bind services manually via `self._bind_services`
  and skip the skill runtime / workspace FS). They reimplement `create` /
  `from_workspace` to round-trip their custom `AGENT.json`. This mirrors
  `contrib/agent/volunteer_dilemma_agent.py`.
- **Full agent** (Template 4): subclasses `AgentBase`, calls `await super().restore(...)`
  to get the workspace FS + skill runtime for free, then adds state. This mirrors
  `PersonAgent`.

---

## Template 1 — Minimal Agent (custom workspace, no skills)

Smallest concrete agent. No skill runtime, no `run_react_loop` — uses `acompletion`
for one-shot LLM calls. Keeps a minimal custom `AGENT.json`.

```python
"""{AgentName}: {Description}"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class {AgentName}(AgentBase):
    """{Description}"""

    # ---- Descriptions (recommended) ----
    @classmethod
    def description(cls) -> str:
        return "{AgentName}: {Short Description}"

    @classmethod
    def init_description(cls) -> str:
        return """{AgentName}: {Short Description}

Agents are created via ``{AgentName}.create(workspace_path, profile, config)`` and
reconstructed via ``await {AgentName}.from_workspace(workspace_path, service_proxy)``.

**Profile fields:**
- id (int): unique agent id.
- name (str | None): display name.

**Example config:**
```json
{{"id": 1, "profile": {{"name": "Alice"}}, "config": {{}}}}
```
"""

    # ==================== Workspace contract ====================
    # Minimal agents reimplement create / from_workspace because they keep a
    # custom AGENT.json shape and bypass the skill runtime.

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        """Write the initial workspace (config.json + custom AGENT.json)."""
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        agent_id = int(profile.get("id", 0))
        name = str(profile.get("name") or f"Agent_{agent_id}")
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {"id": agent_id, "name": name, "profile": profile, "step_count": 0},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: Any
    ) -> "{AgentName}":
        """Reconstruct a ready agent from its workspace."""
        agent = cls()  # arg-less __init__
        await agent.restore(workspace_path, service_proxy)
        return agent

    async def restore(self, workspace_path: Path, service_proxy: Any) -> None:
        """Restore state from AGENT.json + config.json.

        Minimal agents bind services manually and do NOT call super().restore(...)
        (which would set up the skill runtime + workspace FS we don't use here).
        """
        workspace_path = Path(workspace_path)
        cfg: dict = {}
        cfg_path = workspace_path / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        meta = json.loads(
            (workspace_path / "AGENT.json").read_text(encoding="utf-8")
        )
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {"name": meta.get("name")})
        self._name = meta.get("name") or f"Agent_{self._id}"
        self._config = dict(cfg or {})
        self._bind_services(service_proxy)  # injects _env / _dispatcher / _model_name
        self._step_count = int(meta.get("step_count", 0))
        # Add your own business state here.

    async def to_workspace(self, workspace_path: Path) -> None:
        """Write dynamic state back to AGENT.json."""
        workspace_path = Path(workspace_path)
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": self._id,
                    "name": self._name,
                    "profile": self.get_profile(),
                    "step_count": getattr(self, "_step_count", 0),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ==================== Abstract methods ====================

    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        """Answer an external question with a single LLM completion."""
        try:
            response = await self.acompletion(
                [{"role": "user", "content": message}]
            )
            if response and response.choices:
                return response.choices[0].message.content or ""
            return ""
        except Exception as exc:
            self.logger.error("[%s] ask failed: %s", self.name, exc)
            return f"[error] {exc}"

    async def step(self, tick: int, t: datetime) -> str:
        """One simulation step. Minimal example: query env, return summary."""
        self._step_count += 1
        try:
            _, observation = await self.ask_env(
                {}, "Please describe the current environment state.",
                readonly=True,
            )
        except Exception as exc:
            observation = f"[env unavailable: {exc}]"
        return f"{self.name} observed: {observation}"
```

**Use when:** you want the smallest possible agent (benchmark / game role with no
persistent state), or you need full control over `AGENT.json`.

---

## Template 2 — Agent with Internal State (memory / mood)

Same construction model as Template 1, but persists richer dynamic state
(`memories`, `mood`) in `AGENT.json`. Use this for agents whose state must survive
a restart but who do NOT need the skill runtime.

```python
"""{AgentName}: Agent with internal state (memory, mood)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, List

from agentsociety2.agent.base import AgentBase


class {AgentName}(AgentBase):
    """Agent that tracks memories and mood across steps."""

    @classmethod
    def description(cls) -> str:
        return "{AgentName}: {Short Description}"

    @classmethod
    def init_description(cls) -> str:
        return """{AgentName}: agent with memory + mood state.

Construction via ``{AgentName}.create(workspace_path, profile, config)``; reconstruct
via ``await {AgentName}.from_workspace(workspace_path, service_proxy)``.
"""

    # ==================== Workspace contract ====================

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
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
                    "memories": [],
                    "mood": "calm",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: Any
    ) -> "{AgentName}":
        agent = cls()
        await agent.restore(workspace_path, service_proxy)
        return agent

    async def restore(self, workspace_path: Path, service_proxy: Any) -> None:
        workspace_path = Path(workspace_path)
        meta = json.loads(
            (workspace_path / "AGENT.json").read_text(encoding="utf-8")
        )
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {"name": meta.get("name")})
        self._name = meta.get("name") or f"Agent_{self._id}"
        self._config = {}
        self._bind_services(service_proxy)
        self._step_count = int(meta.get("step_count", 0))
        # Business state
        self._memories: List[str] = list(meta.get("memories", []))
        self._mood: str = str(meta.get("mood", "calm"))

    async def to_workspace(self, workspace_path: Path) -> None:
        workspace_path = Path(workspace_path)
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": self._id,
                    "name": self._name,
                    "profile": self.get_profile(),
                    "step_count": self._step_count,
                    "memories": self._memories[-100:],
                    "mood": self._mood,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ==================== Abstract methods ====================

    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        memory_text = (
            "\n".join(self._memories[-5:]) if self._memories else "No memories"
        )
        prompt = (
            f"Profile: {self.get_profile()}\nMood: {self._mood}\n"
            f"Recent memories:\n{memory_text}\n\nQuestion: {message}"
        )
        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}]
            )
            answer = response.choices[0].message.content or ""
        except Exception as exc:
            answer = f"[error] {exc}"
        # Record this interaction in memory (cap length in to_workspace).
        self._memories.append(f"Q: {message}\nA: {answer[:120]}")
        return answer

    async def step(self, tick: int, t: datetime) -> str:
        self._step_count += 1
        try:
            _, observation = await self.ask_env(
                {}, "Please describe the current environment state.",
                readonly=True,
            )
        except Exception:
            observation = "environment nominal"
        # Naive mood update — replace with your own logic.
        if "good" in observation or "fine" in observation:
            self._mood = "happy"
        elif "bad" in observation or "problem" in observation:
            self._mood = "sad"
        else:
            self._mood = "calm"
        self._memories.append(f"obs@tick{tick}: {observation[:120]}")
        return f"{self.name} (mood={self._mood}): {observation}"
```

**Use when:** the agent needs internal state that must round-trip through the
workspace, but you don't need skills or the generic ReAct loop.

---

## Template 3 — Game / Decision Agent (heavy env interaction)

For agents that participate in turn-based games / structured decision tasks. Uses
`ask_env` with `template_mode` for the canonical query-then-submit pattern. This
mirrors `contrib/agent/volunteer_dilemma_agent.py`.

```python
"""{AgentName}: game / structured-decision participant."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List

from agentsociety2.agent.base import AgentBase


class {AgentName}(AgentBase):
    """Game participant that queries env state and submits a decision each step."""

    DECISION_OPTIONS: List[str] = ["OptionA", "OptionB"]  # customize

    @classmethod
    def init_description(cls) -> str:
        return """{AgentName}: game / decision agent.

Construction via ``{AgentName}.create(workspace_path, profile, config)``;
reconstruct via ``await {AgentName}.from_workspace(workspace_path, service_proxy)``.
"""

    # ==================== Workspace contract ====================

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
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
    ) -> "{AgentName}":
        agent = cls()
        await agent.restore(workspace_path, service_proxy)
        return agent

    async def restore(self, workspace_path: Path, service_proxy: Any) -> None:
        workspace_path = Path(workspace_path)
        cfg: dict = {}
        cfg_path = workspace_path / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        meta = json.loads(
            (workspace_path / "AGENT.json").read_text(encoding="utf-8")
        )
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {"name": meta.get("name")})
        self._name = meta.get("name") or f"Agent_{self._id}"
        self._config = dict(cfg or {})
        self._bind_services(service_proxy)
        self._step_count = int(meta.get("step_count", 0))
        self.history: List[dict] = list(meta.get("history", []))

    async def to_workspace(self, workspace_path: Path) -> None:
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

    # ==================== Abstract methods ====================

    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        try:
            response = await self.acompletion(
                [{"role": "user", "content": message}]
            )
            if response and response.choices:
                return response.choices[0].message.content or ""
            return ""
        except Exception as exc:
            self.logger.error("[%s] ask failed: %s", self.name, exc)
            return f"[error] {exc}"

    async def step(self, tick: int, t: datetime) -> str:
        if self._env is None:
            return f"[{self.name}] environment not bound"
        self._step_count += 1
        try:
            # 1) Query current game state — readonly, template_mode=True is safe.
            _, state_text = await self.ask_env(
                {"variables": {"agent_name": self.name}},
                "Please call get_state() using agent_name from ctx['variables'].",
                readonly=True,
                template_mode=True,
            )

            # 2) Decide (LLM or rule-based).
            decision = await self._decide(state_text)

            # 3) Submit — stateful write, default template_mode=False. See
            #    references/pitfalls.md P3 for why writes should avoid the
            #    template cache unless the env tool is verified idempotent.
            _, submit_text = await self.ask_env(
                {"variables": {"agent_name": self.name, "action": decision}},
                "Please call submit_action() using agent_name and action "
                "from ctx['variables'] to submit my decision for this round.",
                readonly=False,
                template_mode=False,
            )

            self.history.append({"tick": tick, "decision": decision})
            return f"{self.name}: {decision}"
        except Exception as exc:
            self.logger.error("[%s] step failed: %s", self.name, exc)
            return f"[{self.name}] [ERROR] {exc}"

    async def _decide(self, state_text: str) -> str:
        """Replace with game-specific decision logic (LLM or rules)."""
        prompt = (
            f"You are {self.name}. Game state:\n{state_text}\n"
            f"Reply with exactly one of: {', '.join(self.DECISION_OPTIONS)}."
        )
        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}]
            )
            content = (response.choices[0].message.content or "").lower()
            for opt in self.DECISION_OPTIONS:
                if opt.lower() in content:
                    return opt
        except Exception as exc:
            self.logger.warning("[%s] decide failed: %s", self.name, exc)
        return self.DECISION_OPTIONS[-1]  # safe default
```

**Use when:** the agent plays a multi-round game or any task with a clear
query-state → decide → submit-action cycle.

---

## Template 4 — Full Skill-Based Agent (uses `super().restore()` + ReAct loop)

This is the **full** pattern: subclass `AgentBase`, call `await super().restore(...)`
to inherit the workspace FS, skill runtime, and the generic `run_react_loop`, then
implement `build_react_messages` (required when you reuse the base ReAct loop) and add
your own state. Mirrors `PersonAgent`.

```python
"""{AgentName}: full agent with skills + ReAct loop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class {AgentName}(AgentBase):
    """Full agent: inherits workspace FS + skill runtime + generic ReAct loop.

    Generic machinery (workspace binding, skill discovery, file/skill/ask_env tool
    dispatch, the ReAct loop, LLM dispatch, AGENT.json persistence, construction
    model) is inherited from AgentBase. This class only adds:
    - build_react_messages: the prompt hook the base ReAct loop calls (REQUIRED
      when you reuse run_react_loop).
    - optional business state in restore().
    """

    @classmethod
    def description(cls) -> str:
        return "{AgentName}: {Short Description}"

    @classmethod
    def init_description(cls) -> str:
        return """{AgentName}: skill-based agent.

Construction via ``{AgentName}.create(workspace_path, profile, config)``;
reconstruct via ``await {AgentName}.from_workspace(workspace_path, service_proxy)``.
``create`` / ``from_workspace`` are inherited from AgentBase unchanged.

**Config keys (written to config.json):** max_react_turns, enable_memory,
enable_todo_list, force_template_mode, allow_template_mode, disabled_skill_ids,
default_activated_skill_ids (all optional).
"""

    # ---- NOTE: create / from_workspace are inherited from AgentBase. ----
    # Override them ONLY if you need a non-standard workspace layout. The
    # normal path is: AgentBase.create writes config.json + AGENT.json + dirs;
    # AgentBase.from_workspace does `agent = cls()` then `await restore(...)`.

    # ==================== restore override ====================

    async def restore(
        self, workspace_path: Path, service_proxy: Any
    ) -> None:
        """Run base restore, then add business-specific state.

        Always call ``await super().restore(...)`` FIRST — it reads config.json +
        AGENT.json, binds services, sets up the workspace FS and skill runtime,
        and restores visible/activated skills + counters.
        """
        await super().restore(workspace_path, service_proxy)
        # Your own state goes here, e.g.:
        # self._world_description: str = ""
        # If you need memory, instantiate your memory runtime here.

    # ==================== build_react_messages (REQUIRED for run_react_loop) ====================

    def build_react_messages(
        self,
        *,
        tick: int,
        t: datetime,
        observations: list[dict[str, Any]],
        question: str | None = None,
        readonly: bool = False,
        skill_hooks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """Build OpenAI-style chat messages for the generic ReAct loop.

        The base class raises NotImplementedError; you MUST override it if you
        call self.run_react_loop(...) (which the default step/ask below do).
        """
        system = (
            f"You are agent {self.name} (id={self.id}). "
            f"Current tick={tick}, time={t.isoformat()}."
        )
        obs_text = "\n".join(
            f"- [{o.get('action')}] {o.get('observation')}"
            for o in observations
        ) or "(no observations yet)"
        user = (
            question
            if question
            else f"Observations:\n{obs_text}\nDecide your next action."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    # ==================== Abstract methods ====================

    async def to_workspace(self, workspace_path: Path) -> None:
        """Persist AGENT.json via the base helper (calls build_agent_json)."""
        # The base persist_agent_json writes profile / step_count / current_time /
        # skills / initialized_at. Override build_agent_json to add fields.
        self.persist_agent_json(tick=None, t=self._current_time)

    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        """Answer an external question via the generic ReAct loop."""
        now = t or self._current_time or datetime.now()
        return await self.run_react_loop(
            tick=0,
            t=now,
            observations=[],
            question=message,
            readonly=readonly,
        )

    async def step(self, tick: int, t: datetime) -> str:
        """One simulation step: pre_step hooks -> ReAct loop -> post_step hooks."""
        self._step_count += 1
        self._current_time = t
        # Optional: run skill pre_step / post_step lifecycle hooks.
        # await self.run_lifecycle_hooks("pre_step", tick=tick, t=t)
        result = await self.run_react_loop(tick=tick, t=t)
        # await self.run_lifecycle_hooks("post_step", tick=tick, t=t)
        return result

    # ==================== Optional overrides ====================
    # - build_agent_json(*, tick, t): extend AGENT.json fields (call super first).
    # - dispatch_react_tool(action, args, *, readonly=False): add tool-name
    #   prefixes (e.g. memory_*); forward unknown actions to super().
```

**Use when:** the agent needs the skill catalog (`activate_skill` / `read_skill_file`
/ `execute_skill_script`), workspace file tools (`read`/`write`/`grep`), `ask_env`,
the TODO list, and the multi-turn ReAct loop. This is the closest analogue of
`PersonAgent`.

---

## Selection Guide

| Need | Template | State | Skills/ReAct | Construction |
|------|----------|-------|--------------|--------------|
| Tiny agent, one-shot LLM | 1 | none (just counters) | no | reimplemented create/from_workspace |
| Memory / mood tracking | 2 | custom AGENT.json | no | reimplemented create/from_workspace |
| Turn-based game | 3 | custom AGENT.json | no | reimplemented create/from_workspace |
| Skills + tool loop | 4 | base AGENT.json + your fields | yes (`run_react_loop`) | inherited from AgentBase |

## Key public API every subclass can call (no `_` prefix)

| API | Purpose |
|-----|---------|
| `await self.acompletion(messages, stream=False, **kw)` | one-shot LLM completion |
| `await self.run_react_loop(*, tick, t, observations=None, question=None, readonly=False, skill_hooks=None)` | generic ReAct loop (requires `build_react_messages`) |
| `await self.run_lifecycle_hooks(hook_type, *, tick, t)` | pre_step / post_step skill hooks |
| `self.discover_skill_sources(env)` | scan custom + env skills, refresh visible set |
| `self.persist_agent_json(*, tick=None, t=None)` | write AGENT.json (calls `build_agent_json`) |
| `self.trace_span(name, ...)` | agent-scoped trace span context manager |
| `self.workspace_root_path()` | workspace root (raises if unbound) |
| `self.dispatch_todo_tool(action, args)` | built-in TODO tools |
| `await self.ask_env(ctx, message, readonly, template_mode=False)` | request to env router |
| `self.get_profile()` | profile as dict |
| `self.skill_runtime` | the `AgentSkillRuntime` (None until `restore`) |
| `self.id` / `self.name` / `self.logger` | identity + logger |

## Current API Notes

- Runtime setup belongs in `restore`.
- Dynamic state is persisted with `to_workspace`.
- Skill access goes through `skill_runtime` and the ReAct tools exposed by the base.
- LLM calls go through `acompletion` or `run_react_loop`.
- `AgentSociety` receives record-based `agent_specs`; the CLI builds these records.
