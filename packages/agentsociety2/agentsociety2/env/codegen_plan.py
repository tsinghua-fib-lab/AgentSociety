"""Bounded tool-plan interpreter; full Python/native programs use workers.

Plans contain data expressions, branches and registered tool calls. No Python
code, library functions, loops or arbitrary object methods run in this engine.
The complete program is classified before its first tool call.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import inspect
import math
import operator
import time

import numpy as np

from .codegen_process import CodeExecutionTimeout, tool_bindings
from .codegen_runtime import LimitedOutput
from .codegen_wire import Record, decode, encode

_CLASSES = {
    name: getattr(builtins, name)
    for name in (
        "dict",
        "list",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "Exception",
        "RuntimeError",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
    )
}
_COMPARISONS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_CALLS = {
    "print",
    "len",
    "str",
    "int",
    "float",
    "bool",
    "isinstance",
    "getattr",
    "hasattr",
}
_EXCEPTIONS = {name for name, cls in _CLASSES.items() if issubclass(cls, Exception)}

_FUNCTIONS = {
    "len": len,
    "int": int,
    "float": float,
    "bool": bool,
    "isinstance": isinstance,
}


def compile_plan(tree, allowed_builtins):
    """Return immutable instructions, or None for the isolated Python backend."""
    if sum(1 for _ in ast.walk(tree)) > 512:
        return None
    enabled = set(allowed_builtins) | _EXCEPTIONS | {"print", "getattr", "hasattr"}
    names = {"ctx", "results", *(name for name in _CLASSES if name in enabled)}
    local_types = set(_CLASSES)
    local_errors = set()

    def expression(node):
        if isinstance(node, ast.Constant):
            if type(node.value) in {str, int, float, bool, type(None)}:
                return ("constant", node.value)
        elif isinstance(node, ast.Name) and node.id in names:
            return ("name", node.id)
        elif isinstance(node, ast.Await):
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Subscript)
                and isinstance(call.func.value.value, ast.Name)
                and call.func.value.value.id == "modules"
            ):
                return expression(call)
        elif isinstance(node, ast.Subscript):
            return ("subscript", expression(node.value), expression(node.slice))
        elif isinstance(node, ast.Attribute) and not node.attr.startswith("_"):
            return ("attribute", expression(node.value), node.attr)
        elif isinstance(node, (ast.List, ast.Tuple)):
            if isinstance(node, ast.Tuple) and all(
                isinstance(v, ast.Name) and v.id in _CLASSES and v.id in enabled
                for v in node.elts
            ):
                return ("constant", tuple(_CLASSES[v.id] for v in node.elts))
            if any(
                isinstance(v, ast.Name) and v.id in local_types | local_errors
                for v in ast.walk(node)
            ):
                raise ValueError("Full Python backend required")
            return (
                "list" if isinstance(node, ast.List) else "tuple",
                tuple(expression(v) for v in node.elts),
            )
        elif isinstance(node, ast.Dict) and all(key is not None for key in node.keys):
            if any(
                isinstance(v, ast.Name) and v.id in local_types | local_errors
                for v in ast.walk(node)
            ):
                raise ValueError("Full Python backend required")
            return (
                "dict",
                tuple(
                    (expression(k), expression(v))
                    for k, v in zip(node.keys, node.values)
                ),
            )
        elif isinstance(node, ast.BoolOp):
            return (
                "and" if isinstance(node.op, ast.And) else "or",
                tuple(expression(v) for v in node.values),
            )
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return ("not", expression(node.operand))
        elif isinstance(node, ast.Compare) and all(
            type(op) in _COMPARISONS for op in node.ops
        ):
            return (
                "compare",
                expression(node.left),
                tuple(
                    (type(op), expression(v))
                    for op, v in zip(node.ops, node.comparators)
                ),
            )
        elif isinstance(node, ast.IfExp):
            return (
                "choose",
                expression(node.test),
                expression(node.body),
                expression(node.orelse),
            )
        elif isinstance(node, ast.JoinedStr) and all(
            not isinstance(v, ast.FormattedValue) or v.format_spec is None
            for v in node.values
        ):
            return (
                "string",
                tuple(
                    ("format", expression(v.value), v.conversion)
                    if isinstance(v, ast.FormattedValue)
                    else expression(v)
                    for v in node.values
                ),
            )
        elif isinstance(node, ast.Call) and all(
            k.arg is not None for k in node.keywords
        ):
            args = tuple(expression(v) for v in node.args)
            kwargs = tuple((k.arg, expression(k.value)) for k in node.keywords)
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Subscript)
                and isinstance(fn.value.value, ast.Name)
                and fn.value.value.id == "modules"
            ):
                return ("tool", expression(fn.value.slice), fn.attr, args, kwargs)
            if isinstance(fn, ast.Name) and fn.id in (_CALLS | _EXCEPTIONS) & enabled:
                return ("call", fn.id, args, kwargs)
            if isinstance(fn, ast.Attribute) and fn.attr in {"get", "model_dump"}:
                return ("method", expression(fn.value), fn.attr, args, kwargs)
        raise ValueError("Full Python backend required")

    def target(node):
        if isinstance(node, ast.Name):
            if node.id in _CALLS | set(_CLASSES) | {"modules"}:
                raise ValueError("Full Python backend required")
            names.add(node.id)
            return ("name", node.id)
        if isinstance(node, ast.Subscript):
            return ("subscript", expression(node.value), expression(node.slice))
        raise ValueError("Full Python backend required")

    def statements(nodes):
        result = []
        for node in nodes:
            if isinstance(node, ast.Assign):
                value = expression(node.value)
                if isinstance(node.value, ast.Name) and node.value.id in local_types:
                    local_types.update(
                        v.id for v in node.targets if isinstance(v, ast.Name)
                    )
                result.append(("assign", tuple(target(v) for v in node.targets), value))
            elif (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and isinstance(node.annotation, ast.Name)
                and node.annotation.id in _CLASSES
            ):
                value = expression(node.value)
                result.append(("assign", (target(node.target),), value))
            elif isinstance(node, ast.Expr):
                result.append(("expression", expression(node.value)))
            elif isinstance(node, ast.If):
                result.append(
                    (
                        "if",
                        expression(node.test),
                        statements(node.body),
                        statements(node.orelse),
                    )
                )
            elif isinstance(node, ast.Try):
                handlers = []
                for handler in node.handlers:
                    if handler.type is not None and (
                        not isinstance(handler.type, ast.Name)
                        or handler.type.id not in _EXCEPTIONS
                    ):
                        raise ValueError("Full Python backend required")
                    if handler.name:
                        names.add(handler.name)
                        local_errors.add(handler.name)
                    handlers.append(
                        (
                            handler.type.id if handler.type else "Exception",
                            handler.name,
                            statements(handler.body),
                        )
                    )
                result.append(
                    (
                        "try",
                        statements(node.body),
                        tuple(handlers),
                        statements(node.orelse),
                        statements(node.finalbody),
                    )
                )
            elif (
                isinstance(node, ast.Raise)
                and node.exc is not None
                and node.cause is None
            ):
                result.append(("raise", expression(node.exc)))
            elif isinstance(node, ast.Pass):
                pass
            else:
                raise ValueError("Full Python backend required")
        return tuple(result)

    try:
        return statements(tree.body)
    except ValueError:
        return None


def data_index(value, key):
    if type(value) in {dict, list, tuple, str}:
        return value[key]
    if not isinstance(value, np.ndarray):
        raise TypeError("Tool plans index only data mappings and sequences")
    consumed, shapes = 0, []
    for index in key if isinstance(key, tuple) else (key,):
        if index is None:
            continue
        if type(index) is int:
            consumed += 1
            continue
        if isinstance(index, list):

            def integer_items(items):
                for item in items:
                    if isinstance(item, list):
                        integer_items(item)
                    elif type(item) not in {int, bool} or not -(2**63) <= item < 2**63:
                        raise IndexError("Array indices must be bounded integer data")

            integer_items(index)
            index = np.asarray(index)
        if not isinstance(index, np.ndarray) or index.dtype.kind not in "biu":
            raise IndexError("Array indices must be integer or boolean data")
        if index.dtype.kind == "b":
            consumed += index.ndim
            shapes.append((int(np.count_nonzero(index)),))
        else:
            consumed += 1
            shapes.append(index.shape)
    shape = np.broadcast_shapes(*shapes) if shapes else ()
    elements = math.prod(shape) * math.prod(value.shape[consumed:])
    if elements * value.dtype.itemsize > 4 * 1024 * 1024:
        raise ValueError("Tool-plan array selection exceeds 4 MiB")
    return value[key]


async def execute_plan(router, plan, ctx, readonly, timeout, state):
    bindings, _manifest = tool_bindings(router._modules)
    scope = {
        **{
            name: cls
            for name, cls in _CLASSES.items()
            if name in router.ALLOWED_BUILTINS or name in _EXCEPTIONS
        },
        "ctx": decode(encode(ctx), records=True),
        "results": {},
    }
    output = LimitedOutput()
    deadline = time.monotonic() + timeout

    def attribute(value, name):
        if name.startswith("_"):
            raise AttributeError("Private attribute access is forbidden")
        if isinstance(value, Record):
            return getattr(value, name)
        if isinstance(value, np.ndarray) and name in {
            "shape",
            "ndim",
            "size",
            "nbytes",
            "itemsize",
        }:
            return getattr(value, name)
        raise AttributeError(f"Data attribute is not exposed: {name}")

    async def evaluate(node):
        kind = node[0]
        if kind == "constant":
            return node[1]
        if kind == "name":
            if node[1] not in scope:
                raise NameError(f"Name is not defined: {node[1]}")
            return scope[node[1]]
        if kind == "subscript":
            value, key = await evaluate(node[1]), await evaluate(node[2])
            return data_index(value, key)
        if kind == "attribute":
            return attribute(await evaluate(node[1]), node[2])
        if kind in {"list", "tuple"}:
            values = [await evaluate(v) for v in node[1]]
            encode(values)
            return tuple(values) if kind == "tuple" else values
        if kind == "dict":
            value = {await evaluate(k): await evaluate(v) for k, v in node[1]}
            encode(value)
            return value
        if kind in {"and", "or"}:
            result = None
            for part in node[1]:
                result = await evaluate(part)
                if (kind == "and" and not result) or (kind == "or" and result):
                    break
            return result
        if kind == "not":
            return not await evaluate(node[1])
        if kind == "compare":
            left = await evaluate(node[1])
            for index, (operation, right_node) in enumerate(node[2]):
                right = await evaluate(right_node)
                arrays = [v for v in (left, right) if isinstance(v, np.ndarray)]
                if arrays:
                    shape = np.broadcast_shapes(*(v.shape for v in arrays))
                    if math.prod(shape) > 4 * 1024 * 1024:
                        raise ValueError("Tool-plan comparison exceeds 4 MiB")
                    if any(isinstance(v, str) and len(v) > 4096 for v in (left, right)):
                        raise ValueError(
                            "Array comparison text exceeds 4096 characters"
                        )
                result = _COMPARISONS[operation](left, right)
                if index == len(node[2]) - 1 or not result:
                    return result
                left = right
        if kind == "choose":
            return await evaluate(node[2] if await evaluate(node[1]) else node[3])
        if kind == "format":
            value = await evaluate(node[1])
            converter = repr if node[2] == 114 else ascii if node[2] == 97 else str
            text = converter(value)
            if len(text) > 65536:
                raise ValueError("Formatted output exceeds 65536 characters")
            return text
        if kind == "string":
            parts = [str(await evaluate(part)) for part in node[1]]
            if sum(map(len, parts)) > 65536:
                raise ValueError("Formatted output exceeds 65536 characters")
            return "".join(parts)
        if kind in {"tool", "call", "method"}:
            if kind == "tool":
                function, tool_readonly = bindings[await evaluate(node[1]), node[2]]
            if kind == "method":
                method_value = await evaluate(node[1])
            args = [await evaluate(v) for v in node[-2]]
            kwargs = {k: await evaluate(v) for k, v in node[-1]}
            if kind == "tool":
                if readonly and not tool_readonly:
                    raise PermissionError(
                        "Write tool is forbidden in readonly execution"
                    )
                # Mark before invocation: a failing tool may already have changed state.
                if not tool_readonly:
                    state.write_attempted = True
                value = function(*args, **kwargs)
                if inspect.isawaitable(value):
                    value = await value
                return decode(encode(value), records=True)
            if kind == "method":
                value = method_value
                if node[2] == "get" and type(value) is dict:
                    return value.get(*args, **kwargs)
                if node[2] == "model_dump" and isinstance(value, Record):
                    return value.model_dump(*args, **kwargs)
                raise AttributeError(f"Data method is not exposed: {node[2]}")
            name = node[1]
            if name == "print":
                if set(kwargs) - {"sep", "end", "flush"}:
                    raise ValueError("Tool-plan print cannot select an output file")
                print(*args, **kwargs, file=output)
                return None
            if name in {"getattr", "hasattr"}:
                if kwargs or len(args) not in ({2, 3} if name == "getattr" else {2}):
                    raise TypeError(f"Invalid {name} arguments")
                try:
                    value = attribute(args[0], args[1])
                    return True if name == "hasattr" else value
                except AttributeError:
                    if name == "hasattr":
                        return False
                    if len(args) == 3:
                        return args[2]
                    raise
            if (
                name in {"int", "float"}
                and args
                and isinstance(args[0], str)
                and len(args[0]) > 4096
            ):
                raise ValueError("Numeric text exceeds 4096 characters")
            if name in _EXCEPTIONS:
                if kwargs or len(args) > 1:
                    raise ValueError("Tool-plan exceptions require one bounded message")
                text = str(args[0]) if args else ""
                if len(text) > 2048:
                    raise ValueError("Exception message exceeds 2048 characters")
                return _CLASSES[name](text)
            if name == "str":
                text = str(*args, **kwargs)
                if len(text) > 65536:
                    raise ValueError("Formatted output exceeds 65536 characters")
                return text
            return _FUNCTIONS[name](*args, **kwargs)
        raise RuntimeError("Invalid tool-plan instruction")

    async def run(nodes):
        for node in nodes:
            if time.monotonic() >= deadline:
                raise TimeoutError("Tool-plan execution deadline exceeded")
            kind = node[0]
            if kind == "assign":
                value = await evaluate(node[2])
                for target in node[1]:
                    if target[0] == "name":
                        scope[target[1]] = value
                    else:
                        mapping, key = (
                            await evaluate(target[1]),
                            await evaluate(target[2]),
                        )
                        if isinstance(mapping, np.ndarray):
                            data_index(mapping, key)
                        elif type(mapping) not in {dict, list}:
                            raise TypeError(
                                "Tool-plan assignment requires a data container"
                            )
                        mapping[key] = value
            elif kind == "expression":
                await evaluate(node[1])
            elif kind == "if":
                await run(node[2] if await evaluate(node[1]) else node[3])
            elif kind == "raise":
                raise await evaluate(node[1])
            elif kind == "try":
                try:
                    try:
                        await run(node[1])
                    except Exception as error:
                        for cls_name, name, body in node[2]:
                            if isinstance(error, _CLASSES[cls_name]):
                                if name:
                                    scope[name] = error
                                try:
                                    await run(body)
                                finally:
                                    if name:
                                        scope.pop(name, None)
                                break
                        else:
                            raise
                    else:
                        await run(node[3])
                finally:
                    await run(node[4])

    try:
        await asyncio.wait_for(run(plan), timeout=timeout)
        results = decode(encode(scope["results"]))
        status = results.get("status")
        if (
            not isinstance(status, str)
            or not status.strip()
            or status.strip().lower() == "unknown"
        ):
            raise ValueError(
                "Generated code did not produce a classified results['status']"
            )
        return {
            "success": True,
            "results": results,
            "output": output.getvalue(),
            "print_outputs": [
                v.strip() for v in output.getvalue().splitlines() if v.strip()
            ],
            "write_attempted": state.write_attempted,
        }
    except TimeoutError as error:
        raise CodeExecutionTimeout(
            f"Code execution timeout: exceeded {timeout:g} seconds limit",
            state.write_attempted,
        ) from error
    except Exception as error:
        try:
            partial_results = decode(encode(scope["results"]))
        except (TypeError, ValueError, RecursionError) as serialization_error:
            partial_results = {}
            error = ValueError(
                f"{error}; result data unavailable: {serialization_error}"
            )
        return {
            "success": False,
            "results": partial_results,
            "output": output.getvalue(),
            "print_outputs": [],
            "error": str(error),
            "error_type": type(error).__name__,
            "write_attempted": state.write_attempted,
        }
    finally:
        updated = decode(encode(scope["ctx"]))
        ctx.clear()
        ctx.update(updated)
