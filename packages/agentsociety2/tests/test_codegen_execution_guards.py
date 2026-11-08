"""Generated programs preserve tool loop ownership and runtime access limits."""

import asyncio
from types import SimpleNamespace

import pytest

from agentsociety2.config.config import Config
from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage


async def test_async_codegen_uses_environment_owner_loop():
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async def get_status(agent_id):
        loop.call_soon(future.set_result, agent_id)
        return await future

    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    get_status._tool_info = {"readonly": True}
    router._modules = {"Tool": SimpleNamespace(get_status=get_status)}
    result = await CodeStage._execute_code(
        router,
        "results['id'] = await modules['Tool'].get_status(ctx['id'])\nresults['status'] = 'success'",
        {"id": 7},
        readonly=True,
    )
    assert result["success"], result
    assert result["results"]["id"] == 7


@pytest.mark.parametrize(
    "expression",
    [
        "getattr(print, '__' + 'globals__')",
        "operator.attrgetter('__globals__')(print)",
        "getattr(print, ctx['attribute'])",
    ],
)
async def test_codegen_rejects_computed_private_attribute_access(expression):
    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    result = await CodeStage._execute_code(
        router,
        f"results['leak'] = {expression}\nresults['status'] = 'success'",
        {"attribute": "__globals__"},
        readonly=True,
    )
    assert not result["success"], result


async def test_codegen_cancels_timed_out_tool_on_owner_loop(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_TIMEOUT", 0.03)
    finished = asyncio.Event()

    async def wait(agent_id):
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    wait._tool_info = {"readonly": True}
    router._modules = {"Tool": SimpleNamespace(wait=wait)}
    with pytest.raises(TimeoutError):
        await CodeStage._execute_code(
            router,
            "await modules['Tool'].wait(ctx['id'])\nresults['status'] = 'success'",
            {"id": 1},
            readonly=True,
        )
    await asyncio.sleep(0)
    assert finished.is_set()


async def test_async_comprehension_deadline_and_loop_progress(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_TIMEOUT", 0.03)
    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)

    async def status():
        return None

    status._tool_info = {"readonly": True}
    router._modules = {"Tool": SimpleNamespace(status=status)}
    code = "await modules['Tool'].status()\nitems = [i for i in range(10**12)]\nresults['status'] = 'success'"
    with pytest.raises(TimeoutError):
        await CodeStage._execute_code(router, code, {}, readonly=True)


@pytest.mark.parametrize(
    "code",
    [
        "from collections import __builtins__\nresults['status'] = 'success'",
        "def __check_deadline__():\n    return None\nresults['status'] = 'success'",
        "def f(__async_check_deadline__):\n    return None\nresults['status'] = 'success'",
    ],
)
def test_codegen_reserves_runtime_helper_bindings(code):
    assert not CodeStage._validate_code_safety(CodeGenRouter, code)[0]


@pytest.mark.parametrize(
    "expression",
    [
        "string.Formatter().get_field('obj.__globals__', (), {'obj': print})[0]",
        "'{0.__globals__}'.format(print)",
        "np.ctypeslib",
    ],
)
async def test_library_reflection_cannot_reach_host_globals(expression):
    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    result = await CodeStage._execute_code(
        router,
        f"results['leak'] = {expression}\nresults['status'] = 'success'",
        {},
        readonly=True,
    )
    assert not result["success"]


@pytest.mark.parametrize(
    "statement",
    [
        "from numpy import ctypeslib",
        "from string import Formatter",
        "from numpy import *",
    ],
)
async def test_import_forms_cannot_bypass_library_guards(statement):
    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    result = await CodeStage._execute_code(
        router, statement + "\nresults['status'] = 'success'", {}, readonly=True
    )
    assert not result["success"]
