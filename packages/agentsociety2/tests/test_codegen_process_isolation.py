"""Owner-loop effects, hard resource limits and data-only worker boundaries."""

from __future__ import annotations

import asyncio
import datetime
import time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from litellm import ModelResponse

from agentsociety2.config import Config
from agentsociety2.env import CodeGenRouter, EnvBase, tool
from agentsociety2.env.codegen_process import get_pool
from agentsociety2.env.codegen_wire import decode, encode
from agentsociety2.env.router_codegen import CodeStage


@pytest.fixture(autouse=True)
def enable_process_backend(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", "process")
    monkeypatch.setenv("AGENTSOCIETY_CODE_EXEC_BACKEND", "process")


class Counter(EnvBase):
    def __init__(self):
        super().__init__()
        self.value = 0
        self.calls = 0

    @classmethod
    def description(cls):
        return "Owned counter fixture."

    @classmethod
    def init_description(cls):
        return "No external services."

    @tool(readonly=False)
    async def add(self, amount: int) -> int:
        """Add an amount exactly once."""
        self.calls += 1
        self.value += amount
        return self.value

    @tool(readonly=False)
    async def add_then_raise(self, amount: int) -> int:
        """Mutate and fail to exercise an uncertain write outcome."""
        self.calls += 1
        self.value += amount
        raise ValueError("owned tool failure after write")

    @tool(readonly=True)
    async def read(self) -> int:
        """Read the owned counter."""
        return self.value

    async def step(self, tick, t):
        pass


CORRECTED = "await modules['Counter'].add(3)\nawait modules['Counter'].add(4)\nresults['counter'] = await modules['Counter'].read()\nresults['status'] = 'success'"


async def ask_outputs(outputs, readonly=False):
    environment = Counter()
    router = CodeGenRouter(
        env_modules=[environment],
        template_cache_enabled=False,
        final_summary_enabled=False,
        max_llm_call_retry=1,
    )
    await router.init(datetime.datetime(2026, 11, 7))
    responses = iter(outputs)
    injected = []

    async def completion(**kwargs):
        source = next(responses)
        injected.append(source)
        return ModelResponse(
            model="local-fixture",
            choices=[
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": source},
                }
            ],
        )

    router.acompletion_with_system_prompt = completion
    result, answer = await router.ask(
        {"id": 1, "outcome": None}, "Add 3 and 4 once", readonly=readonly
    )
    return environment, injected, result, answer


@pytest.mark.parametrize(
    "failure",
    [
        "await modules['Counter'].add(3)\nvalue = 1 / 0\nresults['status'] = 'success'",
        "await modules['Counter'].add(3)\nresults['status'] = ctx['outcome']",
        "await modules['Counter'].add_then_raise(3)\nresults['status'] = 'success'",
        "await modules['Counter'].add(3)\nctx['invalid_data'] = ValueError\nresults['status'] = 'success'",
    ],
)
async def test_failed_program_is_not_replayed_after_write_tool_attempt(failure):
    environment, injected, result, answer = await ask_outputs([failure, CORRECTED])
    assert environment.value == 3 and environment.calls == 1
    assert len(injected) == 1
    assert result["status"] == "error" and result["write_attempted"]
    assert "write-tool attempt" in answer


@pytest.mark.parametrize(
    "failure",
    [
        "results = {}\n" + CORRECTED,
        "value = 1 / 0\nresults['status'] = 'success'",
        "value = await modules['Counter'].read()\nvalue = 1 / 0\nresults['status'] = 'success'",
    ],
)
async def test_correction_can_retry_before_any_write(failure):
    environment, injected, result, _answer = await ask_outputs([failure, CORRECTED])
    assert environment.value == 7 and environment.calls == 2
    assert len(injected) == 2 and result["counter"] == 7


async def test_readonly_policy_is_enforced_at_tool_dispatch():
    environment = Counter()
    router = CodeGenRouter(env_modules=[environment], template_cache_enabled=False)
    result = await CodeStage._execute_code(router, CORRECTED, {}, True)
    assert not result["success"] and "readonly" in result["error"]
    assert (
        not result["write_attempted"]
        and environment.value == 0
        and environment.calls == 0
    )


async def test_unregistered_environment_methods_are_not_exposed():
    environment = Counter()
    router = CodeGenRouter(env_modules=[environment], template_cache_enabled=False)
    source = "await modules['Counter'].step(1, None)\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, False)
    assert not result["success"] and "step" in result["error"]


async def test_scalar_worker_defers_numpy_and_reuses_worker_for_arrays():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    scalar = "results['value'] = sum(range(10))\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, scalar, {}, True)
    assert result["success"] and result["results"]["value"] == 45
    worker = router._codegen_pool.idle[-1]
    maps = Path(f"/proc/{worker.process.pid}/maps")
    assert "numpy" not in maps.read_text()

    result = await CodeStage._execute_code(
        router,
        "results['value'] = np.mean(ctx['values'])\nresults['status'] = 'success'",
        {"values": np.array([1, 2, 3])},
        True,
    )
    assert result["success"] and result["results"]["value"] == 2
    assert "numpy" in maps.read_text()
    assert router._codegen_pool.idle[-1] is worker
    assert (await CodeStage._execute_code(router, scalar, {}, True))["success"]


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


async def test_owner_tool_exception_type_survives_data_only_bridge():
    async def fail():
        raise ValueError("owned failure")

    fail._tool_info = {"readonly": True}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(fail=fail)}
    source = "try:\n    await modules['Tool'].fail()\n    results['caught'] = False\nexcept ValueError:\n    results['caught'] = True\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, True)
    assert result["success"] and result["results"]["caught"]


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


async def test_output_budget_and_worker_recovery():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    result = await CodeStage._execute_code(
        router, "print('x' * 65537)\nresults['status'] = 'success'", {}, True
    )
    assert not result["success"] and "65536" in result["error"]
    assert (
        await CodeStage._execute_code(router, "results['status'] = 'success'", {}, True)
    )["success"]


@pytest.mark.parametrize(
    "value",
    [b"owned bytes", (1, 2), {1: 3}, np.array([1, 2], dtype=np.int32), float("inf")],
)
def test_wire_roundtrip_uses_explicit_data_types(value):
    restored = decode(encode(value))
    if isinstance(value, np.ndarray):
        np.testing.assert_array_equal(restored, value)
        assert restored.dtype == value.dtype
    else:
        assert restored == value


def test_wire_rejects_object_arrays_and_unknown_tags():
    with pytest.raises(TypeError):
        encode(np.array([object()], dtype=object))
    with pytest.raises(ValueError):
        decode({"t": "code", "v": "owned text"})


@pytest.mark.parametrize("tag", ["array", "record", "code"])
def test_wire_mapping_preserves_literal_type_tags_and_snapshot_isolation(tag):
    literal = {"t": tag, "v": {"t": "user data"}, "dtype": "object"}
    value = {"rows": [{"id": 1}], "literal": literal, "keys": {1: "one"}}
    encoded = encode(value)
    value["rows"][0]["id"] = 2
    restored = decode(encoded)
    assert restored == {
        "rows": [{"id": 1}],
        "literal": literal,
        "keys": {1: "one"},
    }
    restored["rows"][0]["id"] = 3
    assert decode(encoded)["rows"][0]["id"] == 1


def test_native_worker_mappings_retain_node_depth_and_scalar_budgets():
    with pytest.raises(ValueError, match="65536"):
        decode({"rows": [0] * 65536})
    with pytest.raises(ValueError, match="8 MiB"):
        encode({"large": "x" * (8 * 1024 * 1024)})
    nested = {}
    for _ in range(65):
        nested = {"child": nested}
    with pytest.raises(ValueError, match="64 nesting"):
        decode(nested)
    with pytest.raises(ValueError, match="keys must be strings"):
        decode({1: "invalid native key"})


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


async def test_unchanged_context_keeps_parent_objects_after_isolated_execution():
    from pydantic import BaseModel

    class Profile(BaseModel):
        value: int

    profile = Profile(value=3)
    rows = [{"id": 1}]
    ctx = {"profile": profile, "rows": rows}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    result = await CodeStage._execute_code(
        router,
        "results['value'] = sum([ctx['profile'].value])\nresults['status'] = 'success'",
        ctx,
        True,
    )
    assert result["success"] and result["results"]["value"] == 3
    assert ctx["profile"] is profile and ctx["rows"] is rows


@pytest.mark.parametrize("ctx", [None, []])
async def test_context_omission_still_rejects_non_mapping_context(ctx):
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    result = await CodeStage._execute_code(
        router,
        "results['value'] = sum([1])\nresults['status'] = 'success'",
        ctx,
        True,
    )
    assert not result["success"]
    assert "invalid context" in result["error"]


@pytest.mark.parametrize(
    "ctx,mutation,expected",
    [
        ({"flag": True}, "ctx['flag'] = 1", {"flag": 1}),
        ({"zero": -0.0}, "ctx['zero'] = 0.0", {"zero": 0.0}),
        (
            {"first": 1, "second": 2},
            "value = ctx.pop('first')\nctx['first'] = value",
            {"second": 2, "first": 1},
        ),
    ],
)
async def test_context_writeback_detects_number_types_zero_sign_and_key_order(
    ctx, mutation, expected
):
    import math

    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    result = await CodeStage._execute_code(
        router,
        mutation + "\nresults['value'] = sum([1])\nresults['status'] = 'success'",
        ctx,
        True,
    )
    assert result["success"] and ctx == expected
    assert list(ctx) == list(expected)
    for key, value in expected.items():
        assert type(ctx[key]) is type(value)
        if isinstance(value, float):
            assert math.copysign(1, ctx[key]) == math.copysign(1, value)


async def test_worker_pool_is_bounded_and_closes_all_children(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_WORKERS", 2)
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "results['value'] = sum([ctx['id']])\nresults['status'] = 'success'"
    results = await asyncio.gather(
        *(CodeStage._execute_code(router, source, {"id": i}, True) for i in range(10))
    )
    assert [r["results"]["value"] for r in results] == list(range(10))
    pool = get_pool(router, Config.CODE_EXEC_MEMORY_MIB, 2)
    assert len(pool.all) == 2
    processes = [worker.process for worker in pool.all]
    await router.close()
    assert all(process.poll() is not None for process in processes)


async def test_oversized_source_is_rejected_before_worker_start():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "#" + "x" * (1024 * 1024) + "\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, True)
    assert not result["success"] and "1 MiB" in result["error"]
    assert not hasattr(router, "_codegen_pool")


async def test_worker_code_cache_stays_synchronized_after_oversized_source():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "results['value'] = sum([2])\nresults['status'] = 'success'"
    assert (await CodeStage._execute_code(router, source, {}, True))["success"]
    large = source + "\n#" + "x" * 70000
    assert (await CodeStage._execute_code(router, large, {}, True))["success"]
    assert (await CodeStage._execute_code(router, source, {}, True))["success"]


async def test_failed_result_encoding_does_not_desynchronize_worker_lru():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    # Functions cannot cross the data-only result channel. Rejection still
    # acknowledges the prepared-code cache transition on both sides.
    bad = "results['value'] = print\nresults['status'] = 'success'"
    assert not (await CodeStage._execute_code(router, bad, {}, True))["success"]
    for index in range(129):
        source = f"results['value'] = sum([{index}])\nresults['status'] = 'success'"
        assert (await CodeStage._execute_code(router, source, {}, True))["success"]
    assert not (await CodeStage._execute_code(router, bad, {}, True))["success"]
    assert (
        await CodeStage._execute_code(router, "results['status'] = 'success'", {}, True)
    )["success"]


def test_wire_bounds_recursive_container_processing():
    with pytest.raises(ValueError, match="65536"):
        encode([1] * 65537)
    with pytest.raises(ValueError, match="65536"):
        decode([1] * 65537)
    nested = 1
    for _ in range(66):
        nested = [nested]
    with pytest.raises(ValueError, match="nesting"):
        encode(nested)


async def test_closing_pool_cancels_active_execution_and_reaps_worker():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    assert (
        await CodeStage._execute_code(
            router,
            "results['value'] = sum([2])\nresults['status'] = 'success'",
            {},
            True,
        )
    )["success"]
    worker = router._codegen_pool.idle[-1]
    task = asyncio.create_task(
        CodeStage._execute_code(
            router, "value = sum(range(10**9))\nresults['status'] = 'success'", {}, True
        )
    )
    await asyncio.sleep(0.01)
    await router.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.process.poll() is not None


@pytest.mark.parametrize(
    "value",
    [
        Decimal("1.25"),
        Fraction(1, 3),
        complex(1, 2),
        frozenset({1, 2}),
        np.longdouble("1.234567890123456789"),
    ],
)
def test_wire_preserves_supported_numeric_and_immutable_types(value):
    result = decode(encode(value))
    assert type(result) is type(value)
    assert result == value


async def test_real_typed_environment_response_preserves_field_access():
    from agentsociety2.contrib.env.self_enhancement import SelfEnhancementEnv

    env = SelfEnhancementEnv(agent_ids=[1])
    router = CodeGenRouter(env_modules=[env], template_cache_enabled=False)
    source = "response = await modules['SelfEnhancementEnv'].get_my_rankings(1)\nresults['agent_id'] = response.agent_id\nresults['completed'] = response.completed_dimensions\nresults['copy'] = response.model_dump()\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, True)
    assert result["success"], result
    assert result["results"]["agent_id"] == 1
    assert result["results"]["completed"] == []
    assert result["results"]["copy"]["agent_id"] == 1


async def test_nested_typed_fields_cross_as_data_without_parent_model_code():
    from pydantic import BaseModel

    class Detail(BaseModel):
        items: list[int]

    class Response(BaseModel):
        detail: Detail

    async def read():
        return Response(detail=Detail(items=[2, 3]))

    read._tool_info = {"readonly": True}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(read=read)}
    source = "response = await modules['Tool'].read()\nresults['sum'] = sum(response.detail.items)\nresults['data'] = response\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, True)
    assert result["success"], result
    assert result["results"]["sum"] == 5
    assert result["results"]["data"] == {"detail": {"items": [2, 3]}}


async def test_worker_is_stopped_when_its_parent_exits_abruptly(tmp_path):
    import subprocess
    import sys

    script = tmp_path / "owned_parent.py"
    warm = "results['value'] = sum([2])\nresults['status'] = 'success'"
    busy = "value = sum(range(10**9))\nresults['status'] = 'success'"
    script.write_text(
        "import asyncio, os\n"
        "from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage\n"
        "async def main():\n"
        "    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)\n"
        f"    await CodeStage._execute_code(router, {warm!r}, {{}}, True)\n"
        "    pid = router._codegen_pool.idle[-1].process.pid\n"
        f"    asyncio.create_task(CodeStage._execute_code(router, {busy!r}, {{}}, True))\n"
        "    await asyncio.sleep(0.01)\n"
        "    print(pid, flush=True)\n"
        "    os._exit(0)\n"
        "asyncio.run(main())\n"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(script), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
    assert process.returncode == 0, stderr.decode()
    pid = int(stdout)
    for _ in range(50):
        status = Path(f"/proc/{pid}/stat")
        try:
            state = status.read_text().split(") ", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == "Z":
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Owned worker survived abrupt parent exit")


def test_wire_limits_aggregate_array_transfers_even_for_aliased_values():
    array = np.zeros(3 * 1024 * 1024, dtype=np.uint8)
    with pytest.raises(ValueError, match="8 MiB"):
        encode([array, array, array])
