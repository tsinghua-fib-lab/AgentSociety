"""2.5 配置自改通道正式化:update_config 工具的契约测试。

正式化前的裸奔状态(评审报告原话):config.json 是运行时"事实上的
自我修改通道"(模型可写、下次 restore 生效)但完全无护栏——坏值会让
restore 直接崩。本套件锁住正式化后的契约:
  - 白名单外键被拒(逐键原因),原配置不动
  - 白名单内非法值被拒(带具体约束说明)
  - 合法变更:备份快照 + 变更日志(old/new/step/time)+ config 落盘
  - 只读模式拒绝写入
  - 通用 workspace write 不再能直写 config.json(核心保护路径)
  - 坏 JSON 被拒
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from agentsociety2.agent.base.agent import AgentBase


class _Probe(AgentBase):
    """绕过 __init__ 的探针;workspace 用真实 tmp 目录。"""

    @classmethod
    def create(cls, *a, **k):  # pragma: no cover - abstract stub
        raise NotImplementedError

    @classmethod
    async def from_workspace(cls, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def to_workspace(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def ask(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def step(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


def _probe_agent(tmp_path: Path) -> tuple[_Probe, Path]:
    ws = tmp_path / "agent_0001"
    ws.mkdir(exist_ok=True)
    (ws / "config.json").write_text(
        json.dumps({"max_react_turns": 8, "idle_skip_enabled": False}),
        encoding="utf-8",
    )
    from agentsociety2.agent.base.workspace_fs import WorkspaceFS

    agent = object.__new__(_Probe)
    agent._workspace_fs = WorkspaceFS(ws)
    agent._config = json.loads((ws / "config.json").read_text())
    agent._step_count = 3
    agent._current_time = datetime(2026, 10, 19, 12, 0)
    return agent, ws


@pytest.mark.asyncio
async def test_valid_update_writes_logs_and_backs_up(tmp_path):
    agent, ws = _probe_agent(tmp_path)
    r = await agent._update_config_tool(
        '{"max_react_turns": 5, "idle_skip_enabled": true}', readonly=False
    )
    assert r.ok is True
    # config 落盘
    saved = json.loads((ws / "config.json").read_text())
    assert saved["max_react_turns"] == 5
    assert saved["idle_skip_enabled"] is True
    # 变更日志
    log = [
        json.loads(line)
        for line in (ws / "config_changes.jsonl").read_text().splitlines()
    ]
    assert log[-1]["changes"]["max_react_turns"] == {"old": 8, "new": 5}
    assert log[-1]["step"] == 3
    # 备份快照存在且为旧值
    backups = list(ws.glob("config_backup_*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["max_react_turns"] == 8


@pytest.mark.asyncio
async def test_unknown_key_rejected_atomically(tmp_path):
    agent, ws = _probe_agent(tmp_path)
    before = (ws / "config.json").read_text()
    r = await agent._update_config_tool(
        '{"max_react_turns": 2, "evil_key": "x"}', readonly=False
    )
    assert r.ok is False
    assert "evil_key" in r.observation
    # 原子性:合法部分也不应用
    assert (ws / "config.json").read_text() == before
    assert not list(ws.glob("config_backup_*"))
    assert not (ws / "config_changes.jsonl").exists()


@pytest.mark.asyncio
async def test_invalid_value_rejected_with_reason(tmp_path):
    agent, _ = _probe_agent(tmp_path)
    r = await agent._update_config_tool('{"max_react_turns": 99}', readonly=False)
    assert r.ok is False
    assert "1..20" in r.observation
    r2 = await agent._update_config_tool('{"enable_memory": "yes"}', readonly=False)
    assert r2.ok is False
    assert "布尔值" in r2.observation


@pytest.mark.asyncio
async def test_readonly_mode_rejects(tmp_path):
    agent, _ = _probe_agent(tmp_path)
    r = await agent._update_config_tool('{"max_react_turns": 5}', readonly=True)
    assert r.ok is False
    assert "readonly" in r.observation


@pytest.mark.asyncio
async def test_bad_json_rejected(tmp_path):
    agent, _ = _probe_agent(tmp_path)
    r = await agent._update_config_tool("{not json", readonly=False)
    assert r.ok is False


@pytest.mark.asyncio
async def test_empty_object_rejected(tmp_path):
    agent, _ = _probe_agent(tmp_path)
    r = await agent._update_config_tool("{}", readonly=False)
    assert r.ok is False


def test_config_json_is_core_owned():
    """通用 workspace 工具不得直写 config.json(自改唯一通道=update_config)。"""
    assert AgentBase._is_core_owned_workspace_path("config.json") is True
    assert AgentBase._is_core_owned_workspace_path("./config.json") is True
    assert AgentBase._is_core_owned_workspace_path("notes.md") is False


def test_todo_state_files_are_core_owned():
    """TODO 状态实际文件必须受保护(2026-11-04 审计修复)。

    旧清单写的是 state/todos.json——从未存在的路径;真实文件是根目录
    TODO.json 与 state/todos_archive.jsonl(todo.py 的 TODO_STATE_PATH/
    TODO_ARCHIVE_PATH),此前 LLM 的 write/append 可直写。
    """
    assert AgentBase._is_core_owned_workspace_path("TODO.json") is True
    assert AgentBase._is_core_owned_workspace_path("./TODO.json") is True
    assert AgentBase._is_core_owned_workspace_path("state/todos_archive.jsonl") is True
    assert AgentBase._is_core_owned_workspace_path("todo_notes.md") is False


def test_core_owned_guard_blocks_bypass_forms():
    """三重绕过形态必须被拦(2026-11-06 审计:.. 归一化/大小写/嵌套)。"""
    assert AgentBase._is_core_owned_workspace_path("subdir/../AGENT.json") is True
    assert AgentBase._is_core_owned_workspace_path("agent.json") is True  # APFS
    assert AgentBase._is_core_owned_workspace_path("x/../memory/episodes.jsonl") is True
    assert AgentBase._is_core_owned_workspace_path("../outside.md") is False


def test_schema_covers_every_consumed_key():
    """白名单必须覆盖运行时实际消费的全部配置键(防键集漂移)。"""
    consumed = {
        "max_react_turns",
        "enable_todo_list",
        "disabled_skill_ids",
        "default_activated_skill_ids",
        "extra_skill_paths",
        "enable_memory",
        "memory_context_max_chars",
        "recent_memory_limit",
        "memory_consolidation_pending_threshold",
        "memory_consolidation_interval_steps",
        "memory_high_importance_threshold",
        "idle_skip_enabled",
    }
    from agentsociety2.agent.base.agent import _CONFIG_SCHEMA

    missing = consumed - set(_CONFIG_SCHEMA)
    assert not missing, f"白名单漏了消费键: {missing}"


@pytest.mark.parametrize("action", ["write", "append"])
@pytest.mark.parametrize("target_name", ["config.json", "TODO.json"])
async def test_core_owned_symlink_cannot_bypass_react_write_guard(
    tmp_path, action, target_name
):
    agent, workspace = _probe_agent(tmp_path)
    target = workspace / target_name
    if not target.exists():
        target.write_text("original")
    before = target.read_text()
    (workspace / "notes-link").symlink_to(target)
    result = await agent.dispatch_react_tool(
        action, {"path": "notes-link", "content": "replacement"}
    )
    assert result.data["core_owned"] is True
    assert target.read_text() == before
