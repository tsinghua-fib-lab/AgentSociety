"""Tool plans preserve Python data semantics and keep slow tools concurrent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from agentsociety2.config import Config
from agentsociety2.env import CodeGenRouter
from agentsociety2.env.codegen_plan import compile_plan
from agentsociety2.env.router_codegen import CodeStage, _prepare_execution


@pytest.fixture(autouse=True)
def enable_process_backend(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", "process")


@pytest.mark.parametrize(
    "source,ctx",
    [
        (
            "value = ctx['x'].get('n', 0)\nresults['value'] = value\nresults['status'] = 'success'",
            {"x": {"n": 3}},
        ),
        (
            "value = ctx['x']\nif isinstance(value, (int, float)) and value > 0:\n    results['value'] = 'positive'\nelse:\n    results['value'] = 'other'\nresults['status'] = 'success'",
            {"x": 3},
        ),
        (
            "try:\n    value = ctx['missing']\n    results['status'] = 'success'\nexcept KeyError as error:\n    results['reason'] = str(error)\n    results['status'] = 'error'",
            {},
        ),
        (
            "results['value'] = ctx['x'] if ctx['x'] else 7\nprint(f\"value={ctx['x']!r}\")\nresults['status'] = 'success'",
            {"x": "abc"},
        ),
        (
            "results['value'] = ctx['array'][0]\nresults['status'] = 'success'",
            {"array": np.array([2, 3])},
        ),
        (
            "results['value'] = ctx['array'] == 2\nresults['status'] = 'success'",
            {"array": np.array([2, 3])},
        ),
        (
            "try:\n    raise ValueError('owned message')\n    results['status'] = 'success'\nexcept ValueError as error:\n    results['reason'] = str(error)\n    results['status'] = 'error'\nfinally:\n    print('done')",
            {},
        ),
    ],
)
async def test_plan_and_worker_have_same_results_and_output(source, ctx):
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    assert _prepare_execution(source, router).plan is not None
    plan = await CodeStage._execute_code(router, source, dict(ctx), True)
    worker = await CodeStage._execute_code(
        router, "import math\n" + source, dict(ctx), True
    )
    assert plan["success"] == worker["success"]
    assert plan["output"] == worker["output"]
    for key, value in plan["results"].items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, worker["results"][key])
        else:
            assert value == worker["results"][key]


@pytest.mark.parametrize(
    "source",
    [
        "results['value'] = sum(range(10**9))\nresults['status'] = 'success'",
        "results['value'] = np.mean([1,2,3])\nresults['status'] = 'success'",
        "while ctx['again']:\n    pass\nresults['status'] = 'success'",
        "print(f\"{ctx['value']:1000000000}\")\nresults['status'] = 'success'",
        "await str('not awaitable')\nresults['status'] = 'success'",
        "str = int\nresults['value'] = str('3')\nresults['status'] = 'success'",
    ],
)
def test_unbounded_or_general_python_is_dispatched_before_execution(source):
    import ast

    assert compile_plan(ast.parse(source), CodeGenRouter.ALLOWED_BUILTINS) is None


async def test_plan_rechecks_builtin_policy_after_warm_execution(monkeypatch):
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "results['value'] = str(3)\nresults['status'] = 'success'"
    assert (await CodeStage._execute_code(router, source, {}, True))["success"]
    monkeypatch.setattr(
        CodeGenRouter, "ALLOWED_BUILTINS", CodeGenRouter.ALLOWED_BUILTINS - {"str"}
    )
    result = await CodeStage._execute_code(router, source, {}, True)
    assert not result["success"]


async def test_plan_does_not_invoke_arguments_before_resolving_tool():
    calls = []

    async def touch():
        calls.append("effect")
        return 1

    touch._tool_info = {"readonly": False}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(touch=touch)}
    source = "await modules['missing'].call(await modules['Tool'].touch())\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, source, {}, False)
    assert not result["success"] and calls == []


async def test_slow_tools_remain_concurrent_without_numerical_worker_slots():
    entered, peak = 0, 0
    release = asyncio.Event()

    async def read(identifier):
        nonlocal entered, peak
        entered += 1
        peak = max(peak, entered)
        if entered == 32:
            release.set()
        await asyncio.wait_for(release.wait(), 2)
        return identifier

    read._tool_info = {"readonly": True}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(read=read)}
    source = "results['value'] = await modules['Tool'].read(ctx['id'])\nresults['status'] = 'success'"
    results = await asyncio.gather(
        *(CodeStage._execute_code(router, source, {"id": i}, True) for i in range(32))
    )
    assert peak == 32
    assert [r["results"]["value"] for r in results] == list(range(32))
    assert not hasattr(router, "_codegen_pool")


async def test_plan_bounds_array_broadcasting_before_native_allocation():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "results['value'] = ctx['a'] == ctx['b']\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(
        router, source, {"a": np.zeros((10000, 1)), "b": np.zeros((1, 10000))}, True
    )
    assert not result["success"] and "4 MiB" in result["error"]


async def test_plan_limits_repeated_large_values_before_stringification():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "values = [ctx['text'], ctx['text']]\nprint(values)\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(
        router, source, {"text": "x" * (5 * 1024 * 1024)}, True
    )
    assert not result["success"] and "8 MiB" in result["error"]


async def test_plan_preparation_skips_python_compiler(monkeypatch):
    import agentsociety2.env.router_codegen as cg

    cg._prepare_execution_cached.cache_clear()

    def unavailable(*args, **kwargs):
        raise RuntimeError("compiler is not used by data plans")

    monkeypatch.setattr(cg._ExecutionGuards, "visit", unavailable)
    result = await CodeStage._execute_code(
        CodeGenRouter(env_modules=[], template_cache_enabled=False),
        "results['value'] = 3\nresults['status'] = 'success'",
        {},
        True,
    )
    assert result["success"] and result["results"]["value"] == 3
