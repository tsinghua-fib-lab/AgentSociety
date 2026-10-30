"""AgentBase — the generic agent runtime base class.

中文：``AgentBase`` 是所有 agent 的基类，直接拥有 workspace 绑定、skill
runtime、ReAct 工具调度、identity、service slots、抽象契约和构造模型。
English: ``AgentBase`` is the base class for all agents. It directly owns
workspace binding, the skill runtime, ReAct tool dispatch, identity, service
slots, the abstract contract, and the construction model.

Construction model (no meaningful ``__init__``):

- ``AgentBase.__init__(self)`` — arg-less. Initializes empty slots only.
- ``AgentBase.create(workspace_path, profile, config)`` — write initial
  workspace (``config.json`` + ``AGENT.json`` + dirs). No instance.
- ``AgentBase.from_workspace(workspace_path, service_proxy)`` —
  ``agent = cls()``; ``await agent.restore(ws, proxy)``; return.
- ``AgentBase.restore(workspace_path, service_proxy)`` — the real init:
  read config.json + AGENT.json; set ``_id``/``_profile``/``_name``/``_config``;
  call ``_bind_services`` + ``_bind_workspace``; restore visible/activated
  skills + counters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentsociety2.agent.base.react import (
    ReactDecision,
    ReactToolResult,
    ReactTurn,
)
from agentsociety2.agent.base.skill_registry import get_skill_registry
from agentsociety2.agent.base.skill_runtime import AgentSkillRuntime
from agentsociety2.agent.base.todo import TodoStateStore
from agentsociety2.agent.base.tool_schema import react_tool_schemas
from agentsociety2.agent.base.workspace_fs import WorkspaceFS
from agentsociety2.agent.person_prompt import (
    json_block as _json_block,
)
from agentsociety2.agent.person_prompt import (
    short_text as _short_text,
)
from agentsociety2.agent.person_prompt import (
    xml_block as _xml_block,
)
from agentsociety2.env.router_base import RouterBase
from agentsociety2.logger import get_logger
from agentsociety2.trace import (
    JsonlTraceWriter,
    TraceSpan,
)

if TYPE_CHECKING:
    from agentsociety2.agent.service_proxy import ServiceProxy

__all__ = [
    "AgentBase",
]

logger = get_logger()

# agent workspace 布局常量（agent 专属）。
AGENT_JSON_PATH = "AGENT.json"
STANDARD_WORKSPACE_DIRS = ("state", "memory")

# Short clock shorthand (HH:MM) used to normalize TODO ``due`` values.
_SHORT_CLOCK_RE = re.compile(r"^(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)$")


def _brief_memories_summary(memories: Any) -> str:
    """Derive a one-line step result from inline finish memories.

    Step-mode ``finish`` carries only ``memories`` (no ``final`` text); this
    builds a short summary from the first recorded episode so the step result /
    trace stays readable. Returns ``""`` when there is nothing to summarize.

    :param memories: The ``memories`` list from a finish tool call (or None).
    :returns: A short summary string (empty if no usable memory text).
    """
    if not isinstance(memories, list) or not memories:
        return ""
    first = memories[0]
    text = ""
    if isinstance(first, dict):
        text = str(first.get("text") or "").strip()
    elif isinstance(first, str):
        text = first.strip()
    return text[:160]


#: Cap on the assistant text echoed back into the thread alongside native tool
#: calls. Reasoning models can put a lot of prose there; the echo exists for
#: conversational fidelity, not to re-read it.
_ASSISTANT_ECHO_MAX_CHARS = 4000


def _tool_call_payload(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    """Build one OpenAI ``tool_calls`` entry."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _raw_assistant_message(content: str, tool_calls: Any) -> dict[str, Any]:
    """Echo a native assistant turn verbatim (ids and arguments untouched).

    Used on the parse-error path: the loop answers **every** raw id with the
    error text, so the ids and ``arguments`` must match what the provider sent.
    """
    return {
        "role": "assistant",
        "content": _short_text(content, limit=_ASSISTANT_ECHO_MAX_CHARS) or None,
        "tool_calls": [
            _tool_call_payload(
                str(getattr(tool_call, "id", "") or f"call_{index}"),
                str(getattr(getattr(tool_call, "function", None), "name", "") or ""),
                str(
                    getattr(getattr(tool_call, "function", None), "arguments", "")
                    or "{}"
                ),
            )
            for index, tool_call in enumerate(tool_calls)
        ],
    }


def _decisions_assistant_message(
    content: str, decisions: list[ReactDecision]
) -> dict[str, Any]:
    """Build the assistant turn from the decisions that will actually run.

    Rebuilding (rather than echoing the raw response) is required: when a
    response contains a ``finish`` call, ``_build_react_decisions`` drops the
    other calls, and an echoed id that nothing answers makes the next request
    invalid.
    """
    return {
        "role": "assistant",
        "content": _short_text(content, limit=_ASSISTANT_ECHO_MAX_CHARS) or None,
        "tool_calls": [
            _tool_call_payload(
                decision.call_id,
                decision.action,
                json.dumps(decision.args, ensure_ascii=False, default=str),
            )
            for decision in decisions
            if decision.call_id
        ],
    }


def _react_tool_replies(
    decisions: list[ReactDecision],
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the messages answering one turn's tool calls.

    Two encodings, matching how the turn was parsed:

    - **native** (every decision carries a ``call_id``) — one ``role: "tool"``
      message per call, keyed by id. Failed calls get an ``ERROR: `` prefix:
      the native encoding has no ``ok`` field, so the text is the only place
      the model can learn the call failed.
    - **text-parsed** (no ids) — a single user message carrying the same
      ``<recent_observations>`` JSON block the model would have seen under the
      previous re-render layout, so text-fallback models lose no information.
    """
    if decisions and all(decision.call_id for decision in decisions):
        return [
            {
                "role": "tool",
                "tool_call_id": decision.call_id,
                "content": (
                    entry["observation"]
                    if entry.get("ok")
                    else f"ERROR: {entry['observation']}"
                ),
            }
            for decision, entry in zip(decisions, entries)
        ]
    return [{"role": "user", "content": _json_block("recent_observations", entries)}]


def _synthesize_step_fallback_episode(
    *,
    step_count: int,
    t: datetime,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one rule-based memory episode when the model never recorded one.

    Used at the end of ``run_react_loop`` (step mode) when no valid
    ``finish(memories=...)`` was produced, so the agent still carries a
    cross-step memory derived from this step's observations. The episode is
    tagged ``source=step_result_fallback`` so it can be distinguished from
    LLM-produced memories.

    :param step_count: Current agent step count.
    :param t: Current simulation time.
    :param observations: ReAct observations collected this step.
    :returns: One validated episode dict.
    """
    parts: list[str] = []
    for obs in observations:
        action = str(obs.get("action") or "").strip()
        text = str(obs.get("observation") or "").strip()
        if not text:
            continue
        prefix = f"{action}: " if action and action != "(invalid)" else ""
        parts.append(prefix + text[:200])
    summary = " | ".join(parts[:5]) if parts else "no notable events recorded"
    text = f"Step {step_count} ({t.isoformat()}): {summary}"[:1000]
    return {
        "type": "observation",
        "importance": 0.4,
        "keywords": [],
        "text": text,
        "source": "step_result_fallback",
        "refs": [],
    }


class AgentBase(ABC):
    """Abstract base class for all agents.

    Directly owns the generic agent runtime (workspace binding, skill
    runtime, ReAct tool dispatch) plus identity, service slots, and the
    abstract contract.  Construction is via ``create`` / ``from_workspace``;
    ``__init__`` is arg-less.

    Subclasses must implement (forced abstracts):

    - :meth:`create`
    - :meth:`from_workspace`
    - :meth:`to_workspace`
    - :meth:`ask`
    - :meth:`step`
    """

    def __init__(self) -> None:
        """Initialize an unbound agent (arg-less).

        Only empty slots are set; no profile parsing, no id required.  The
        real initialization happens in :meth:`restore` (called by
        :meth:`from_workspace`).
        """
        # Identity slots — populated by restore.
        self._id: int | None = None
        self._profile: Any = None
        self._name: str | None = None
        self._config: dict[str, Any] = {}

        # Runtime service slots — injected by _bind_services.
        self._service_proxy: ServiceProxy | None = None
        self._dispatcher = None
        self._model_name: str | None = None
        self._env: RouterBase | None = None
        self._logger = get_logger()

        # Memories the model recorded inline in the step-mode `finish` tool call
        # (avoids a separate extraction LLM pass). Set by run_react_loop on
        # finish; consumed by step() -> memory_runtime.after_step. None when the
        # loop finished without a finish tool call or in ask mode.
        self._last_finish_memories: list[dict[str, Any]] | None = None
        # Ask-mode scratch: the most recent free-text answer the model emitted
        # without wrapping it in a finish(answer=...) tool call. Used as the
        # end-of-loop fallback answer when the model never self-corrects.
        self._last_raw_answer_text: str = ""
        # Most recent ReAct parse/validation error surfaced from the LLM call;
        # read by run_react_loop to push corrective feedback on a no-decision
        # turn so the model can retry instead of silently ending as "done".
        self._last_react_error: str = ""

        # Workspace / trace placeholders.
        self._workspace_root: Path | None = None
        self._workspace_fs: WorkspaceFS | None = None
        self._jsonl_trace_writer: JsonlTraceWriter | None = None

        # Skill placeholders.  _setup_skill_runtime needs an agent id, so it
        # runs inside restore once _id is known.
        self._skill_registry = None
        self.skill_runtime = None
        self._disabled_skill_ids: set[str] = set()
        self._default_activated_skill_ids: set[str] = set()
        self._default_activated_skills_applied: bool = False
        # Extra skill scan roots beyond the default <root>/custom/skills
        # locations. Populated from config["extra_skill_paths"] in restore;
        # relative paths resolve against the workspace root.
        self._extra_skill_paths: list[Path] = []

        # Generic counters / state — set by restore / subclass restore.
        self._step_count: int = 0
        self._initialized_at: str | None = None
        self._current_time: datetime | None = None

        # Generic ReAct / tool-loop config flags — populated by restore from
        # self._config.  Subclasses (e.g. PersonAgent) may additionally set
        # feature-specific flags (such as _enable_memory) in their own config
        # helper, but these base flags are owned here so the generic react
        # loop and tool dispatcher work for any AgentBase subclass.
        self._max_react_turns: int = 10
        self._enable_todo_list: bool = True
        self._enable_memory: bool = False

    # ------------------------------------------------------------------
    # Service binding
    # ------------------------------------------------------------------

    def _bind_services(self, service_proxy: ServiceProxy) -> None:
        """Inject runtime shared services (called by ``from_workspace``).

        Binds ``service_proxy`` and its env + default-LLM dispatcher to
        ``self._env`` / ``self._dispatcher`` / ``self._model_name``.

        Args:
            service_proxy: Shared service container (env / llm / trace / replay).
        """
        self._service_proxy = service_proxy
        self._env = service_proxy.env
        default = service_proxy.llm.default
        self._dispatcher = default
        self._model_name = getattr(default, "model_name", None)

    # ------------------------------------------------------------------
    # Construction model
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        """Create the initial agent workspace (static, write-once config).

        Writes ``config.json`` (static, never rewritten) + initial ``AGENT.json``
        + the standard empty directories.  Does NOT return an agent instance;
        use :meth:`from_workspace` to reconstruct.

        Args:
            workspace_path: Agent workspace root (created if missing).
            profile: Agent profile dict (must include ``id``).
            config: Static config dict written verbatim to ``config.json``.
        """
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        for rel in STANDARD_WORKSPACE_DIRS:
            (workspace_path / rel).mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(dict(config or {}), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        agent_id = int(profile.get("id", 0))
        name = AgentBase._derive_name(profile, agent_id)
        initial_agent = {
            "schema_version": 1,
            "agent_class": cls.__name__,
            "agent_id": agent_id,
            "id": agent_id,
            "name": name,
            "profile": profile,
            "step_count": 0,
            "current_time": None,
            "tick": None,
            "visible_skills": [],
            "activated_skills": [],
            "disabled_skills": sorted(
                str(s)
                for s in (config or {}).get("disabled_skill_ids", [])
                if str(s).strip()
            ),
            "default_activated_skills": sorted(
                str(s)
                for s in (config or {}).get("default_activated_skill_ids", [])
                if str(s).strip()
            ),
            "initialized_at": None,
        }
        (workspace_path / AGENT_JSON_PATH).write_text(
            json.dumps(initial_agent, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: ServiceProxy
    ) -> AgentBase:
        """Reconstruct a ready agent from its workspace.

        ``agent = cls()`` (arg-less); ``await agent.restore(ws, proxy)``;
        return the agent.

        Args:
            workspace_path: Agent workspace root.
            service_proxy: Shared service container (env / llm / trace / replay).

        Returns:
            Ready agent instance.
        """
        agent = cls()
        await agent.restore(workspace_path, service_proxy)
        return agent

    async def restore(
        self,
        workspace_path: Path,
        service_proxy: ServiceProxy,
    ) -> None:
        """The real initialization (called by ``from_workspace``).

        Reads ``config.json`` + ``AGENT.json``; sets ``_id``/``_profile``/
        ``_name``/``_config``; calls ``_bind_services`` + ``_bind_workspace``;
        restores visible/activated skills + counters.

        Subclasses override this to ALSO restore person-specific state after
        ``await super().restore(...)``.

        Args:
            workspace_path: Agent workspace root.
            service_proxy: Shared service container.
        """
        workspace_path = Path(workspace_path)
        config = json.loads(
            (workspace_path / "config.json").read_text(encoding="utf-8")
        )
        meta = json.loads(
            (workspace_path / AGENT_JSON_PATH).read_text(encoding="utf-8")
        )
        self._config = dict(config or {})
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {})
        self._name = meta.get("name") or self._derive_name(self._profile, self._id)

        # Generic config-derived skill sets.
        self._disabled_skill_ids = set(self._config.get("disabled_skill_ids") or [])
        self._default_activated_skill_ids = {
            str(sid)
            for sid in (self._config.get("default_activated_skill_ids") or [])
            if str(sid).strip()
        } - self._disabled_skill_ids

        # Services + workspace.
        self._bind_services(service_proxy)
        self._setup_skill_runtime(agent_id=self._id)
        self._bind_workspace(workspace_path)

        # Generic react-loop / tool config flags (own read; subclasses extend).
        self._max_react_turns = max(
            1, int(self._config.get("max_react_turns", 10) or 10)
        )
        self._enable_todo_list = bool(self._config.get("enable_todo_list", True))
        # _enable_memory defaults to False at the base level; PersonAgent
        # overrides it in _apply_person_config.

        # Restore visible/activated skill subset from AGENT.json.
        visible = {str(s) for s in meta.get("visible_skills", []) if str(s).strip()}
        activated = {str(s) for s in meta.get("activated_skills", []) if str(s).strip()}
        self.skill_runtime.set_visible_skills(visible)
        self.skill_runtime.set_activated_skills(activated)

        # Restore counters and time.
        self._step_count = int(meta.get("step_count", 0))
        current_time = meta.get("current_time")
        if current_time:
            try:
                self._current_time = datetime.fromisoformat(str(current_time))
            except ValueError:
                self._current_time = None
        else:
            self._current_time = None
        initialized_at = meta.get("initialized_at")
        self._initialized_at = str(initialized_at) if initialized_at else None
        # ``_default_activated_skills_applied`` tracks whether
        # ``add_default_activated_skills`` has actually been invoked inside
        # ``discover_skill_sources``. It must NOT be set just because
        # ``default_activated_skill_ids`` is configured — for a freshly-created
        # agent ``activated`` is still empty at this point, and setting the flag
        # here would make ``discover_skill_sources`` skip the default-activation
        # step entirely, so the configured defaults would never activate. We
        # only treat it as already-applied when persisted ``activated`` skills
        # were restored (resume path); the fresh path leaves it False so the
        # first ``discover_skill_sources`` applies the defaults once.
        self._default_activated_skills_applied = bool(activated)

        # Extra skill scan roots from config (declarative; no code change
        # needed to add skill sources). Relative paths resolve against the
        # workspace root. Discovery merges these with the default
        # <root>/custom/skills locations.
        self._extra_skill_paths = self._resolve_skill_paths(
            self._config.get("extra_skill_paths")
        )

        # Re-scan skill sources into the process-global registry on every
        # restore. Agents are workspace-bound records reconstructed per step
        # via Ray ``from_workspace``; ``SkillRegistry`` is process-global and
        # starts empty on a fresh worker (only builtins are pre-scanned). A
        # reconstructed agent whose AGENT.json was persisted in another process
        # would otherwise see an incomplete registry: ``set_visible_skills``
        # (above) resolves persisted tokens against the registry and silently
        # drops the missing ones, and ``step``'s ``_refresh_visible_skills``
        # then recomputes from the same incomplete registry — so env/custom
        # skills (and their lifecycle hooks / activations) are lost until first
        # use. ``discover_skill_sources`` is idempotent (scans dedupe; default
        # activation is guarded by ``_default_activated_skills_applied``), so
        # running it here is cheap after the first scan in a process and keeps
        # the visible/activated sets consistent with the live registry.
        if self._env is not None:
            try:
                self.discover_skill_sources(self._env)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Agent %s: skill re-discovery on restore failed: %s",
                    self.id,
                    exc,
                )

    # ------------------------------------------------------------------
    # Abstract methods (subclasses must implement these three;
    # create / from_workspace have concrete base implementations above)
    # ------------------------------------------------------------------

    @abstractmethod
    async def to_workspace(self, workspace_path: Path) -> None:
        """Write current dynamic state back to the workspace."""
        raise NotImplementedError

    @abstractmethod
    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        """Answer an external question through the agent's reasoning flow."""
        raise NotImplementedError

    @abstractmethod
    async def step(self, tick: int, t: datetime) -> str:
        """Run one simulation step."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Identity + properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> int:
        """Agent unique identifier."""
        return self._id

    @property
    def name(self) -> str:
        """Agent display name."""
        return self._name

    @property
    def logger(self) -> logging.Logger:
        """Agent-scoped logger."""
        return self._logger

    def env_ask_env_ctx_overlay(self) -> dict[str, Any]:
        """Generate the ask_env / CodeGenRouter.ask context overlay.

        Returns the stable identity keys (id, agent_id, person_id) provided by
        the framework, independent of any skill.

        :returns: dict with id, agent_id, person_id.
        """
        i = self.id
        return {"id": i, "agent_id": i, "person_id": i}

    async def ask_env(
        self,
        ctx: dict,
        message: str,
        readonly: bool,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ):
        """Send a request to the environment router.

        Wraps interaction with the simulation environment, supporting template
        mode and context-variable substitution.

        :param ctx: Context dict (may include a ``variables`` key for template mode).
        :param message: Request message.
        :param readonly: Whether this is a read-only request.
        :param template_mode: Whether to enable template mode.
        :param trace_id: OTel trace ID for cross-agent/env correlation.
        :param parent_span_id: OTel parent span ID.
        :returns: Tuple ``(ctx, answer)``.
        """
        assert self._env is not None, "Environment is not initialized"
        merged_ctx = {**ctx, **self.env_ask_env_ctx_overlay()}
        ctx, answer = await self._env.ask(
            merged_ctx,
            message,
            readonly=readonly,
            template_mode=template_mode,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )
        return ctx, answer

    @staticmethod
    def _extract_json_list_from_text(text: str) -> list[Any]:
        """Scan ``text`` for the first JSON array and return it.

        :param text: Free-form text that may embed a JSON array.
        :returns: The first decoded list, or ``[]`` if none is found.
        """
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "[":
                continue
            try:
                value, _ = decoder.raw_decode(text[idx:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, list):
                return value
        return []

    def _extract_env_list_result(
        self,
        env_result: Any,
        answer: str,
        key: str,
    ) -> list[Any]:
        """Extract a list payload from an ``ask_env`` return value.

        Prefers a direct list, then ``env_result[key]``, then the first JSON
        array embedded in ``answer``.

        :param env_result: First element of ``ask_env`` (usually ``results``).
        :param answer: Second element of ``ask_env`` (printed summary text).
        :param key: Dict key to read when ``env_result`` is a mapping.
        :returns: A list (possibly empty).
        """
        if isinstance(env_result, list):
            return env_result
        if isinstance(env_result, dict):
            value = env_result.get(key)
            if isinstance(value, list):
                return value
        return self._extract_json_list_from_text(answer)

    def _ensure_env_ask_ok(
        self,
        env_result: Any,
        answer: str,
        *,
        op: str,
    ) -> None:
        """Raise if an ``ask_env`` call did not report a successful status.

        :param env_result: First element of ``ask_env`` (usually ``results``).
        :param answer: Second element of ``ask_env`` (printed summary text).
        :param op: Short label for the operation (used in the error message).
        :raises RuntimeError: When status is missing or not success-like.
        """
        if not isinstance(env_result, dict):
            raise RuntimeError(
                f"{op} returned non-dict results: {type(env_result).__name__}"
            )
        status = str(env_result.get("status", "")).lower()
        if status not in {"success", "submitted"}:
            reason = env_result.get("reason") or answer.strip()[:200] or "no reason"
            raise RuntimeError(f"{op} failed (status={status or 'missing'}): {reason}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def acompletion(
        self,
        messages: list[dict[str, Any]],
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Single LLM completion via the bound default-role dispatcher.

        Convenience for subclasses that need a one-shot LLM call (the full
        multi-turn tool loop is :meth:`run_react_loop`). Uses the agent's
        bound dispatcher + model.

        Args:
            messages: Chat messages.
            stream: Streaming flag (False by default; the local LLM dispatcher
                does not support streaming).
            **kwargs: Extra litellm kwargs (timeout, tools, ...).

        Returns:
            The LLM response (litellm ``ModelResponse``).
        """
        assert self._dispatcher is not None, "Agent LLM dispatcher is not bound"
        return await self._dispatcher.call(
            model=self._model_name,
            messages=messages,
            stream=stream,
            **kwargs,
        )

    async def _completion_text(
        self,
        messages: list[dict[str, Any]],
        *,
        empty_attempts: int = 3,
        **kwargs: Any,
    ) -> str:
        """Return nonempty completion text with bounded empty-response retries."""
        if empty_attempts < 1:
            raise ValueError("empty_attempts must be positive")
        for attempt in range(1, empty_attempts + 1):
            response = await self.acompletion(messages, stream=False, **kwargs)
            choices = getattr(response, "choices", None)
            message = getattr(choices[0], "message", None) if choices else None
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content
            if attempt < empty_attempts:
                self._logger.warning(
                    "[%s] Empty LLM response (%d/%d); retrying",
                    self.name,
                    attempt,
                    empty_attempts,
                )
        raise RuntimeError(
            f"LLM returned empty responses after {empty_attempts} attempts"
        )

    async def close(self):
        """Close the agent and release resources. Subclasses may override."""

    def get_profile(self) -> dict[str, Any]:
        """Return the agent profile as a dict.

        :returns: Profile dict (raw dict, model_dump, or ``{"raw": str}``).
        """
        if isinstance(self._profile, dict):
            return self._profile
        elif hasattr(self._profile, "model_dump"):
            return self._profile.model_dump()
        else:
            return {"raw": str(self._profile)}

    # ------------------------------------------------------------------
    # Descriptions
    # ------------------------------------------------------------------

    @classmethod
    def description(cls) -> str:
        """Return a short agent description for module lists."""
        if cls is AgentBase:
            return "Abstract base class for agents."
        doc = (cls.__doc__ or "").strip().splitlines()
        return doc[0].strip() if doc else f"{cls.__name__}: Agent class."

    @classmethod
    def init_description(cls) -> str:
        """Return AI-readable initialization guidance for this agent class."""
        if cls is AgentBase:
            description = f"""{cls.__name__}: Abstract base class for agents.

**Description:** {cls.__doc__ or "No description available"}

**Construction:** Agents are created via ``AgentBase.create(workspace_path, profile, config)``
and reconstructed via ``await AgentBase.from_workspace(workspace_path, service_proxy)``.
The constructor ``__init__`` is arg-less.

**Note:** This is an abstract base class. Do not use it directly.

**Example initialization config:**
```json
{{
  "id": 1,
  "profile": {{
    "name": "Alice",
    "gender": "female",
    "age": 30,
    "education": "University",
    "occupation": "Engineer",
    "marriage_status": "single",
    "persona": "helpful",
    "background_story": "A software engineer who loves coding."
  }},
  "config": {{}}
}}
```
"""
        else:
            description = f"""{cls.__name__}: Agent class.

**Description:** {cls.__doc__ or "No description available"}

**Construction:** Agents are created via ``{cls.__name__}.create(workspace_path, profile, config)``
and reconstructed via ``await {cls.__name__}.from_workspace(workspace_path, service_proxy)``.
The constructor ``__init__`` is arg-less.

**Note:** This subclass has not provided a detailed description. Please refer to the class documentation or source code.
"""
        return description

    # ==================================================================
    # Workspace binding
    # ==================================================================

    def _bind_workspace(self, workspace_path: Path) -> None:
        """Bind runtime objects to an EXISTING workspace (no directory creation).

        Assumes the workspace already exists (created by :meth:`create`).
        Sets up WorkspaceFS + the trace writer, and binds the skill runtime.

        Trace writes go through a local :class:`ShardedAppendSink`
        (``service_proxy.trace`` carries only the output dir) — no per-workspace
        event file, no central trace actor. When no proxy trace is bound, spans
        are still created (the span API works) but not recorded (no-op).

        Args:
            workspace_path: Existing agent workspace root.
        """
        workspace = Path(workspace_path).resolve()
        self._workspace_root = workspace
        self._workspace_fs = WorkspaceFS(workspace)
        sharded = self._maybe_proxy_sharded_writer()
        self._jsonl_trace_writer = JsonlTraceWriter(
            agent_id=self.id,
            sharded_writer=sharded,
        )
        # Bind the skill runtime if present.
        skill_runtime = getattr(self, "skill_runtime", None)
        if skill_runtime is not None:
            skill_runtime.bind_workspace(
                workspace_root=workspace,
                fs=self._workspace_fs,
                trace_writer=self._jsonl_trace_writer,
            )

    def _maybe_proxy_sharded_writer(self):
        """Return a local sharded sink if trace is enabled on the bound proxy.

        Looks at ``self._service_proxy.trace``; if it carries a ``trace_dir``,
        build this agent's own :class:`ShardedAppendSink` (distributed,
        append-only, no central actor). Otherwise return ``None`` (no-op).
        """
        proxy = getattr(self, "_service_proxy", None)
        if proxy is None:
            return None
        trace = getattr(proxy, "trace", None)
        if trace is None:
            return None
        from agentsociety2.trace import build_local_sink

        return build_local_sink(trace)

    @staticmethod
    def _derive_name(profile: Any, agent_id: int) -> str:
        """Derive a display name from profile/id.

        Args:
            profile: Agent profile (dict or object).
            agent_id: Agent id fallback.

        Returns:
            Display name string.
        """
        if isinstance(profile, dict) and profile.get("name"):
            return str(profile["name"])
        if hasattr(profile, "name") and getattr(profile, "name", None):
            return str(profile.name)
        return f"Agent_{agent_id}"

    def workspace_root_path(self) -> Path:
        """Return the agent-owned workspace root.

        Raises:
            RuntimeError: When the workspace is not initialized.
        """
        if self._workspace_root is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._workspace_root

    @property
    def _workspace(self) -> WorkspaceFS:
        """Return the agent-owned workspace filesystem."""
        if self._workspace_fs is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._workspace_fs

    @property
    def _trace(self) -> JsonlTraceWriter:
        """Return the agent-owned trace writer."""
        if self._jsonl_trace_writer is None:
            raise RuntimeError("Agent trace writer is not initialized")
        return self._jsonl_trace_writer

    # ------------------------------------------------------------------
    # Trace span helpers
    # ------------------------------------------------------------------

    @property
    def _current_trace_span(self) -> TraceSpan | None:
        """Return the current active trace span, or None."""
        return (
            self._jsonl_trace_writer.current_span if self._jsonl_trace_writer else None
        )

    def _start_trace_span(
        self,
        name: str,
        *,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceSpan:
        """Start an agent-owned trace span."""
        return self._trace.start_span(
            name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attributes=attributes,
        )

    def _end_trace_span(
        self,
        span: TraceSpan,
        *,
        status: str = "ok",
        message: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """End an agent-owned trace span."""
        self._trace.end_span(
            span,
            status=status,
            message=message,
            attributes=attributes,
        )

    @contextmanager
    def trace_span(
        self,
        name: str,
        *,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        end_attributes: dict[str, Any] | None = None,
    ) -> Iterator[TraceSpan]:
        """Create an agent-owned trace span context."""
        with self._trace.trace_span(
            name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attributes=attributes,
            end_attributes=end_attributes,
        ) as span:
            yield span

    # ------------------------------------------------------------------
    # AGENT.json persistence
    # ------------------------------------------------------------------

    def build_agent_json(
        self,
        *,
        tick: int | None,
        t: Any | None,
    ) -> dict[str, Any]:
        """Build the consolidated self-description file for the agent.

        Subclasses may override to add extra fields (e.g. memory summary).

        Args:
            tick: Current simulation tick, if available.
            t: Current simulation time, if available.

        Returns:
            Serializable AGENT.json dictionary.
        """
        skill_runtime = getattr(self, "skill_runtime", None)
        visible = sorted(skill_runtime.visible_skill_ids()) if skill_runtime else []
        activated = sorted(skill_runtime.activated_skill_ids()) if skill_runtime else []
        return {
            "schema_version": 1,
            "agent_class": type(self).__name__,
            "agent_id": self.id,
            "name": self.name,
            "current_time": t.isoformat() if t is not None else None,
            "tick": tick,
            "step_count": getattr(self, "_step_count", 0),
            "profile": self.get_profile(),
            "workspace": {
                "root": str(self.workspace_root_path()),
                "agent_json_path": AGENT_JSON_PATH,
            },
            "skills": {
                "visible": visible,
                "activated": activated,
            },
            "initialized_at": getattr(self, "_initialized_at", None),
        }

    def build_prompt_agent_view(
        self,
        *,
        tick: int | None,
        t: Any | None,
    ) -> dict[str, Any]:
        """Project AGENT.json down to its run-stable, prompt-safe subset.

        :meth:`build_agent_json` is the persisted AGENT.json payload — it is
        read back by the resume path and is documented as a subclass extension
        point, so it is left alone. This projection strips what must not reach
        the prompt:

        - ``initialized_at`` — wall-clock, differs per agent and per run.
        - ``current_time`` / ``tick`` / ``step_count`` — change every step, so
          they are emitted as a separate ``<turn_state>`` block placed after
          the run-stable blocks.
        - ``workspace.root`` — an absolute host path, useless to the model
          (every workspace tool takes a workspace-relative path).

        Subclass extras added by a :meth:`build_agent_json` override survive.

        Args:
            tick: Current simulation tick, if available.
            t: Current simulation time, if available.

        Returns:
            Prompt-safe view of the agent self-description.
        """
        data = dict(self.build_agent_json(tick=tick, t=t))
        for volatile in ("initialized_at", "current_time", "tick", "step_count"):
            data.pop(volatile, None)
        workspace = dict(data.get("workspace") or {})
        workspace.pop("root", None)
        data["workspace"] = workspace
        return data

    def build_prompt_turn_state(
        self,
        *,
        tick: int | None,
        t: Any | None,
    ) -> dict[str, Any]:
        """Build the per-step ``<turn_state>`` block payload.

        Constant across every ReAct turn within one simulation step, which is
        why it is rendered ahead of ``<recent_observations>``.

        Args:
            tick: Current simulation tick, if available.
            t: Current simulation time, if available.

        Returns:
            Per-step state dictionary.
        """
        return {
            "current_time": t.isoformat() if t is not None else None,
            "tick": tick,
            "step_count": getattr(self, "_step_count", 0),
        }

    def persist_agent_json(
        self,
        *,
        tick: int | None = None,
        t: Any | None = None,
    ) -> dict[str, Any]:
        """Persist consolidated agent self-description to AGENT.json.

        Args:
            tick: Current simulation tick, if available.
            t: Current simulation time, if available.

        Returns:
            Data written to AGENT.json.
        """
        data = self.build_agent_json(tick=tick, t=t)
        self._workspace.write_text(
            AGENT_JSON_PATH,
            json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str),
        )
        return data

    # ==================================================================
    # Skill runtime
    # ==================================================================

    def _setup_skill_runtime(self, *, agent_id: int) -> None:
        """Initialize the shared skill registry and this agent's runtime.

        Args:
            agent_id: Numeric agent id.
        """
        self._skill_registry = get_skill_registry()
        self.skill_runtime = AgentSkillRuntime(
            agent_id=agent_id,
            registry=self._skill_registry,
        )

    # ------------------------------------------------------------------
    # Discovery + visibility
    # ------------------------------------------------------------------

    def _refresh_visible_skills(self) -> None:
        """Refresh visible skills after registry changes."""
        visible_skill_ids = {
            info.skill_id
            for info in self._skill_registry.list_all()
            if info.skill_id not in self._disabled_skill_ids
        }
        self.skill_runtime.set_visible_skills(visible_skill_ids)

    def _resolve_skill_paths(self, items: Iterable[Any]) -> list[Path]:
        """Resolve a set of skill-directory paths to absolute, deduped paths.

        Accepts ``str`` / ``Path`` items. Relative paths resolve against the
        workspace root; absolute paths are used as-is. Empty / falsy items are
        skipped and invalid input never raises (yields fewer entries).

        Args:
            items: Iterable of skill-directory path candidates.

        Returns:
            Deduplicated absolute paths, insertion order preserved.
        """
        workspace = self._workspace_root
        resolved: list[Path] = []
        seen: set[Path] = set()
        if items is None:
            return resolved
        # A bare str/Path is one path, not an iterable of characters.
        if isinstance(items, (str, Path)):
            items = [items]
        if not isinstance(items, Iterable):
            return resolved
        for item in items:
            text = str(item or "").strip()
            if not text:
                continue
            path = Path(text).expanduser()
            if not path.is_absolute() and workspace is not None:
                path = workspace / path
            path = path.resolve()
            if path not in seen:
                seen.add(path)
                resolved.append(path)
        return resolved

    def discover_skill_sources(
        self,
        env: RouterBase,
        *,
        extra_skill_paths: Iterable[Path | str] | None = None,
    ) -> dict[str, list[str]]:
        """Discover custom and environment-provided skill sources.

        Scans the default ``<root>/custom/skills`` locations (``env.run_dir``
        and this agent's workspace root), then any extra skill directories
        merged from two sources:

        - declarative: ``extra_skill_paths`` in ``config.json`` (resolved in
          :meth:`restore`);
        - programmatic: the ``extra_skill_paths`` argument here.

        Each extra entry is a directory containing skill subdirectories (same
        layout as ``custom/skills``). Relative entries resolve against the
        workspace root. The default scan is unchanged when neither is given, so
        agents can load custom skills stored anywhere via either entry point.

        Args:
            env: Environment router used to locate run directories and modules.
            extra_skill_paths: Additional skill directories to scan now (each a
                root of skill subdirectories).

        Returns:
            Mapping from discovery source labels to added skill IDs.
        """
        discovered: dict[str, list[str]] = {}

        roots: list[Path] = []
        run_dir = getattr(env, "run_dir", None)
        if run_dir:
            roots.append(Path(run_dir))
        roots.append(self.workspace_root_path())

        seen: set[Path] = set()
        for root in roots:
            root_abs = root.resolve()
            if root_abs in seen:
                continue
            seen.add(root_abs)
            try:
                added = self._skill_registry.scan_custom(root_abs / "custom" / "skills")
            except Exception as exc:
                logger.warning(
                    "Agent %s: custom skill scan failed at %s: %s",
                    self.id,
                    root_abs,
                    exc,
                )
                added = []
            if added:
                discovered[f"custom:{root_abs}"] = added

        # Extra skill paths (config-driven + programmatic), scanned directly.
        # Lets an agent load custom skills stored at any location.
        for path in self._resolve_skill_paths(
            [*self._extra_skill_paths, *(extra_skill_paths or [])]
        ):
            if path in seen:
                continue
            seen.add(path)
            try:
                added = self._skill_registry.scan_custom(path)
            except Exception as exc:
                logger.warning(
                    "Agent %s: extra skill scan failed at %s: %s",
                    self.id,
                    path,
                    exc,
                )
                added = []
            if added:
                discovered[f"custom:{path}"] = added

        # Env-provided skills come from two shapes of ``env``:
        # - in-process router (``RouterBase``): exposes concrete ``env_modules``
        #   instances, each with a ``skill_dirs()`` method;
        # - Ray ``EnvRouterProxy``: carries no module instances (they live in the
        #   actor's process) but exposes ``env_skill_dirs`` —
        #   ``(module_class_name, skill_dir)`` pairs resolved from the registry
        #   at proxy construction. Scan both so env skills are discoverable in
        #   the distributed path too.
        env_skill_pairs: list[tuple[str, str]] = []
        for module in getattr(env, "env_modules", []) or []:
            class_name = type(module).__name__
            for skills_dir in module.skill_dirs() or []:
                env_skill_pairs.append((class_name, str(skills_dir)))
        for class_name, skills_dir_str in getattr(env, "env_skill_dirs", []) or []:
            env_skill_pairs.append((class_name, str(skills_dir_str)))

        seen_env: set[tuple[str, str]] = set()
        for class_name, skills_dir_str in env_skill_pairs:
            if not skills_dir_str or (class_name, skills_dir_str) in seen_env:
                continue
            seen_env.add((class_name, skills_dir_str))
            skills_dir = Path(skills_dir_str)
            try:
                added = self._skill_registry.scan_env(skills_dir, class_name)
            except Exception as exc:
                logger.warning(
                    "Agent %s: env skill scan failed at %s: %s",
                    self.id,
                    skills_dir,
                    exc,
                )
                added = []
            if added:
                discovered[f"env:{class_name}:{skills_dir}"] = added

        self._refresh_visible_skills()
        if not self._default_activated_skills_applied:
            self.skill_runtime.add_default_activated_skills(
                self._default_activated_skill_ids
            )
            self._default_activated_skills_applied = True
        return discovered

    def _resolve_skill_id_from_args(self, args: Mapping[str, Any]) -> str:
        """Resolve skill_name-first tool arguments to a registry skill id.

        Args:
            args: Tool argument mapping containing ``skill_name``.

        Returns:
            Matching visible skill ID, or an empty string.
        """
        skill_id = self.skill_runtime.resolve_skill_id(
            str(args.get("skill_name") or "")
        )
        if skill_id:
            return skill_id
        return self.skill_runtime.infer_single_script_skill_id()

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    async def run_lifecycle_hooks(
        self,
        hook_type: str,
        *,
        tick: int,
        t: Any,
    ) -> list[dict[str, Any]]:
        """Run lifecycle hooks for currently activated skills.

        Args:
            hook_type: Lifecycle hook name, such as ``pre_step`` or ``post_step``.
            tick: Current simulation tick.
            t: Current simulation time.

        Returns:
            Hook execution summaries.
        """
        payload = {
            "hook_type": hook_type,
            "tick": tick,
            "time": t.isoformat(),
            "agent_id": self.id,
            "step_count": getattr(self, "_step_count", 0),
        }
        summaries: list[dict[str, Any]] = []
        argv = ["--args-json", json.dumps(payload, ensure_ascii=False, default=str)]
        with self.trace_span(
            f"skill.lifecycle_hooks.{hook_type}",
            attributes={
                "operation.type": "skill",
                "hook.type": hook_type,
                "agent.tick": tick,
            },
        ) as span:
            for info in self.skill_runtime.active_hook_skills(hook_type):
                result = await self.skill_runtime.run_skill_hook(
                    info.skill_id,
                    hook_type,
                    argv,
                    timeout_sec=30,
                )
                summary = {
                    "skill_id": info.skill_id,
                    "hook_type": hook_type,
                    "ok": result.ok,
                    "exit_code": result.exit_code,
                    "stdout": _short_text(result.stdout, limit=1000),
                    "stderr": _short_text(result.stderr, limit=1000),
                }
                summaries.append(summary)
                if not result.ok:
                    logger.warning(
                        "Agent %s: lifecycle hook failed: %s %s",
                        self.id,
                        info.skill_id,
                        hook_type,
                    )
            span.attributes.update(
                {
                    "hook.executed_count": len(summaries),
                    "hook.failed_count": sum(1 for item in summaries if not item["ok"]),
                }
            )
        return summaries

    # ==================================================================
    # ReAct tool dispatch
    # ==================================================================

    # ------------------------------------------------------------------
    # Tool execution (trace-span wrapper)
    # ------------------------------------------------------------------

    # Read-only tools that are safe to run concurrently within one assistant
    # turn. Mutation / env tools stay serial to preserve side-effect order.
    _REACT_PARALLEL_SAFE_ACTIONS = frozenset(
        {
            "read",
            "list",
            "grep",
            "read_skill_file",
            "todo_list",
        }
    )

    async def _execute_react_tools(
        self,
        decisions: list[ReactDecision],
        *,
        readonly: bool = False,
    ) -> list[ReactToolResult]:
        """Execute one assistant turn's tools, parallelizing read-only actions.

        Args:
            decisions: Parsed ReAct decisions in assistant order.
            readonly: Whether mutation tools should be blocked.

        Returns:
            Results aligned with ``decisions`` order.
        """

        async def _one(decision: ReactDecision) -> ReactToolResult:
            try:
                return await self._execute_react_tool(decision, readonly=readonly)
            except Exception as exc:
                # Every id in the assistant turn must be answered before the
                # next assistant/user message, so a throwing tool becomes a
                # failed result rather than a stranded tool_call id.
                return ReactToolResult(
                    False,
                    f"tool execution failed: {exc}",
                    {"error": str(exc)},
                )

        if len(decisions) > 1 and all(
            decision.action in self._REACT_PARALLEL_SAFE_ACTIONS
            for decision in decisions
        ):
            return list(
                await asyncio.gather(*[_one(decision) for decision in decisions])
            )
        results: list[ReactToolResult] = []
        for decision in decisions:
            results.append(await _one(decision))
        return results

    async def _execute_react_tool(
        self,
        decision: ReactDecision,
        *,
        readonly: bool = False,
    ) -> ReactToolResult:
        """Execute one ReAct tool under a trace span.

        Args:
            decision: Parsed ReAct decision to execute.
            readonly: Whether mutation tools should be blocked.

        Returns:
            Tool execution result.
        """
        action = decision.action
        args = decision.args
        with self.trace_span(
            "react.tool",
            attributes={
                "operation.type": "react",
                "react.action": action,
            },
        ) as span:
            result = await self.dispatch_react_tool(action, args, readonly=readonly)
            update: dict[str, Any] = {
                "result.ok": result.ok,
                "output.summary": {
                    "observation": result.observation,
                },
            }
            if result.data:
                update["tool.data"] = result.data
            span.attributes.update(update)
            return result

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------

    async def dispatch_react_tool(
        self,
        action: str,
        args: dict[str, Any],
        *,
        readonly: bool = False,
    ) -> ReactToolResult:
        """Dispatch one ReAct tool call.

        Handles workspace file tools, skill tools, and ask_env. Person-specific
        tools (memory_*, todo_*) are handled by the subclass before this method
        is reached (or via a subclass override).

        Args:
            action: Tool name.
            args: Tool argument dictionary.
            readonly: Whether mutation tools should be blocked.

        Returns:
            Tool execution result.
        """
        try:
            if readonly and action in {"write", "append"}:
                return ReactToolResult(
                    False,
                    f"{action} is disabled in readonly mode",
                    {"action": action, "readonly": True},
                )
            if action == "read":
                path = str(args.get("path") or "")
                requested_path = path
                path = self._normalize_workspace_read_path(path)
                with self.trace_span(
                    "workspace.read_text",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": requested_path,
                        "workspace.normalized_path": path,
                    },
                ) as workspace_span:
                    try:
                        content = self._workspace.read_text(path)
                    except ValueError:
                        # The path escapes the agent workspace. If it points at
                        # a file bundled inside a visible skill (a common
                        # mistake — e.g. trying to ``read`` a skill's
                        # ``references/*.md``), serve it via read_skill_file
                        # instead of surfacing an opaque escape error.
                        resolved = self._try_read_skill_path(requested_path or path)
                        if resolved is not None:
                            skill_id, rel_path, content = resolved
                            workspace_span.attributes["skill_redirect"] = skill_id
                            workspace_span.attributes["result.size"] = len(content)
                            return ReactToolResult(
                                True,
                                content,
                                {
                                    "skill_id": skill_id,
                                    "path": rel_path,
                                    "redirected_from": requested_path,
                                },
                            )
                        raise
                    workspace_span.attributes["result.size"] = len(content)
                return ReactToolResult(True, content, {"path": path})
            if action == "write":
                path = str(args.get("path") or "")
                if self._is_core_owned_workspace_path(path):
                    return ReactToolResult(
                        True,
                        (
                            f"{path} is managed by the agent runtime and cannot "
                            "be written directly; no workspace write was performed"
                        ),
                        {"path": path, "core_owned": True, "noop": True},
                    )
                content = str(args.get("content") or "")
                with self.trace_span(
                    "workspace.write_text",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": path,
                    },
                ) as workspace_span:
                    result = self._workspace.write_text(path, content)
                    workspace_span.attributes["result.bytes"] = result.bytes_written
                # Workspace-relative, like ``read``/``grep``: an absolute host
                # path is noise to the model and varies per agent, so it would
                # break prompt-prefix reuse for no benefit.
                return ReactToolResult(True, f"written: {path}", {"path": path})
            if action == "append":
                path = str(args.get("path") or "")
                if self._is_core_owned_workspace_path(path):
                    return ReactToolResult(
                        True,
                        (
                            f"{path} is managed by the agent runtime and cannot "
                            "be appended directly; no workspace append was performed"
                        ),
                        {"path": path, "core_owned": True, "noop": True},
                    )
                content = str(args.get("content") or "")
                with self.trace_span(
                    "workspace.append_text",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": path,
                    },
                ) as workspace_span:
                    result = self._workspace.append_text(path, content)
                    workspace_span.attributes["result.bytes"] = result.bytes_written
                return ReactToolResult(result.ok, f"appended: {path}", result.__dict__)
            if action == "list":
                path = str(args.get("path") or ".")
                files = [
                    item.path
                    for item in self._workspace.list(path, limit=10_000)
                    if not item.is_dir
                ]
                return ReactToolResult(
                    True,
                    json.dumps(files, ensure_ascii=False, default=str),
                    {"files": files},
                )
            if action == "grep":
                pattern = str(args.get("pattern") or "")
                path = str(args.get("path") or ".")
                limit = int(args.get("limit") or 100)
                with self.trace_span(
                    "workspace.grep",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": path,
                        "grep.pattern": pattern,
                    },
                ) as workspace_span:
                    matches = await self._workspace.grep(pattern, path, limit=limit)
                    workspace_span.attributes["result.count"] = len(matches)
                data = {"matches": [item.__dict__ for item in matches]}
                return ReactToolResult(
                    True, json.dumps(data, ensure_ascii=False, default=str), data
                )
            if action == "activate_skill":
                requested_skill_name = str(args.get("skill_name") or "")
                activated, skill_id, doc = self.skill_runtime.activate_skill(
                    requested_skill_name
                )
                if not activated:
                    if skill_id:
                        observation = (
                            "activate_skill failed: "
                            f"skill_name={requested_skill_name!r} resolved to "
                            f"skill_id={skill_id!r}, but its SKILL.md is missing or empty"
                        )
                        error = "skill_doc_unavailable"
                    else:
                        observation = (
                            "activate_skill failed: "
                            f"skill_name={requested_skill_name!r} is not visible, "
                            "does not exist, or is ambiguous; use a skill name from "
                            "the visible skill catalog"
                        )
                        error = "skill_not_resolved"
                    return ReactToolResult(
                        False,
                        observation,
                        {
                            "skill_id": skill_id,
                            "skill_name": requested_skill_name,
                            "activated": False,
                            "error": error,
                        },
                    )
                return ReactToolResult(
                    True,
                    doc,
                    {
                        "skill_id": skill_id,
                        "skill_name": requested_skill_name,
                        "activated": True,
                    },
                )
            if action == "deactivate_skill":
                removed, skill_id = self.skill_runtime.deactivate_skill(
                    str(args.get("skill_name") or "")
                )
                return ReactToolResult(
                    True,
                    f"deactivated: {skill_id}"
                    if removed
                    else f"not active: {skill_id}",
                    {"skill_id": skill_id, "removed": removed},
                )
            if action == "read_skill_file":
                skill_id = self._resolve_skill_id_from_args(args)
                path = str(args.get("path") or "")
                content = self.skill_runtime.read_skill_file(skill_id, path)
                return ReactToolResult(
                    bool(content),
                    content,
                    {
                        "skill_id": skill_id,
                        "path": path,
                        "content_len": len(content or ""),
                    },
                )
            if action == "execute_skill_script":
                skill_id = self._resolve_skill_id_from_args(args)
                script_path = str(args.get("script_path") or "")
                argv = args.get("argv")
                argv_list = (
                    [str(item) for item in argv] if isinstance(argv, list) else []
                )
                if skill_id.startswith("env:"):
                    instruction = self._build_env_skill_instruction(args, argv_list)
                    env_readonly = bool(args.get("readonly", False))
                    if readonly and not env_readonly:
                        return ReactToolResult(
                            False,
                            "environment skill mutation is disabled in readonly mode",
                            {
                                "skill_id": skill_id,
                                "argv": argv_list,
                                "readonly": True,
                            },
                        )
                    _span = self._current_trace_span
                    _, answer = await self.ask_env(
                        self._build_env_tool_context(args),
                        instruction,
                        readonly=env_readonly,
                        template_mode=True,
                        trace_id=_span.trace_id if _span else None,
                        parent_span_id=_span.span_id if _span else None,
                    )
                    return ReactToolResult(
                        True,
                        str(answer or ""),
                        {
                            "skill_id": skill_id,
                            "argv": argv_list,
                            "instruction": instruction,
                            "redirected_to": "ask_env",
                            "readonly": env_readonly,
                        },
                    )
                result = await self.skill_runtime.run_skill_script(
                    skill_id,
                    script_path,
                    argv_list,
                    timeout_sec=int(args.get("timeout_sec") or 30),
                )
                return ReactToolResult(
                    result.ok,
                    json.dumps(result.as_dict(), ensure_ascii=False, default=str),
                    {
                        "skill_id": skill_id,
                        "script_path": script_path,
                        "argv": argv_list,
                        "exit_code": result.exit_code,
                        "stdout_len": len(result.stdout or ""),
                        "stderr_len": len(result.stderr or ""),
                        **({"stdout": result.stdout} if result.stdout else {}),
                        **({"stderr": result.stderr} if result.stderr else {}),
                    },
                )
            if action == "ask_env":
                ctx = self._build_env_tool_context(args)
                instruction = str(args.get("instruction") or "")
                if not instruction:
                    return ReactToolResult(
                        False,
                        "ask_env requires instruction",
                        {"error": "missing instruction"},
                    )
                # Template/cache mode is always forced on for ask_env so the
                # router reuses cached code for similar instructions instead of
                # regenerating (and paying an LLM round-trip) on every call.
                template = True
                env_readonly = bool(args.get("readonly", False))
                if readonly and not env_readonly:
                    return ReactToolResult(
                        False,
                        "ask_env mutation is disabled in readonly mode",
                        {"instruction": instruction, "readonly": True},
                    )
                _span = self._current_trace_span
                _, answer = await self.ask_env(
                    ctx,
                    instruction,
                    readonly=env_readonly,
                    template_mode=bool(template),
                    trace_id=_span.trace_id if _span else None,
                    parent_span_id=_span.span_id if _span else None,
                )
                return ReactToolResult(
                    True,
                    str(answer or ""),
                    {"instruction": instruction, "template_mode": bool(template)},
                )
            return ReactToolResult(
                False,
                f"unknown action: {action}",
                {"action": action},
            )
        except Exception as exc:
            return ReactToolResult(False, str(exc), {"error": str(exc)})

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_core_owned_workspace_path(path: str) -> bool:
        """Return whether a workspace path is owned by agent core runtime.

        Args:
            path: Workspace-relative path requested by the LLM tool loop.

        Returns:
            True when generic workspace mutation tools must not edit the path.
        """
        normalized = str(path or "").replace("\\", "/").strip().lstrip("./")
        return (
            normalized == "AGENT.json"
            or normalized == "MEMORY.md"
            or normalized.startswith(("memory/", "state/daily_guidance/"))
            or normalized == "state/todos.json"
        )

    def _normalize_workspace_read_path(self, path: str) -> str:
        """Map known agent-workspace absolute paths to this workspace.

        Args:
            path: Model-provided read path.

        Returns:
            Original relative path or a path relative to this agent workspace.
        """
        raw = str(path or "").strip()
        if not raw:
            return raw
        candidate = Path(raw)
        if not candidate.is_absolute():
            return raw
        parts = candidate.parts
        agent_dir = self.workspace_root_path().name
        for idx, part in enumerate(parts):
            if part == agent_dir:
                rel_parts = parts[idx + 1 :]
                if rel_parts:
                    return Path(*rel_parts).as_posix()
        return raw

    def _try_read_skill_path(self, path: str) -> tuple[str, str, str] | None:
        """Resolve an escaping read path to a visible skill file's content.

        Args:
            path: The path the model tried to read (absolute or relative).

        Returns:
            ``(skill_id, relative_path, content)`` if the path maps to a file
            inside a visible skill root, else ``None``.
        """
        resolved = self.skill_runtime.resolve_skill_path(path)
        if resolved is None:
            return None
        skill_id, rel_path = resolved
        content = self.skill_runtime.read_skill_file(skill_id, rel_path)
        if not content:
            return None
        return skill_id, rel_path, content

    def _build_env_tool_context(self, args: dict[str, Any]) -> dict[str, Any]:
        """Build ask_env context from tool arguments.

        Args:
            args: ask_env tool arguments.

        Returns:
            Context dictionary passed to RouterBase.ask.
        """
        raw_ctx = args.get("ctx")
        ctx = dict(raw_ctx) if isinstance(raw_ctx, Mapping) else {}
        raw_variables = args.get("variables")
        if isinstance(raw_variables, Mapping):
            current = ctx.get("variables")
            variables = dict(current) if isinstance(current, Mapping) else {}
            variables.update(dict(raw_variables))
            ctx["variables"] = variables
        return ctx

    def _build_env_skill_instruction(
        self,
        args: Mapping[str, Any],
        argv: list[str],
    ) -> str:
        """Build an ask_env instruction for env skill calls sent to script execution.

        Args:
            args: Original tool arguments.
            argv: Command-like arguments supplied by the model.

        Returns:
            Natural-language instruction for the environment router.
        """
        skill_name = str(args.get("skill_name") or "environment").strip()
        if argv:
            return (
                f"Use the {skill_name} environment skill to perform: {' '.join(argv)}"
            )
        return f"Use the {skill_name} environment skill for the current state."

    # ==================================================================
    # ReAct loop (generic orchestration)
    # ==================================================================
    #
    # The loop is generic: it builds messages via ``self.build_react_messages``
    # (a subclass-provided prompt hook), dispatches the LLM via
    # ``self._dispatcher.call``, executes tools via ``self._execute_react_tool``
    # (which calls ``self.dispatch_react_tool`` polymorphically), and respects
    # ``self._max_react_turns``.  Nothing person-specific is inlined here.

    async def run_react_loop(
        self,
        *,
        tick: int,
        t: datetime,
        observations: list[dict[str, Any]] | None = None,
        question: str | None = None,
        readonly: bool = False,
        skill_hooks: list[dict[str, Any]] | None = None,
    ) -> str:
        """Run the ReAct loop until finish or turn limit.

        Args:
            tick: Current simulation tick.
            t: Current simulation time.
            observations: Initial observation list (appended in-place).
            question: Optional external question (ask mode).
            readonly: Whether mutation tools are blocked.
            skill_hooks: Optional pre_step hook outputs for the prompt.

        Returns:
            Final result string from the loop.
        """
        if observations is None:
            observations = []
        # Reset inline finish memories for this loop invocation; set below when
        # a step-mode `finish` carrying `memories` is observed.
        self._last_finish_memories = None
        self._last_raw_answer_text = ""
        self._last_react_error = ""
        # ONE thread per loop invocation, built once and thereafter only
        # appended to. That is what makes every request a strict
        # prefix-extension of the previous one, so the provider's prompt-prefix
        # cache grows across turns instead of resetting each turn (measured
        # ~52% -> ~82% aggregate hit rate over a 6-turn conversation).
        #
        # Do NOT rebuild this per turn, and do NOT truncate it from the front:
        # both destroy the cached prefix and give back the entire win.
        messages: list[dict[str, Any]] = list(
            self.build_react_messages(
                tick=tick,
                t=t,
                observations=observations,
                question=question,
                readonly=readonly,
                skill_hooks=skill_hooks,
            )
        )
        with self.trace_span(
            "react.loop",
            attributes={
                "agent.tick": tick,
                "operation.type": "react",
                "react.max_turns": self._max_react_turns,
                "react.readonly": readonly,
                "input.message_chars": len(question or ""),
            },
        ) as loop_span:
            for turn in range(1, self._max_react_turns + 1):
                with self.trace_span(
                    "react.turn",
                    attributes={
                        "agent.tick": tick,
                        "operation.type": "react",
                        "react.turn": turn,
                    },
                ) as turn_span:
                    # Clear the per-turn parse error so a stale message from an
                    # earlier turn never surfaces as corrective feedback if the
                    # current turn yields empty decisions for a different reason
                    # (e.g. an empty-content response that carries no error).
                    self._last_react_error = ""
                    react_turn = await self._call_react_llm_with_messages(
                        messages, readonly=readonly
                    )
                    decisions = react_turn.decisions
                    turn_span.attributes.update(
                        {
                            "react.action": ", ".join(d.action for d in decisions)
                            if decisions
                            else "(none)",
                            "react.tool_count": len(decisions),
                            "llm.message_count": len(messages),
                            # Which encoding served this turn — lets a production
                            # run be sliced by it, so the append-only change can
                            # be A/B-ed from logs without a permanent switch.
                            "react.history_encoding": (
                                "tool"
                                if (react_turn.assistant_message or {}).get(
                                    "tool_calls"
                                )
                                else "user"
                            ),
                        }
                    )

                    finish_d = next(
                        (d for d in decisions if d.action == "finish"), None
                    )
                    if finish_d is not None:
                        # Capture memories the model recorded inline in the
                        # step-mode finish tool, so step() can ingest them
                        # without a separate extraction pass. Absent in ask mode
                        # (finish carries only `answer`) — stays None there.
                        self._last_finish_memories = finish_d.args.get("memories")
                        # Step-mode finish has no `final` text; derive a brief
                        # step result from the recorded memories so the trace /
                        # step summary stays meaningful (ask mode keeps its
                        # explicit `answer`).
                        final = (
                            finish_d.final
                            or _brief_memories_summary(self._last_finish_memories)
                            or finish_d.thought
                            or "done"
                        )
                        loop_span.attributes.update(
                            {
                                "react.end_reason": "finish",
                                "output.summary": {"final": final},
                            }
                        )
                        return final

                    if not decisions:
                        # No valid tool call this turn (parse/validation failed
                        # even after the within-turn retry). Instead of silently
                        # ending as "done" — which drops the ask answer / step
                        # memory — record the failure so the model can
                        # self-correct on a later turn. The corrective feedback
                        # is already in `messages`; `observations` stays the
                        # side-channel that react.tool_ok and the end-of-loop
                        # fallbacks read. The loop is still bounded by
                        # _max_react_turns; if the model never recovers we
                        # synthesize a fallback below.
                        feedback = (
                            self._last_react_error or "No valid tool call was produced."
                        )
                        observations.append(
                            {
                                "turn": turn,
                                "action": "(invalid)",
                                "ok": False,
                                "observation": feedback,
                                "data": {"error": feedback},
                            }
                        )
                        continue

                    if react_turn.assistant_message is not None:
                        messages.append(react_turn.assistant_message)
                    entries: list[dict[str, Any]] = []
                    results = await self._execute_react_tools(
                        decisions,
                        readonly=readonly,
                    )
                    for decision, result in zip(decisions, results):
                        if not result.ok:
                            logger.warning(
                                "Agent %s: ReAct tool failed: action=%s observation=%s",
                                self.id,
                                decision.action,
                                _short_text(result.observation, limit=300),
                            )
                        entries.append(
                            {
                                "turn": turn,
                                "action": decision.action,
                                "ok": result.ok,
                                "observation": result.observation,
                                "data": result.data,
                            }
                        )
                    observations.extend(entries)
                    messages.extend(_react_tool_replies(decisions, entries))
                    self._append_context_refresh(
                        messages, decisions, entries, tick=tick, t=t
                    )
                    turn_span.attributes["react.tool_ok"] = all(
                        obs["ok"] for obs in observations if obs.get("turn") == turn
                    )

            # Loop exhausted without a valid finish. Fall back to a rule-based
            # result so the agent always carries forward *something*: a step
            # memory synthesized from the turn observations (step mode), or the
            # last free-text answer the model emitted (ask mode).
            if readonly:
                final = self._synthesize_ask_fallback()
                loop_span.attributes.update(
                    {
                        "react.end_reason": "ask_fallback",
                        "output.summary": {"final": final},
                    }
                )
                return final
            self._last_finish_memories = self._synthesize_step_fallback_memory(
                tick=tick, t=t, observations=observations
            )
            final = _brief_memories_summary(self._last_finish_memories) or "done"
            loop_span.attributes.update(
                {
                    "react.end_reason": "step_memory_fallback",
                    "output.summary": {"final": final},
                }
            )
            return final

    async def _call_react_llm_with_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        readonly: bool = False,
    ) -> ReactTurn:
        """Call the LLM and retry once on invalid tool arguments.

        ``messages`` is extended **in place** with this turn's assistant message
        and, on error, with the corrective replies — so the next request is a
        prefix-extension of this one and the prompt-prefix cache keeps growing.

        Args:
            messages: OpenAI-style chat messages (mutated in place).
            readonly: Whether mutation tools are blocked.

        Returns:
            The parsed :class:`ReactTurn` from the final attempt.
        """
        with self.trace_span(
            "llm.completion",
            attributes={
                "operation.type": "llm",
                "llm.model": self._model_name or "",
                "input.message_count": len(messages),
            },
        ) as span:
            turn, appended = await self._append_react_turn(
                messages, readonly=readonly, span=span
            )
            if turn.error:
                self._last_react_error = turn.error
                span.attributes["llm.retry"] = True
                span.attributes["input.message_count"] = len(messages)
                turn, appended = await self._append_react_turn(
                    messages, readonly=readonly, span=span
                )
            if turn.error:
                self._last_react_error = turn.error
                span.attributes["schema.error"] = turn.error
                logger.warning(
                    "Agent %s: invalid ReAct decision: %s", self.id, turn.error
                )
            if not turn.decisions and not appended:
                # Guarantee the next request differs from this one. The thread
                # is no longer rebuilt per turn, so an un-appended empty turn
                # would re-send a byte-identical prompt — and with a prefix
                # cache in play the model could spin on it until the turn limit.
                messages.append(
                    {
                        "role": "user",
                        "content": _xml_block(
                            "react_error",
                            (
                                self._last_react_error
                                or "No valid tool call was produced."
                            )
                            + "\nRespond with a single valid tool call.",
                        ),
                    }
                )
        return turn

    async def _append_react_turn(
        self,
        messages: list[dict[str, Any]],
        *,
        readonly: bool,
        span: Any,
    ) -> tuple[ReactTurn, bool]:
        """Run one completion, appending error-correction replies when needed.

        On success the assistant message is deliberately **not** appended here:
        :meth:`run_react_loop` appends it together with its tool replies, so a
        tool that raises can still produce a reply and never leaves an
        unanswered tool-call id.

        Args:
            messages: Chat messages (mutated in place).
            readonly: Whether mutation tools are blocked.
            span: The open ``llm.completion`` span, for usage accounting.

        Returns:
            ``(turn, appended)`` — ``appended`` reports whether ``messages`` grew.
        """
        response = await self._complete_react_once(messages, readonly=readonly)
        self._record_llm_usage(span, response)
        turn = self._parse_react_turn(response, readonly=readonly)
        if not turn.error:
            return turn, False

        error_block = _xml_block(
            "schema_error",
            turn.error + "\nCall valid tool(s) with valid arguments.",
        )
        if turn.assistant_message is not None:
            messages.append(turn.assistant_message)
            tool_calls = turn.assistant_message.get("tool_calls") or []
            # An assistant turn that carries tool_calls must have every id
            # answered before any later assistant/user message, so answer them
            # with the error text rather than following up with a bare user turn.
            for tool_call in tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": error_block,
                    }
                )
            if not tool_calls:
                messages.append({"role": "user", "content": error_block})
        else:
            messages.append({"role": "user", "content": error_block})
        return turn, True

    def _record_llm_usage(self, span: Any, response: Any) -> None:
        """Copy one response's token usage onto the ``llm.completion`` span.

        Exposes per-turn, per-agent prompt-cache hits in the trace JSONL. This
        is what localizes a low hit rate to "the shared system prefix missed"
        vs "the per-turn window was invalidated" vs "this was an ask-mode turn",
        which the aggregate counters in the run summary cannot distinguish.

        Span attributes are accumulated across the within-turn retry, so a turn
        that retried reports the sum of both completions.

        Args:
            span: The open ``llm.completion`` trace span.
            response: Raw LLM response from the dispatcher.

        Returns:
            None.
        """
        from agentsociety2.config.llm_dispatcher import extract_cached_tokens

        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        cached = extract_cached_tokens(response)
        attributes = span.attributes
        attributes["llm.input_tokens"] = (
            int(attributes.get("llm.input_tokens", 0)) + input_tokens
        )
        attributes["llm.cached_input_tokens"] = (
            int(attributes.get("llm.cached_input_tokens", 0)) + cached
        )
        total_input = int(attributes["llm.input_tokens"])
        attributes["llm.cache_hit_rate"] = (
            max(0.0, min(1.0, int(attributes["llm.cached_input_tokens"]) / total_input))
            if total_input > 0
            else 0.0
        )

    async def _complete_react_once(
        self,
        messages: list[dict[str, str]],
        *,
        readonly: bool = False,
    ) -> Any:
        """Run one ReAct LLM completion.

        Args:
            messages: OpenAI-style chat messages.
            readonly: Whether mutation tools are blocked.

        Returns:
            Raw LLM response object.
        """
        assert self._model_name is not None, "LLM is not initialized"
        enable_skill_tools = self.skill_runtime.visible_skill_count() > 0
        response = await self._dispatcher.call(
            model=self._model_name,
            messages=messages,
            stream=False,
            tools=react_tool_schemas(
                enable_todo_list=self._enable_todo_list,
                enable_memory=self._enable_memory,
                disable_skills=not enable_skill_tools,
                readonly=readonly,
                overrides=self._react_tool_overrides(readonly=readonly),
            ),
            tool_choice="auto",
        )
        return response

    def _react_tool_overrides(self, *, readonly: bool) -> dict[str, dict[str, Any]]:
        """Per-agent ReAct tool-schema overrides, keyed by tool name.

        Subclass hook (default: no overrides). Applied by
        :meth:`_complete_react_once` before the readonly filter, so a subclass
        can replace a tool per mode — e.g. PersonAgent swaps ``finish`` for an
        answer-only variant in ask mode and a result+memories variant in step
        mode (the latter records memories inline, removing a separate extraction
        LLM call).

        :param readonly: Whether the loop is in readonly (ask) mode.
        :returns: ``{tool_name: full_tool_schema_dict}`` (empty by default).
        """
        return {}

    def _synthesize_step_fallback_memory(
        self,
        *,
        tick: int,
        t: datetime,
        observations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Synthesize a one-item memory list when no valid finish was produced.

        Wraps :func:`_synthesize_step_fallback_episode` so ``run_react_loop``
        can populate ``self._last_finish_memories`` (consumed by
        ``step() -> memory_runtime.after_step``) even when the model never
        emitted an acceptable ``finish(memories=...)``.

        :param tick: Current simulation tick (unused, kept for symmetry).
        :param t: Current simulation time.
        :param observations: ReAct observations collected this step.
        :returns: A one-element list with the fallback episode.
        """
        del tick  # step_count is the meaningful counter here.
        return [
            _synthesize_step_fallback_episode(
                step_count=self._step_count,
                t=t,
                observations=observations,
            )
        ]

    def _synthesize_ask_fallback(self) -> str:
        """Return a last-resort ask-mode answer when no valid finish happened.

        Prefers the most recent free-text answer the model emitted (stashed in
        ``self._last_raw_answer_text`` during response parsing); falls back to
        ``"done"`` only when the model produced no usable text at all.

        :returns: The fallback answer string.
        """
        text = (self._last_raw_answer_text or "").strip()
        return text or "done"

    def _parse_react_responses(
        self, response: Any, *, readonly: bool = False
    ) -> tuple[list[ReactDecision], str]:
        """Parse OpenAI tool calls from one LLM response.

        Thin delegate over :meth:`_parse_react_turn`, kept because callers and
        tests only need the ``(decisions, error)`` pair.

        Args:
            response: Raw LLM response object.
            readonly: Whether the loop is in readonly (ask) mode.

        Returns:
            Tuple of (decisions, error).  When ``error`` is non-empty the
            caller may retry once; ``decisions`` is empty on error.
        """
        turn = self._parse_react_turn(response, readonly=readonly)
        return turn.decisions, turn.error

    def _parse_react_turn(self, response: Any, *, readonly: bool = False) -> ReactTurn:
        """Parse one LLM response into decisions plus the assistant turn to append.

        Some OpenAI-compatible endpoints never emit native ``tool_calls`` and
        instead render every tool invocation as text in ``message.content``
        (e.g. ``ask_env(instruction="...", readonly=false)``). To keep agents
        functional against such models, when there are no native tool calls we
        fall back to :meth:`_parse_text_tool_calls`, which understands the
        common textual encodings (Python-kwarg calls, ``name({...})`` JSON
        calls, Hermes/Qwen ``<tool_call>``/``<tool_input>`` blocks, bare JSON
        objects, and ``<invoke>`` XML).

        In ask mode (``readonly=True``), when the model returns a free-text
        answer with no recognizable tool call, we first try a conservative
        answer extraction (a JSON object with an ``answer``-ish key, or a bare
        JSON scalar) and synthesize a ``finish(answer=...)``; anything we
        cannot confidently match is rejected with an error so the loop feeds
        the failure back to the model and retries (the primary correction
        mechanism). The raw free text is stashed for the end-of-loop fallback.

        Besides the decisions, this returns the normalized ``assistant_message``
        the loop appends to the thread so each request extends the previous
        one. Two shapes are produced, and they must not be mixed within a turn:

        - **native** (the response carried ``tool_calls``) — the message
          carries ``tool_calls`` rebuilt from the *surviving* decisions, not
          echoed from the raw response. ``_build_react_decisions`` keeps only
          the ``finish`` decision when one is present, so echoing the raw call
          list would leave tool-call ids that nothing answers and the next
          request would be rejected.
        - **text** (no native calls) — a plain assistant text message; the
          results are appended by the loop as a ``<recent_observations>`` user
          block, exactly the shape the model already saw.

        On error with native calls, the message echoes the *raw* calls (ids and
        ``arguments`` verbatim) so the loop can answer every id with the error
        text.

        Args:
            response: Raw LLM response object.
            readonly: Whether the loop is in readonly (ask) mode.

        Returns:
            :class:`ReactTurn` with decisions, error, and the message to append
            (``None`` when the response carried nothing appendable).
        """
        if not getattr(response, "choices", None):
            return ReactTurn([], "missing response choices", None)
        message = getattr(response.choices[0], "message", None)
        if message is None:
            return ReactTurn([], "missing response message", None)

        content = str(getattr(message, "content", "") or "").strip()
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            calls: list[tuple[str, dict[str, Any]]] = []
            call_ids: list[str] = []
            for index, tool_call in enumerate(tool_calls):
                function = getattr(tool_call, "function", None)
                name = str(getattr(function, "name", "") or "").strip()
                raw_args = str(getattr(function, "arguments", "") or "{}")
                try:
                    from agentsociety2.agent.json_utils import jr_parse_from_llm

                    parsed_args = jr_parse_from_llm(raw_args)
                except Exception:
                    try:
                        parsed_args = json.loads(raw_args)
                    except Exception as exc:
                        return ReactTurn(
                            [],
                            f"invalid tool arguments for {name}: {exc}",
                            _raw_assistant_message(content, tool_calls),
                        )
                if not isinstance(parsed_args, Mapping):
                    return ReactTurn(
                        [],
                        f"tool arguments for {name} must be an object",
                        _raw_assistant_message(content, tool_calls),
                    )
                calls.append((name, dict(parsed_args)))
                # Providers normally supply an id; synthesize one when they do
                # not, so every native turn can still be answered 1:1.
                call_ids.append(str(getattr(tool_call, "id", "") or f"call_{index}"))

            decisions, error = self._build_react_decisions(
                calls, readonly=readonly, call_ids=call_ids
            )
            if error:
                return ReactTurn(
                    decisions, error, _raw_assistant_message(content, tool_calls)
                )
            return ReactTurn(
                decisions, "", _decisions_assistant_message(content, decisions)
            )

        # No native tool calls: try parsing tool invocations from the text
        # content before rejecting the response. Many OpenAI-compatible models
        # emit calls only as text.
        if not content:
            return ReactTurn([], "", None)
        assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
        if readonly:
            # Stash the raw free text so run_react_loop can fall back to it if
            # the model never produces a valid finish(answer=...) tool call.
            self._last_raw_answer_text = content
        text_calls = self._parse_text_tool_calls(content)
        if text_calls:
            decisions, error = self._build_react_decisions(
                text_calls, readonly=readonly
            )
            return ReactTurn(decisions, error, assistant_message)
        # Ask mode: attempt a conservative answer extraction from free text
        # before giving up. This recovers obvious cases (e.g. {"answer": ...});
        # everything else falls through to an error so the loop corrects the
        # model via feedback.
        if readonly:
            answer = self._extract_free_text_answer(content)
            if answer:
                decisions, error = self._build_react_decisions(
                    [("finish", {"answer": answer})], readonly=readonly
                )
                return ReactTurn(decisions, error, assistant_message)
            return ReactTurn(
                [],
                "In ask mode you must deliver your answer through the `finish` "
                "tool with a non-empty `answer` argument. Free-text answers are "
                "not accepted. Re-issue your complete answer as a single "
                "finish(answer=...) tool call.",
                assistant_message,
            )
        return ReactTurn(
            [],
            "Respond with tool calls only. Free text is not accepted.",
            assistant_message,
        )

    # Keys whose JSON value may carry a direct answer in ask-mode free text.
    _FREE_TEXT_ANSWER_KEYS = ("answer", "final", "result", "response", "value")

    def _extract_free_text_answer(self, content: str) -> str:
        """Conservatively extract an ask-mode answer from free-form text.

        Only confidently-shaped payloads are matched, so that everything
        ambiguous is left to the error-feedback path:

        - A JSON object with an ``answer``-ish key (e.g. ``{"answer": "left"}``).
        - A bare JSON scalar (string / number / boolean).

        Natural-language answers (e.g. "The answer is left") are intentionally
        NOT matched here — those are corrected via retry feedback instead.

        Args:
            content: Raw ``message.content`` text.

        Returns:
            The extracted answer string, or ``""`` when nothing confident
            matches.
        """
        from agentsociety2.agent.json_utils import jr_parse_from_llm

        text = content.strip().strip("`")
        # Strip a leading "json" code-fence marker if present.
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
        parsed: Any = None
        try:
            parsed = jr_parse_from_llm(text)
        except Exception:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
        if isinstance(parsed, Mapping):
            for key in self._FREE_TEXT_ANSWER_KEYS:
                if key in parsed:
                    raw = parsed.get(key)
                    # Skip null/None payloads — str(None) would yield the
                    # literal "None", which is never a real answer. Let these
                    # fall through to the error-feedback path instead.
                    if raw is None:
                        continue
                    value = str(raw).strip()
                    if value:
                        return value
            return ""
        if parsed is None:
            return ""
        if isinstance(parsed, (str, int, float, bool)):
            return str(parsed).strip()
        return ""

    def _build_react_decisions(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        *,
        readonly: bool = False,
        call_ids: list[str] | None = None,
    ) -> tuple[list[ReactDecision], str]:
        """Build ReAct decisions from a list of (name, args) tool calls.

        Shared by the native-tool-call path and the text-parsing fallback so
        the ``finish`` semantics stay identical: ``finish`` wins and at most
        one is returned. The ``finish`` payload is validated per mode and a
        rejected ``finish`` returns an error so the caller retries:

        - ask / readonly mode: ``finish`` must carry a non-empty ``answer``;
        - step mode: ``finish`` must carry a ``memories`` list with at least
          one item (an empty list is invalid — memory generation happens here).

        Args:
            calls: Ordered ``(tool_name, args)`` pairs.
            readonly: Whether the loop is in readonly (ask) mode.
            call_ids: Optional provider tool-call ids, positional with
                ``calls``. Omitted by the text-parsing fallback, which has no
                ids; the resulting decisions then carry ``call_id=""``.

        Returns:
            Tuple of (decisions, error).
        """
        decisions: list[ReactDecision] = []
        for index, (name, args) in enumerate(calls):
            call_id = call_ids[index] if call_ids and index < len(call_ids) else ""
            if name == "finish":
                if readonly:
                    answer = str(args.get("answer") or "").strip()
                    if not answer:
                        return (
                            [],
                            (
                                "In ask mode `finish` requires a non-empty `answer` "
                                "with your complete answer to the question. Re-issue "
                                "your answer as a single finish(answer=...) tool call."
                            ),
                        )
                    decisions.append(ReactDecision("", name, args, answer, call_id))
                else:
                    memories = args.get("memories")
                    if not isinstance(memories, list) or not memories:
                        return (
                            [],
                            (
                                "`finish` requires `memories` with at least one "
                                "memory item from this step (an empty list is not "
                                "accepted). Record at least one episode (key "
                                "decision/event/observation/intention) and call "
                                "finish again."
                            ),
                        )
                    decisions.append(ReactDecision("", name, args, "", call_id))
            else:
                decisions.append(ReactDecision("", name, args, "", call_id))
        finish_decisions = [d for d in decisions if d.action == "finish"]
        if finish_decisions:
            return finish_decisions[:1], ""
        return decisions, ""

    # Keys that may carry the tool name across textual encodings.
    _TEXT_TOOL_NAME_KEYS = ("name", "function", "tool", "tool_name", "action")
    # Keys that may carry the tool arguments across textual encodings.
    _TEXT_TOOL_ARG_KEYS = (
        "arguments",
        "parameters",
        "args",
        "params",
        "tool_input",
        "input",
        "inputs",
    )

    def _parse_text_tool_calls(self, content: str) -> list[tuple[str, dict[str, Any]]]:
        """Parse tool calls embedded in free-form LLM text content.

        Supports the encodings emitted by OpenAI-compatible models that do not
        return native ``tool_calls``:

        - Python-kwarg style: ``ask_env(instruction="...", readonly=false)``
          (the most common shape from these models).
        - JSON function call: ``finish({"answer": "..."})`` or ``name({...})``.
        - Hermes / Qwen blocks: ``<tool_call>name</tool_call><tool_input>{...}
          </tool_input>`` (and the JSON-in-``<tool_call>`` variant).
        - Bare JSON object: ``{"name"/"tool": ..., "arguments"/...: {...}}``.
        - XML invoke: ``<invoke name="...">...</invoke>`` (with a
          ``<parameters>`` JSON body).

        Returns an empty list when no recognizable tool call is found (the
        caller then treats the content as free text). Parsing is best-effort:
        malformed fragments are skipped rather than raised.

        Args:
            content: Raw ``message.content`` text.

        Returns:
            Ordered ``(tool_name, args)`` pairs (possibly empty).
        """
        results: list[tuple[str, dict[str, Any]]] = []
        # Guard against pathological input dominating the regex passes.
        if len(content) > 200_000:
            content = content[:200_000]

        def _clean_name(raw: str) -> str:
            # Strip XML tags, quotes, backticks and surrounding whitespace.
            cleaned = re.sub(r"<[^>]+>", "", raw)
            cleaned = cleaned.strip().strip("`\"' \t\r\n")
            # Take the leading identifier token (drop trailing junk like "()").
            m = re.match(r"^([A-Za-z_][\w\-\.]*)", cleaned)
            return m.group(1) if m else cleaned

        def _coerce_args(value: Any) -> dict[str, Any]:
            if isinstance(value, Mapping):
                return dict(value)
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return {}
                try:
                    from agentsociety2.agent.json_utils import jr_parse_from_llm

                    parsed = jr_parse_from_llm(value)
                except Exception:
                    try:
                        parsed = json.loads(value)
                    except Exception:
                        return {}
                return dict(parsed) if isinstance(parsed, Mapping) else {}
            return {}

        def _record(name: str, args: Any) -> None:
            name = _clean_name(name)
            if name:
                results.append((name, _coerce_args(args)))

        def _json_loads_lenient(text: str) -> Any:
            text = text.strip()
            if not text:
                return None
            try:
                from agentsociety2.agent.json_utils import jr_parse_from_llm

                return jr_parse_from_llm(text)
            except Exception:
                try:
                    return json.loads(text)
                except Exception:
                    return None

        def _extract_name_args(obj: Any) -> tuple[str, Any]:
            """Pull (name, args) from a JSON object using the known key sets."""
            if not isinstance(obj, Mapping):
                return "", {}
            name = ""
            for key in self._TEXT_TOOL_NAME_KEYS:
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    name = val.strip()
                    break
            args: Any = {}
            for key in self._TEXT_TOOL_ARG_KEYS:
                if key in obj:
                    args = obj[key]
                    break
            return name, args

        def _parse_call_body(body: str) -> dict[str, Any]:
            """Parse a ``NAME(...)`` argument body.

            Handles two shapes:
            - Python-kwarg style: ``instruction="...", readonly=false, n=3``;
            - JSON object: ``{"answer": "..."}`` (possibly with stray code
              fences / trailing commas).
            """
            body = body.strip()
            if not body:
                return {}
            # JSON object form first.
            if body.startswith("{"):
                parsed = _json_loads_lenient(body)
                return dict(parsed) if isinstance(parsed, Mapping) else {}
            # Python-kwarg form: key=value pairs separated by commas (values may
            # contain commas inside quotes, so we walk char-by-char).
            kwargs: dict[str, Any] = {}
            for key, raw_val in _split_kwargs(body):
                kwargs[key] = _parse_python_literal(raw_val)
            return kwargs

        def _split_kwargs(body: str) -> list[tuple[str, str]]:
            """Split ``k=v, k2=v2`` honoring quotes/braces (no eval)."""
            pairs: list[tuple[str, str]] = []
            i, n = 0, len(body)
            while i < n:
                # Skip whitespace and stray commas.
                while i < n and body[i] in " \t\r\n,":
                    i += 1
                # Read key.
                km = re.match(r"([A-Za-z_][\w\-\.]*)\s*=\s*", body[i:])
                if not km:
                    break
                key = km.group(1)
                i += km.end()
                # Read value up to the next top-level comma.
                start = i
                quote: str | None = None
                bracket = 0
                while i < n:
                    ch = body[i]
                    if quote:
                        if ch == "\\":
                            i += 2
                            continue
                        if ch == quote:
                            quote = None
                    elif ch in "\"'":
                        quote = ch
                    elif ch in "[{(":
                        bracket += 1
                    elif ch in "]})":
                        bracket -= 1
                    elif ch == "," and bracket <= 0:
                        break
                    i += 1
                pairs.append((key, body[start:i].strip()))
            return pairs

        def _parse_python_literal(raw: str) -> Any:
            """Coerce a Python-kwarg value token to a JSON-friendly value."""
            raw = raw.strip()
            if not raw:
                return ""
            if raw.lower() in ("true", "false"):
                return raw.lower() == "true"
            if raw.lower() in ("none", "null"):
                return None
            if (raw[0] in "\"'" and raw[-1] == raw[0]) or (
                len(raw) >= 6 and raw[:3] in ('"""', "'''") and raw[-3:] == raw[:3]
            ):
                # Quoted string: use ast.literal_eval for escape fidelity if
                # available, else strip quotes.
                try:
                    import ast

                    return ast.literal_eval(raw)
                except Exception:
                    return raw[1:-1]
            # JSON-ish (dict/list/number/string) — try strict then lenient.
            parsed = _json_loads_lenient(raw)
            if parsed is not None:
                return parsed
            return raw

        # 1. <tool_call>NAME</tool_call><tool_input>{...}</tool_input>  (Hermes/Qwen)
        for m in re.finditer(
            r"<tool_call>\s*(.*?)\s*</tool_call>.*?"
            r"<tool_input>\s*(.*?)\s*</tool_input>",
            content,
            re.DOTALL,
        ):
            _record(m.group(1), m.group(2))

        # 2. <tool_call>{...json with name + arguments...}</tool_call> (Qwen JSON variant)
        if not results:
            for m in re.finditer(
                r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, re.DOTALL
            ):
                obj = _json_loads_lenient(m.group(1))
                if obj:
                    name, args = _extract_name_args(obj)
                    if name:
                        _record(name, args)

        # 3. Function-call style: NAME(...) — covers both kwarg and JSON arg forms.
        #    Matches the outermost parenthesized group (non-greedy, balanced-ish via
        #    [^()]* fallback for simple bodies; complex nested JSON is handled by
        #    greedy matching up to the last ')' on the same logical call).
        if not results:
            for m in re.finditer(
                r"([A-Za-z_][\w\-\.]*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
                content,
            ):
                body = m.group(2).strip()
                _record(m.group(1), _parse_call_body(body))

        # 4. Bare JSON object: {"name"/"tool": ..., "arguments"/...: {...}}
        if not results:
            for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content):
                obj = _json_loads_lenient(m.group(0))
                if obj:
                    name, args = _extract_name_args(obj)
                    if name:
                        _record(name, args)

        # 5. XML invoke: <invoke name="..."> ... <parameters>{...}</parameters> ...
        if not results:
            for m in re.finditer(
                r'<invoke\s+name="([^"]+)">.*?</invoke>',
                content,
                re.DOTALL,
            ):
                inner = m.group(0)
                pm = re.search(
                    r"<parameters>\s*(.*?)\s*</parameters>", inner, re.DOTALL
                )
                _record(m.group(1), pm.group(1) if pm else {})

        return results

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
        """Build ReAct prompt messages (subclass prompt hook).

        The base implementation raises :class:`NotImplementedError`.
        Subclasses (e.g. PersonAgent) override this to assemble their
        agent-specific prompt and return OpenAI-style chat messages.

        Args:
            tick: Current simulation tick.
            t: Current simulation time.
            observations: Recent observation list.
            question: Optional external question (ask mode).
            readonly: Whether mutation tools are blocked.
            skill_hooks: Optional pre_step hook outputs for the prompt.

        Returns:
            OpenAI-style chat messages.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError(
            "Subclasses must implement build_react_messages to use the "
            "generic ReAct loop."
        )

    def build_context_refresh_message(
        self,
        *,
        actions: list[str],
        tick: int,
        t: datetime,
    ) -> dict[str, Any] | None:
        """Message to append when a tool invalidated a block of the thread head.

        The thread is built once per loop invocation, so per-agent blocks that
        live in the first user message (``<todo_context>``, ``<skill_content>``)
        no longer re-render every turn. Re-rendering them would rebuild the
        prompt and throw away the cached prefix; appending a refreshed block
        keeps the prefix intact. Subclass hook (default: no refresh).

        Only actions that **succeeded** are passed in, and at most one message
        is appended per turn even when several of them fired.

        Args:
            actions: Names of the tool actions that succeeded this turn.
            tick: Current simulation tick.
            t: Current simulation time.

        Returns:
            A chat message to append, or ``None`` when nothing needs refreshing.
        """
        return None

    def _append_context_refresh(
        self,
        messages: list[dict[str, Any]],
        decisions: list[ReactDecision],
        entries: list[dict[str, Any]],
        *,
        tick: int,
        t: datetime,
    ) -> None:
        """Append the subclass's context-refresh message, if it returns one.

        Must run **after** the tool replies: a ``role: "tool"`` reply has to
        follow its assistant turn before any later message.

        Args:
            messages: Chat messages (mutated in place).
            decisions: Decisions executed this turn.
            entries: Their observation entries, positionally aligned.
            tick: Current simulation tick.
            t: Current simulation time.
        """
        actions = [
            decision.action
            for decision, entry in zip(decisions, entries)
            if entry.get("ok")
        ]
        if not actions:
            return
        refresh = self.build_context_refresh_message(actions=actions, tick=tick, t=t)
        if refresh is not None:
            messages.append(refresh)

    # ==================================================================
    # TODO handling (generic)
    # ==================================================================

    def _todo_store(self) -> TodoStateStore:
        """Return the TODO store for this agent workspace.

        Returns:
            TodoStateStore bound to the agent workspace root.
        """
        return TodoStateStore(self.workspace_root_path())

    def _ensure_todo_state(self) -> None:
        """Initialize TODO state when the feature gate is enabled."""
        if self._enable_todo_list:
            self._todo_store().ensure()

    def _build_todo_context(self, t: datetime) -> dict[str, Any]:
        """Build compact prompt context for TODO state.

        Args:
            t: Current simulation time.

        Returns:
            TODO prompt-context dict (empty when the feature is disabled).
        """
        if not self._enable_todo_list:
            return {}
        return self._todo_store().build_prompt_context(t)

    def _current_simulation_time(self) -> datetime | None:
        """Return the best known simulation time for tool normalization.

        Returns:
            Current simulation time, or ``None`` when unavailable.
        """
        if self._current_time is not None:
            return self._current_time
        if self._workspace_fs is None:
            return None
        try:
            data = json.loads(self._workspace.read_text(AGENT_JSON_PATH))
        except Exception:
            return None
        current_time = str(data.get("current_time") or "").strip()
        if not current_time:
            return None
        try:
            return datetime.fromisoformat(current_time)
        except ValueError:
            return None

    def _normalize_todo_due_value(self, value: Any) -> Any:
        """Normalize common TODO due shorthand before strict store validation.

        Args:
            value: Raw ``due`` value from the model.

        Returns:
            Normalized value (ISO string when a ``HH:MM`` shorthand was
            resolved against the current simulation time; otherwise the
            original value).
        """
        if value in (None, ""):
            return value
        text = str(value).strip()
        match = _SHORT_CLOCK_RE.match(text)
        if not match:
            return value
        current = self._current_simulation_time()
        if current is None:
            return value
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        return current.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ).isoformat()

    def _normalize_todo_tool_args(
        self,
        action: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize TODO tool arguments at the agent boundary.

        Args:
            action: TODO tool action name.
            args: Tool argument dictionary.

        Returns:
            New argument dict with normalized ``due`` values.
        """
        normalized = dict(args)
        if action == "todo_add" and "due" in normalized:
            normalized["due"] = self._normalize_todo_due_value(normalized["due"])
        if action == "todo_update" and isinstance(normalized.get("patch"), Mapping):
            patch = dict(normalized["patch"])
            if "due" in patch:
                patch["due"] = self._normalize_todo_due_value(patch["due"])
            normalized["patch"] = patch
        if action == "todo_defer" and "new_due" in normalized:
            normalized["new_due"] = self._normalize_todo_due_value(
                normalized["new_due"]
            )
        return normalized

    def dispatch_todo_tool(
        self,
        action: str,
        args: dict[str, Any],
    ) -> ReactToolResult:
        """Dispatch built-in TODO tools.

        Args:
            action: TODO tool action name.
            args: Tool argument dictionary.

        Returns:
            Tool execution result.
        """
        if not self._enable_todo_list:
            return ReactToolResult(
                False,
                "todo_list feature is disabled",
                {"error": "todo_list feature is disabled"},
            )
        args = self._normalize_todo_tool_args(action, args)
        store = self._todo_store()
        if action == "todo_list":
            limit_raw = args.get("limit")
            limit = int(limit_raw) if limit_raw is not None else None
            data = store.list(
                status=str(args.get("status") or "").strip() or None,
                limit=limit,
            )
            return ReactToolResult(
                True, json.dumps(data, ensure_ascii=False, indent=2, default=str), data
            )
        if action == "todo_add":
            data = store.add(dict(args))
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_update":
            patch = args.get("patch")
            data = store.update(
                str(args.get("todo_id") or ""),
                dict(patch) if isinstance(patch, Mapping) else {},
            )
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_start":
            data = store.start(str(args.get("todo_id") or ""))
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_complete":
            data = store.complete(
                str(args.get("todo_id") or ""),
                outcome=str(args.get("outcome") or ""),
            )
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_defer":
            data = store.defer(
                str(args.get("todo_id") or ""),
                new_due=str(args["new_due"])
                if args.get("new_due") not in (None, "")
                else None,
                reason=str(args.get("reason") or ""),
            )
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_clear_completed":
            keep_raw = args.get("keep_recent")
            keep_recent = int(keep_raw) if keep_raw is not None else 2
            data = store.clear_completed(keep_recent=keep_recent)
            summary = {
                "archived": data["archived"],
                "kept_terminal": data["kept_terminal"],
                "remaining": data["remaining"],
            }
            return ReactToolResult(
                True,
                json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                data,
            )
        return ReactToolResult(False, f"unknown action: {action}", {"action": action})
