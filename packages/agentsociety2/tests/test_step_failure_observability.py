"""Phase 1.8a + 0.5:step 失败保状态与失败记录可观测。

覆盖三个行为:
- runner: step 抛错后仍尽力 to_workspace 持久化已推进的状态,错误与
  state_persisted 标志随结果返回;from_workspace 阶段的失败不误报 persisted
- society: tick 部分失败时,每个失败 agent 一行写入 core_step_failures
  replay 表(含 step/时间/agent_id/是否持久化/错误文本),并更新计数;
  replay 写入失败不得吞掉 tick 的 RuntimeError
- (CLI 状态语义由 pid.json 集成测试路径覆盖;此处测 society 侧计数器)
"""

from datetime import datetime
from typing import ClassVar

import pytest

from agentsociety2.agent.runner import _step_agent_batch_async
from agentsociety2.society.society import AgentSociety
from agentsociety2.storage import TableSchema

# ----------------------------- runner failure path --------------------------


class _FailingAgent:
    """from_workspace 成功、step 抛错的桩 agent,记录 to_workspace 调用。"""

    persisted: ClassVar[list] = []  # 类级记录,跨实例共享

    def __init__(self) -> None:
        self.closed = False

    @classmethod
    async def from_workspace(cls, ws, service_proxy):
        return cls()

    async def step(self, tick, t):
        raise RuntimeError("LLM exploded mid-step")

    async def to_workspace(self, ws):
        _FailingAgent.persisted.append(ws)

    async def close(self):
        self.closed = True


class _BrokenFromWorkspaceAgent:
    """from_workspace 就失败的桩 agent——无法持久化任何状态。"""

    @classmethod
    async def from_workspace(cls, ws, service_proxy):
        raise RuntimeError("workspace corrupted")

    async def step(self, tick, t):  # pragma: no cover - never reached
        raise AssertionError

    async def to_workspace(self, ws):  # pragma: no cover - never reached
        raise AssertionError

    async def close(self):  # pragma: no cover - never reached
        raise AssertionError


@pytest.mark.asyncio
async def test_failed_step_still_persists_state(tmp_path, monkeypatch):
    _FailingAgent.persisted.clear()
    monkeypatch.setattr(
        "agentsociety2.agent.runner._resolve_agent_class",
        lambda name, root: _FailingAgent,
    )
    ws = tmp_path / "agent_0001"
    ws.mkdir()

    results = await _step_agent_batch_async(
        [1], str(tmp_path), "FailingAgent", 1, datetime(2026, 1, 1), None
    )

    assert len(results) == 1
    r = results[0]
    assert r["ok"] is False
    assert "LLM exploded" in r["error"]
    # 关键断言:失败后状态仍被持久化,且如实报告。
    assert _FailingAgent.persisted == [ws]
    assert r["state_persisted"] is True


@pytest.mark.asyncio
async def test_from_workspace_failure_reports_not_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentsociety2.agent.runner._resolve_agent_class",
        lambda name, root: _BrokenFromWorkspaceAgent,
    )
    results = await _step_agent_batch_async(
        [1], str(tmp_path), "BrokenAgent", 1, datetime(2026, 1, 1), None
    )
    r = results[0]
    assert r["ok"] is False
    assert "workspace corrupted" in r["error"]
    # 没有 agent 实例就没有可持久化状态,必须报 False 而不是缺省 True。
    assert r["state_persisted"] is False


@pytest.mark.asyncio
async def test_to_workspace_after_failure_does_not_mask_error(tmp_path, monkeypatch):
    """持久化本身也炸时,错误仍是 step 的原始错误,不是持久化的错误。"""

    class _DoubleFailureAgent(_FailingAgent):
        async def to_workspace(self, ws):  # pragma: no cover - raises
            raise RuntimeError("disk full during best-effort save")

    monkeypatch.setattr(
        "agentsociety2.agent.runner._resolve_agent_class",
        lambda name, root: _DoubleFailureAgent,
    )
    results = await _step_agent_batch_async(
        [1], str(tmp_path), "DoubleFailureAgent", 1, datetime(2026, 1, 1), None
    )
    r = results[0]
    assert r["ok"] is False
    # 报的是 step 的错,不是 save 的错;persisted 如实为 False。
    assert "LLM exploded" in r["error"]
    assert r["state_persisted"] is False


# --------------------------- society failure records -------------------------


class _StubReplayWriter:
    """记录 write() 调用的最小 replay writer 桩。"""

    def __init__(self) -> None:
        self.tables: dict[str, list[TableSchema]] = {}
        self.datasets: list = []
        self.rows: dict[str, list[dict]] = {}

    async def register_table(self, schema):
        self.tables.setdefault(schema.name, []).append(schema)

    async def register_dataset(self, spec, columns):
        self.datasets.append(spec)

    async def write(self, table, row):
        self.rows.setdefault(table, []).append(dict(row))


def _bare_society(replay_writer) -> AgentSociety:
    """不跑 __init__ 的最小 AgentSociety——只挂本测试触及的字段。"""
    soc = object.__new__(AgentSociety)
    soc._replay_writer = replay_writer
    soc._step_failures_ready = False
    soc._step_failure_count = 0
    return soc


@pytest.mark.asyncio
async def test_record_step_failures_writes_rows_and_counts():
    writer = _StubReplayWriter()
    soc = _bare_society(writer)

    await soc._record_step_failures(
        3,
        datetime(2026, 1, 1, 9, 0),
        [
            {"id": 1, "error": "RuntimeError('boom')", "state_persisted": True},
            {"id": 2, "error": "TimeoutError()", "state_persisted": False},
        ],
    )

    from agentsociety2.storage.replay_metadata import STEP_FAILURE_TABLE_NAME

    rows = writer.rows[STEP_FAILURE_TABLE_NAME]
    assert len(rows) == 2
    assert rows[0] == {
        "step": 3,
        "t": datetime(2026, 1, 1, 9, 0),
        "agent_id": 1,
        "state_persisted": True,
        "error": "RuntimeError('boom')",
    }
    assert rows[1]["agent_id"] == 2 and rows[1]["state_persisted"] is False
    assert soc._step_failure_count == 2
    # 幂等注册:两次调用只注册一次表。
    assert len(writer.tables[STEP_FAILURE_TABLE_NAME]) == 1


@pytest.mark.asyncio
async def test_record_step_failures_survives_replay_errors():
    """replay 写入炸掉不得抛——不能把 tick 原本的 RuntimeError 顶掉。"""

    class _ExplodingWriter(_StubReplayWriter):
        async def write(self, table, row):
            raise RuntimeError("replay unavailable")

    soc = _bare_society(_ExplodingWriter())
    await soc._record_step_failures(
        1,
        datetime(2026, 1, 1, 9, 0),
        [{"id": 1, "error": "x", "state_persisted": False}],
    )
    assert soc._step_failure_count == 1  # 计数仍前进


@pytest.mark.asyncio
async def test_record_step_failures_noop_without_writer():
    """replay 关闭(enable_replay=False)时静默跳过,计数仍前进。"""
    soc = _bare_society(None)
    await soc._record_step_failures(
        1,
        datetime(2026, 1, 1, 9, 0),
        [{"id": 1, "error": "x", "state_persisted": False}],
    )
    assert soc._step_failure_count == 1


async def test_crashed_batch_records_every_affected_agent_and_waits_for_siblings(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import agentsociety2.society.society as society_module

    society = object.__new__(AgentSociety)
    society._agent_ids = [1, 2, 3, 4]
    society._batch_size = 2
    society._workspace_root = tmp_path
    society._agent_class_name = "Probe"
    society._t = datetime(2026, 1, 1)
    society._step_count = 0
    society._replay_writer = None
    society._env_router = SimpleNamespace(set_current_time=lambda t: None)
    siblings_finished = []
    recorded = []

    async def proxy():
        return None

    async def await_ref(ids):
        if ids[0] == 1:
            raise RuntimeError("worker lost")
        import asyncio

        await asyncio.sleep(0)
        siblings_finished.append(ids)
        return {"results": [{"id": aid, "ok": True} for aid in ids]}

    async def record(step, t, failures):
        recorded.extend(failures)

    society._resolve_service_proxy = proxy
    society._await_ref = await_ref
    society._record_step_failures = record
    monkeypatch.setattr(
        society_module, "step_agent_batch", SimpleNamespace(remote=lambda ids, *a: ids)
    )
    with pytest.raises(RuntimeError, match="worker lost"):
        await society.step(1)
    assert siblings_finished == [[3, 4]]
    assert [item["id"] for item in recorded] == [1, 2]
    assert all(item["state_persisted"] is False for item in recorded)
    assert society._step_count == 0
