"""Shared-service handle container :class:`ServiceProxy`.

Agents do not own runtime objects (LLM dispatchers, env routers, trace/replay
writers). Instead these shared services are injected as serializable handles via
a single :class:`ServiceProxy`, received in :meth:`from_workspace`. The proxy
holds only handles/data (no locks, connections, or threads), so it crosses Ray
Task boundaries cleanly.

The proxy, protocol, and factory live here; the concrete proxy classes live in
their runtime modules (:class:`~agentsociety2.trace.TraceProxy`,
:class:`~agentsociety2.storage.replay_proxy.ReplayProxy`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ═══════════════════════════════════════════════════════════
# Service interface protocols (agents depend on these, not concretes)
# ═══════════════════════════════════════════════════════════


@runtime_checkable
class EnvLike(Protocol):
    """Environment router protocol (in-process ``RouterBase`` or remote ``EnvRouterProxy``)."""

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> tuple[dict, str]:
        raise NotImplementedError

    def set_current_time(self, t: Any) -> None:
        raise NotImplementedError

    async def step(self, tick: int, t: Any) -> None:
        raise NotImplementedError

    async def get_world_description(self) -> str:
        raise NotImplementedError


@runtime_checkable
class LLMClientLike(Protocol):
    """LLM client protocol: a single completion request."""

    async def call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool = False,
        thinking: str = "inherit",
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError


@runtime_checkable
class TraceLike(Protocol):
    """Trace writer protocol."""

    def append_record(self, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        raise NotImplementedError


@runtime_checkable
class ReplayLike(Protocol):
    """Replay writer protocol."""

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════
# Containers
# ═══════════════════════════════════════════════════════════


@dataclass
class LLMClients:
    """LLM client set organized by role.

    Agents use ``default``; the env router uses ``coder`` / ``default``.
    """

    coder: Any
    default: Any
    embedding: Any | None = None


@dataclass
class ServiceProxy:
    """One-stop container for all shared-service handles.

    ``from_workspace(path, service_proxy)`` receives only this object. All
    fields are serializable handles (LLM clients, env router, optional trace
    and replay proxies), so the container travels across Ray Task boundaries.

    The ``llm`` clients carry only connection params (no live Router/semaphore);
    each Ray Task / actor that receives a deserialized copy rebuilds its own
    per-loop runtime on first ``call()``. :meth:`take_token_stats` drains the
    per-task token-usage delta so a Ray Task can carry it back in its return
    value (no actor, no module-global aggregate).
    """

    env: Any  # EnvLike
    llm: LLMClients
    trace: Any  # TraceLike | None
    replay: Any  # ReplayLike | None
    run_dir: Path | None = None

    def take_token_stats(self) -> dict[str, dict[str, int]]:
        """Drain + return this proxy's LLM clients' token usage (a delta).

        Called at the end of a Ray Task so it can fold the delta into its
        return value. Each ``LLMClient`` clears its own stats, so a reused
        worker process never double-counts across tasks.
        """
        from agentsociety2.config.llm_dispatcher import merge_token_stats

        deltas: list[dict] = []
        for client in (self.llm.default, self.llm.coder, self.llm.embedding):
            if client is not None and hasattr(client, "take_token_stats"):
                deltas.append(client.take_token_stats())
        return merge_token_stats(*deltas) if deltas else {}


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def _role_configured(role: str) -> bool:
    """Whether a role is configured (avoids forcing a dispatcher for unconfigured embedding)."""
    try:
        from agentsociety2.config import get_model_name

        return bool(get_model_name(role))
    except Exception:
        return False


def _client_for_role(role: str) -> Any:
    """Build a serializable :class:`LLMClient` carrying one role's connection params.

    Thin delegation to :func:`agentsociety2.config.llm_dispatcher.build_client_for_role`.
    This used to duplicate that function's body, which meant every new client
    field (e.g. the thinking settings) had to be added in two places or the
    driver path would silently miss it.
    """
    from agentsociety2.config.llm_dispatcher import build_client_for_role

    return build_client_for_role(role)


def build_service_proxy(
    env: Any,
    *,
    run_dir: Path | None = None,
    trace: bool | Any = True,
    trace_dir: Path | str | None = None,
    replay: bool | Any = True,
    replay_db_path: Path | str | None = None,
    replay_sample_rate: float = 1.0,
) -> ServiceProxy:
    """Compose a :class:`ServiceProxy` from local LLM clients and optional actors.

    Builds serializable LLM clients whose Routers are created per process /
    event loop on first use, plus optional :class:`~agentsociety2.trace.TraceProxy`
    and :class:`~agentsociety2.storage.replay_proxy.ReplayProxy` pointing at
    append-only replay/trace directories. All fields are serializable handles, so the resulting
    proxy can be passed into agent Ray tasks / ``from_workspace``.

    Args:
        env: An in-process router (``RouterBase``) or an ``EnvRouterProxy`` —
            both satisfy :class:`EnvLike`. This is the only variation; the rest
            of the wiring is identical.
        run_dir: Run directory (also the default base for trace / replay paths).
        trace: Trace wiring. Accepts:

            * a pre-built :class:`~agentsociety2.trace.TraceProxy`
              (used as-is) — lets the driver share one trace dir between the
              agents' ``ServiceProxy`` and the env router actor;
            * ``True`` — build a :class:`~agentsociety2.trace.TraceProxy`
              pointing at ``trace_dir`` (or ``run_dir / "trace"``);
            * ``False`` / ``None`` — ``trace`` is ``None`` on the proxy (no-op).

            Trace is distributed and lock-free: the proxy only carries an output
            dir, and each consumer builds its own append-only
            :class:`~agentsociety2.trace.ShardedAppendSink`.
        trace_dir: Override for the trace base directory (defaults to
            ``run_dir / "trace"``). Ignored when ``trace`` is a
            :class:`~agentsociety2.trace.TraceProxy`.
        replay: Replay wiring. Accepts:

            * a pre-built :class:`~agentsociety2.storage.replay_proxy.ReplayProxy`
              (used as-is) — lets the driver hand the same replay directory to
              the agents' ``ServiceProxy`` and the env router actor;
            * ``True`` — create a new ``ReplayProxy`` here;
            * ``False`` / ``None`` — a disabled ``ReplayProxy`` (no-op).

        replay_db_path: Legacy parameter name. It now overrides the replay
            output directory (defaults to ``run_dir / "replay"``). Ignored when
            ``replay`` is a :class:`~agentsociety2.storage.replay_proxy.ReplayProxy`.
        replay_sample_rate: Sampling rate for replay writes (1.0 = all).
            Ignored when ``replay`` is a
            :class:`~agentsociety2.storage.replay_proxy.ReplayProxy`.

    Returns:
        A fully wired :class:`ServiceProxy`.
    """
    from agentsociety2.storage.replay_proxy import ReplayProxy
    from agentsociety2.trace import TraceProxy

    llm = LLMClients(
        coder=_client_for_role("coder"),
        default=_client_for_role("default"),
        embedding=_client_for_role("embedding")
        if _role_configured("embedding")
        else None,
    )

    # Trace wiring: a pre-built TraceProxy wins; otherwise build one. Trace is
    # distributed & lock-free now — TraceProxy just carries the output dir; each
    # consumer builds its own local ShardedAppendSink. No central actor.
    trace_proxy: TraceProxy | None
    if isinstance(trace, TraceProxy):
        trace_proxy = trace
    elif trace:
        base = (
            Path(trace_dir)
            if trace_dir is not None
            else ((Path(run_dir) / "trace") if run_dir is not None else Path("./trace"))
        )
        trace_proxy = TraceProxy(trace_dir=str(base))
    else:
        trace_proxy = None

    # Replay wiring: a pre-built ReplayProxy wins; otherwise build one. Replay
    # is distributed & lock-free now — ReplayProxy just carries the output dir;
    # each consumer builds its own local ReplaySink. No central actor.
    replay_proxy: ReplayProxy | None
    if isinstance(replay, ReplayProxy):
        replay_proxy = replay
    elif replay:
        replay_dir = (
            Path(replay_db_path)
            if replay_db_path is not None
            else ((Path(run_dir) / "replay") if run_dir is not None else None)
        )
        if replay_dir is not None:
            replay_proxy = ReplayProxy(replay_dir=str(replay_dir), enabled=True)
        else:
            replay_proxy = None
    else:
        replay_proxy = None

    return ServiceProxy(
        env=env,
        llm=llm,
        trace=trace_proxy,
        replay=replay_proxy,
        run_dir=run_dir,
    )


__all__ = [
    "EnvLike",
    "LLMClientLike",
    "LLMClients",
    "ReplayLike",
    "ServiceProxy",
    "TraceLike",
    "build_service_proxy",
]
