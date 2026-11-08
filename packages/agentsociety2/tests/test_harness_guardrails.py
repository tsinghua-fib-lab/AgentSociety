"""Guardrail tests for Phase 1.2 / 1.3 / 1.8c (exp/harness-optimization).

Covers:
- LLM dispatcher fails fast on context-window-exceeded errors instead of
  retrying the same oversized prompt (and still retries generic errors).
- The agent ``read`` tool caps oversized observations with a grep pointer.
- The memory consolidation fuse pauses after repeated empty merges instead
  of burning one LLM call per step.
"""

from datetime import datetime

import pytest

from agentsociety2.agent.base.agent import AgentBase
from agentsociety2.agent.memory import AgentMemoryStore, MemoryConsolidationConfig
from agentsociety2.config.llm_dispatcher import (
    AdaptiveSemaphore,
    LLMClient,
    LLMDispatchError,
    is_context_limit_error,
)

# ------------------------ context-limit fail-fast -------------------------


class _FakeRouter:
    """Router stand-in that raises ``error`` on every acompletion call."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def acompletion(self, **kwargs):
        self.calls += 1
        raise self.error


def _client_with_router(error: Exception) -> tuple[LLMClient, _FakeRouter]:
    client = LLMClient(
        model_name="test-model",
        base_url="http://localhost:1",
        api_key="k",
        model_type="default",
    )
    router = _FakeRouter(error)
    client._router = router
    client._sem = AdaptiveSemaphore(initial=4)
    client._loop = None
    # Bypass per-loop runtime (re)build so the fake router stays installed.
    client._ensure_runtime = lambda: None  # type: ignore[method-assign]
    return client, router


def _make_context_error() -> Exception:
    from litellm.exceptions import ContextWindowExceededError

    return ContextWindowExceededError(
        message="This model's maximum context length is 4096 tokens.",
        llm_provider="openai",
        model="test-model",
    )


def test_is_context_limit_error_matches_typed_and_text_variants():
    assert is_context_limit_error(_make_context_error())

    class Wrapped400(Exception):
        pass

    assert is_context_limit_error(
        Wrapped400("Error code: 400 - maximum context length is 8192 tokens")
    )
    assert is_context_limit_error(
        Wrapped400(
            "your messages resulted in 128000 tokens, the context window is 64000"
        )
    )


def test_is_context_limit_error_rejects_rate_limit_and_generic():
    class RateLimitish(Exception):
        pass

    assert not is_context_limit_error(RateLimitish("Rate limit reached, try again in 5 seconds"))
    assert not is_context_limit_error(RuntimeError("connection reset by peer"))


@pytest.mark.asyncio
async def test_context_limit_error_fails_fast_without_retry():
    from litellm.exceptions import ContextWindowExceededError

    client, router = _client_with_router(_make_context_error())
    with pytest.raises(LLMDispatchError, match="[Cc]ontext window exceeded"):
        await client.call(messages=[{"role": "user", "content": "hi"}])
    # The whole point: exactly one attempt, no re-send of the oversized prompt.
    assert router.calls == 1
    assert isinstance(router.error, ContextWindowExceededError)


@pytest.mark.asyncio
async def test_generic_error_still_retries_then_raises():
    client, router = _client_with_router(RuntimeError("connection reset by peer"))
    with pytest.raises(LLMDispatchError):
        await client.call(
            messages=[{"role": "user", "content": "hi"}],
            max_retries=2,
            base_delay=0.0,
        )
    # max_retries=2 → 3 attempts; fail-fast must not fire for generic errors.
    assert router.calls == 3


# ------------------------------ read cap ----------------------------------


class _ReadCapProbe(AgentBase):
    """Concrete stub so the abstract AgentBase can be instantiated bare."""

    async def ask(self, *args, **kwargs):  # pragma: no cover - abstract stub
        raise NotImplementedError

    async def step(self, *args, **kwargs):  # pragma: no cover - abstract stub
        raise NotImplementedError

    def to_workspace(self, *args, **kwargs):  # pragma: no cover - abstract stub
        raise NotImplementedError


def _bare_agent_base() -> AgentBase:
    """AgentBase instance without running __init__ (pure-method tests)."""
    return object.__new__(_ReadCapProbe)


def test_read_observation_small_content_untouched():
    agent = _bare_agent_base()
    content = "short file body"
    out, truncated = agent._cap_read_observation(content)
    assert out == content
    assert truncated is False


def test_read_observation_large_content_truncated_with_marker(monkeypatch):
    from agentsociety2.config.config import Config

    monkeypatch.setattr(Config, "WORKSPACE_READ_MAX_BYTES", 2048)
    agent = _bare_agent_base()
    content = "x" * 10_000
    out, truncated = agent._cap_read_observation(content)
    assert truncated is True
    assert out.startswith("xxxx")
    assert "truncated" in out and "grep" in out
    # Kept prefix respects the byte cap regardless of the marker's size.
    assert len(out.encode("utf-8")) < 2048 + 400


def test_read_observation_multibyte_boundary_survives(monkeypatch):
    from agentsociety2.config.config import Config

    monkeypatch.setattr(Config, "WORKSPACE_READ_MAX_BYTES", 1024)
    agent = _bare_agent_base()
    content = "中文内容" * 500  # 3 bytes per char
    out, truncated = agent._cap_read_observation(content)
    assert truncated is True
    # Decoding a cut multibyte sequence must not raise; content is still str.
    assert isinstance(out, str) and out


# --------------------------- consolidation fuse ----------------------------


def _fuse_runtime(tmp_path, merge_content):
    """PersonMemoryRuntime whose LLM merge returns ``merge_content``."""
    from agentsociety2.agent.memory_runtime import (
        MemoryRuntimeConfig,
        PersonMemoryRuntime,
    )

    calls = {"n": 0}

    async def dispatch_llm(**kwargs):
        calls["n"] += 1
        response = type(
            "R",
            (),
            {
                "choices": [
                    type("C", (), {"message": type("M", (), {"content": merge_content})()})
                ]
            },
        )()
        return response

    rt = PersonMemoryRuntime(
        agent_id=1,
        config=MemoryRuntimeConfig(
            consolidation=MemoryConsolidationConfig(
                pending_threshold=1,
                interval_steps=99,
                high_importance_threshold=0.75,
            )
        ),
        get_model_name=lambda: "m",
        dispatch_llm=dispatch_llm,
        logger=__import__("logging").getLogger("test"),
    )
    rt.ensure_store(tmp_path)
    return rt, calls


def _episodes():
    return [
        {
            "type": "goal",
            "importance": 0.6,
            "keywords": ["test"],
            "text": "Wanted to exercise regularly.",
        }
    ]


@pytest.mark.asyncio
async def test_empty_merges_engage_fuse_and_skip_consolidation(tmp_path):
    rt, calls = _fuse_runtime(tmp_path, " ")  # whitespace-only → empty merge
    store: AgentMemoryStore = rt.store

    # Step 1: first empty merge → streak 1, consolidation attempted.
    await rt.after_step(tick=1, t=datetime(2026, 1, 2, 9, 0), step_count=1, finish_memories=_episodes())
    state = store.read_state()
    assert state["consolidation_empty_streak"] == 1
    assert state["consolidation_cooldown_until_step"] == 0
    assert calls["n"] == 1

    # Step 2: second empty merge → streak resets, cooldown engaged.
    await rt.after_step(tick=2, t=datetime(2026, 1, 2, 9, 15), step_count=2, finish_memories=_episodes())
    state = store.read_state()
    assert state["consolidation_empty_streak"] == 0
    assert state["consolidation_cooldown_until_step"] == 2 + 16
    assert calls["n"] == 2

    # Step 3 (inside cooldown): trigger fires but consolidation is skipped —
    # no LLM call. This is the fuse's whole job: previously step 3 burned one.
    await rt.after_step(tick=3, t=datetime(2026, 1, 2, 9, 30), step_count=3, finish_memories=_episodes())
    assert calls["n"] == 2
    # Cursor untouched by empty merges.
    assert store.read_state()["last_consolidated_step"] == 0


@pytest.mark.asyncio
async def test_successful_merge_clears_streak_and_advances_cursor(tmp_path):
    rt, _calls = _fuse_runtime(tmp_path, "# Long-term memory\n\n- Alice likes test")
    store: AgentMemoryStore = rt.store

    # Prime the fuse with one empty merge.
    rt2, _calls2 = _fuse_runtime(tmp_path, " ")
    await rt2.after_step(tick=1, t=datetime(2026, 1, 2, 9, 0), step_count=1, finish_memories=_episodes())
    assert store.read_state()["consolidation_empty_streak"] == 1

    # A successful merge (step 2, within interval) clears the streak and
    # advances the consolidation cursor.
    await rt.after_step(tick=2, t=datetime(2026, 1, 2, 9, 15), step_count=2, finish_memories=_episodes())
    state = store.read_state()
    assert state["consolidation_empty_streak"] == 0
    assert state["last_consolidated_step"] == 2
