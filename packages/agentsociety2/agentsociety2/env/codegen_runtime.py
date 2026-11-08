"""Reusable execution kernel for numerical workers and trusted containers.

This module has no SDK/config imports or API clients.
Policy bindings are immutable and cached; contexts, output, results and deadlines
are allocated per execution. Isolated workers receive a hard parent deadline;
trusted in-process execution uses cooperative Python deadline checks.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import math
import random
import re
import time
import types
from datetime import datetime
from functools import lru_cache
from io import StringIO


@lru_cache(maxsize=32)
def policy_bindings(policy, np):
    router = types.SimpleNamespace(
        **{name: frozenset(values) for name, values in policy}
    )

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name not in router.ALLOWED_MODULES or level:
            raise ImportError(f"Module not allowed: {name}")
        module = allowed_modules[name]
        for member in fromlist or ():
            guarded_getattr(module, member)
        return module

    import collections
    import copy
    import decimal
    import fractions
    import functools
    import itertools
    import operator
    import statistics
    import string

    allowed_modules = {
        "asyncio": types.SimpleNamespace(sleep=asyncio.sleep),
        "collections": collections,
        "itertools": itertools,
        "functools": functools,
        "operator": operator,
        "copy": copy,
        "decimal": decimal,
        "fractions": fractions,
        "statistics": statistics,
        "string": string,
        "re": re,
        "datetime": datetime,
        "json": json,
        "math": math,
        "random": random,
        "numpy": np,
        "np": np,
    }
    allowed_modules = {
        name: module
        for name, module in allowed_modules.items()
        if name in router.ALLOWED_MODULES
    }
    restricted_builtins = {
        k: v for k, v in vars(builtins).items() if k in router.ALLOWED_BUILTINS
    }
    restricted_builtins["__import__"] = safe_import
    missing = object()
    execution_types = (
        types.FrameType,
        types.CodeType,
        types.TracebackType,
        asyncio.Future,
        asyncio.AbstractEventLoop,
    )

    def module_allowed(module):
        name = module.__name__
        if name == "numpy" or name.startswith("numpy."):
            return (
                bool({"numpy", "np"} & router.ALLOWED_MODULES)
                and name in router.NUMPY_NUMERIC_NAMESPACES
            )
        return name in router.ALLOWED_MODULES

    def guarded_getattr(obj, name, default=missing):
        if not isinstance(name, str) or name.startswith("_"):
            if isinstance(name, str) and name == "__name__" and isinstance(obj, type):
                # Read the built-in type descriptor, bypassing metaclass hooks.
                return type.__dict__["__name__"].__get__(obj)
            raise AttributeError("Private attribute access is forbidden")
        if isinstance(obj, execution_types) or (
            isinstance(obj, type) and issubclass(obj, execution_types)
        ):
            raise AttributeError("Execution introspection is forbidden")
        if name in {
            "gi_frame",
            "gi_code",
            "cr_frame",
            "cr_code",
            "ag_frame",
            "ag_code",
        } and isinstance(
            obj, (types.GeneratorType, types.CoroutineType, types.AsyncGeneratorType)
        ):
            raise AttributeError("Execution introspection is forbidden")
        if name in {"ctypes", "cffi", "capsule"}:
            origin = (
                obj.__name__
                if isinstance(obj, types.ModuleType)
                else obj.__module__
                if isinstance(obj, type)
                else type(obj).__module__
            )
            if origin.startswith(("numpy", "ctypes", "_ctypes", "cffi", "_cffi")):
                raise AttributeError("Native interfaces are forbidden")
        if isinstance(obj, types.ModuleType):
            module_name = obj.__name__
            if module_name.split(".")[0] in router.DANGEROUS_MODULES:
                raise AttributeError("Access to host modules is forbidden")
            if module_name.startswith("numpy.ctypeslib") or (
                module_name == "numpy" and name == "ctypeslib"
            ):
                raise AttributeError("Native library loading is forbidden")
            if obj is string and name == "Formatter":
                raise AttributeError("Reflective formatter access is forbidden")
            if not module_allowed(obj):
                raise AttributeError("Module namespace is not allowed")
            if module_name == "numpy" or module_name.startswith("numpy."):
                if name in router.NUMPY_IO_NAMES:
                    raise AttributeError(
                        "NumPy file and serialization operations are forbidden"
                    )
        # Decoding or constructing an array loads NumPy first. Ordinary data
        # attributes must not materialize the worker's lazy NumPy module.
        elif type(np) is types.ModuleType and (
            isinstance(obj, (np.ndarray, np.generic))
            or (isinstance(obj, type) and issubclass(obj, (np.ndarray, np.generic)))
        ):
            if name in {"tofile", "dump", "dumps"}:
                raise AttributeError(
                    "NumPy file and serialization operations are forbidden"
                )
        if isinstance(obj, str) and name in {"format", "format_map"}:

            def check_fields(template):
                for _, field, spec, _ in string.Formatter().parse(template):
                    if field is not None and re.search(r"\._", field):
                        raise AttributeError("Private format field access is forbidden")
                    if spec:
                        check_fields(spec)

            def format_value(*args, **kwargs):
                check_fields(obj)
                return getattr(obj, name)(*args, **kwargs)

            return format_value
        if obj is operator and name == "attrgetter":

            def attrgetter(*names):
                def get(item):
                    values = []
                    for dotted in names:
                        value = item
                        for part in dotted.split("."):
                            value = guarded_getattr(value, part)
                        values.append(value)
                    return values[0] if len(values) == 1 else tuple(values)

                return get

            return attrgetter
        if obj is operator and name == "methodcaller":

            def methodcaller(method, *args, **kwargs):
                return lambda item: guarded_getattr(item, method)(*args, **kwargs)

            return methodcaller
        value = getattr(obj, name, default)
        if value is missing:
            raise AttributeError(name)
        # Allowed libraries expose public aliases to other host modules
        # (e.g. json.codecs.open). The import allowlist applies to aliases too.
        if isinstance(value, types.ModuleType) and not module_allowed(value):
            raise AttributeError("Module namespace is not allowed")
        return value

    def guarded_hasattr(obj, name):
        try:
            guarded_getattr(obj, name)
            return True
        except AttributeError:
            return False

    if "operator" in allowed_modules:
        allowed_modules["operator"] = types.SimpleNamespace(
            **{
                name: guarded_getattr(operator, name)
                for name in dir(operator)
                if not name.startswith("_")
            }
        )

    restricted_builtins["getattr"] = guarded_getattr
    restricted_builtins["hasattr"] = guarded_hasattr

    return types.MappingProxyType(
        {
            "__builtins__": types.MappingProxyType(restricted_builtins),
            **allowed_modules,
            "Exception": Exception,
            "RuntimeError": RuntimeError,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "SyntaxError": SyntaxError,
            "NameError": NameError,
            "AttributeError": AttributeError,
            "IndexError": IndexError,
            "KeyError": KeyError,
            "__safe_getattr__": guarded_getattr,
        }
    )


class LimitedOutput(StringIO):
    def write(self, value):
        if self.tell() + len(value) > 65536:
            raise ValueError("Generated output exceeds 65536 characters")
        return super().write(value)


async def execute(compiled, is_async, ctx, modules, policy, timeout, np):
    results = {}
    captured_output = LimitedOutput()

    def sandbox_print(*args, sep=" ", end="\n", file=None, flush=False):
        print(
            *args,
            sep=sep,
            end=end,
            file=file if file is not None else captured_output,
            flush=flush,
        )

    exec_globals = dict(policy_bindings(policy, np))
    guarded_getattr = exec_globals["__safe_getattr__"]
    exec_globals.update(
        {
            "ctx": ctx,
            "modules": types.MappingProxyType(modules),
            "results": results,
            "print": sandbox_print,
        }
    )
    exec_locals = {}
    try:
        exec_timeout = max(float(timeout), 0.001)
        deadline = time.monotonic() + exec_timeout
        last_yield = time.monotonic()

        def check_deadline():
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Code execution timeout: exceeded {exec_timeout:g} seconds limit"
                )

        async def async_check_deadline():
            nonlocal last_yield
            check_deadline()
            now = time.monotonic()
            if now - last_yield >= 0.005:
                last_yield = now
                await asyncio.sleep(0)

        def deadline_iter(items):
            for item in items:
                check_deadline()
                yield item

        async def deadline_aiter(items):
            async for item in items:
                await async_check_deadline()
                yield item

        exec_globals.update(
            {
                "__safe_getattr__": guarded_getattr,
                "__check_deadline__": check_deadline,
                "__async_check_deadline__": async_check_deadline,
                "__deadline_iter__": deadline_iter,
                "__deadline_aiter__": deadline_aiter,
            }
        )
        if is_async:
            exec(compiled, exec_globals, exec_locals)
            await asyncio.wait_for(
                exec_locals["_generated_main"](), timeout=exec_timeout
            )
        else:
            exec(compiled, exec_globals, exec_locals)
        output = captured_output.getvalue()
        print_outputs = [line.strip() for line in output.split("\n") if line.strip()]
        status = results.get("status")
        if (
            not isinstance(status, str)
            or not status.strip()
            or status.strip().lower() == "unknown"
        ):
            return {
                "results": results,
                "output": output,
                "print_outputs": print_outputs,
                "success": False,
                "error": "Generated code did not produce a classified results['status']",
            }
        return {
            "results": results,
            "output": output,
            "print_outputs": print_outputs,
            "success": True,
        }
    except TimeoutError:
        raise TimeoutError(
            f"Code execution timeout: exceeded {timeout:g} seconds limit"
        ) from None
    except Exception as e:
        return {
            "results": results,
            "output": captured_output.getvalue(),
            "print_outputs": [],
            "error": str(e),
            "success": False,
        }
