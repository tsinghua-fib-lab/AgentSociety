"""Core execution, tool effects and host capability boundaries."""

import asyncio
import datetime
from types import SimpleNamespace

import pytest
from litellm import ModelResponse
from pydantic import BaseModel

import agentsociety2.env.router_codegen as cg
from agentsociety2.config import Config
from agentsociety2.env import CodeGenRouter, EnvBase, tool
from agentsociety2.env.router_codegen import CodeStage


@pytest.fixture(params=["inprocess", "process"])
def execution_backend(request, monkeypatch):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", request.param)


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


@pytest.mark.usefixtures("execution_backend")
@pytest.mark.parametrize(
    "failure",
    [
        "await modules['Counter'].add(3)\nvalue = 1 / 0\nresults['status'] = 'success'",
        "await modules['Counter'].add_then_raise(3)\nresults['status'] = 'success'",
    ],
)
async def test_failed_program_is_not_replayed_after_write_tool_attempt(failure):
    environment, injected, result, answer = await ask_outputs([failure, CORRECTED])
    assert environment.value == 3 and environment.calls == 1
    assert len(injected) == 1
    assert result["status"] == "error" and result["write_attempted"]
    assert "write-tool attempt" in answer


@pytest.mark.usefixtures("execution_backend")
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


@pytest.mark.usefixtures("execution_backend")
@pytest.mark.parametrize(
    "body",
    ["items = [i for i in range(10**12)]", "i = 0\nwhile i < 10**12:\n    i += 1"],
)
async def test_cpu_work_after_await_obeys_deadline(monkeypatch, body):
    monkeypatch.setattr(Config, "CODE_EXEC_TIMEOUT", 0.03)
    router = CodeGenRouter(env_modules=[], final_summary_enabled=False)

    async def status():
        return None

    status._tool_info = {"readonly": True}
    router._modules = {"Tool": SimpleNamespace(status=status)}
    code = f"await modules['Tool'].status()\n{body}\nresults['status'] = 'success'"
    with pytest.raises(TimeoutError):
        await CodeStage._execute_code(router, code, {}, readonly=True)


@pytest.mark.usefixtures("execution_backend")
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


@pytest.mark.parametrize(
    "expression, reason",
    [
        ("print.__globals__", "Dunder"),
        ("getattr(print, ctx['attribute'])", "Private attribute"),
        ("type(print).__mro__", "Dunder"),
        ("np.load(ctx['path'], allow_pickle=True)", "forbidden"),
        ("np.save(ctx['path'], np.array([1]))", "forbidden"),
        ("np.array([1]).ctypes", "forbidden"),
        ("json.codecs.open(ctx['path'], 'r')", "not allowed"),
        ("(x for x in [1]).gi_frame", "Execution introspection"),
        ("'{0.__globals__}'.format(print)", "forbidden"),
    ],
)
async def test_generated_code_rejects_host_capabilities(
    execution_backend, tmp_path, expression, reason
):
    target = tmp_path / "owned.npy"
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    result = await CodeStage._execute_code(
        router,
        f"results['value'] = {expression}\nresults['status'] = 'success'",
        {"attribute": "__globals__", "path": str(target)},
        True,
    )
    assert not result["success"]
    assert reason.lower() in result["error"].lower()
    assert not target.exists()


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


def router():
    return CodeGenRouter(env_modules=[], template_cache_enabled=False)


@pytest.mark.usefixtures("execution_backend")
async def test_policy_change_invalidates_previously_accepted_program(monkeypatch):
    source = (
        "import math\nresults['value'] = math.sqrt(4)\nresults['status'] = 'success'"
    )
    instance = router()
    assert (await cg.CodeStage._execute_code(instance, source, {}, True))["success"]
    monkeypatch.setattr(
        cg.CodeGenRouter, "ALLOWED_MODULES", cg.CodeGenRouter.ALLOWED_MODULES - {"math"}
    )
    monkeypatch.setattr(
        cg.CodeGenRouter,
        "DANGEROUS_MODULES",
        cg.CodeGenRouter.DANGEROUS_MODULES | {"math"},
    )
    result = await cg.CodeStage._execute_code(instance, source, {}, True)
    assert not result["success"]
    assert "Dangerous import" in result["error"]


@pytest.mark.usefixtures("execution_backend")
async def test_shared_program_concurrent_requests_do_not_share_execution_state():
    source = "response = await modules['Tool'].read(ctx['id'])\nresults['value'] = response\nresults['status'] = 'success'"

    async def one(identifier):
        async def read(value):
            await asyncio.sleep(0)
            return value

        read._tool_info = {"readonly": True}
        instance = router()
        instance._modules = {"Tool": SimpleNamespace(read=read)}
        return await cg.CodeStage._execute_code(
            instance, source, {"id": identifier}, True
        )

    results = await asyncio.gather(*(one(i) for i in range(3)))
    assert [r["results"]["value"] for r in results] == list(range(3))
    assert len({id(r["results"]) for r in results}) == 3


async def test_exception_diagnostics_remain_usable(execution_backend):
    result = await CodeStage._execute_code(
        router(),
        "try:\n    raise ValueError('expected')\nexcept ValueError as error:\n    results['name'] = type(error).__name__\nresults['status'] = 'success'",
        {},
        True,
    )
    assert result["success"] and result["results"]["name"] == "ValueError"
