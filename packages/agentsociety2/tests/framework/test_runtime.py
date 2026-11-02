import json

import pytest

from agentsociety2.agent.base.skill_registry import SkillRegistry
from agentsociety2.agent.base.skill_runtime import AgentSkillRuntime
from agentsociety2.agent.base.workspace_fs import WorkspaceFS
from agentsociety2.trace import JsonlTraceWriter, ShardedTraceWriter


def _bind_runtime_workspace(runtime, tmp_path, agent_id):
    workspace = tmp_path / "agents" / f"agent_{agent_id:04d}"
    workspace.mkdir(parents=True)
    for rel in ("state", "memory"):
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    runtime.bind_workspace(
        workspace_root=workspace,
        fs=WorkspaceFS(workspace),
        trace_writer=JsonlTraceWriter(
            agent_id=agent_id,
            sharded_writer=ShardedTraceWriter(tmp_path / "trace"),
        ),
    )
    return workspace


def test_runtime_visible_catalog_and_skill_files(tmp_path):
    registry = SkillRegistry()
    registry.scan_builtin()
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 13)

    runtime.set_visible_skills(["built-in@daily-guidance", "built-in@memory"])
    catalog = runtime.skill_catalog()

    assert {item["name"] for item in catalog} == {"daily-guidance"}
    assert "# Daily Guidance" in runtime.load_skill_doc("built-in@daily-guidance")
    assert "# Daily Guidance Examples" in runtime.read_skill_file(
        "built-in@daily-guidance",
        "references/examples.md",
    )
    assert runtime.load_skill_doc("built-in@plan") == ""


@pytest.mark.asyncio
async def test_runtime_run_skill_script_uses_explicit_script_path(tmp_path):
    skill_root = tmp_path / "skills" / "echo"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: echo\n"
        "description: echo argv\n"
        "---\n",
        encoding="utf-8",
    )
    (skill_root / "run.py").write_text(
        "import json, sys\n"
        "open('argv.json','w').write(json.dumps(sys.argv[1:]))\n"
        "print('|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    registry.scan_custom(tmp_path / "skills")
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 14)
    runtime.set_visible_skills(["custom@echo"])

    result = await runtime.run_skill_script(
        "custom@echo",
        "run.py",
        ["--flag", "value"],
    )

    assert result.ok
    assert result.stdout.strip() == "--flag|value"
    assert json.loads(runtime.fs.read_text("argv.json")) == ["--flag", "value"]
    assert "--args-json" not in result.stdout

    escaped = await runtime.run_skill_script(
        "custom@echo",
        "../outside.py",
        [],
    )
    assert not escaped.ok
    assert escaped.error_type == "validation"


@pytest.mark.asyncio
async def test_runtime_run_skill_script_uses_default_script(tmp_path):
    skill_root = tmp_path / "skills" / "echo"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: echo\n"
        "description: echo argv\n"
        "script: run.py\n"
        "---\n",
        encoding="utf-8",
    )
    (skill_root / "run.py").write_text(
        "import sys\n"
        "print('|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    registry.scan_custom(tmp_path / "skills")
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 15)
    runtime.set_visible_skills(["custom@echo"])

    result = await runtime.run_skill_script("custom@echo", "", ["--flag", "value"])

    assert result.ok
    assert result.stdout.strip() == "--flag|value"


@pytest.mark.asyncio
async def test_runtime_run_skill_script_maps_default_script_basename(tmp_path):
    skill_root = tmp_path / "skills" / "echo"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: echo\n"
        "description: echo argv\n"
        "script: scripts/run.py\n"
        "---\n",
        encoding="utf-8",
    )
    (skill_root / "scripts").mkdir()
    (skill_root / "scripts" / "run.py").write_text(
        "import sys\n"
        "print('|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    registry.scan_custom(tmp_path / "skills")
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 151)
    runtime.set_visible_skills(["custom@echo"])

    result = await runtime.run_skill_script("custom@echo", "run.py", ["--flag", "value"])

    assert result.ok
    assert result.stdout.strip() == "--flag|value"


def test_runtime_infers_single_active_script_skill(tmp_path):
    skill_root = tmp_path / "skills" / "echo"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: echo\n"
        "description: echo argv\n"
        "script: run.py\n"
        "---\n",
        encoding="utf-8",
    )
    (skill_root / "run.py").write_text("print('ok')\n", encoding="utf-8")

    registry = SkillRegistry()
    registry.scan_custom(tmp_path / "skills")
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 16)
    runtime.set_visible_skills(["custom@echo"])
    runtime.set_activated_skills(["custom@echo"])

    assert runtime.infer_single_script_skill_id() == "custom@echo"


def test_runtime_resolves_exact_visible_skill_id(tmp_path):
    registry = SkillRegistry()
    registry.scan_builtin()
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 17)
    runtime.set_visible_skills(["built-in@daily-guidance"])

    assert (
        runtime.resolve_skill_id("built-in@daily-guidance")
        == "built-in@daily-guidance"
    )


def test_runtime_uses_bound_workspace_fs(tmp_path):
    registry = SkillRegistry()
    registry.scan_builtin()
    runtime = AgentSkillRuntime(registry=registry)
    workspace = _bind_runtime_workspace(runtime, tmp_path, 11)

    runtime.fs.write_text("state/a.json", json.dumps({"x": 1}))
    assert runtime.fs.read_text("state/a.json") == '{"x": 1}'
    assert json.loads(runtime.fs.read_text("state/a.json")) == {"x": 1}
    assert [item.path for item in runtime.fs.list("state") if not item.is_dir] == [
        "state/a.json"
    ]

    with pytest.raises(ValueError):
        runtime.fs.write_text("../escape.txt", "blocked")

    assert runtime.workspace_root() == workspace.resolve()
