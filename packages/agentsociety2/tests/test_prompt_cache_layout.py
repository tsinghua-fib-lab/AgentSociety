"""Prompt-layout invariants that keep the provider's prefix cache effective.

Provider prompt-prefix caching is a longest-common-prefix match over the
serialized request (tools -> system -> user). Every assertion here exists to
protect one of the properties that makes that prefix reusable; a regression in
any of them silently costs cache hits without failing anything else, which is
exactly the failure mode this file is meant to catch.
"""

from __future__ import annotations

import re

from agentsociety2.agent.person_prompt import (
    build_base_rules,
    build_capabilities_block,
    build_react_messages,
)

# ------------------------ fixtures -------------------------


def _base_kwargs(**overrides):
    kwargs = {
        "world_description": "A small town on a river.",
        "skill_catalog": [{"name": "daily-guidance", "description": "Daily routine."}],
        "activated_skill_content": '<skill_content name="daily-guidance">Doc</skill_content>',
        "observations": [{"turn": 1, "action": "read", "ok": True}],
    }
    kwargs.update(overrides)
    return kwargs


#: Section blocks, as opposed to tags nested inside them (``<skill_hook>`` is
#: rendered by ``_render_skill_hooks_xml`` at a line start too).
_SECTIONS = frozenset(
    {
        "identity",
        "prompt_guide",
        "decision_workflow",
        "behavior",
        "world",
        "available_skills",
        "capabilities",
        "skill_content",
        "agent",
        "turn_state",
        "memory_context",
        "todo_context",
        "skill_hooks",
        "recent_observations",
        "ask_mode_rules",
        "question",
    }
)


def _section_tags(text: str) -> list[str]:
    """Section blocks in the order they appear.

    Matches line-start tags (attributes allowed — ``<skill_content name="...">``
    and the hook entries both render that way) and keeps only known sections.
    """
    return [
        tag
        for tag in re.findall(r"^<(\w+)[\s>]", text, re.MULTILINE)
        if tag in _SECTIONS
    ]


def _system_of(messages: list[dict[str, str]]) -> str:
    return messages[0]["content"]


def _user_of(messages: list[dict[str, str]]) -> str:
    return messages[1]["content"]


# ------------------------ the core cache invariant -------------------------


def test_system_message_is_identical_across_agents():
    """The whole point of the layout: the system prefix must be shareable.

    Two agents differing only in name / id / profile (and even in profile key
    order) must produce byte-identical system messages, so one cached prefix
    serves the entire fleet.
    """
    alice = build_react_messages(
        agent_json={"name": "Alice", "agent_id": 1, "profile": {"b": 1, "a": 2}},
        turn_state={"tick": 60, "step_count": 3},
        **_base_kwargs(),
    )
    bob = build_react_messages(
        agent_json={"name": "Bob", "agent_id": 2, "profile": {"a": 2, "b": 1}},
        turn_state={"tick": 60, "step_count": 3},
        **_base_kwargs(),
    )
    assert _system_of(alice) == _system_of(bob)


def test_system_message_is_identical_between_step_and_ask_mode():
    """Ask mode must not perturb the shared prefix either.

    The ask-mode rules used to be appended to the system preamble, which gave
    the same agent a completely different system message in ask mode.
    """
    step = build_react_messages(agent_json={"name": "Alice"}, **_base_kwargs())
    ask = build_react_messages(
        agent_json={"name": "Alice"}, question="What did you eat?", **_base_kwargs()
    )
    assert _system_of(step) == _system_of(ask)
    # ...and the ask rules now live in the user message, next to the question.
    assert "<ask_mode_rules>" not in _system_of(ask)
    assert "<ask_mode_rules>" in _user_of(ask)


def test_system_message_does_not_contain_the_agent_name():
    """A per-agent name early in the system message would break sharing."""
    messages = build_react_messages(agent_json={"name": "Alice"}, **_base_kwargs())
    assert "Alice" not in _system_of(messages)
    assert "Alice" in _user_of(messages)


def test_invariant_head_survives_capability_variants():
    """Config-flag variants must only differ in the trailing block.

    The invariant head (base rules + world + skill catalog) has to be a prefix
    of what every capability variant renders.
    """
    default = build_react_messages(agent_json={"name": "A"}, **_base_kwargs())
    no_memory = build_react_messages(
        agent_json={"name": "A"}, enable_memory=False, **_base_kwargs()
    )
    assert _system_of(default) != _system_of(no_memory)
    head = f"{build_base_rules()}\n\n<world>\nA small town on a river.\n</world>"
    assert _system_of(default).startswith(head)
    assert _system_of(no_memory).startswith(head)


# ------------------------ section ordering -------------------------


def test_system_section_order_is_least_to_most_volatile():
    messages = build_react_messages(
        agent_json={"name": "A"},
        turn_state={"tick": 60},
        **_base_kwargs(),
    )
    assert _section_tags(_system_of(messages)) == [
        "identity",
        "prompt_guide",
        "decision_workflow",
        "behavior",
        "world",
        "available_skills",
        "capabilities",
        "skill_content",
    ]


def test_user_section_order_puts_observations_last():
    """Observations change every ReAct turn; everything ahead of them does not
    (within a step), so they must not sit at the front invalidating the rest."""
    messages = build_react_messages(
        agent_json={"name": "A"},
        turn_state={"tick": 60, "step_count": 3},
        memory_context={"memory_md": "m"},
        todo_context={"counts": {"pending": 1}},
        skill_hooks=[
            {"skill": "daily-guidance", "hook": "pre_step", "ok": True, "output": "x"}
        ],
        **_base_kwargs(),
    )
    assert _section_tags(_user_of(messages)) == [
        "agent",
        "turn_state",
        "memory_context",
        "todo_context",
        "skill_hooks",
        "recent_observations",
    ]


def test_ask_sections_append_at_the_end():
    messages = build_react_messages(
        agent_json={"name": "A"}, question="Q?", **_base_kwargs()
    )
    assert _section_tags(_user_of(messages)) == [
        "agent",
        "recent_observations",
        "ask_mode_rules",
        "question",
    ]


def test_turn_state_is_not_duplicated_inside_agent():
    """Time/tick/step count belong to <turn_state> only, so that <agent> stays
    byte-stable across steps and can be cached."""
    messages = build_react_messages(
        agent_json={"name": "A", "profile": {"x": 1}},
        turn_state={"current_time": "2026-01-01T00:00:00", "tick": 60, "step_count": 7},
        **_base_kwargs(),
    )
    user = _user_of(messages)
    agent_block = user.split("</agent>")[0]
    for volatile in ("current_time", "tick", "step_count"):
        assert volatile not in agent_block
    assert '"step_count": 7' in user


# ------------------------ empty-block suppression -------------------------


def test_empty_contexts_render_no_block():
    """A disabled/uninitialized store yields ``{}``, which must not emit an
    empty block (nor claim memory is available in <capabilities>)."""
    messages = build_react_messages(
        agent_json={"name": "A"},
        memory_context={},
        todo_context={},
        **_base_kwargs(),
    )
    user = _user_of(messages)
    assert "<memory_context>" not in user
    assert "<todo_context>" not in user


def test_capabilities_reflect_explicit_flags_not_block_presence():
    """Capability flags come from the agent config, not from whether a context
    dict happened to be empty."""
    system = _system_of(
        build_react_messages(
            agent_json={"name": "A"},
            enable_memory=False,
            enable_todo_list=False,
            **_base_kwargs(),
        )
    )
    assert "- memory retrieval: disabled" in system
    assert "- task list (TODO): disabled" in system


# ------------------------ determinism -------------------------


def test_json_blocks_are_key_sorted():
    """Dict insertion order must not leak into the request bytes."""
    messages = build_react_messages(
        agent_json={"name": "A", "profile": {"zeta": 1, "alpha": 2}},
        **_base_kwargs(),
    )
    user = _user_of(messages)
    assert user.index('"alpha"') < user.index('"zeta"')


def test_identical_inputs_render_identical_messages():
    """Byte-stability across repeated renders — the cache's basic requirement."""
    first = build_react_messages(
        agent_json={"name": "A", "profile": {"z": 1, "a": 2}},
        turn_state={"tick": 60},
        memory_context={"memory_md": "m", "b": 1, "a": 2},
        **_base_kwargs(),
    )
    second = build_react_messages(
        agent_json={"name": "A", "profile": {"a": 2, "z": 1}},
        turn_state={"tick": 60},
        memory_context={"a": 2, "memory_md": "m", "b": 1},
        **_base_kwargs(),
    )
    assert first == second


# ------------------------ preamble block composition -------------------------


def test_preamble_blocks_compose_without_agent_name():
    """真实部件组合(替代已删除的 build_preamble 兼容 helper)。"""
    prompt = build_base_rules() + "\n\n" + build_capabilities_block()
    assert build_base_rules() in prompt
    assert "<capabilities>" in prompt
    # The agent name lives in <agent>, never in the preamble blocks.
    assert "Alice" not in prompt
    assert "ask_mode_rules" not in prompt


def test_capabilities_block_lists_tools_only_when_enabled():
    full = build_capabilities_block()
    assert "activate_skill" in full
    assert "memory_recent" in full
    assert "todo_add" in full

    bare = build_capabilities_block(
        enable_memory=False, enable_todo_list=False, disable_skills=True
    )
    for tool in ("activate_skill", "memory_recent", "todo_add"):
        assert tool not in bare
