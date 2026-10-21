"""Unit tests for society LLM XML plan/answer parsing."""

from __future__ import annotations

from agentsociety2.society.helper import AgentSocietyHelper, PlanStep
from agentsociety2.society.llm_xml import (
    normalize_args,
    normalize_steps,
    parse_xml_object,
)


class _EnvironmentRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str, bool]] = []

    async def ask(self, ctx: dict, instruction: str, readonly: bool):
        self.calls.append((ctx, instruction, readonly))
        return {"status": "success"}, "done"


def test_parse_plan_xml_with_list_args() -> None:
    raw = """
    Here is the plan:
    ```xml
    <plan>
      <direct_answer>false</direct_answer>
      <reasoning>List then ask</reasoning>
      <steps>
        <step>
          <description>List agents</description>
          <tool>list_agents</tool>
          <args></args>
          <expected_output>roster</expected_output>
        </step>
        <step>
          <description>Ask Alice</description>
          <tool>ask_agents</tool>
          <args>
            <agent_ids>
              <item>1</item>
              <item>2</item>
            </agent_ids>
            <question>Who are you?</question>
          </args>
          <expected_output>answers</expected_output>
        </step>
      </steps>
    </plan>
    ```
    """
    helper = object.__new__(AgentSocietyHelper)
    data = helper._parse_plan_payload(raw)
    assert data["direct_answer"] is False
    assert len(data["steps"]) == 2
    steps = [PlanStep.model_validate(s) for s in data["steps"]]
    assert steps[0].tool == "list_agents"
    assert steps[0].args == {}
    assert steps[1].args["agent_ids"] == ["1", "2"] or steps[1].args["agent_ids"] == [
        1,
        2,
    ]
    # XML text nodes are strings; coerce path handles ints later.
    assert AgentSocietyHelper._coerce_agent_ids(steps[1].args["agent_ids"]) == [1, 2]


def test_parse_plan_xml_malformed_still_repairs() -> None:
    # Missing closing tags — xenon should repair.
    raw = """
    <plan>
      <direct_answer>true</direct_answer>
      <answer>Just Alice
    """
    helper = object.__new__(AgentSocietyHelper)
    data = helper._parse_plan_payload(raw)
    assert data["direct_answer"] is True
    assert "Just Alice" in str(data["answer"])


def test_parse_answer_xml() -> None:
    helper = object.__new__(AgentSocietyHelper)
    data = helper._parse_answer_payload(
        "<result><answer>Alice is curious.</answer></result>"
    )
    assert data["answer"] == "Alice is curious."


def test_normalize_steps_single_step_object() -> None:
    steps = normalize_steps({"step": {"description": "x", "tool": "list_agents"}})
    assert len(steps) == 1
    assert steps[0]["tool"] == "list_agents"
    assert normalize_args(None) == {}


def test_parse_xml_object_root() -> None:
    data = parse_xml_object(
        "<plan><reasoning>ok</reasoning><steps></steps></plan>", root_tag="plan"
    )
    assert data["reasoning"] == "ok"


def test_get_agent_profile_tool_from_specs() -> None:
    helper = object.__new__(AgentSocietyHelper)

    class _Society:
        def __init__(self) -> None:
            self.agent_specs = [
                {
                    "id": 1,
                    "profile": {
                        "id": 1,
                        "name": "Alice",
                        "personality": "curious",
                        "bio": "likes hiking",
                    },
                }
            ]

    helper._society = _Society()  # type: ignore[attr-defined]
    import asyncio

    out = asyncio.run(helper._tool_get_agent_profile(name="Alice"))
    assert out["id"] == 1
    assert out["profile"]["personality"] == "curious"
    missing = asyncio.run(helper._tool_get_agent_profile(name="Bob"))
    assert "error" in missing


def test_environment_access_propagates_readonly_mode() -> None:
    import asyncio

    helper = object.__new__(AgentSocietyHelper)
    router = _EnvironmentRouter()
    helper._env_router = router  # type: ignore[attr-defined]
    helper._register_tools()

    result = asyncio.run(
        helper._dispatch_tool(
            "ask_environment",
            {"question": "change the weather"},
            readonly=False,
        )
    )
    assert result == {"answer": "done", "context": {"status": "success"}}
    assert router.calls == [({}, "change the weather", False)]

    result = asyncio.run(
        helper._dispatch_tool(
            "ask_environment",
            {"question": "read the weather"},
            readonly=True,
        )
    )
    assert result == {"answer": "done", "context": {"status": "success"}}
    assert router.calls[-1] == ({}, "read the weather", True)
