from pathlib import Path

from agentsociety2.agent.base.skill_registry import SkillDescriptor
from agentsociety2.agent.base.skill_runtime import AgentSkillRuntime
from agentsociety2.agent.base.tool_schema import react_tool_schemas
from agentsociety2.env.router_base import (
    _empty_env_skill_catalog,
    _env_skill_catalog_row,
)


class _Registry:
    def __init__(self) -> None:
        self.skill = SkillDescriptor(
            skill_id="env:MobilitySpace@mobility",
            name="mobility",
            namespace="env:MobilitySpace",
            description="Move around the city.",
            root=Path("."),
            source="env",
            source_label="test",
            script=None,
            hooks={},
        )

    def list_all(self):
        return [self.skill]

    def get(self, skill_id: str):
        return self.skill if skill_id == self.skill.skill_id else None

    def find_by_name(self, name: str):
        return [self.skill] if name == self.skill.name else []

    def read_skill_doc(self, skill_id: str):
        return ""

    def read_skill_file(self, skill_id: str, relative_path: str):
        return ""

    def list_hooks(self, hook_type: str):
        return []


def _tool_schema(name: str) -> dict:
    for tool in react_tool_schemas():
        if tool["function"]["name"] == name:
            return tool["function"]
    raise AssertionError(f"tool not found: {name}")


def test_skill_catalog_exposes_only_skill_name_to_model():
    runtime = AgentSkillRuntime(registry=_Registry())
    runtime.set_visible_skills(["env:MobilitySpace@mobility"])

    catalog = runtime.skill_catalog()

    assert catalog == [{"name": "mobility", "description": "Move around the city."}]
    assert "skill_id" not in catalog[0]


def test_env_skill_catalog_rows_hide_registry_skill_id(tmp_path: Path):
    skill_dir = tmp_path / "mobility"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: mobility\ndescription: Move around the city.\n---\n",
        encoding="utf-8",
    )

    row = _env_skill_catalog_row(skill_md, module_name="MobilitySpace")

    assert "env:MobilitySpace@mobility" not in row
    assert row == "| mobility | MobilitySpace | Move around the city. |"
    assert "skill_id" not in _empty_env_skill_catalog()


def test_ask_env_schema_requires_variables_for_forced_template_mode():
    ask_env = _tool_schema("ask_env")
    params = ask_env["parameters"]
    variables = params["properties"]["variables"]

    assert "variables" in params["required"]
    assert "template/cache mode" in ask_env["description"]
    assert "Required mapping" in variables["description"]


class _DocRegistry(_Registry):
    """Variant whose skills carry a non-empty SKILL.md body for activate()."""

    def read_skill_doc(self, skill_id: str):
        return f"# {self.skill.name}\n\nbody" if skill_id == self.skill.skill_id else ""


def test_resolve_skill_id_accepts_both_id_and_name():
    runtime = AgentSkillRuntime(registry=_Registry())
    runtime.set_visible_skills(["env:MobilitySpace@mobility"])

    assert (
        runtime.resolve_skill_id("env:MobilitySpace@mobility")
        == "env:MobilitySpace@mobility"
    )
    assert runtime.resolve_skill_id("mobility") == "env:MobilitySpace@mobility"
    assert runtime.resolve_skill_id("does-not-exist") == ""


def test_set_visible_skills_accepts_mixed_id_and_name():
    runtime = AgentSkillRuntime(registry=_Registry())

    runtime.set_visible_skills(["env:MobilitySpace@mobility", "mobility"])

    assert runtime.visible_skill_ids() == {"env:MobilitySpace@mobility"}


def test_set_visible_skills_accepts_name_before_visible():
    """名字在置 visible 前即可解析;未知名字静默跳过,不污染集合。"""
    runtime = AgentSkillRuntime(registry=_Registry())

    runtime.set_visible_skills(["mobility"])
    assert runtime.visible_skill_ids() == {"env:MobilitySpace@mobility"}
    runtime.set_visible_skills(["ghost"])
    assert runtime.visible_skill_ids() == set()


def test_activate_skill_accepts_both_id_and_name():
    runtime = AgentSkillRuntime(registry=_DocRegistry())
    runtime.set_visible_skills(["env:MobilitySpace@mobility"])

    activated_by_name, skill_id_name, doc_name = runtime.activate_skill("mobility")
    activated_by_id, skill_id_id, _doc_id = runtime.activate_skill(
        "env:MobilitySpace@mobility"
    )

    assert (activated_by_name, skill_id_name, bool(doc_name)) == (
        True,
        "env:MobilitySpace@mobility",
        True,
    )
    assert (activated_by_id, skill_id_id) == (True, "env:MobilitySpace@mobility")
    assert runtime.activated_skill_ids() == {"env:MobilitySpace@mobility"}


def test_deactivate_skill_accepts_both_id_and_name():
    runtime = AgentSkillRuntime(registry=_DocRegistry())
    runtime.set_visible_skills(["env:MobilitySpace@mobility"])
    runtime.activate_skill("env:MobilitySpace@mobility")
    assert runtime.activated_skill_ids() == {"env:MobilitySpace@mobility"}

    removed_by_name, skill_id_name = runtime.deactivate_skill("mobility")
    assert (removed_by_name, skill_id_name) == (True, "env:MobilitySpace@mobility")
    assert runtime.activated_skill_ids() == set()

    # Deactivating by id when already inactive reports removed=False but still resolves.
    runtime.activate_skill("mobility")
    removed_by_id, skill_id_id = runtime.deactivate_skill("env:MobilitySpace@mobility")
    assert (removed_by_id, skill_id_id) == (True, "env:MobilitySpace@mobility")
    assert runtime.activated_skill_ids() == set()
