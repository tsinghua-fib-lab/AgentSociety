"""故障注入：保存失败不能提交总进度，也不能继续报告实验成功。"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agentsociety2.env.router_base import RouterBase
from agentsociety2.society.society import AgentSociety


@pytest.mark.asyncio
async def test_router_reports_failure_after_other_modules_finish(tmp_path):
    broken = SimpleNamespace(
        name="broken", to_workspace=AsyncMock(side_effect=OSError("disk full"))
    )
    healthy = SimpleNamespace(name="healthy", to_workspace=AsyncMock())
    router = SimpleNamespace(
        _env_workspace_root=tmp_path, env_modules=[broken, healthy]
    )
    with pytest.raises(RuntimeError, match="broken"):
        await RouterBase.to_workspaces(router)
    healthy.to_workspace.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_environment_save_preserves_society_checkpoint(tmp_path):
    checkpoint = tmp_path / "SOCIETY_STEP.json"
    checkpoint.write_text('{"step_count": 3}')
    soc = object.__new__(AgentSociety)
    soc._run_dir = tmp_path
    soc._env_router = SimpleNamespace(
        to_workspaces=AsyncMock(side_effect=OSError("disk full"))
    )
    soc._write_society_step_json = Mock()
    with pytest.raises(OSError, match="disk full"):
        await soc.to_workspace()
    soc._write_society_step_json.assert_not_called()
    assert json.loads(checkpoint.read_text()) == {"step_count": 3}


@pytest.mark.asyncio
async def test_cli_stops_on_step_failure_and_records_failed(tmp_path, monkeypatch):
    from agentsociety2.society import cli

    runner = cli.ExperimentRunner(tmp_path / "run")
    monkeypatch.setattr(runner, "_validate_environment", lambda: None)
    monkeypatch.setattr(runner, "_update_progress", lambda: None)
    monkeypatch.setattr(runner, "_log_llm_stats", lambda: None)
    monkeypatch.setattr(runner, "_build_agent_specs", lambda args: ([], "PersonAgent"))
    config = SimpleNamespace(
        env_modules=[],
        agents=[],
        codegen_router=SimpleNamespace(final_summary_enabled=False),
    )
    monkeypatch.setattr(runner, "_load_config", lambda path: config)
    steps = tmp_path / "steps.yaml"
    steps.write_text(
        'start_t: "2018-06-13T23:30:00"\nsteps:\n  - type: run\n    num_steps: 1\n    tick: 900\n  - type: run\n    num_steps: 1\n    tick: 900\n'
    )
    soc = SimpleNamespace(
        init=AsyncMock(),
        run=AsyncMock(side_effect=OSError("checkpoint unavailable")),
        close=AsyncMock(),
        mark_step_completed=Mock(),
        current_time=datetime(2018, 6, 13, 23, 30),
        _step_failure_count=0,
    )
    monkeypatch.setattr(cli, "AgentSociety", Mock(return_value=soc))
    monkeypatch.setattr(
        cli,
        "get_env_router_actor_class",
        Mock(return_value=SimpleNamespace(remote=Mock())),
    )
    monkeypatch.setattr(cli, "EnvRouterProxy", Mock())
    monkeypatch.setattr(
        "agentsociety2.config.llm_dispatcher.init_dispatchers", AsyncMock()
    )
    monkeypatch.setattr(
        "agentsociety2.config.llm_dispatcher.build_client_for_role", Mock()
    )
    monkeypatch.setattr("agentsociety2.agent.service_proxy.build_service_proxy", Mock())
    with pytest.raises(OSError, match="checkpoint unavailable"):
        await runner.run(tmp_path / "config.json", steps)
    soc.run.assert_awaited_once()
    soc.close.assert_awaited_once()
    soc.mark_step_completed.assert_not_called()
    status = json.loads(runner.pid_file.read_text())
    assert status["status"] == "failed"
    assert "checkpoint unavailable" in status["error"]
