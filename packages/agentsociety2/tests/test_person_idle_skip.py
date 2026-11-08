"""PersonAgent 闲置跳过(Reflex 快路径)测试。

T1 实测依据:全部深夜 slot 问卷 80/80 回答 sleep——睡眠段的 run step
是"花钱让模型说我在睡觉"。开启 idle_skip_enabled 后,pre_step hook 判定
睡眠段时 run step 跳过 observe + react 循环,写一条合成记忆;问卷
(ask 路径)不受影响;一切失败形态回退完整 ReAct(fail-open)。
"""

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from agentsociety2.agent.person import PersonAgent


class _StubMemoryRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def after_step(self, **kwargs):
        self.calls.append(kwargs)
        return [{"id": "m1"}]


class _Probe(PersonAgent):
    """绕过 __init__ 的探针 agent,只挂 step() 触及的成员。"""

    def __init__(self, pre_hooks, *, idle_skip=True):
        self._idle_skip_enabled = idle_skip
        self._pre_hooks = pre_hooks
        self._step_count = 0
        self._current_time = None
        self._env = None
        self._memory_runtime = _StubMemoryRuntime()
        self._react_called = False
        self._last_finish_memories = None
        self.skill_runtime = SimpleNamespace(visible_skill_count=lambda: 0)

    async def _ensure_initialized(self):
        return None

    def _refresh_visible_skills(self):
        return None

    async def run_lifecycle_hooks(self, hook_type, *, tick, t):
        return list(self._pre_hooks) if hook_type == "pre_step" else []

    async def run_react_loop(self, **kwargs):
        self._react_called = True
        return "react-result"

    def trace_span(self, name, **kwargs):
        span = SimpleNamespace(attributes=kwargs.get("attributes", {}))
        import contextlib

        @contextlib.contextmanager
        def _cm():
            yield span

        return _cm()


def _sleep_hook(start="23:00", end="07:00", activity="sleep"):
    output = yaml.safe_dump(
        {
            "ok": True,
            "skill": "daily-guidance",
            "active_segment": {
                "id": "seg-3",
                "activity": activity,
                "location_policy": "stay at home",
                "start": start,
                "end": end,
            },
            "guidance": "…",
        }
    )
    return {
        "skill_id": "built-in@daily-guidance",
        "hook_type": "pre_step",
        "ok": True,
        "output": output,
    }


@pytest.mark.asyncio
async def test_sleep_segment_skips_react_and_writes_synthetic_memory():
    agent = _Probe([_sleep_hook()])
    t = datetime(2026, 10, 19, 23, 30)
    result = await agent.step(1, t)

    assert agent._react_called is False
    assert "[idle-skip] sleep" in result
    assert "23:00" in result and "07:00" in result
    mem = agent._memory_runtime.calls
    assert len(mem) == 1
    episode = mem[0]["finish_memories"][0]
    assert episode["type"] == "observation"
    assert episode["keywords"] == ["sleep", "idle-skip"]
    assert "per the daily plan" in episode["text"]


@pytest.mark.asyncio
async def test_work_segment_goes_through_react():
    agent = _Probe([_sleep_hook(activity="work", start="09:00", end="12:00")])
    await agent.step(1, datetime(2026, 10, 19, 10, 0))
    assert agent._react_called is True


@pytest.mark.asyncio
async def test_disabled_never_skips_even_on_sleep():
    agent = _Probe([_sleep_hook()], idle_skip=False)
    await agent.step(1, datetime(2026, 10, 19, 23, 30))
    assert agent._react_called is True


@pytest.mark.asyncio
async def test_malformed_hook_output_falls_back_to_react():
    bad = {
        "skill_id": "x",
        "hook_type": "pre_step",
        "ok": True,
        "stdout": "{{{ not yaml",
    }
    agent = _Probe([bad])
    await agent.step(1, datetime(2026, 10, 19, 23, 30))
    assert agent._react_called is True


@pytest.mark.asyncio
async def test_no_active_segment_falls_back_to_react():
    gap = {
        "skill_id": "built-in@daily-guidance",
        "hook_type": "pre_step",
        "ok": True,
        "stdout": yaml.safe_dump(
            {
                "ok": True,
                "skill": "daily-guidance",
                "note": "no segment covers the current time",
            }
        ),
    }
    agent = _Probe([gap])
    await agent.step(1, datetime(2026, 10, 19, 23, 30))
    assert agent._react_called is True
