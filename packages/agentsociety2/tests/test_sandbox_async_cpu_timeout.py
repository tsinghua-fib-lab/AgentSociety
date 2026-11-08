"""Async generated programs enforce CPU-loop deadlines and allow normal tools."""

from __future__ import annotations

import asyncio
import time

import pytest

from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage

pytestmark = pytest.mark.asyncio


class _FakeAsyncTool:
    """沙箱可 await 的假环境工具(async 形态载体,零副作用)。"""

    async def get_status(self, agent_id):
        return {"status": "success", "aoi_id": 1}


async def _make_router():
    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    _FakeAsyncTool.get_status._tool_info = {"readonly": True}
    router._modules = {"MobilitySpace": _FakeAsyncTool()}
    return router


async def test_async_cpu_loop_hits_timeout(monkeypatch):
    from agentsociety2.config import Config

    monkeypatch.setattr(Config, "CODE_EXEC_TIMEOUT", 0.05)
    """含 await 的纯 CPU 大循环必须被 timeout 打断(修复前永久挂死)。"""
    router = await _make_router()
    code = (
        "i = 0\n"
        "response = await modules['MobilitySpace'].get_status(ctx['id'])\n"
        "while i < 10**12:\n"
        "    i += 1\n"
        "results['count'] = i\n"
        "results['status'] = 'success'"
    )
    t0 = time.monotonic()
    # 修复后行为:超时以 TimeoutError 抛出(与同步路径同语义);
    # 修复前:此处永久挂死(wait_for 的 timer 永不触发)。
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            CodeStage._execute_code(router, code, {"id": 1}, readonly=True),
            timeout=2,
        )
    elapsed = time.monotonic() - t0
    assert elapsed < 1, f"CPU 循环未被超时打断: {elapsed:.1f}s(修复前永久挂死)"


async def test_async_normal_tool_call_still_works():
    """正常 async 工具调用路径不受修复影响。"""
    router = await _make_router()
    code = (
        "response = await modules['MobilitySpace'].get_status(ctx['id'])\n"
        "status = response.get('status', 'success') if isinstance(response, dict) else 'success'\n"
        "if status == 'success':\n"
        "    loc = response.get('aoi_id')\n"
        '    print(f"Checked the agent\'s status: it is currently at AOI {loc} and idle.")\n'
        "    outcome = 'success'\n"
        "else:\n"
        "    print('Could not read the agent\\'s status from the environment.')\n"
        "    outcome = 'fail'\n"
        "    results['reason'] = response.get('reason', 'The tool reported a failure.')\n"
        "results['status'] = outcome"
    )
    res = await CodeStage._execute_code(router, code, {"id": 1}, readonly=True)
    assert res.get("success") is True
    assert "AOI 1" in res.get("output", "")
