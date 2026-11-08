"""Explicit trusted-container execution, retaining code and tool policies."""

from __future__ import annotations

import base64
import inspect
import marshal
import types
from functools import lru_cache

from .codegen_process import CodeExecutionTimeout, tool_bindings
from .codegen_runtime import execute
from .codegen_wire import np


@lru_cache(maxsize=128)
def _compiled_cached(program):
    # Only the parent-validated, parent-compiled preparation cache supplies this.
    return marshal.loads(base64.b64decode(program))


async def execute_inprocess(router, prepared, ctx, readonly, policy, timeout, state):
    bindings, _manifest = tool_bindings(router._modules)
    modules = {}

    def bridge(function, tool_readonly):
        def check_call():
            if readonly and not tool_readonly:
                raise PermissionError("Write tool is forbidden in readonly execution")
            if not tool_readonly:
                state.write_attempted = True

        if inspect.iscoroutinefunction(function):

            async def async_call(*args, **kwargs):
                check_call()
                return await function(*args, **kwargs)

            return async_call

        def sync_call(*args, **kwargs):
            check_call()
            return function(*args, **kwargs)

        return sync_call

    for (module, method), (function, tool_readonly) in bindings.items():
        namespace = modules.setdefault(module, types.SimpleNamespace())
        setattr(namespace, method, bridge(function, tool_readonly))
    try:
        result = await execute(
            (
                _compiled_cached(prepared.program)
                if len(prepared.program) <= 131072
                else _compiled_cached.__wrapped__(prepared.program)
            ),
            prepared.is_async,
            ctx,
            modules,
            policy,
            timeout,
            np,
        )
        result["write_attempted"] = state.write_attempted
        return result
    except TimeoutError as error:
        raise CodeExecutionTimeout(str(error), state.write_attempted) from error
