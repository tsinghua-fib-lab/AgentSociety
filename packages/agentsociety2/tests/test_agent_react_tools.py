from datetime import datetime
from pathlib import Path

from agentsociety2.agent.base.agent import AgentBase


class _DummySkillRuntime:
    def activate_skill(self, skill_name: str):
        return False, "", ""


class _DummyAgent(AgentBase):
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


async def test_activate_skill_failure_reports_reason():
    agent = _DummyAgent()
    agent.skill_runtime = _DummySkillRuntime()

    result = await agent.dispatch_react_tool(
        "activate_skill",
        {"skill_name": "does-not-exist"},
    )

    assert result.ok is False
    assert result.observation
    assert "does-not-exist" in result.observation
    assert result.data["error"]


# ------------------------ text-encoded tool-call parsing ----------------------


def _parse(content: str):
    agent = _DummyAgent()
    return agent._parse_text_tool_calls(content)


def test_parse_text_kwarg_style_call():
    """Python-kwarg style — the most common shape from non-native models."""
    calls = _parse('ask_env(instruction="go home", readonly=false)')
    assert calls == [("ask_env", {"instruction": "go home", "readonly": False})]


def test_parse_text_json_function_call():
    calls = _parse('finish({"answer": "left"})')
    assert calls == [("finish", {"answer": "left"})]


def test_parse_text_json_with_code_fence_and_prose():
    """Prose + fenced JSON must still yield the call (json_repair path)."""
    calls = _parse(
        'I will finish now.\n```json\n{"name": "finish", "arguments": {"answer": "ok"}}\n```'
    )
    assert calls == [("finish", {"answer": "ok"})]


def test_parse_text_bare_json_object():
    calls = _parse('{"name": "read", "arguments": {"path": "a.txt"}}')
    assert calls == [("read", {"path": "a.txt"})]


def test_parse_text_bare_json_tool_key_variant():
    calls = _parse('{"tool": "read", "args": {"path": "b.txt"}}')
    assert calls == [("read", {"path": "b.txt"})]


def test_parse_text_xml_invoke():
    calls = _parse(
        '<invoke name="move_to">\n<parameters>{"destination": "mall"}</parameters>\n</invoke>'
    )
    assert calls == [("move_to", {"destination": "mall"})]


def test_parse_text_plain_prose_yields_no_calls():
    calls = _parse("I think the best plan is to walk to the park and relax.")
    assert calls == []


def test_parse_text_malformed_fragments_are_skipped_not_raised():
    calls = _parse('ask_env(instruction="unclosed')
    assert calls == []
