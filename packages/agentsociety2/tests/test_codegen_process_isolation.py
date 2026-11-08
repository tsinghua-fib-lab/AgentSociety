"""Optional workers enforce resource limits and preserve data and concurrency."""

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from agentsociety2.config import Config
from agentsociety2.env import CodeGenRouter
from agentsociety2.env.router_codegen import CodeStage


@pytest.fixture(autouse=True)
def enable_process_backend(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", "process")
    monkeypatch.setenv("AGENTSOCIETY_CODE_EXEC_BACKEND", "process")


async def test_native_computation_is_killed_without_blocking_parent_loop(monkeypatch):
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    simple = "results['value'] = sum([2])\nresults['status'] = 'success'"
    assert (await CodeStage._execute_code(router, simple, {}, True))["success"]
    worker = router._codegen_pool.idle[-1]
    ticks = []

    async def heartbeat():
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.002)

    beat = asyncio.create_task(heartbeat())
    monkeypatch.setattr(Config, "CODE_EXEC_TIMEOUT", 0.04)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            await CodeStage._execute_code(
                router,
                "value = sum(range(10**9))\nresults['status'] = 'success'",
                {},
                True,
            )
    finally:
        beat.cancel()
        await asyncio.gather(beat, return_exceptions=True)
    assert time.monotonic() - started < 1
    assert len(ticks) >= 3
    assert worker.process.poll() is not None
    assert (await CodeStage._execute_code(router, simple, {}, True))["success"]
    assert router._codegen_pool.idle[-1].process.pid != worker.process.pid


async def test_worker_memory_limit_rejects_large_native_allocation(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_MEMORY_MIB", 128)
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "values = np.empty(128*1024*1024, dtype=np.uint8)\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, True)
    assert not result["success"]
    assert (
        "allocat" in result["error"].lower()
        or result.get("error_type") == "MemoryError"
    )
    assert (
        await CodeStage._execute_code(router, "results['status'] = 'success'", {}, True)
    )["success"]


async def test_worker_returns_nested_context_updates_with_literal_type_tags():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    ctx = {"rows": [{"id": 1}, {"id": 2}], "literal": {"t": "code", "v": 3}}
    result = await CodeStage._execute_code(
        router,
        "for row in ctx['rows']:\n    row['seen'] = True\n"
        "results['value'] = ctx['literal']['v']\nresults['status'] = 'success'",
        ctx,
        True,
    )
    assert result["success"] and result["results"]["value"] == 3
    assert ctx == {
        "rows": [{"id": 1, "seen": True}, {"id": 2, "seen": True}],
        "literal": {"t": "code", "v": 3},
    }


async def test_numpy_array_and_integer_mapping_keys_survive_tool_bridge():
    async def read():
        return {1: np.array([2, 3], dtype=np.int16), "tuple": (4, 5)}

    read._tool_info = {"readonly": True}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(read=read)}
    source = "data = await modules['Tool'].read()\nresults['value'] = int(np.sum(data[1])) + sum(data['tuple'])\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, True)
    assert result["success"] and result["results"]["value"] == 14


async def test_worker_environment_excludes_api_credentials(monkeypatch):
    monkeypatch.setenv("OWNED_SECRET_API_KEY", "synthetic-secret-marker")
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    await CodeStage._execute_code(
        router, "results['value'] = sum([2])\nresults['status'] = 'success'", {}, True
    )
    worker = router._codegen_pool.idle[-1]
    environment = Path(f"/proc/{worker.process.pid}/environ").read_bytes()
    assert b"OWNED_SECRET_API_KEY" not in environment
    assert b"AGENTSOCIETY_LLM_API_KEY" not in environment
    assert b"OPENBLAS_NUM_THREADS=1" in environment


async def test_slow_tools_remain_concurrent_without_numerical_worker_slots():
    entered, peak = 0, 0
    release = asyncio.Event()

    async def read(identifier):
        nonlocal entered, peak
        entered += 1
        peak = max(peak, entered)
        if entered == 5:
            release.set()
        await asyncio.wait_for(release.wait(), 2)
        return identifier

    read._tool_info = {"readonly": True}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(read=read)}
    source = "results['value'] = await modules['Tool'].read(ctx['id'])\nresults['status'] = 'success'"
    results = await asyncio.gather(
        *(CodeStage._execute_code(router, source, {"id": i}, True) for i in range(5))
    )
    assert peak == 5
    assert [r["results"]["value"] for r in results] == list(range(5))
    assert not hasattr(router, "_codegen_pool")
