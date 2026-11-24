"""故障注入：保存失败不能提交总进度，也不能继续报告实验成功。"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agentsociety2.env.router_base import RouterBase


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
async def test_cli_records_failure_before_stats_and_recreates_artifacts(
    tmp_path, monkeypatch
):
    from agentsociety2.society import cli

    runner = cli.ExperimentRunner(tmp_path / "run")
    runner.artifacts_dir.mkdir()
    (runner.artifacts_dir / "old.md").write_text("old", encoding="utf-8")

    def check_stats_order():
        assert json.loads(runner.pid_file.read_text())["status"] == "failed"

    monkeypatch.setattr(runner, "_validate_environment", lambda: None)
    monkeypatch.setattr(runner, "_update_progress", lambda: None)
    monkeypatch.setattr(runner, "_log_llm_stats", check_stats_order)
    monkeypatch.setattr(runner, "_build_agent_specs", lambda args: ([], "PersonAgent"))
    config = SimpleNamespace(
        env_modules=[],
        agents=[],
        codegen_router=SimpleNamespace(final_summary_enabled=False),
    )
    monkeypatch.setattr(runner, "_load_config", lambda path: config)
    steps = tmp_path / "steps.yaml"
    steps.write_text(
        'start_t: "2018-06-13T23:30:00"\nsteps:\n'
        '  - type: ask\n    question: "How are things?"\n'
        "  - type: run\n    num_steps: 1\n    tick: 900\n"
        "  - type: run\n    num_steps: 1\n    tick: 900\n"
    )
    soc = SimpleNamespace(
        init=AsyncMock(),
        ask=AsyncMock(return_value="Fine"),
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
    replay = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        "agentsociety2.storage.replay_proxy.ReplayProxy", Mock(return_value=replay)
    )
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    with pytest.raises(OSError, match="checkpoint unavailable"):
        await runner.run(config_path, steps, overwrite=True)
    soc.run.assert_awaited_once()
    soc.close.assert_awaited_once()
    replay.close.assert_awaited_once()
    soc.mark_step_completed.assert_called_once_with(0)
    artifacts = list(runner.artifacts_dir.iterdir())
    assert len(artifacts) == 1
    assert artifacts[0].name.startswith("ask_step_0_")
    assert "Fine" in artifacts[0].read_text(encoding="utf-8")
    status = json.loads(runner.pid_file.read_text())
    assert status["status"] == "failed"
    assert "checkpoint unavailable" in status["error"]
