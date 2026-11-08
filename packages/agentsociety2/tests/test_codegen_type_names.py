"""Ordinary exception diagnostics expose type names, with no object traversal."""

import math

import pytest

from agentsociety2.config import Config
from agentsociety2.env import CodeGenRouter
from agentsociety2.env.codegen_runtime import policy_bindings
from agentsociety2.env.router_codegen import CodeStage


@pytest.mark.parametrize("backend", ["process", "inprocess"])
@pytest.mark.parametrize(
    "expression",
    [
        "type(error).__name__",
        "getattr(type(error), '__name__')",
        "getattr(type(error), ctx['attribute'])",
    ],
)
async def test_exception_type_name_is_available_in_error_diagnostics(
    monkeypatch, backend, expression
):
    monkeypatch.setattr(Config, "CODE_EXEC_BACKEND", backend)
    router = CodeGenRouter(env_modules=[], template_cache_enabled=False)
    try:
        result = await CodeStage._execute_code(
            router,
            "try:\n    raise ValueError('expected')\n"
            f"except ValueError as error:\n    results['name'] = {expression}\n"
            "results['status'] = 'success'",
            {"attribute": "__name__"},
            True,
        )
        assert result["success"], result
        assert result["results"]["name"] == "ValueError"
    finally:
        await router.close()


def test_type_name_descriptor_bypasses_metaclass_hooks_and_keeps_private_guards():
    class MetadataTrap(type):
        @property
        def __name__(cls):
            raise AssertionError("Metaclass getter must not run")

    class OwnedError(Exception, metaclass=MetadataTrap):
        pass

    bindings = policy_bindings(
        (("ALLOWED_BUILTINS", ()), ("ALLOWED_MODULES", ())), None
    )
    get = bindings["__safe_getattr__"]
    assert get(OwnedError, "__name__") == "OwnedError"
    for obj, attribute in [
        (OwnedError, "__mro__"),
        (OwnedError, "__dict__"),
        (OwnedError, "__class__"),
        (OwnedError, "__subclasses__"),
        (OwnedError(), "__name__"),
        (math, "__name__"),
    ]:
        with pytest.raises(AttributeError, match="Private attribute"):
            get(obj, attribute)
