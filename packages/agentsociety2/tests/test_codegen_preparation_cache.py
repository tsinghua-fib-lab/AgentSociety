"""Prepared programs must retain every request-dependent security boundary."""

import asyncio
from types import SimpleNamespace

import pytest

import agentsociety2.env.router_codegen as cg
from agentsociety2.config import Config


def router():
    return cg.CodeGenRouter(env_modules=[], final_summary_enabled=False)


async def test_prepared_program_keeps_context_and_results_request_local():
    instance = router()
    source = "results['value'] = ctx['value']\nresults['status'] = 'success'"
    first = await cg.CodeStage._execute_code(instance, source, {"value": 1}, True)
    second = await cg.CodeStage._execute_code(instance, source, {"value": 2}, True)
    assert first["results"]["value"] == 1
    assert second["results"]["value"] == 2
    assert first["results"] is not second["results"]


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


async def test_validator_replacement_invalidates_cached_acceptance(monkeypatch):
    source = "results['status'] = 'success'"
    assert (await cg.CodeStage._execute_code(router(), source, {}, True))["success"]
    monkeypatch.setattr(
        cg.CodeStage,
        "_validate_code_safety",
        staticmethod(lambda *args: (False, "replacement policy rejects")),
    )
    result = await cg.CodeStage._execute_code(router(), source, {}, True)
    assert not result["success"]
    assert result["error"] == "replacement policy rejects"


async def test_cached_program_rechecks_dynamic_attribute_names():
    source = "results['value'] = getattr(print, ctx['attribute'], None)\nresults['status'] = 'success'"
    instance = router()
    benign = await cg.CodeStage._execute_code(
        instance, source, {"attribute": "not_present"}, True
    )
    malicious = await cg.CodeStage._execute_code(
        instance, source, {"attribute": "__globals__"}, True
    )
    assert benign["success"]
    assert not malicious["success"]
    assert "Private attribute" in malicious["error"]


async def test_cached_program_uses_new_deadline_and_cancels_new_tool(monkeypatch):
    instance = router()
    source = "await modules['Tool'].wait()\nresults['status'] = 'success'"

    async def immediate():
        return None

    immediate._tool_info = {"readonly": True}
    instance._modules = {"Tool": SimpleNamespace(wait=immediate)}
    assert (await cg.CodeStage._execute_code(instance, source, {}, True))["success"]
    finished = asyncio.Event()

    async def blocking():
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    blocking._tool_info = {"readonly": True}
    instance._modules = {"Tool": SimpleNamespace(wait=blocking)}
    monkeypatch.setattr(Config, "CODE_EXEC_TIMEOUT", 0.01)
    with pytest.raises(TimeoutError):
        await cg.CodeStage._execute_code(instance, source, {}, True)
    assert finished.is_set()


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

    results = await asyncio.gather(*(one(i) for i in range(64)))
    assert [r["results"]["value"] for r in results] == list(range(64))
    assert len({id(r["results"]) for r in results}) == 64


def test_preparation_cache_is_bounded_and_excludes_oversized_sources():
    cg._prepare_execution_cached.cache_clear()
    for index in range(140):
        assert not cg._prepare_execution(
            f"results['value'] = {index}\nresults['status'] = 'success'",
            cg.CodeGenRouter,
        ).error
    assert cg._prepare_execution_cached.cache_info().currsize <= 128
    before = cg._prepare_execution_cached.cache_info()
    large = "#" + "x" * 70000 + "\nresults['status'] = 'success'"
    assert not cg._prepare_execution(large, cg.CodeGenRouter).error
    assert cg._prepare_execution_cached.cache_info() == before


def test_repeated_program_does_not_repeat_ast_preparation(monkeypatch):
    cg._prepare_execution_cached.cache_clear()
    source = "results['value'] = 42\nresults['status'] = 'success'"
    assert not cg._prepare_execution(source, cg.CodeGenRouter).error
    monkeypatch.setattr(
        cg.ast,
        "parse",
        lambda *args, **kwargs: pytest.fail(
            "identical program should reuse immutable preparation"
        ),
    )
    assert not cg._prepare_execution(source, cg.CodeGenRouter).error


async def test_instance_policy_restriction_is_not_hidden_by_shared_cache():
    source = "results['value'] = 1\nresults['status'] = 'success'"
    normal = router()
    assert (await cg.CodeStage._execute_code(normal, source, {}, True))["success"]
    restricted = router()
    restricted.FORBIDDEN_AST_NODES = cg.CodeGenRouter.FORBIDDEN_AST_NODES | {
        cg.ast.Assign
    }
    result = await cg.CodeStage._execute_code(restricted, source, {}, True)
    assert not result["success"]
    assert "Forbidden AST node" in result["error"]


async def test_invalid_unicode_is_a_rejected_program_not_an_uncaught_exception():
    result = await cg.CodeStage._execute_code(
        router(), "results['value'] = '\ud800'\nresults['status'] = 'success'", {}, True
    )
    assert not result["success"]
    assert "Code preparation failed" in result["error"]


async def test_preparation_resource_failure_remains_a_failed_execution(monkeypatch):
    cg._prepare_execution_cached.cache_clear()

    def exhausted(*args, **kwargs):
        raise RecursionError("synthetic compiler recursion exhaustion")

    monkeypatch.setattr(cg._ExecutionGuards, "visit", exhausted)
    result = await cg.CodeStage._execute_code(
        router(),
        "results['value'] = sum([31337])\nresults['status'] = 'success'",
        {},
        True,
    )
    assert not result["success"]
    assert "compiler recursion exhaustion" in result["error"]
    monkeypatch.undo()
    recovered = await cg.CodeStage._execute_code(
        router(),
        "results['value'] = sum([31337])\nresults['status'] = 'success'",
        {},
        True,
    )
    assert recovered["success"]


async def test_validator_resource_failure_does_not_poison_later_valid_execution(
    monkeypatch,
):
    cg._prepare_execution_cached.cache_clear()
    source = "results['value'] = 727272\nresults['status'] = 'success'"
    parse = cg.ast.parse

    def exhausted(*args, **kwargs):
        raise MemoryError("synthetic validation memory exhaustion")

    monkeypatch.setattr(cg.ast, "parse", exhausted)
    failed = await cg.CodeStage._execute_code(router(), source, {}, True)
    assert not failed["success"]
    assert "validation memory exhaustion" in failed["error"]
    monkeypatch.setattr(cg.ast, "parse", parse)
    recovered = await cg.CodeStage._execute_code(router(), source, {}, True)
    assert recovered["success"] and recovered["results"]["value"] == 727272


async def test_empty_rejection_reason_is_still_a_rejected_program(monkeypatch):
    monkeypatch.setattr(
        cg.CodeStage, "_validate_code_safety", staticmethod(lambda *args: (False, ""))
    )
    result = await cg.CodeStage._execute_code(
        router(), "results['status'] = 'success'", {}, True
    )
    assert not result["success"] and result["results"] == {}


@pytest.mark.parametrize(
    "modules, expression, expected",
    [
        (set(), "1 + 2", 3),
        ({"math"}, "math.sqrt(4)", 2),
        ({"numpy", "np"}, "float(np.mean(np.array([1, 2, 3])))", 2),
        ({"operator"}, "operator.add(1, 2)", 3),
    ],
)
async def test_narrow_module_policy_keeps_unrelated_programs_executable(
    modules, expression, expected
):
    instance = router()
    instance.ALLOWED_MODULES = modules
    result = await cg.CodeStage._execute_code(
        instance,
        f"results['value'] = {expression}\nresults['status'] = 'success'",
        {},
        True,
    )
    assert result["success"], result.get("error")
    assert result["results"]["value"] == expected


@pytest.mark.parametrize("expression", ["math.pi", "operator.add(1, 2)"])
async def test_removed_module_is_not_left_in_the_execution_namespace(expression):
    instance = router()
    instance.ALLOWED_MODULES = set()
    result = await cg.CodeStage._execute_code(
        instance,
        f"results['value'] = {expression}\nresults['status'] = 'success'",
        {},
        True,
    )
    assert not result["success"] and "not defined" in result["error"]
