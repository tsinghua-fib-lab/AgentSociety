"""Explicit container backend keeps owner-loop tools and baseline code policies."""

import asyncio
import json
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from agentsociety2.config import Config
from agentsociety2.env import CodeGenRouter
from agentsociety2.env.router_codegen import CodeStage


@pytest.mark.parametrize("backend", [None, "process"])
async def test_backend_configuration_controls_worker_creation(backend):
    env = os.environ.copy()
    env.pop("AGENTSOCIETY_CODE_EXEC_BACKEND", None)
    env["PYTHON_DOTENV_DISABLED"] = "1"
    if backend is not None:
        env["AGENTSOCIETY_CODE_EXEC_BACKEND"] = backend
    program = textwrap.dedent(
        """
        import asyncio, json
        from agentsociety2.config import Config
        from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage

        async def main():
            router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
            result = await CodeStage._execute_code(
                router, "results['value'] = sum([2]); results['status'] = 'success'", {}, True
            )
            assert result['success'], result
            print(json.dumps([
                Config.CODE_EXEC_BACKEND,
                result['results']['value'],
                hasattr(router, '_codegen_pool'),
            ]))
            await router.close()

        asyncio.run(main())
        """
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        program,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
    assert process.returncode == 0, stderr.decode()
    assert json.loads(stdout) == [backend or "inprocess", 2, backend == "process"]


@pytest.mark.parametrize("backend", ["process", "inprocess"])
async def test_numeric_and_tool_loop_results_match_with_data_boundaries(
    monkeypatch, backend
):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", backend)
    owner = asyncio.get_running_loop()
    calls = []

    class Reply(BaseModel):
        value: int

    async def read(value):
        assert asyncio.get_running_loop() is owner
        calls.append(value)
        return Reply(value=value)

    read._tool_info = {"readonly": True}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(read=read)}
    source = "total=0\nfor i in range(5):\n    reply = await modules['Tool'].read(i)\n    total += reply.value\nresults['value']=float(np.mean([total,20]))\nresults['status']='success'\nctx['done']=True"
    ctx = {}
    result = await CodeStage._execute_code(router, source, ctx, True)
    assert result["success"] and result["results"]["value"] == 15
    assert calls == list(range(5)) and ctx == {"done": True}
    if backend == "inprocess":
        assert not hasattr(router, "_codegen_pool")


async def test_inprocess_refuses_write_and_retains_unknown_write_outcome(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", "inprocess")
    calls = []

    def write():
        calls.append(1)
        raise ValueError("owned mutation then error")

    write._tool_info = {"readonly": False}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(write=write)}
    source = "import math\nmodules['Tool'].write()\nresults['status']='success'"
    readonly = await CodeStage._execute_code(router, source, {}, True)
    assert not readonly["success"] and not readonly["write_attempted"] and calls == []
    failed = await CodeStage._execute_code(router, source, {}, False)
    assert not failed["success"] and failed["write_attempted"] and calls == [1]


@pytest.mark.parametrize(
    "source",
    [
        "results['value'] = np.load('owned-unused-file')\nresults['status']='success'",
        "import json\nresults['value'] = json.codecs\nresults['status']='success'",
        "g=(i for i in [1])\nresults['value']=getattr(g,'gi_frame')\nresults['status']='success'",
    ],
)
async def test_inprocess_keeps_library_and_execution_object_policies(
    monkeypatch, source
):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", "inprocess")
    result = await CodeStage._execute_code(
        CodeGenRouter(env_modules=[], template_cache_enabled=False), source, {}, True
    )
    assert not result["success"]


async def test_inprocess_python_loop_deadline_is_cooperative(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", "inprocess")
    monkeypatch.setattr(Config, "CODE_EXEC_TIMEOUT", 0.01)
    with pytest.raises(TimeoutError):
        await CodeStage._execute_code(
            CodeGenRouter(env_modules=[], template_cache_enabled=False),
            "i=0\nwhile i < 10**9:\n    i += 1\nresults['status']='success'",
            {},
            True,
        )


async def test_invalid_backend_is_explicit_configuration_error(monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", "typo")
    with pytest.raises(ValueError, match="CODE_EXEC_BACKEND"):
        await CodeStage._execute_code(
            CodeGenRouter(env_modules=[], template_cache_enabled=False),
            "results['status']='success'",
            {},
            True,
        )
