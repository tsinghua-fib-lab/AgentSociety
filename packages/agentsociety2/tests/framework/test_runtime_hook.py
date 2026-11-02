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


@pytest.mark.asyncio
async def test_runtime_run_skill_hook_selects_hook_type(tmp_path):
    skill_root = tmp_path / "skills" / "hooks"
    skill_root.mkdir(parents=True)
    (skill_root / "pre.py").write_text(
        "import json, os, sys\n"
        "open(os.path.join(os.environ['AGENT_WORK_DIR'], 'pre.json'),'w').write(json.dumps({'argv': sys.argv[1:], 'skill': os.environ['SKILL_ID']}))\n",
        encoding="utf-8",
    )
    (skill_root / "post.py").write_text(
        "import os, sys\nopen(os.path.join(os.environ['AGENT_WORK_DIR'], 'post.txt'),'w').write('|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: hooks\n"
        "description: hook skill\n"
        "hooks:\n"
        "  pre_step: pre.py\n"
        "  post_step: post.py\n"
        "---\n",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    registry.scan_custom(tmp_path / "skills")
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 21)
    runtime.set_visible_skills(["custom@hooks"])

    pre = await runtime.run_skill_hook("custom@hooks", "pre_step", ["--x", "1"])
    post = await runtime.run_skill_hook("custom@hooks", "post_step", [])
    missing = await runtime.run_skill_hook("custom@hooks", "unknown", [])

    assert pre.ok
    assert post.ok
    assert not missing.ok
    assert missing.error_type == "validation"
    assert json.loads(runtime.fs.read_text("pre.json")) == {
        "argv": ["--x", "1"],
        "skill": "custom@hooks",
    }
    assert runtime.fs.read_text("post.txt") == ""


@pytest.mark.asyncio
async def test_runtime_run_skill_hook_requires_visible_skill(tmp_path):
    registry = SkillRegistry()
    registry.scan_builtin()
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path, 22)

    result = await runtime.run_skill_hook("built-in@daily-guidance", "pre_step", [])

    assert not result.ok
    assert result.error_type == "validation"
    assert "not visible" in result.stderr
