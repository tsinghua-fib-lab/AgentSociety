"""Per-loop LLM dispatcher (no module-global cache).

An :class:`LLMClient` carries the raw connection params (model_name, base_url,
api_key) so it can travel across Ray task boundaries. Each consumer — each agent
Ray task, the env-router actor, the driver — builds its OWN litellm ``Router`` +
:class:`AdaptiveSemaphore` (AIMD) fresh, in its OWN event loop, on first
``call()``. There is no module-global Router/semaphore cache: the previous
process-global cache bound asyncio primitives to the first event loop that
touched them and broke under Ray's ``asyncio.run``-per-task model ("bound to a
different event loop"). Building per-loop removes that class of bug entirely.

Token usage is tracked per :class:`LLMClient` instance and drained back to the
driver via Ray Task return values (:func:`merge_token_stats` is a pure helper —
no global aggregate, no actor).
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from litellm import AllMessageValues
from litellm.exceptions import ContextWindowExceededError, RateLimitError
from litellm.types.router import RouterRateLimitError
from litellm.types.utils import ModelResponse

from agentsociety2.config.config import Config
from agentsociety2.logger import get_logger

__all__ = [
    "AdaptiveSemaphore",
    "LLMClient",
    "LLMDispatchError",
    "ThinkingSettings",
    "cache_hit_rate",
    "extract_cached_tokens",
    "init_dispatchers",
    "is_rate_limit_like_error",
    "merge_token_stats",
    "rate_limit_retry_seconds",
    "shutdown_dispatchers",
]

logger = get_logger()

# Per-request timeout (seconds) passed to litellm acompletion. The API
# occasionally accepts a connection but never responds; without a timeout that
# hangs the call (and the agent's react turn, and the tick) forever. This is a
# hard requirement, not a diagnostic — removing it reintroduces the stall at the
# per-process level (verified). litellm raises on expiry; the dispatcher retries.
_LLM_REQUEST_TIMEOUT = float(os.getenv("AGENTSOCIETY_LLM_REQUEST_TIMEOUT", "60"))

# Disable Ray's uv-runtime-env packaging (see comment below in init_dispatchers).
os.environ.setdefault("RAY_ENABLE_UV_RUN_RUNTIME_ENV", "0")

# 跨进程共享配额门(2026-10-19,评审 P0):同机多实验并行时,各进程的
# AIMD 只看自己窗口内的 429/延迟,会互相踩踏(T2 生产实锤:100 agent
# 并发把网关打进持续 429,AIMD 退到 1 仍撞)。网关不暴露配额头,故
# 采用保守可调上限 + 跨进程文件锁轮询:env AGENTSOCIETY_SHARED_LLM_QUOTA
# 设为正整数即启用(表示本机所有进程合计的在途请求数上限);未设置=
# 关闭(默认,单实验行为与现状一致)。锁走 flock,轮询在 asyncio 循环
# 内小步进行；归还计数在线程中等待锁，避免阻塞事件循环。
_SHARED_QUOTA_LIMIT = int(os.getenv("AGENTSOCIETY_SHARED_LLM_QUOTA", "0") or 0)
_SHARED_QUOTA_FILE = os.getenv(
    "AGENTSOCIETY_SHARED_QUOTA_FILE",
    os.path.join(tempfile.gettempdir(), "agentsociety_llm_quota.lock"),
)
_SHARED_QUOTA_POLL = float(os.getenv("AGENTSOCIETY_SHARED_QUOTA_POLL", "0.2"))
_SHARED_QUOTA_WAIT = float(os.getenv("AGENTSOCIETY_SHARED_QUOTA_WAIT", "300"))


async def _acquire_shared_quota() -> None:
    """获取一份跨进程共享配额额度(轮询 flock)。

    :returns: 无返回值;配额未启用时立即返回(零开销路径)。
    :raises TimeoutError: 超过 ``AGENTSOCIETY_SHARED_QUOTA_WAIT``
        秒仍未获得额度时抛出,交由 call() 既有错误路径处理。
    """
    if _SHARED_QUOTA_LIMIT <= 0:
        return
    import fcntl

    deadline = time.monotonic() + _SHARED_QUOTA_WAIT
    while True:
        acquired = False
        fd = os.open(_SHARED_QUOTA_FILE, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # LOCK_NB 下"锁被他人持有"是预期信号而非异常:本轮
                # 抢锁失败,sleep 后重试(2026-10-19 修复——此前该
                # 异常直接炸穿,并发竞争下 ~30% 复现率使配额门不可用)。
                pass
            else:
                try:
                    raw = os.read(fd, 64).decode("utf-8", "ignore") or "0"
                    inflight = int(raw.strip() or 0)
                except ValueError:
                    inflight = 0
                if inflight < _SHARED_QUOTA_LIMIT:
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.ftruncate(fd, 0)
                    os.write(fd, str(inflight + 1).encode("ascii"))
                    acquired = True
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        if acquired:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"shared LLM quota wait exceeded {_SHARED_QUOTA_WAIT}s")
        await asyncio.sleep(_SHARED_QUOTA_POLL)


def _release_shared_quota() -> None:
    """等待计数锁并归还一份跨进程共享配额额度。

    异步调用方在线程中执行，避免锁竞争阻塞事件循环。

    :returns: 无返回值;配额未启用时零开销。
    """
    if _SHARED_QUOTA_LIMIT <= 0:
        return
    import fcntl

    fd = os.open(_SHARED_QUOTA_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            raw = os.read(fd, 64).decode("utf-8", "ignore") or "0"
            inflight = int(raw.strip() or 0)
        except ValueError:
            inflight = 1
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(max(inflight - 1, 0)).encode("ascii"))
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ═══════════════════════════════════════════════════════════
# Errors / helpers
# ═══════════════════════════════════════════════════════════


class LLMDispatchError(RuntimeError):
    """LLM request failed after retries."""

    def __init__(self, message: str, *, rate_limit_like: bool = False) -> None:
        super().__init__(message)
        self.rate_limit_like = rate_limit_like


def is_rate_limit_like_error(error: Exception) -> bool:
    """Whether an exception looks like a rate-limit (429)."""
    if isinstance(error, RateLimitError):
        return True
    if RouterRateLimitError is not None and isinstance(error, RouterRateLimitError):
        return True
    err_type_name = type(error).__name__
    err_text = str(error).lower()
    return (
        err_type_name == "RouterRateLimitError"
        or "routerratelimiterror" in err_text
        or "no deployments available for selected model" in err_text
        or "try again in" in err_text
    )


def rate_limit_retry_seconds(error: Exception, fallback: float) -> float:
    """Extract provider-requested wait from a rate-limit error, else ``fallback``.

    DeepSeek / OpenAI-compatible gateways often say ``Try again in N seconds``.
    Ignoring that and sleeping 1–4s burns retries into guaranteed failure.
    """
    match = re.search(r"[Tt]ry again in (\d+(?:\.\d+)?)\s*seconds?", str(error))
    if match:
        return float(match.group(1))
    return fallback


def is_context_limit_error(error: Exception) -> bool:
    """Whether the request can never succeed at its current size.

    Context-window-exceeded errors are deterministic: retrying re-sends the
    same oversized prompt (the most expensive request in the run) for a
    guaranteed-identical failure. ``call`` fails fast on these instead of
    burning ``max_retries`` extra attempts.
    """
    if isinstance(error, ContextWindowExceededError):
        return True
    # Some gateways wrap the upstream 400 generically; match common provider
    # phrasings so the fail-fast still applies behind proxies.
    err_text = str(error).lower()
    return any(
        marker in err_text
        for marker in (
            "context_length_exceeded",
            "context length",
            "context window",
            "maximum context",
            "input length and",
            "prompt is too long",
        )
    )


# ═══════════════════════════════════════════════════════════
# Adaptive concurrency (AIMD) — per-process flow control
# ═══════════════════════════════════════════════════════════


class _AdjustableSemaphore:
    """Capacity-adjustable asyncio semaphore (Condition-based)."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._available = capacity
        self._cond = asyncio.Condition()

    @property
    def capacity(self) -> int:
        return self._capacity

    async def acquire(self) -> None:
        async with self._cond:
            while self._available <= 0:
                await self._cond.wait()
            self._available -= 1

    async def release(self) -> None:
        async with self._cond:
            self._available += 1
            self._cond.notify(1)

    async def set_capacity(self, new_capacity: int) -> int:
        new_capacity = max(new_capacity, 0)
        async with self._cond:
            old = self._capacity
            delta = new_capacity - old
            self._capacity = new_capacity
            if delta > 0:
                self._available += delta
                self._cond.notify(delta)
            elif delta < 0:
                self._available = max(0, self._available + delta)
            return old


class AdaptiveSemaphore:
    """TCP-style AIMD adaptive concurrency semaphore (one per process).

    ``max_limit=None`` means unbounded — AIMD probes freely (additive
    increase / multiplicative decrease) with no artificial cap, relying on
    latency slowdown and rate-limit errors to back off. Use this for LLM
    I/O where the remote API is the real ceiling. Pass a finite
    ``max_limit`` for CPU/local work that must not overrun a single process.
    """

    def __init__(
        self,
        initial: int = 10,
        min_limit: int = 1,
        max_limit: int | None = None,
        decrease_factor: float = 0.7,
        overload_threshold: float = 0.1,
        min_round_size: int = 20,
        round_sample_cap: int = 64,
        latency_degrade_factor: float = float("inf"),
        slow_latency_ms: float | None = None,
        baseline_window: int = 48,
        baseline_percentile: float = 0.25,
        warmup_samples: int = 16,
    ) -> None:
        self._sem = _AdjustableSemaphore(initial)
        self._limit = initial
        self._min = min_limit
        self._max = max_limit
        self._decrease_factor = decrease_factor
        self._overload_threshold = overload_threshold
        self._min_round_size = min_round_size
        self._round_sample_cap = max(1, round_sample_cap)
        self._latency_degrade_factor = latency_degrade_factor
        self._slow_latency_ms = slow_latency_ms

        self._step = 1
        self._round_finished = 0
        self._round_overloaded = 0
        self._round_slow = 0
        self._adjust_lock = asyncio.Lock()
        self._cooldown_remaining = 0

        self._latency_window: deque[float] = deque(maxlen=max(8, baseline_window))
        self._baseline_percentile = max(0.0, min(1.0, baseline_percentile))
        self._warmup_samples = max(1, warmup_samples)
        self._in_flight = 0

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def baseline_latency_ms(self) -> float | None:
        if len(self._latency_window) < self._warmup_samples:
            return None
        ordered = sorted(self._latency_window)
        idx = min(len(ordered) - 1, int(len(ordered) * self._baseline_percentile))
        return ordered[idx]

    async def acquire(self) -> None:
        await self._sem.acquire()
        self._in_flight += 1

    async def release(self, overloaded: bool = False) -> None:
        self._in_flight = max(0, self._in_flight - 1)
        async with self._adjust_lock:
            self._round_finished += 1
            if overloaded:
                self._round_overloaded += 1
            round_size = max(
                self._min_round_size, min(self._limit, self._round_sample_cap)
            )
            should_adjust = self._round_finished >= round_size

        await self._sem.release()

        if should_adjust:
            await self._adjust()

    def record_latency(self, latency_ms: float, is_error: bool = False) -> None:
        if is_error:
            return
        self._latency_window.append(latency_ms)
        baseline = self.baseline_latency_ms
        slow = False
        if (
            baseline is not None
            and self._latency_degrade_factor != float("inf")
            and latency_ms > baseline * self._latency_degrade_factor
        ):
            slow = True
        if self._slow_latency_ms is not None and latency_ms > self._slow_latency_ms:
            slow = True
        if slow:
            self._round_slow += 1

    async def _adjust(self) -> None:
        async with self._adjust_lock:
            finished = self._round_finished
            overloaded = self._round_overloaded
            slow = self._round_slow
            self._round_finished = 0
            self._round_overloaded = 0
            self._round_slow = 0

            if finished == 0:
                return

            combined = (overloaded + slow) / finished
            old_limit = self._limit

            if combined > self._overload_threshold:
                new_limit = max(self._min, int(self._limit * self._decrease_factor))
                self._step = 1
                self._cooldown_remaining = 3
                logger.info(
                    "[AdaptiveSem] DECREASE: 429=%d/%d slow=%d/%d -> %d -> %d "
                    "(cooldown=3)",
                    overloaded,
                    finished,
                    slow,
                    finished,
                    old_limit,
                    new_limit,
                )
            else:
                if self._cooldown_remaining > 0:
                    self._cooldown_remaining -= 1
                    logger.debug(
                        "[AdaptiveSem] COOLDOWN: left=%d, stays %d",
                        self._cooldown_remaining,
                        old_limit,
                    )
                    return

                bumped = self._limit + self._step
                new_limit = bumped if self._max is None else min(self._max, bumped)
                next_step = min(self._step * 2, 16)
                logger.info(
                    "[AdaptiveSem] INCREASE: %d -> %d (next_step=%d)",
                    old_limit,
                    new_limit,
                    next_step,
                )
                self._step = next_step

            if new_limit != old_limit:
                await self._sem.set_capacity(new_limit)

            self._limit = new_limit


# ═══════════════════════════════════════════════════════════
# Router construction (pure — no cache) + token-stats merge helper
# ═══════════════════════════════════════════════════════════


def _build_router(base_url: str, api_key: str, model: str) -> Any:
    """Build a litellm :class:`Router` for one model from raw connection params.

    Takes explicit params instead of reading them from process config/env, so a
    :class:`LLMClient` that crossed a Ray task boundary can rebuild its Router
    in the worker without depending on worker env state. ``num_retries=0``: the
    dispatcher's own retry loop (rate-limit backoff + bounded attempts) is
    authoritative; litellm's internal retries are disabled to keep the total
    attempt count predictable.
    """
    from litellm import Router

    model_list = [
        {
            "model_name": model,
            "litellm_params": {
                "model": f"openai/{model}",
                "api_key": api_key,
                "api_base": base_url,
            },
        }
    ]
    # ``cache_responses=False`` is deliberate: that flag is litellm's own
    # RESPONSE cache (it forwards ``caching=True`` to the completion), not the
    # provider's prompt-prefix cache. It is inert unless a global
    # ``litellm.cache`` is configured — and if one ever is, identical ReAct
    # prompts would replay stale completions. Prompt-prefix cache hits are a
    # provider-side property of the request bytes; we only measure them
    # (:func:`extract_cached_tokens`).
    return Router(model_list=model_list, cache_responses=False, num_retries=0)


def _usage_field(obj: Any, key: str) -> Any:
    """Read ``key`` off a usage object that may be a model or a plain mapping.

    litellm returns pydantic-ish usage objects, but gateways that bypass its
    normalization hand back dicts. Never raises — a missing/unreadable field
    is ``None``.
    """
    if obj is None:
        return None
    try:
        value = getattr(obj, key, None)
        if value is not None:
            return value
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        if isinstance(obj, dict):
            return obj.get(key)
    except Exception:  # pragma: no cover - defensive
        pass
    return None


def extract_cached_tokens(response: Any) -> int:
    """Prompt tokens served from the provider's prefix cache, or 0.

    Prompt-prefix caching is provider-side, and gateways disagree on where the
    hit count lands. Tolerate every shape we have seen, in priority order:

    - ``usage.prompt_tokens_details.cached_tokens`` — canonical. litellm folds
      DeepSeek's ``prompt_cache_hit_tokens`` and Anthropic's
      ``cache_read_input_tokens`` into this, so it holds for those too.
    - ``usage.cached_tokens`` / ``usage.prompt_cache_hit_tokens`` /
      ``usage.cache_read_input_tokens`` — fallbacks for gateways that pass the
      raw upstream usage through without litellm's normalization.

    Called on the hot path for every completion, so it swallows any error and
    returns 0 rather than risk failing a request.
    """
    usage = _usage_field(response, "usage")
    if usage is None:
        return 0
    details = _usage_field(usage, "prompt_tokens_details")
    for candidate in (
        _usage_field(details, "cached_tokens"),
        _usage_field(usage, "cached_tokens"),
        _usage_field(usage, "prompt_cache_hit_tokens"),
        _usage_field(usage, "cache_read_input_tokens"),
    ):
        if candidate is None:
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0


def merge_token_stats(*deltas: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Pure merge of token-stats deltas into a fresh dict (no global state).

    Each agent Ray Task returns its :meth:`LLMClient.take_token_stats` delta;
    the driver folds them together with this helper. Pass the running aggregate
    as the first arg to accumulate across ticks, e.g.
    ``self._token_stats = merge_token_stats(self._token_stats, delta)``.

    Every key is read with ``.get(..., 0)`` so a delta produced by an older
    build (``calls``/``input``/``output`` only) still merges cleanly across a
    mixed-version Ray cluster.
    """
    merged: dict[str, dict[str, int]] = {}
    for delta in deltas:
        for model, s in delta.items():
            agg = merged.setdefault(
                model, {"calls": 0, "input": 0, "output": 0, "cached_input": 0}
            )
            agg["calls"] += int(s.get("calls", 0))
            agg["input"] += int(s.get("input", 0))
            agg["output"] += int(s.get("output", 0))
            agg["cached_input"] += int(s.get("cached_input", 0))
    return merged


def cache_hit_rate(stats: dict[str, dict[str, int]]) -> float:
    """Prompt-cache hit rate over token stats: ``cached_input / input``.

    Clamped to ``[0, 1]``: Anthropic-shaped usage reports ``prompt_tokens``
    *excluding* cache reads, so a naive ratio can exceed 1 for gateways that
    pass that shape through. Raw counters are kept in the stats, so a caller
    who knows their gateway's convention can recompute it themselves.

    Note the denominator is *all* billed input tokens, including one-shot
    utility calls (world description, memory consolidation) and ask-mode turns
    that are structurally prefix-unique and always read 0%. An aggregate rate
    therefore understates the ReAct loop's own hit rate — prefer the per-turn
    trace spans when judging a prompt-layout change.
    """
    total_input = sum(int(s.get("input", 0)) for s in stats.values())
    if total_input <= 0:
        return 0.0
    cached = sum(int(s.get("cached_input", 0)) for s in stats.values())
    return max(0.0, min(1.0, cached / total_input))


def build_client_for_role(role: str) -> LLMClient:
    """Build a serializable :class:`LLMClient` carrying one role's connection params.

    Resolves ``(base_url, api_key, model_name)`` from :class:`Config` for the
    role and returns a client that crosses Ray task boundaries carrying only
    params; each consumer builds its own Router + AIMD semaphore in its own
    event loop on first call.

    Also resolves the role's reasoning (thinking) settings — see
    :func:`agentsociety2.config.config.get_llm_thinking`.
    """
    from agentsociety2.config.config import get_llm_connection, get_llm_thinking

    base_url, api_key, model_name = get_llm_connection(role)
    return LLMClient(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key or "",
        model_type=role,
        thinking=ThinkingSettings(**get_llm_thinking(role)),
    )


# ═══════════════════════════════════════════════════════════
# LLMClient — serializable config; calls litellm in-process
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ThinkingSettings:
    """One role's reasoning (thinking) request parameters.

    Resolved once per role from the environment by
    :func:`agentsociety2.config.config.get_llm_thinking` and carried on the
    :class:`LLMClient` so it survives the Ray task boundary.

    Only OpenAI-compatible chat-completions parameters are produced — no
    per-model-family probing. ``policy="inherit"`` (the default, and what an
    unset environment yields) emits **nothing at all**, leaving the outgoing
    request byte-identical to a build without this feature.
    """

    policy: str = "inherit"
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] | None = None

    def request_kwargs(self) -> dict[str, Any]:
        """Return the completion kwargs this policy contributes.

        ``inherit`` contributes nothing. Otherwise emit whichever of
        ``reasoning_effort`` / ``extra_body`` were resolved (both may be set for
        ``on``; ``get_llm_thinking`` deliberately leaves ``reasoning_effort``
        unset for ``off`` when a gateway-specific ``extra_body`` is configured).
        """
        if self.policy == "inherit":
            return {}
        kwargs: dict[str, Any] = {}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.extra_body:
            kwargs["extra_body"] = dict(self.extra_body)
        return kwargs


@dataclass
class LLMClient:
    """Serializable LLM connection config that builds its runtime per-loop.

    Carries the raw connection params (``model_name``/``base_url``/``api_key``)
    so it can cross Ray task boundaries. On first ``call()`` in a given event
    loop it builds its OWN litellm ``Router`` + :class:`AdaptiveSemaphore`
    (both loop-bound asyncio objects), cached on the instance and **rebuilt if
    the running loop changes**. ``__getstate__`` strips the runtime so every
    deserialized copy rebuilds fresh in its own loop — no module-global cache,
    no cross-event-loop binding.

    Token usage accumulates in a per-instance dict drained via
    :meth:`take_token_stats` (returned through Ray Task results).
    """

    model_name: str
    base_url: str
    api_key: str = field(repr=False)
    model_type: str = "default"
    thinking: ThinkingSettings | None = None

    def __post_init__(self) -> None:
        self._router: Any = None
        self._sem: AdaptiveSemaphore | None = None
        self._token_stats: dict[str, dict[str, int]] = {}
        self._loop: Any = None

    # Pickle/cloudpickle: keep only connection params so the client crosses Ray
    # task boundaries. Each side rebuilds its own Router + semaphore in its own
    # event loop on first call.
    def __getstate__(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model_type": self.model_type,
            "thinking": self.thinking,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.model_name = state["model_name"]
        self.base_url = state["base_url"]
        self.api_key = state["api_key"]
        self.model_type = state.get("model_type", "default")
        # ``.get`` keeps state dicts written by older builds loadable; the
        # ``or`` normalizes a missing/None value to the inert default so a
        # deserialized client can never crash on a missing attribute.
        self.thinking = state.get("thinking") or ThinkingSettings()
        self._router = None
        self._sem = None
        self._token_stats = {}
        self._loop = None

    def _ensure_runtime(self) -> None:
        """Build (or rebuild) the Router + semaphore for the current event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._loop is loop and self._router is not None:
            return
        self._router = _build_router(self.base_url, self.api_key, self.model_name)
        initial = max(1, Config.LLM_RAY_CONCURRENCY)
        # No hard cap: AIMD probes the real API ceiling freely and backs off
        # on latency slowdown / rate-limit errors. min=1 lets it shed load
        # all the way down under sustained pressure.
        self._sem = AdaptiveSemaphore(
            initial=initial,
            min_limit=1,
            max_limit=None,
            latency_degrade_factor=Config.LLM_LATENCY_DEGRADE_FACTOR,
            slow_latency_ms=Config.LLM_SLOW_LATENCY_MS,
            round_sample_cap=Config.LLM_ROUND_SAMPLE_CAP,
        )
        # Reset stats so a rebuilt runtime (new loop / fresh task) starts clean
        # and a reused worker process never double-counts across tasks.
        self._token_stats = {}
        self._loop = loop

    def _record_tokens(self, model: str, response: Any) -> None:
        """Accumulate one call's token usage into this client's local stats."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        s = self._token_stats.setdefault(
            model, {"calls": 0, "input": 0, "output": 0, "cached_input": 0}
        )
        s["calls"] += 1
        s["input"] += int(getattr(usage, "prompt_tokens", 0) or 0)
        s["output"] += int(getattr(usage, "completion_tokens", 0) or 0)
        s["cached_input"] += extract_cached_tokens(response)

    def _resolve_thinking_kwargs(
        self, thinking: str, kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        """在调用方 kwargs 之上合并本 client 的思考设置。

        仅 ``"inherit"`` 与 ``"off"`` 有意义:client 每角色只携带一份已
        解析的负载,不存在单独的"on"负载可强制。若调用方想在 ``off``
        角色策略下仍启用推理,直接传 ``reasoning_effort`` /
        ``extra_body``——它们在此胜出。

        :param thinking: ``"inherit"`` 或 ``"off"``。
        :param kwargs: 调用方的 completion kwargs(冲突时胜出)。
        :returns: 转发给 ``router.acompletion`` 的 kwargs。
        """
        if thinking == "off" or self.thinking is None:
            effective: dict[str, Any] = {}
        else:
            effective = self.thinking.request_kwargs()
        merged = {**effective, **kwargs}

        # litellm's ``openai/`` adapter validates request params against its own
        # model map. This deployment points at an OpenAI-compatible gateway
        # serving a model litellm does not know, so ``reasoning_effort`` is
        # rejected outright ("openai does not support parameters:
        # ['reasoning_effort']"). Allow it explicitly whenever we send one.
        #
        # Deliberately NOT ``litellm.drop_params = True``: that would silently
        # swallow the parameter and the switch would appear to work while doing
        # nothing.
        if "reasoning_effort" in merged:
            allowed = list(merged.get("allowed_openai_params") or [])
            if "reasoning_effort" not in allowed:
                allowed.append("reasoning_effort")
            merged["allowed_openai_params"] = allowed
        return merged

    def take_token_stats(self) -> dict[str, dict[str, int]]:
        """Return and clear this client's token stats (a delta)."""
        snapshot = {model: dict(s) for model, s in self._token_stats.items()}
        self._token_stats.clear()
        return snapshot

    def snapshot_token_stats(self) -> dict[str, dict[str, int]]:
        """Return a copy of this client's token stats without clearing."""
        return {model: dict(s) for model, s in self._token_stats.items()}

    async def call(
        self,
        model: str | None = None,
        messages: list[AllMessageValues] | None = None,
        stream: bool = False,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        thinking: str = "inherit",
        **kwargs: Any,
    ) -> ModelResponse:
        """Send a completion request with per-loop AIMD gating + retry.

        ``thinking`` is consumed here and never forwarded: ``"inherit"`` (the
        default) applies this client's role-level :class:`ThinkingSettings`,
        ``"off"`` suppresses them for this call. Utility calls that gain
        nothing from reasoning (memory consolidation, world-description
        generation) pass ``thinking="off"``.

        Any caller-supplied ``reasoning_effort`` / ``extra_body`` in ``kwargs``
        **replaces** the role-level value wholesale — no deep merge, so what
        gets sent is always predictable.
        """
        if stream:
            raise NotImplementedError(
                "streaming is not supported; callers must use stream=False"
            )
        if messages is None:
            messages = []
        max_retries = max(max_retries, 1)
        effective_model = model or self.model_name
        request_kwargs = self._resolve_thinking_kwargs(thinking, kwargs)
        self._ensure_runtime()
        router = self._router
        sem = self._sem
        assert sem is not None  # _ensure_runtime guarantees it
        last_error: Exception | None = None
        last_error_was_rate_limit = False

        for attempt in range(max_retries + 1):
            await sem.acquire()
            # 跨进程共享配额(评审 P0):多实验并行时限制全机在途请求数。
            # 未启用(默认)时 _acquire_shared_quota 立即返回,零开销;
            # 超时抛 asyncio.TimeoutError,走本循环既有异常路径计入
            # 重试(与限流同型处理)。
            quota_held = False
            try:
                await _acquire_shared_quota()
                quota_held = True
            except TimeoutError as e:
                overloaded = True
                last_error = e
                last_error_was_rate_limit = True
                if attempt >= max_retries:
                    raise LLMDispatchError(
                        f"Shared LLM quota wait exceeded after {max_retries + 1} "
                        f"attempts. Last error: {e!s}",
                        rate_limit_like=True,
                    ) from e
                continue
            finally:
                # 等待配额失败（包括取消）时也必须归还本地容量。
                if not quota_held:
                    await sem.release(overloaded=False)
            t0 = time.monotonic()
            overloaded = False
            retry_delay = 0.0
            try:
                response = await router.acompletion(
                    model=effective_model,
                    messages=messages,
                    stream=False,
                    timeout=_LLM_REQUEST_TIMEOUT,
                    **request_kwargs,
                )
                latency_ms = (time.monotonic() - t0) * 1000
                sem.record_latency(latency_ms, is_error=False)
                self._record_tokens(effective_model, response)
                return response
            except Exception as e:
                latency_ms = (time.monotonic() - t0) * 1000
                overloaded = is_rate_limit_like_error(e)
                sem.record_latency(latency_ms, is_error=overloaded)
                last_error = e
                last_error_was_rate_limit = overloaded
                if is_context_limit_error(e):
                    # Deterministic failure: retrying re-sends the same
                    # oversized prompt (the most expensive request in the
                    # run) for a guaranteed-identical outcome. Fail now.
                    logger.error(
                        "Context window exceeded for '%s' via LLMClient(%s); "
                        "not retrying. Error: %s",
                        effective_model,
                        self.model_type,
                        e,
                    )
                    raise LLMDispatchError(
                        f"Context window exceeded for '{effective_model}' "
                        f"via LLMClient({self.model_type}); request not "
                        f"retried. Error: {e!s}",
                        rate_limit_like=False,
                    ) from e
                if attempt >= max_retries:
                    raise LLMDispatchError(
                        f"Failed to get valid response after {max_retries + 1} "
                        f"attempts. Last error: {e!s}",
                        rate_limit_like=overloaded,
                    ) from e
                if overloaded:
                    delay = min(base_delay * (2**attempt), max_delay)
                    delay = min(
                        max(delay, rate_limit_retry_seconds(e, delay)),
                        max_delay,
                    )
                    logger.warning(
                        "Rate limit for '%s' via LLMClient(%s) (attempt %d/%d). "
                        "Backoff %.1fs. Error: %s",
                        effective_model,
                        self.model_type,
                        attempt + 1,
                        max_retries + 1,
                        delay,
                        e,
                    )
                    retry_delay = delay
                else:
                    # 连接错误也可能是短暂故障；立即连发会在恢复前耗尽重试次数。
                    retry_delay = min(base_delay * (2**attempt), max_delay)
                    logger.warning(
                        "Request failed for '%s' via LLMClient(%s) (attempt %d/%d). "
                        "Backoff %.1fs. Error: %s",
                        effective_model,
                        self.model_type,
                        attempt + 1,
                        max_retries + 1,
                        retry_delay,
                        e,
                        exc_info=True,
                    )
            finally:
                try:
                    if quota_held and _SHARED_QUOTA_LIMIT > 0:
                        # 在线程中等待计数锁，不阻塞事件循环。
                        await asyncio.to_thread(_release_shared_quota)
                finally:
                    await sem.release(overloaded=overloaded)
            # 退避期间没有在途请求，不占共享额度和本地容量。
            if retry_delay:
                await asyncio.sleep(retry_delay)

        raise LLMDispatchError(
            f"Failed to get valid response after {max_retries + 1} attempts. "
            f"Last error: {last_error!s}",
            rate_limit_like=last_error_was_rate_limit,
        )


# ═══════════════════════════════════════════════════════════
# Public lifecycle
# ═══════════════════════════════════════════════════════════


def _build_ray_job_config() -> Any:
    """Build a Ray job config that does not package the local workspace."""
    import ray

    source_paths = [
        str(Path(__file__).resolve().parents[2]),
    ]
    pythonpath_parts = [
        p
        for p in source_paths + os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if p
    ]
    env_vars = {
        key: value for key, value in os.environ.items() if not key.startswith("UV")
    }
    env_vars["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(pythonpath_parts))
    return ray.job_config.JobConfig(runtime_env={"env_vars": env_vars})


async def init_dispatchers() -> None:
    """Initialize Ray (for the env-router actor / agent Ray tasks).

    No pool is created — LLM calls are per-process. Ray is needed only for the
    actor/task execution model (env router, step_agent_batch). When launching
    via ``uv run``, Ray's uv-runtime-env packaging is disabled
    (RAY_ENABLE_UV_RUN_RUNTIME_ENV=0, set at import) so workers inherit the
    driver environment instead of re-building the package.
    """
    import ray

    if not ray.is_initialized():
        from ray._private import ray_constants

        old_uv = ray_constants.RAY_ENABLE_UV_RUN_RUNTIME_ENV
        old_env = os.environ.get("RAY_ENABLE_UV_RUN_RUNTIME_ENV")
        os.environ["RAY_ENABLE_UV_RUN_RUNTIME_ENV"] = "0"
        ray_constants.RAY_ENABLE_UV_RUN_RUNTIME_ENV = False
        try:
            ray.init(
                ignore_reinit_error=True,
                include_dashboard=False,
                num_cpus=Config.LLM_RAY_MAX_WORKERS,
                object_store_memory=1_000_000_000,
                job_config=_build_ray_job_config(),
                runtime_env=None,
            )
        finally:
            if old_env is None:
                os.environ.pop("RAY_ENABLE_UV_RUN_RUNTIME_ENV", None)
            else:
                os.environ["RAY_ENABLE_UV_RUN_RUNTIME_ENV"] = old_env
            ray_constants.RAY_ENABLE_UV_RUN_RUNTIME_ENV = old_uv
    logger.info("LLM dispatchers ready (per-process, no central pool)")


async def shutdown_dispatchers() -> None:
    """No-op (no pool / workers to shut down). Per-process Routers are released
    when their process exits."""
    return
