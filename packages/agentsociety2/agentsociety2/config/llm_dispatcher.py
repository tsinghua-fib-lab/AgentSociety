"""按事件循环(per-loop)的 LLM 调度器(无模块级全局缓存)。

:class:`LLMClient` 携带原始连接参数(model_name、base_url、api_key),因此可以跨
Ray task 边界传输。每个消费者——每个 agent Ray task、env-router actor、driver——
都在首次 ``call()`` 时在自己的事件循环里全新构建 litellm ``Router`` 与
:class:`AdaptiveSemaphore`(AIMD)。模块级没有 Router/信号量缓存: 之前的进程级
全局缓存会把 asyncio 原语绑定到第一个触碰它们的事件循环,在 Ray 每 task 一次
``asyncio.run`` 的模型下直接出错("bound to a different event loop")。按循环
构建彻底消灭了这一类 bug。

token 用量按 :class:`LLMClient` 实例统计,经 Ray Task 返回值回汇到 driver
(:func:`merge_token_stats` 是纯函数工具——没有全局聚合,也没有 actor)。
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
    """LLM 请求在重试耗尽后失败。"""

    def __init__(self, message: str, *, rate_limit_like: bool = False) -> None:
        super().__init__(message)
        self.rate_limit_like = rate_limit_like


def is_rate_limit_like_error(error: Exception) -> bool:
    """判断异常是否形似限流(429)。"""
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
    """从限流错误中提取服务方要求的等待秒数,取不到则用 ``fallback`` 。

    DeepSeek / OpenAI 兼容网关常返回 ``Try again in N seconds`` 。无视它而只睡
    1–4 秒会把重试烧成必然失败。
    """
    match = re.search(r"[Tt]ry again in (\d+(?:\.\d+)?)\s*seconds?", str(error))
    if match:
        return float(match.group(1))
    return fallback


def is_context_limit_error(error: Exception) -> bool:
    """判断请求在当前规模下是否永远不可能成功。

    上下文超限错误是确定性的: 重试只会把同一个超长 prompt(整个运行中最贵的
    请求)再发一遍,换来一次必然相同的失败。``call`` 对这类错误直接快速失败,
    而不是烧掉 ``max_retries`` 次额外尝试。
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
    """容量可调的信号量,在请求仍在途时保留欠账。

    容量收缩到低于持有者数量后,``_available`` 可能为负。release 会先偿还
    欠账,再唤醒新的请求。
    """

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
            self._available = min(self._available + 1, self._capacity)
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
                self._available += delta
            return old


class AdaptiveSemaphore:
    """TCP 风格的 AIMD 自适应并发信号量(每进程一个)。

    ``max_limit=None`` 表示不设上限——AIMD(加性增/乘性减)自由探测,没有人为
    封顶,靠延迟变慢与限流错误来退避。LLM I/O 这类远端 API 才是真实天花板的
    场景应这样用;CPU/本地工作不得压垮单进程时,请传入有限的 ``max_limit`` 。
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


def _build_router(
    base_url: str, api_key: str, model: str, api_type: str = "openai"
) -> Any:
    """从原始连接参数为单个模型构建 litellm :class:`Router` 。

    接受显式参数而非读取进程配置/env,使跨过 Ray task 边界的
    :class:`LLMClient` 能在 worker 内重建 Router 而不依赖 worker 的 env 状态。
    ``num_retries=0``: 调度器自身的重试循环(限流退避 + 有界尝试)才是权威;
    关闭 litellm 内部重试,使总尝试次数可预测。
    """
    from litellm import Router

    if api_type not in {"openai", "anthropic"}:
        raise ValueError("LLM api_type must be openai or anthropic")
    if api_type == "anthropic":
        # LiteLLM appends /v1/messages. Both a gateway root and its /v1 base
        # are accepted in the configuration page.
        base_url = base_url.rstrip("/").removesuffix("/v1")
    model_list = [
        {
            "model_name": model,
            "litellm_params": {
                "model": f"{api_type}/{model}",
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
    """从 usage 对象读取 ``key``;该对象可能是模型,也可能是普通映射。

    litellm 返回 pydantic 风格的 usage 对象,但绕过其规范化的网关会直接回传
    dict。永不抛异常——缺失或不可读的字段返回 ``None`` 。
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
    """由服务方前缀缓存命中的 prompt token 数,否则为 0。

    prompt 前缀缓存是服务方行为,各网关对命中计数落在哪里并无共识。按优先级
    兼容我们见过的所有形态:

    - ``usage.prompt_tokens_details.cached_tokens`` —— 规范字段。litellm 已把
      DeepSeek 的 ``prompt_cache_hit_tokens`` 与 Anthropic 的
      ``cache_read_input_tokens`` 折叠进该字段,对二者同样成立。
    - ``usage.cached_tokens`` / ``usage.prompt_cache_hit_tokens`` /
      ``usage.cache_read_input_tokens`` —— 供不经 litellm 规范化、直接透传
      上游 usage 的网关回退使用。

    它在每次补全的热路径上被调用,因此吞掉一切错误并返回 0,而不是冒险让请求
    失败。
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
    """把多份 token 统计增量纯函数式地合并进新 dict(无全局状态)。

    每个 agent Ray Task 返回自己的 :meth:`LLMClient.take_token_stats` 增量,
    driver 用本函数把它们汇总。把累计值作为第一个参数传入即可跨 tick 累加,
    例如 ``self._token_stats = merge_token_stats(self._token_stats, delta)`` 。

    所有键都用 ``.get(..., 0)`` 读取,因此旧版本产出的增量(只有
    ``calls``/``input``/``output``)在混合版本的 Ray 集群里仍能干净合并。
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
    """token 统计上的 prompt 缓存命中率: ``cached_input / input`` 。

    结果夹在 ``[0, 1]``: Anthropic 形态的 usage 上报的 ``prompt_tokens``
    *不含*缓存读取,直接透传该形态的网关会让朴素比值超过 1。原始计数保留在
    统计里,了解自己网关约定的调用方可以自行重算。

    注意分母是*全部*计费输入 token,包括一次性工具调用(世界描述、记忆整理)
    以及结构上就是前缀唯一、命中率恒为 0% 的 ask 模式轮次。因此聚合命中率会
    低估 ReAct 循环自身的命中率——评估 prompt 布局改动时,请优先看逐轮的
    trace span。
    """
    total_input = sum(int(s.get("input", 0)) for s in stats.values())
    if total_input <= 0:
        return 0.0
    cached = sum(int(s.get("cached_input", 0)) for s in stats.values())
    return max(0.0, min(1.0, cached / total_input))


def build_client_for_role(role: str) -> LLMClient:
    """构建携带某角色连接参数的可序列化 :class:`LLMClient` 。

    从 :class:`Config` 解析该角色的 ``(base_url, api_key, model_name)``,返回
    只携带参数、可跨 Ray task 边界的 client;每个消费者在首次调用时于自己的
    事件循环里构建自己的 Router + AIMD 信号量。

    同时解析该角色的推理(thinking)设置——见
    :func:`agentsociety2.config.config.get_llm_thinking` 。
    """
    from agentsociety2.config.config import (
        get_llm_api_type,
        get_llm_connection,
        get_llm_thinking,
    )

    base_url, api_key, model_name = get_llm_connection(role)
    return LLMClient(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key or "",
        model_type=role,
        thinking=ThinkingSettings(**get_llm_thinking(role)),
        api_type=get_llm_api_type(role),
    )


# ═══════════════════════════════════════════════════════════
# LLMClient — serializable config; calls litellm in-process
# ═══════════════════════════════════════════════════════════


def reasoning_fields(response: Any) -> dict[str, Any]:
    """对原生 Messages 或显式开启推理的情形回放推理内容。

    默认 Chat Completions 保持其原有的历史编码与 token 开销。
    """
    metadata = getattr(response, "_hidden_params", {})
    if not isinstance(metadata, dict) or not metadata.get(
        "agentsociety_preserve_reasoning"
    ):
        return {}
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    return {
        key: value
        for key in ("reasoning_content", "thinking_blocks")
        if (value := getattr(message, key, None))
    }


@dataclass(frozen=True)
class ThinkingSettings:
    """单个角色的推理(thinking)请求参数。

    由 :func:`agentsociety2.config.config.get_llm_thinking` 按角色从环境解析
    一次,并挂在 :class:`LLMClient` 上携带,从而穿越 Ray task 边界。

    所选协议决定线上参数。模型名原样透传。``inherit`` 不产生任何请求参数。
    """

    policy: str = "inherit"
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] | None = None
    format: str = ""

    def request_kwargs(
        self, api_type: str = "openai", *, policy: str | None = None
    ) -> dict[str, Any]:
        """生成真实的开/关指令,同时保留自定义 body 字段。"""
        selected = policy or self.policy
        if selected == "inherit":
            return {}
        if selected not in {"on", "off"}:
            raise ValueError("thinking must be inherit, on or off")
        if self.format not in {
            "",
            "reasoning_effort",
            "thinking",
            "enable_thinking",
            "chat_template_kwargs",
            "reasoning",
        }:
            raise ValueError("Unsupported thinking control format")
        enabled = selected == "on"
        body = dict(self.extra_body or {})
        if api_type == "openai":
            # A declared wire format also works with custom model aliases.
            controls = {
                "thinking": {
                    "thinking": {"type": "enabled" if enabled else "disabled"}
                },
                "enable_thinking": {"enable_thinking": enabled},
                "chat_template_kwargs": {
                    "chat_template_kwargs": {"enable_thinking": enabled}
                },
                "reasoning": {"reasoning": {"enabled": enabled}},
            }
            for key, value in controls.get(self.format, {}).items():
                if isinstance(value, dict) and isinstance(body.get(key), dict):
                    body[key] = {**body[key], **value}
                else:
                    body[key] = value
        kwargs: dict[str, Any] = {}
        # Preserve the gateway's declared native switch and unrelated fields.
        # These are protocol field names, never model-family guesses.
        native_switch = False
        if isinstance(body.get("thinking"), dict):
            body["thinking"] = {
                **body["thinking"],
                "type": (
                    "adaptive"
                    if body["thinking"].get("type") == "adaptive"
                    else "enabled"
                )
                if enabled
                else "disabled",
            }
            if not enabled:
                body["thinking"].pop("budget_tokens", None)
            native_switch = True
        if "enable_thinking" in body:
            body["enable_thinking"] = enabled
            native_switch = True
        if (
            isinstance(body.get("chat_template_kwargs"), dict)
            and "enable_thinking" in body["chat_template_kwargs"]
        ):
            body["chat_template_kwargs"] = {
                **body["chat_template_kwargs"],
                "enable_thinking": enabled,
            }
            native_switch = True
        if isinstance(body.get("reasoning"), dict) and (
            "enabled" in body["reasoning"] or "effort" in body["reasoning"]
        ):
            reasoning = dict(body["reasoning"])
            if "enabled" in reasoning:
                reasoning["enabled"] = enabled
            if "effort" in reasoning:
                reasoning["effort"] = (
                    (
                        self.reasoning_effort
                        or (
                            reasoning["effort"]
                            if reasoning["effort"] != "none"
                            else "medium"
                        )
                    )
                    if enabled
                    else "none"
                )
            body["reasoning"] = reasoning
            native_switch = True
        if api_type == "anthropic":
            thinking = body.pop("thinking", {})
            kwargs["thinking"] = (
                {"type": "enabled", "budget_tokens": 1024, **thinking}
                if enabled
                else {"type": "disabled"}
            )
            if kwargs["thinking"].get("type") == "adaptive":
                kwargs["thinking"].pop("budget_tokens", None)
        elif not native_switch:
            kwargs["reasoning_effort"] = (
                (self.reasoning_effort or "medium") if enabled else "none"
            )
        if enabled and self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if body:
            kwargs["extra_body"] = body
        return kwargs


@dataclass
class LLMClient:
    """可序列化的 LLM 连接配置,按事件循环构建自己的运行时。

    携带原始连接参数(``model_name``/``base_url``/``api_key``)以跨 Ray task
    边界。在某个事件循环里首次 ``call()`` 时,构建自己的 litellm ``Router`` 与
    :class:`AdaptiveSemaphore` (两者都是绑定该循环的 asyncio 对象),缓存在实例
    上,且 **运行循环改变时重建** 。 ``__getstate__`` 剥离运行时,使每个反序列化
    副本都在自己的循环里全新构建——没有模块级缓存,没有跨事件循环绑定。

    token 用量累积在实例级 dict 中,经 :meth:`take_token_stats` 取走(通过
    Ray Task 返回值带回)。
    """

    model_name: str
    base_url: str
    api_key: str = field(repr=False)
    model_type: str = "default"
    thinking: ThinkingSettings | None = None
    api_type: str = "openai"

    def __post_init__(self) -> None:
        self._router: Any = None
        self._sem: AdaptiveSemaphore | None = None
        self._token_stats: dict[str, dict[str, int]] = {}
        self._loop: Any = None
        self._thinking_off_warning = False

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
            "api_type": self.api_type,
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
        self.api_type = state.get("api_type", "openai")
        self._router = None
        self._sem = None
        self._token_stats = {}
        self._loop = None
        self._thinking_off_warning = False

    def _ensure_runtime(self) -> None:
        """为当前事件循环构建(或重建)Router 与信号量。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._loop is loop and self._router is not None:
            return
        self._router = _build_router(
            self.base_url, self.api_key, self.model_name, self.api_type
        )
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
        """把一次调用的 token 用量累加进本 client 的本地统计。"""
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
        """先应用角色级或本次调用的策略,再叠加调用方传入的覆盖项。"""
        settings = self.thinking or ThinkingSettings()
        effective = settings.request_kwargs(
            self.api_type, policy=None if thinking == "inherit" else thinking
        )
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
        explicit_params = [
            key for key in ("reasoning_effort", "thinking") if key in merged
        ]
        if explicit_params:
            allowed = list(merged.get("allowed_openai_params") or [])
            for key in explicit_params:
                if key not in allowed:
                    allowed.append(key)
            merged["allowed_openai_params"] = allowed
        return merged

    def take_token_stats(self) -> dict[str, dict[str, int]]:
        """返回并清空本 client 的 token 统计(一份增量)。"""
        snapshot = {model: dict(s) for model, s in self._token_stats.items()}
        self._token_stats.clear()
        return snapshot

    def snapshot_token_stats(self) -> dict[str, dict[str, int]]:
        """返回本 client token 统计的副本,不清空。"""
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
        """发送补全请求,带按循环的 AIMD 门控与重试。

        ``thinking`` 在此消费、绝不转发: ``"inherit"`` (默认)应用本 client 的
        角色级 :class:`ThinkingSettings` ，``"on"`` 与 ``"off"`` 则为本次调用
        发送显式指令。内置工具调用继承所配置的策略,使必须思考的模型在未选择
        关闭策略时仍可用。

        调用方在 ``kwargs`` 里传入的 ``reasoning_effort`` / ``extra_body`` 会
        **整体替换** 角色级取值——不做深合并,因此实际发送内容始终可预测。
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
                policy = (
                    thinking
                    if thinking != "inherit"
                    else (self.thinking.policy if self.thinking else "inherit")
                )
                if self.api_type == "anthropic" or policy == "on":
                    metadata = getattr(response, "_hidden_params", None)
                    if not isinstance(metadata, dict):
                        metadata = {}
                        response._hidden_params = metadata
                    metadata["agentsociety_preserve_reasoning"] = True
                body = request_kwargs.get("extra_body") or {}

                def field(value: Any, key: str) -> Any:
                    return value.get(key) if isinstance(value, dict) else None

                disabled = (
                    request_kwargs.get("reasoning_effort") == "none"
                    or field(request_kwargs.get("thinking"), "type") == "disabled"
                    or field(body.get("thinking"), "type") == "disabled"
                    or body.get("enable_thinking") is False
                    or field(body.get("reasoning"), "enabled") is False
                    or field(body.get("reasoning"), "effort") == "none"
                    or field(body.get("chat_template_kwargs"), "enable_thinking")
                    is False
                )
                if disabled and not self._thinking_off_warning:
                    choices = getattr(response, "choices", None) or []
                    message = getattr(choices[0], "message", None) if choices else None
                    details = getattr(
                        getattr(response, "usage", None),
                        "completion_tokens_details",
                        None,
                    )
                    if (
                        getattr(message, "reasoning_content", None)
                        or any(
                            isinstance(block, dict)
                            and (
                                block.get("thinking")
                                or block.get("type") == "redacted_thinking"
                            )
                            for block in (
                                getattr(message, "thinking_blocks", None) or []
                            )
                        )
                        or getattr(details, "reasoning_tokens", 0)
                    ):
                        self._thinking_off_warning = True
                        logger.warning(
                            "Model %s returned reasoning after a disable request via %s. "
                            "Check the endpoint protocol and model thinking support.",
                            effective_model,
                            self.api_type,
                        )
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
    """构建不打包本地工作区的 Ray job 配置。"""
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
    """初始化 Ray(供 env-router actor / agent Ray task 使用)。

    不创建任何池——LLM 调用是每进程独立的。Ray 只用于 actor/task 执行模型
    (env router、step_agent_batch)。经 ``uv run`` 启动时会禁用 Ray 的
    uv-runtime-env 打包(import 时设 RAY_ENABLE_UV_RUN_RUNTIME_ENV=0),让
    worker 继承 driver 环境而非重新构建包。
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
    """空操作(没有池/worker 需要关闭)。每进程的 Router 随其进程退出而释放。"""
    return
