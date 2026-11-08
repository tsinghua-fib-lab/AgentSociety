"""The ReAct loop builds one thread and only appends to it.

Provider prompt-prefix caching is a longest-common-prefix match, so each turn's
request must be a strict prefix-extension of the previous one for the cached
region to grow instead of resetting. The old loop rebuilt ``[system, user]``
from scratch every turn, which capped the hit rate at the static prefix.

These tests capture the exact message list of every completion the loop issues
and assert the properties that make the cache work — plus the three
API-contract rules that a naive append would violate (an assistant turn that
carries ``tool_calls`` must have every id answered before any later
assistant/user message).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from agentsociety2.agent.base.agent import AgentBase
from agentsociety2.agent.base.react import ReactToolResult
from agentsociety2.trace import JsonlTraceWriter

T0 = datetime(2026, 1, 1, 8, 0, 0)


# ------------------------ fake provider objects -------------------------


class _Function:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.function = _Function(name, arguments)


class _Message:
    def __init__(self, content: str | None = None, tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message: _Message):
        self.message = message


class _Usage:
    prompt_tokens = 100
    completion_tokens = 10


class _Response:
    def __init__(self, message: _Message):
        self.choices = [_Choice(message)]
        self.usage = _Usage()


def _native(*calls: tuple[str, str, str]) -> _Response:
    """A native response: (call_id, name, arguments_json) triples."""
    return _Response(
        _Message(tool_calls=[_ToolCall(cid, name, args) for cid, name, args in calls])
    )


def _text(content: str) -> _Response:
    return _Response(_Message(content=content))


def _empty() -> _Response:
    return _Response(_Message(content=""))


# ------------------------ scripted agent -------------------------


def _snapshot(message: dict[str, Any]) -> dict[str, Any]:
    """Copy one message without inventing keys the loop never added."""
    snapshot = dict(message)
    tool_calls = snapshot.get("tool_calls")
    if tool_calls:
        snapshot["tool_calls"] = [
            {**tc, "function": dict(tc.get("function") or {})} for tc in tool_calls
        ]
    else:
        snapshot.pop("tool_calls", None)
    return snapshot


class _ScriptedAgent(AgentBase):
    """AgentBase with a scripted provider and recorded requests."""

    def __init__(self, script: list[_Response]):
        super().__init__()
        self._script = list(script)
        self.requests: list[list[dict[str, Any]]] = []
        self.build_count = 0
        self.tool_results: dict[str, ReactToolResult] = {}
        self.raise_on: set[str] = set()
        # A sink-less writer keeps the span API working and discards records.
        self._jsonl_trace_writer = JsonlTraceWriter(agent_id=0)

    # -- Abstract surface -------------------------------------------------
    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        raise NotImplementedError

    @classmethod
    async def from_workspace(cls, workspace_path: Path, service_proxy):
        raise NotImplementedError

    def to_workspace(self) -> dict:
        raise NotImplementedError

    async def ask(self, question: str, readonly: bool = True) -> str:
        raise NotImplementedError

    async def step(self, tick: int, t: datetime) -> str:
        raise NotImplementedError

    # -- Hooks ------------------------------------------------------------
    def build_react_messages(
        self, *, tick, t, observations, question=None, readonly=False, skill_hooks=None
    ):
        self.build_count += 1
        return [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": f"HEAD len(obs)={len(observations)}"},
        ]

    async def dispatch_react_tool(self, action, args, *, readonly=False):
        if action in self.raise_on:
            raise RuntimeError(f"boom: {action}")
        return self.tool_results.get(
            action, ReactToolResult(True, f"result of {action}", {"action": action})
        )

    # -- Scripted provider ------------------------------------------------
    async def _complete_react_once(self, messages, *, readonly=False):
        # The loop mutates `messages` in place, so snapshot what it sent.
        self.requests.append([_snapshot(m) for m in messages])
        if not self._script:
            return _empty()
        return self._script.pop(0)


async def _run(agent: _ScriptedAgent, **kwargs) -> tuple[str, list[list[dict]]]:
    result = await agent.run_react_loop(tick=60, t=T0, **kwargs)
    return result, agent.requests


# ------------------------ contract validators -------------------------


def assert_no_orphan_tool_calls(messages: list[dict[str, Any]]) -> None:
    """Every answerable tool_call id must be answered before the next turn.

    Mirrors the OpenAI rule an append-only loop can break: an assistant message
    with ``tool_calls`` must be followed by one ``role:"tool"`` message per id
    before any later assistant/user message.
    """
    pending: set[str] = set()
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "tool":
            call_id = message.get("tool_call_id")
            assert call_id in pending, (
                f"message {index}: tool reply for unknown/already-answered id {call_id!r}"
            )
            pending.discard(call_id)
            continue
        assert not pending, (
            f"message {index} ({role}) started before these tool_call ids were "
            f"answered: {sorted(pending)}"
        )
        for tool_call in message.get("tool_calls") or []:
            assert tool_call.get("id"), f"message {index}: tool_call without an id"
            assert tool_call.get("type") == "function"
            assert "arguments" in tool_call.get("function", {})
            pending.add(tool_call["id"])
    assert not pending, f"unanswered tool_call ids at end: {sorted(pending)}"


# ------------------------ the core invariant -------------------------


async def test_turn_n_plus_one_is_a_strict_prefix_extension():
    """The whole point of the change: the thread only ever grows."""
    agent = _ScriptedAgent(
        [
            _native(("c1", "read", '{"path": "a.txt"}')),
            _native(("c2", "grep", '{"pattern": "x"}')),
            _native(("c3", "finish", '{"memories": [{"text": "done"}]}')),
        ]
    )
    _, requests = await _run(agent)

    assert len(requests) == 3
    for i in range(len(requests) - 1):
        previous, following = requests[i], requests[i + 1]
        assert len(following) > len(previous), f"turn {i + 2} did not grow the thread"
        assert following[: len(previous)] == previous, (
            f"turn {i + 2} is not a prefix-extension of turn {i + 1} — the cached "
            f"prefix would be lost"
        )
    for request in requests:
        assert_no_orphan_tool_calls(request)


async def test_first_request_is_byte_identical_to_build_react_messages():
    """Only turns >= 2 change; turn 1 is exactly what the hook returned."""
    agent = _ScriptedAgent([_native(("c1", "finish", '{"memories": [{"text": "x"}]}'))])
    _, requests = await _run(agent)
    assert requests[0] == agent.build_react_messages(
        tick=60, t=T0, observations=[], question=None, readonly=False, skill_hooks=None
    )


async def test_build_react_messages_called_once_per_loop_invocation():
    agent = _ScriptedAgent(
        [
            _native(("c1", "read", '{"path": "a"}')),
            _native(("c2", "read", '{"path": "b"}')),
            _native(("c3", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    await _run(agent)
    assert agent.build_count == 1


# ------------------------ native encoding -------------------------


async def test_native_turn_appends_assistant_plus_tool_replies():
    agent = _ScriptedAgent(
        [
            _native(("c1", "read", '{"path": "a.txt"}')),
            _native(("c2", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    _, requests = await _run(agent)

    second = requests[1]
    assistant = second[2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "read"
    assert second[3] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": "result of read",
    }


async def test_native_turn_echo_uses_surviving_decisions():
    """A finish in the same response short-circuits the others.

    Echoing the raw response's calls would leave the dropped call's id
    unanswered and make the *next* request invalid — there is no next request
    here, but the assertion guards the reconstruction rule.
    """
    agent = _ScriptedAgent(
        [
            _native(
                ("c1", "read", '{"path": "a"}'),
                ("c2", "finish", '{"memories": [{"text": "x"}]}'),
            )
        ]
    )
    result, requests = await _run(agent)
    assert result == "x"
    assert len(requests) == 1
    assert_no_orphan_tool_calls(requests[0])


async def test_error_prefix_marks_failed_tool_calls():
    """Native replies carry no `ok` flag, so the text must convey failure."""
    agent = _ScriptedAgent(
        [
            _native(("c1", "read", '{"path": "missing"}')),
            _native(("c2", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    agent.tool_results["read"] = ReactToolResult(False, "no such file", {"error": "x"})
    _, requests = await _run(agent)
    assert requests[1][3]["content"] == "ERROR: no such file"


async def test_tool_exception_still_yields_a_tool_reply():
    agent = _ScriptedAgent(
        [
            _native(("c1", "read", '{"path": "a"}')),
            _native(("c2", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    agent.raise_on = {"read"}
    _, requests = await _run(agent)
    reply = requests[1][3]
    assert reply["role"] == "tool"
    assert reply["tool_call_id"] == "c1"
    assert "tool execution failed" in reply["content"]
    assert_no_orphan_tool_calls(requests[1])


async def test_multiple_tool_calls_get_one_reply_each():
    agent = _ScriptedAgent(
        [
            _native(
                ("c1", "read", '{"path": "a"}'), ("c2", "grep", '{"pattern": "p"}')
            ),
            _native(("c3", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    _, requests = await _run(agent)
    replies = [m for m in requests[1] if m["role"] == "tool"]
    assert [r["tool_call_id"] for r in replies] == ["c1", "c2"]
    assert_no_orphan_tool_calls(requests[1])


# ------------------------ error / empty paths -------------------------


async def test_schema_error_turn_replies_with_tool_messages():
    """An invalid finish is answered per-id, then retried."""
    agent = _ScriptedAgent(
        [
            _native(("c1", "finish", '{"memories": []}')),
            _native(("c2", "finish", '{"memories": [{"text": "ok"}]}')),
        ]
    )
    result, requests = await _run(agent)

    assert result == "ok"
    retry = requests[1]
    # Strict extension, ending in a per-id tool reply carrying the schema error.
    assert retry[: len(requests[0])] == requests[0]
    assert retry[-1]["role"] == "tool"
    assert retry[-1]["tool_call_id"] == "c1"
    assert "<schema_error>" in retry[-1]["content"]
    assert_no_orphan_tool_calls(retry)


async def test_text_parsed_turn_appends_assistant_text_plus_user_block():
    agent = _ScriptedAgent(
        [
            _text('read(path="a.txt")'),
            _native(("c1", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    _, requests = await _run(agent)
    second = requests[1]
    assert second[2] == {"role": "assistant", "content": 'read(path="a.txt")'}
    assert second[3]["role"] == "user"
    assert "<recent_observations>" in second[3]["content"]
    assert "result of read" in second[3]["content"]


async def test_empty_response_turn_appends_failure_feedback():
    """A silently-empty turn must still change the next request.

    Without this the thread would be byte-identical and, with a prefix cache,
    the loop could re-send the same prompt until the turn limit.
    """
    agent = _ScriptedAgent(
        [
            _empty(),
            _native(("c1", "finish", '{"memories": [{"text": "recovered"}]}')),
        ]
    )
    result, requests = await _run(agent)
    assert result == "recovered"
    assert len(requests[1]) > len(requests[0])
    assert requests[1][-1]["role"] == "user"
    assert "<react_error>" in requests[1][-1]["content"]


async def test_loop_exhaustion_falls_back_and_keeps_observations():
    """The observation side-channel still drives the end-of-loop fallbacks."""
    agent = _ScriptedAgent([_native(("c1", "read", '{"path": "a"}'))] * 3)
    agent._max_react_turns = 3
    observations: list[dict[str, Any]] = []
    result = await agent.run_react_loop(tick=60, t=T0, observations=observations)
    # Never finished, so the step-memory fallback summarises the observations.
    assert "result of read" in result
    assert [o["action"] for o in observations] == ["read", "read", "read"]
    assert agent._last_finish_memories is not None


# ------------------------ context refresh -------------------------


class _RefreshAgent(_ScriptedAgent):
    def build_context_refresh_message(self, *, actions, tick, t):
        if "todo_add" not in actions:
            return None
        return {"role": "user", "content": "<todo_context>refreshed</todo_context>"}


async def test_refresh_block_is_appended_after_tool_replies():
    agent = _RefreshAgent(
        [
            _native(("c1", "todo_add", '{"title": "x"}')),
            _native(("c2", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    _, requests = await _run(agent)
    second = requests[1]
    assert second[3]["role"] == "tool"
    assert second[4] == {
        "role": "user",
        "content": "<todo_context>refreshed</todo_context>",
    }
    assert_no_orphan_tool_calls(second)


async def test_no_refresh_for_read_only_actions():
    agent = _RefreshAgent(
        [
            _native(("c1", "read", '{"path": "a"}')),
            _native(("c2", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    _, requests = await _run(agent)
    assert all("refreshed" not in str(m.get("content")) for m in requests[1])


async def test_failed_action_does_not_trigger_refresh():
    agent = _RefreshAgent(
        [
            _native(("c1", "todo_add", '{"title": "x"}')),
            _native(("c2", "finish", '{"memories": [{"text": "x"}]}')),
        ]
    )
    agent.tool_results["todo_add"] = ReactToolResult(False, "rejected", {})
    _, requests = await _run(agent)
    assert all("refreshed" not in str(m.get("content")) for m in requests[1])


# ------------------------ ask mode -------------------------


async def test_ask_mode_question_only_in_the_first_message():
    agent = _ScriptedAgent(
        [
            _native(("c1", "read", '{"path": "a"}')),
            _native(("c2", "finish", '{"answer": "42"}')),
        ]
    )
    question = "What is the answer?"
    result, requests = await _run(agent, question=question, readonly=True)
    assert result == "42"
    # The thread head (system + first user) is built by the hook, which the
    # scripted agent renders as "HEAD"; later turns carry only appended history.
    assert requests[0][1]["content"].startswith("HEAD")
    assert (
        sum(1 for m in requests[1] if str(m.get("content", "")).startswith("HEAD")) == 1
    )


async def test_ask_fallback_still_reads_stashed_free_text():
    """_last_raw_answer_text survives the parser refactor."""
    agent = _ScriptedAgent([_text("I think the answer is 7.")] * 2)
    agent._max_react_turns = 2
    result = await agent.run_react_loop(
        tick=0, t=T0, observations=None, question="?", readonly=True
    )
    assert result == "I think the answer is 7."


async def test_ask_mode_free_text_error_is_fed_back_as_user_message():
    agent = _ScriptedAgent(
        [
            _text("just some prose"),
            _native(("c1", "finish", '{"answer": "ok"}')),
        ]
    )
    result, requests = await _run(agent, question="?", readonly=True)
    assert result == "ok"
    assert requests[1][-1]["role"] == "user"
    assert "<schema_error>" in requests[1][-1]["content"]


@pytest.mark.parametrize("preserve", [True, False])
async def test_react_keeps_requested_thinking_and_preserves_default_chat_history(
    preserve,
):
    first = _native(("call_keep", "read", '{"path":"a.txt"}'))
    first._hidden_params = {"agentsociety_preserve_reasoning": preserve}  # type: ignore[attr-defined]
    first.choices[0].message.thinking_blocks = [  # type: ignore[attr-defined]
        {
            "type": "thinking",
            "thinking": "fixture reasoning",
            "signature": "fixture-signature",
        }
    ]
    first.choices[0].message.reasoning_content = "fixture reasoning"  # type: ignore[attr-defined]
    agent = _ScriptedAgent(
        [first, _native(("finish", "finish", '{"memories":[{"text":"done"}]}'))]
    )
    _, requests = await _run(agent)
    assistant = requests[1][2]
    if preserve:
        assert assistant["thinking_blocks"][0]["signature"] == "fixture-signature"
        assert assistant["reasoning_content"] == "fixture reasoning"
    else:
        assert "thinking_blocks" not in assistant
        assert "reasoning_content" not in assistant
    assert requests[1][: len(requests[0])] == requests[0]
    assert_no_orphan_tool_calls(requests[1])
