"""Standalone bounded numerical worker launched with Python -I -S.

Only parent-approved compiled code enters this process. Tools are data-only RPC
proxies; real environment objects and API credentials remain in the parent.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import builtins
import ctypes
import marshal
import os
import resource
import signal
import sys
from collections import OrderedDict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--numpy-path", required=True)
    parser.add_argument("--memory-mib", type=int, required=True)
    args = parser.parse_args()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot install worker parent-death signal")
    if os.getppid() != args.parent_pid:
        return
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot set worker no-new-privileges flag")
    limit = args.memory_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    # -S skips site files and SDK imports; expose only the recorded dependency
    # directory and these worker modules after resource limits are installed.
    sys.path[:0] = [str(Path(__file__).resolve().parent), args.numpy_path]
    import json

    from codegen_runtime import execute
    from codegen_wire import MAX_MESSAGE_BYTES, decode, encode, np, pack

    incoming, outgoing = sys.stdin.buffer, sys.stdout.buffer

    def send(record):
        outgoing.write(pack(record))
        outgoing.flush()

    def receive():
        raw = incoming.readline(MAX_MESSAGE_BYTES + 1)
        if not raw:
            raise EOFError("Parent closed worker channel")
        if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
            raise ValueError("Invalid worker frame length")
        return json.loads(raw)

    class ModuleProxy:
        def __init__(self, module, methods):
            self._module = module
            self._methods = methods

        def __getattr__(self, name):
            if name.startswith("_") or name not in self._methods:
                raise AttributeError(f"Environment tool is not exposed: {name}")

            def call(*args, **kwargs):
                send(
                    {
                        "event": "tool",
                        "module": self._module,
                        "method": name,
                        "args": encode(args),
                        "kwargs": encode(kwargs),
                    }
                )
                reply = receive()
                if reply["event"] != "tool_result":
                    raise ValueError("Unexpected tool response")
                if not reply["ok"]:
                    error_class = getattr(
                        builtins, reply.get("error_type", "RuntimeError"), RuntimeError
                    )
                    if not isinstance(error_class, type) or not issubclass(
                        error_class, Exception
                    ):
                        error_class = RuntimeError
                    raise error_class(reply["error"])
                return decode(reply["value"], records=True)

            if self._methods[name]:

                async def async_call(*args, **kwargs):
                    return call(*args, **kwargs)

                return async_call
            return call

    cache = OrderedDict()
    loop = asyncio.new_event_loop()
    send({"event": "ready", "pid": os.getpid(), "memory_limit_bytes": limit})
    while True:
        try:
            message = receive()
        except EOFError:
            loop.close()
            return
        cache_ok = False
        try:
            key = message["program_key"]
            if key in cache:
                compiled = cache.pop(key)
            else:
                # marshal only decodes code sent by the trusted parent; worker
                # replies are always data-only JSON with explicit value tags.
                compiled = marshal.loads(
                    base64.b64decode(message["program"], validate=True)
                )
            if message["retain_program"]:
                cache[key] = compiled
                if len(cache) > 128:
                    cache.popitem(last=False)
            cache_ok = message["retain_program"]
            modules = {
                name: ModuleProxy(name, methods)
                for name, methods in message["modules"].items()
            }
            original_ctx = pack(message["ctx"])
            ctx = decode(message["ctx"], records=True)
            policy = tuple((name, tuple(values)) for name, values in message["policy"])
            result = loop.run_until_complete(
                execute(
                    compiled,
                    message["is_async"],
                    ctx,
                    modules,
                    policy,
                    message["timeout"],
                    np,
                )
            )
            updated_ctx = encode(ctx)
            # Compare wire bytes, not Python equality: bool/int, signed zero
            # and dictionary order must still trigger context writeback.
            if pack(updated_ctx) == original_ctx:
                updated_ctx = None
            send(
                {
                    "event": "result",
                    "result": encode(result),
                    "ctx": updated_ctx,
                    "program_cached": cache_ok,
                }
            )
        except Exception as error:
            send(
                {
                    "event": "error",
                    "program_cached": cache_ok,
                    "error_type": type(error).__name__,
                    "error": str(error)[:2048],
                }
            )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import json

        sys.stdout.write(
            json.dumps(
                {
                    "event": "startup_error",
                    "error": f"{type(error).__name__}: {error}"[:2048],
                }
            )
            + "\n"
        )
        sys.stdout.flush()
        raise SystemExit(1) from None
