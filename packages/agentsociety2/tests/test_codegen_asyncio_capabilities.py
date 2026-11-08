"""Generated programs can import cooperative sleep, with no task or I/O APIs."""

import asyncio

import numpy as np
import pytest

from agentsociety2.config import Config
from agentsociety2.env import CodeGenRouter
from agentsociety2.env.codegen_runtime import policy_bindings
from agentsociety2.env.router_codegen import CodeStage


@pytest.mark.parametrize("backend", ["process", "inprocess"])
@pytest.mark.parametrize(
    "code",
    [
        "import asyncio\nresults['value'] = 7",
        "import asyncio\nawait asyncio.sleep(0)\nresults['value'] = 7",
        "from asyncio import sleep\nawait sleep(0)\nresults['value'] = 7",
    ],
)
async def test_asyncio_import_and_cooperative_sleep(monkeypatch, backend, code):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", backend)
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    try:
        result = await CodeStage._execute_code(
            router, code + "\nresults['status'] = 'success'", {}, True
        )
        assert result["success"], result
        assert result["results"]["value"] == 7
    finally:
        await router.close()


@pytest.mark.parametrize("backend", ["process", "inprocess"])
async def test_pending_sleep_cannot_expose_its_event_loop(monkeypatch, backend):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", backend)
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    try:
        result = await CodeStage._execute_code(
            router,
            "import asyncio\n"
            "pending = asyncio.sleep(1)\n"
            "try:\n"
            "    future = pending.send(None)\n"
            "    results['loop_accessible'] = hasattr(future, 'get_loop')\n"
            "    results['class_accessible'] = hasattr(type(future), 'get_loop')\n"
            "finally:\n"
            "    pending.close()\n"
            "results['status'] = 'success'",
            {},
            True,
        )
        assert result["success"], result
        assert result["results"]["loop_accessible"] is False
        assert result["results"]["class_accessible"] is False
    finally:
        await router.close()


def test_execution_loop_and_future_are_not_attribute_data():
    get = policy_bindings((("ALLOWED_BUILTINS", ()), ("ALLOWED_MODULES", ())), np)[
        "__safe_getattr__"
    ]
    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        for obj, name in [
            (future, "get_loop"),
            (type(future), "get_loop"),
            (loop, "create_task"),
            (type(loop), "create_task"),
        ]:
            with pytest.raises(AttributeError, match="Execution introspection"):
                get(obj, name)
    finally:
        loop.close()


@pytest.mark.parametrize("backend", ["process", "inprocess"])
async def test_asyncio_namespace_excludes_task_thread_and_io_apis(monkeypatch, backend):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", backend)
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    names = [
        "create_task",
        "ensure_future",
        "to_thread",
        "run",
        "get_running_loop",
        "create_subprocess_exec",
        "open_connection",
        "start_server",
    ]
    try:
        result = await CodeStage._execute_code(
            router,
            "import asyncio\n"
            "results['available'] = [hasattr(asyncio, name) for name in ctx['names']]\n"
            "results['status'] = 'success'",
            {"names": names},
            True,
        )
        assert result["success"], result
        assert result["results"]["available"] == [False] * len(names)
    finally:
        await router.close()
