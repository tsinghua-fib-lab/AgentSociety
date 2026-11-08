"""Inspecting execution frames/code is denied; business data stays usable."""

from types import SimpleNamespace

import pytest

from agentsociety2.env import CodeGenRouter
from agentsociety2.env.router_codegen import CodeStage


@pytest.mark.parametrize(
    "source",
    [
        "generator = (value for value in [1])\ncapability = generator.gi_frame",
        "generator = (value for value in [1])\ncapability = generator.gi_code",
        "generator = (value for value in [1])\ncapability = getattr(generator, ctx['attribute'])",
        "generator = (value for value in [1])\ncapability = operator.attrgetter('gi_frame')(generator)",
        "async def empty():\n    return 1\ncoro = empty()\ntry:\n    capability = coro.cr_frame\nfinally:\n    coro.close()",
        "async def empty():\n    return 1\ncoro = empty()\ntry:\n    capability = coro.cr_code\nfinally:\n    coro.close()",
        "async def values():\n    yield 1\ngenerator = values()\ncapability = generator.ag_frame",
        "async def values():\n    yield 1\ngenerator = values()\ncapability = generator.ag_code",
    ],
)
async def test_execution_objects_are_rejected_before_capability_acquisition(source):
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    result = await CodeStage._execute_code(
        router,
        source
        + "\nresults['obtained'] = capability is not None\nresults['status'] = 'success'",
        {"attribute": "gi_frame"},
        True,
    )
    assert not result["success"]
    assert "Execution introspection" in result["error"]
    assert not result["results"].get("obtained")


async def test_warm_program_rechecks_computed_generator_attribute():
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    source = "generator = (value for value in [1])\ncapability = getattr(generator, ctx['attribute'])\nresults['value'] = capability\nresults['status'] = 'success'"
    assert (
        await CodeStage._execute_code(router, source, {"attribute": "gi_running"}, True)
    )["success"]
    result = await CodeStage._execute_code(
        router, source, {"attribute": "gi_frame"}, True
    )
    assert not result["success"] and "Execution introspection" in result["error"]


@pytest.mark.parametrize("prefix", ["", "import math\n"])
async def test_same_named_business_tool_and_record_fields_remain_data(prefix):
    from pydantic import BaseModel

    class Data(BaseModel):
        gi_frame: int = 7

    async def gi_frame():
        return Data()

    gi_frame._tool_info = {"readonly": True}
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    router._modules = {"Tool": SimpleNamespace(gi_frame=gi_frame)}
    source = "data = await modules['Tool'].gi_frame()\nresults['value'] = data.gi_frame\nresults['status'] = 'success'"
    result = await CodeStage._execute_code(router, prefix + source, {}, True)
    assert result["success"] and result["results"]["value"] == 7
