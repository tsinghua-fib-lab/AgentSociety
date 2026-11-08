"""Thinking (reasoning) switch: env resolution, serialization, request kwargs.

Covers Chat Completions and Messages wire protocols without model-name inference.
"""

from __future__ import annotations

import json
import pickle

import pytest

from agentsociety2.config.config import get_llm_thinking
from agentsociety2.config.llm_dispatcher import LLMClient, ThinkingSettings

_THINKING_VARS = (
    "AGENTSOCIETY_LLM_THINKING",
    "AGENTSOCIETY_LLM_THINKING_FORMAT",
    "AGENTSOCIETY_CODER_LLM_THINKING_FORMAT",
    "AGENTSOCIETY_LLM_REASONING_EFFORT",
    "AGENTSOCIETY_LLM_EXTRA_BODY",
    "AGENTSOCIETY_CODER_LLM_THINKING",
    "AGENTSOCIETY_CODER_LLM_REASONING_EFFORT",
    "AGENTSOCIETY_CODER_LLM_EXTRA_BODY",
    "AGENTSOCIETY_EMBEDDING_LLM_THINKING",
)


@pytest.fixture(autouse=True)
def _clean_thinking_env(monkeypatch):
    for name in _THINKING_VARS:
        monkeypatch.delenv(name, raising=False)


def _kwargs(role: str = "default") -> dict:
    return ThinkingSettings(**get_llm_thinking(role)).request_kwargs()


# ------------------------ env resolution -------------------------


def test_unset_sends_nothing():
    """The backward-compatibility guarantee: unset env must add no parameter."""
    assert get_llm_thinking("default") == {
        "policy": "inherit",
        "reasoning_effort": None,
        "extra_body": None,
    }
    assert _kwargs() == {}
    assert _kwargs("coder") == {}


@pytest.mark.parametrize("value", ["on", "ON", "1", "true", "yes"])
def test_thinking_on_is_recognized(monkeypatch, value):
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", value)
    monkeypatch.setenv("AGENTSOCIETY_LLM_REASONING_EFFORT", "high")
    assert _kwargs() == {"reasoning_effort": "high"}


def test_thinking_on_without_effort_sends_medium(monkeypatch):
    """An explicit on request must enable reasoning."""
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "on")
    assert _kwargs() == {"reasoning_effort": "medium"}


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no"])
def test_thinking_off_sends_none(monkeypatch, value):
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", value)
    assert _kwargs() == {"reasoning_effort": "none"}


def test_thinking_off_ignores_reasoning_strength(monkeypatch):
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "off")
    monkeypatch.setenv("AGENTSOCIETY_LLM_REASONING_EFFORT", "low")
    assert _kwargs() == {"reasoning_effort": "none"}


def test_thinking_off_with_extra_body_sends_only_extra_body(monkeypatch):
    """A gateway-specific switch must not be accompanied by reasoning_effort,
    which the same gateway may reject."""
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "off")
    monkeypatch.setenv("AGENTSOCIETY_LLM_EXTRA_BODY", '{"enable_thinking": false}')
    assert _kwargs() == {"extra_body": {"enable_thinking": False}}


def test_thinking_on_can_combine_effort_and_extra_body(monkeypatch):
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "on")
    monkeypatch.setenv("AGENTSOCIETY_LLM_REASONING_EFFORT", "medium")
    monkeypatch.setenv("AGENTSOCIETY_LLM_EXTRA_BODY", '{"enable_thinking": true}')
    assert _kwargs() == {
        "reasoning_effort": "medium",
        "extra_body": {"enable_thinking": True},
    }


def test_unknown_policy_value_is_inert(monkeypatch):
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "maybe")
    assert _kwargs() == {}


@pytest.mark.parametrize("bad", ["{not json", "[1, 2]", '"a string"', "null"])
def test_malformed_extra_body_never_raises(monkeypatch, bad):
    """A bad env var must degrade to "send nothing", not abort a run."""
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "off")
    monkeypatch.setenv("AGENTSOCIETY_LLM_EXTRA_BODY", bad)
    assert _kwargs() == {"reasoning_effort": "none"}


# ------------------------ per-role overrides -------------------------


def test_coder_role_overrides_default(monkeypatch):
    """The split the switch exists for: agents reason, env-router codegen does not."""
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "on")
    monkeypatch.setenv("AGENTSOCIETY_LLM_REASONING_EFFORT", "high")
    monkeypatch.setenv("AGENTSOCIETY_CODER_LLM_THINKING", "off")
    monkeypatch.setenv("AGENTSOCIETY_CODER_LLM_REASONING_EFFORT", "low")
    assert _kwargs("default") == {"reasoning_effort": "high"}
    assert _kwargs("coder") == {"reasoning_effort": "none"}


def test_coder_role_falls_back_to_default_settings(monkeypatch):
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "off")
    monkeypatch.setenv("AGENTSOCIETY_LLM_EXTRA_BODY", '{"x": 1}')
    assert _kwargs("coder") == {"reasoning_effort": "none", "extra_body": {"x": 1}}


def test_non_coder_roles_ignore_coder_overrides(monkeypatch):
    monkeypatch.setenv("AGENTSOCIETY_CODER_LLM_THINKING", "off")
    assert _kwargs("embedding") == {}


# ------------------------ ThinkingSettings -------------------------


def test_inherit_policy_contributes_nothing_even_with_payloads():
    settings = ThinkingSettings(
        policy="inherit", reasoning_effort="high", extra_body={"x": 1}
    )
    assert settings.request_kwargs() == {}


def test_request_kwargs_returns_a_copy_of_extra_body():
    settings = ThinkingSettings(policy="off", extra_body={"x": 1})
    kwargs = settings.request_kwargs()
    kwargs["extra_body"]["x"] = 2
    assert settings.extra_body == {"x": 1}


# ------------------------ serialization (Ray boundary) -------------------------


def test_thinking_survives_pickle_round_trip():
    client = LLMClient(
        model_name="m",
        base_url="u",
        api_key="k",
        model_type="default",
        thinking=ThinkingSettings(policy="off", reasoning_effort="minimal"),
    )
    restored = pickle.loads(pickle.dumps(client))
    assert restored.thinking == ThinkingSettings(
        policy="off", reasoning_effort="minimal"
    )
    assert (
        restored._resolve_thinking_kwargs("inherit", {})["reasoning_effort"] == "none"
    )


def test_state_dict_without_thinking_still_loads():
    """A client pickled by an older build must not break on the new field."""
    client = LLMClient.__new__(LLMClient)
    client.__setstate__({"model_name": "m", "base_url": "u", "api_key": "k"})
    assert client.thinking == ThinkingSettings()
    assert client.thinking.request_kwargs() == {}


def test_explicit_none_thinking_normalizes_to_inert_default():
    client = LLMClient.__new__(LLMClient)
    client.__setstate__(
        {"model_name": "m", "base_url": "u", "api_key": "k", "thinking": None}
    )
    assert client._resolve_thinking_kwargs("inherit", {}) == {}


# ------------------------ merge precedence -------------------------


def _client(policy: str = "off", effort: str = "minimal") -> LLMClient:
    return LLMClient(
        model_name="m",
        base_url="u",
        api_key="k",
        thinking=ThinkingSettings(policy=policy, reasoning_effort=effort),
    )


def test_inherit_applies_the_role_settings():
    assert _client()._resolve_thinking_kwargs("inherit", {"tools": []}) == {
        "reasoning_effort": "none",
        "allowed_openai_params": ["reasoning_effort"],
        "tools": [],
    }


def test_per_call_off_sends_disable_parameters():
    assert _client()._resolve_thinking_kwargs("off", {"tools": []}) == {
        "tools": [],
        "reasoning_effort": "none",
        "allowed_openai_params": ["reasoning_effort"],
    }


def test_caller_kwargs_win_over_role_settings():
    assert _client()._resolve_thinking_kwargs(
        "inherit", {"reasoning_effort": "high"}
    ) == {"reasoning_effort": "high", "allowed_openai_params": ["reasoning_effort"]}


def test_client_without_thinking_sends_nothing():
    client = LLMClient(model_name="m", base_url="u", api_key="k", thinking=None)
    assert client._resolve_thinking_kwargs("inherit", {"tools": []}) == {"tools": []}


# ------------------------ litellm param allow-listing -------------------------


def test_reasoning_effort_is_allow_listed():
    """litellm's openai/ adapter rejects reasoning_effort for models outside its
    model map — i.e. any OpenAI-compatible gateway. Without this the switch
    400s on the very deployments it exists for (verified against a real
    gateway), so the parameter has to be explicitly allowed."""
    resolved = _client()._resolve_thinking_kwargs("inherit", {})
    assert resolved["reasoning_effort"] == "none"
    assert resolved["allowed_openai_params"] == ["reasoning_effort"]


def test_allow_list_is_absent_when_no_reasoning_param_is_sent():
    assert "allowed_openai_params" not in _client("inherit")._resolve_thinking_kwargs(
        "inherit", {}
    )


def test_caller_allow_list_is_preserved_and_deduplicated():
    resolved = _client()._resolve_thinking_kwargs(
        "inherit", {"allowed_openai_params": ["temperature", "reasoning_effort"]}
    )
    assert resolved["allowed_openai_params"] == ["temperature", "reasoning_effort"]


def test_extra_body_only_directive_skips_the_allow_list():
    """A gateway-specific extra_body switch carries no reasoning_effort, so it
    must not gain an allow-list entry for one."""
    client = LLMClient(
        model_name="m",
        base_url="u",
        api_key="k",
        thinking=ThinkingSettings(policy="off", extra_body={"enable_thinking": False}),
    )
    resolved = client._resolve_thinking_kwargs("inherit", {})
    assert resolved == {"extra_body": {"enable_thinking": False}}


@pytest.mark.parametrize(
    "api_type,control_format",
    [
        ("openai", ""),
        ("anthropic", ""),
        ("openai", "thinking"),
        ("openai", "enable_thinking"),
        ("openai", "chat_template_kwargs"),
        ("openai", "reasoning"),
    ],
)
@pytest.mark.parametrize("policy", ["on", "off"])
async def test_thinking_wire_parameters_reach_the_selected_endpoint(
    monkeypatch, api_type, control_format, policy
):
    import asyncio

    from agentsociety2.config.llm_dispatcher import LLMClient, ThinkingSettings

    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    requests = []

    async def handle(reader, writer):
        headers = (await reader.readuntil(b"\r\n\r\n")).decode()
        length = next(
            int(line.split(":", 1)[1])
            for line in headers.splitlines()
            if line.lower().startswith("content-length:")
        )
        body = json.loads(await reader.readexactly(length))
        requests.append((headers.splitlines()[0], body))
        if api_type == "anthropic":
            reply = {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 1},
            }
        else:
            reply = {
                "id": "chat_fixture",
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 1,
                    "total_tokens": 5,
                },
            }
        payload = json.dumps(reply).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
            + str(len(payload)).encode()
            + b"\r\n\r\n"
            + payload
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        client = LLMClient(
            model_name="unknown-thinking-alias",
            base_url=f"http://127.0.0.1:{port}/v1",
            api_key="owned-fixture",
            api_type=api_type,
            thinking=ThinkingSettings(policy=policy, format=control_format),
        )
        response = await client.call(
            messages=[{"role": "user", "content": "Return OK"}],
            max_tokens=2048,
            max_retries=1,
        )
    assert response.choices[0].message.content == "OK"
    assert bool(response._hidden_params.get("agentsociety_preserve_reasoning")) is (
        api_type == "anthropic" or policy == "on"
    )
    path, body = requests[0]
    assert path.split()[1] == (
        "/v1/messages" if api_type == "anthropic" else "/v1/chat/completions"
    )
    if api_type == "anthropic":
        assert body["thinking"]["type"] == ("enabled" if policy == "on" else "disabled")
    elif control_format == "thinking":
        assert body["thinking"]["type"] == ("enabled" if policy == "on" else "disabled")
        assert "reasoning_effort" not in body
    elif control_format == "enable_thinking":
        assert body["enable_thinking"] is (policy == "on")
    elif control_format == "chat_template_kwargs":
        assert body["chat_template_kwargs"]["enable_thinking"] is (policy == "on")
    elif control_format == "reasoning":
        assert body["reasoning"]["enabled"] is (policy == "on")
    else:
        assert body["reasoning_effort"] == ("medium" if policy == "on" else "none")
    assert len(requests) == 1


def test_per_call_off_disables_native_switches_and_keeps_custom_fields():
    from agentsociety2.config.llm_dispatcher import LLMClient, ThinkingSettings

    extra = {
        "thinking": {"type": "enabled", "budget_tokens": 2048},
        "enable_thinking": True,
        "chat_template_kwargs": {"enable_thinking": True, "custom": 7},
        "custom": "retained",
    }
    settings = ThinkingSettings(policy="on", reasoning_effort="high", extra_body=extra)
    client = LLMClient(
        model_name="owned-model",
        base_url="https://example.invalid/v1",
        api_key="owned",
        thinking=settings,
    )
    sent = client._resolve_thinking_kwargs("off", {})
    assert "reasoning_effort" not in sent
    assert sent["extra_body"]["thinking"] == {"type": "disabled"}
    assert sent["extra_body"]["enable_thinking"] is False
    assert sent["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False,
        "custom": 7,
    }
    assert sent["extra_body"]["custom"] == "retained"
    assert extra["thinking"]["type"] == "enabled"
    assert client._resolve_thinking_kwargs("inherit", {})["reasoning_effort"] == "high"
    assert ThinkingSettings().request_kwargs() == {}


def test_llm_protocol_role_inheritance_and_serialization(monkeypatch):
    import pickle

    from agentsociety2.config.config import get_llm_api_type, get_llm_thinking
    from agentsociety2.config.llm_dispatcher import LLMClient, ThinkingSettings

    monkeypatch.setenv("AGENTSOCIETY_LLM_API_TYPE", "anthropic")
    monkeypatch.delenv("AGENTSOCIETY_CODER_LLM_API_TYPE", raising=False)
    assert get_llm_api_type("coder") == "anthropic"
    assert get_llm_api_type("embedding") == "openai"
    monkeypatch.setenv("AGENTSOCIETY_CODER_LLM_API_TYPE", "openai")
    assert get_llm_api_type("coder") == "openai"
    monkeypatch.setenv("AGENTSOCIETY_LLM_THINKING", "off")
    monkeypatch.setenv("AGENTSOCIETY_LLM_REASONING_EFFORT", "high")
    monkeypatch.delenv("AGENTSOCIETY_LLM_EXTRA_BODY", raising=False)
    assert ThinkingSettings(**get_llm_thinking()).request_kwargs() == {
        "reasoning_effort": "none"
    }
    client = LLMClient(
        model_name="owned-model",
        base_url="https://example.invalid/v1",
        api_key="owned",
        api_type="anthropic",
        thinking=ThinkingSettings(policy="off"),
    )
    restored = pickle.loads(pickle.dumps(client))
    assert restored.api_type == "anthropic"
    assert restored._resolve_thinking_kwargs("inherit", {})["thinking"] == {
        "type": "disabled"
    }
