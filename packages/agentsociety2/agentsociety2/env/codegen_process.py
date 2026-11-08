"""Bounded worker pool and owner-loop tool bridge for generated Python."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import signal
import subprocess
import sys
import tempfile
import weakref
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .base import EnvBase
from .codegen_wire import MAX_MESSAGE_BYTES, decode, encode, pack

_POOLS = weakref.WeakKeyDictionary()


@dataclass
class ExecutionState:
    write_attempted: bool = False


class CodeExecutionTimeout(TimeoutError):
    def __init__(self, message, write_attempted=False):
        super().__init__(message)
        self.write_attempted = write_attempted


def _reap(process, directory):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)
    process.stdin.close()
    process.stdout.close()
    directory.cleanup()


class Worker:
    def __init__(self, memory_mib):
        directory = tempfile.TemporaryDirectory(prefix="as2-codegen-")
        command = [
            sys.executable,
            "-I",
            "-S",
            str(Path(__file__).with_name("codegen_worker.py")),
            "--parent-pid",
            str(os.getpid()),
            "--numpy-path",
            str(Path(np.__file__).parent.parent),
            "--memory-mib",
            str(memory_mib),
        ]
        environment = {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            cwd=directory.name,
            start_new_session=True,
            bufsize=0,
        )
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        self.buffer = bytearray()
        self.programs = OrderedDict()
        self.finalizer = weakref.finalize(self, _reap, self.process, directory)

    async def _readable(self, fd, writing=False):
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def ready():
            if not future.done():
                future.set_result(None)

        add = loop.add_writer if writing else loop.add_reader
        remove = loop.remove_writer if writing else loop.remove_reader
        add(fd, ready)
        try:
            await future
        finally:
            remove(fd)

    async def send(self, message):
        payload = memoryview(pack(message))
        fd = self.process.stdin.fileno()
        while payload:
            try:
                count = os.write(fd, payload)
                payload = payload[count:]
            except BlockingIOError:
                await self._readable(fd, writing=True)

    async def receive(self):
        fd = self.process.stdout.fileno()
        while True:
            position = self.buffer.find(b"\n")
            if position >= 0:
                raw = self.buffer[:position]
                del self.buffer[: position + 1]
                return json.loads(raw)
            if len(self.buffer) >= MAX_MESSAGE_BYTES:
                raise ValueError("Worker message exceeds 8 MiB")
            try:
                part = os.read(fd, min(65536, MAX_MESSAGE_BYTES - len(self.buffer)))
            except BlockingIOError:
                await self._readable(fd)
                continue
            if not part:
                raise RuntimeError(
                    f"Code worker closed its channel (exit={self.process.poll()})"
                )
            self.buffer.extend(part)

    async def close(self):
        await asyncio.to_thread(self.finalizer)


class WorkerPool:
    def __init__(self, memory_mib, workers):
        self.memory_mib = memory_mib
        self.slots = asyncio.Semaphore(workers)
        self.idle = []
        self.all = set()
        self.owners = weakref.WeakSet()
        self.closed = False
        self.active = set()

    @asynccontextmanager
    async def lease(self):
        async with self.slots:
            if self.closed:
                raise RuntimeError("Code worker pool is closed")
            task = asyncio.current_task()
            self.active.add(task)
            worker = self.idle.pop() if self.idle else None
            try:
                if worker is None:
                    worker = Worker(self.memory_mib)
                    self.all.add(worker)
                    ready = await asyncio.wait_for(worker.receive(), timeout=10)
                    if ready.get("event") != "ready":
                        raise RuntimeError(
                            f"Worker startup failed: {ready.get('error', 'invalid response')}"
                        )
                yield worker
            except BaseException:
                if worker is not None:
                    self.all.discard(worker)
                    await worker.close()
                raise
            else:
                if self.closed:
                    self.all.discard(worker)
                    await worker.close()
                else:
                    self.idle.append(worker)
            finally:
                self.active.discard(task)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        tasks = [task for task in self.active if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        workers, self.all = list(self.all), set()
        self.idle.clear()
        await asyncio.gather(*(worker.close() for worker in workers))


def get_pool(router, memory_mib, workers):
    if sys.platform != "linux":
        raise RuntimeError("CodeGen workers require Linux process and resource limits")
    if memory_mib < 64 or workers < 1:
        raise ValueError("Code workers require at least 64 MiB and one worker")
    loop = asyncio.get_running_loop()
    pools = _POOLS.setdefault(loop, {})
    key = (memory_mib, workers)
    pool = pools.get(key)
    if pool is None or pool.closed:
        pool = pools[key] = WorkerPool(memory_mib, workers)
    pool.owners.add(router)
    router._codegen_pool = pool
    return pool


async def close_pools():
    pools = _POOLS.pop(asyncio.get_running_loop(), {})
    await asyncio.gather(*(pool.close() for pool in pools.values()))


@lru_cache(maxsize=128)
def _class_methods(cls):
    methods = {}
    for base in reversed(cls.__mro__):
        methods.update(
            {
                name: value
                for name, value in vars(base).items()
                if not name.startswith("_")
            }
        )
    return tuple(
        name
        for name, value in methods.items()
        if callable(value)
        and (
            not issubclass(cls, EnvBase)
            or getattr(value, "_tool_info", None) is not None
        )
    )


def tool_bindings(modules):
    bindings, manifest = {}, {}
    for module_name, module in modules.items():
        methods = {}
        names = set(_class_methods(type(module)))
        names.update(
            name
            for name, value in vars(module).items()
            if not name.startswith("_") and callable(value)
        )
        for name in names:
            function = getattr(module, name)
            info = getattr(function, "_tool_info", None)
            if isinstance(module, EnvBase) and info is None:
                continue
            if not callable(function):
                continue
            bindings[module_name, name] = (
                function,
                (info or {}).get("readonly", False),
            )
            methods[name] = inspect.iscoroutinefunction(function)
        manifest[module_name] = methods
    return bindings, manifest


async def execute_in_worker(
    router,
    prepared,
    ctx,
    readonly,
    policy,
    timeout,
    memory_mib,
    workers,
    retain_program,
    state,
):
    bindings, manifest = tool_bindings(router._modules)
    pool = get_pool(router, memory_mib, workers)
    async with pool.lease() as worker:
        key = prepared.program_key

        async def conversation():
            await worker.send(
                {
                    "program_key": key,
                    "program": prepared.program if key not in worker.programs else None,
                    "retain_program": retain_program,
                    "is_async": prepared.is_async,
                    "modules": manifest,
                    "ctx": encode(ctx),
                    "policy": policy,
                    "timeout": timeout,
                }
            )
            while True:
                message = await worker.receive()
                event = message["event"]
                if event in {"result", "error"}:
                    worker.programs.pop(key, None)
                    if message.get("program_cached", False):
                        worker.programs[key] = None
                        if len(worker.programs) > 128:
                            worker.programs.popitem(last=False)
                if event == "result":
                    updated = ctx if message["ctx"] is None else decode(message["ctx"])
                    if not isinstance(updated, dict):
                        raise ValueError("Worker returned an invalid context")
                    if message["ctx"] is not None:
                        ctx.clear()
                        ctx.update(updated)
                    result = decode(message["result"])
                    result["write_attempted"] = state.write_attempted
                    return result
                if event == "error":
                    if message["error_type"] == "TimeoutError":
                        raise CodeExecutionTimeout(
                            message["error"], state.write_attempted
                        )
                    return {
                        "success": False,
                        "results": {},
                        "output": "",
                        "print_outputs": [],
                        "error": message["error"],
                        "error_type": message["error_type"],
                        "write_attempted": state.write_attempted,
                    }
                if event != "tool":
                    raise ValueError("Unexpected worker protocol event")
                try:
                    function, tool_readonly = bindings[
                        message["module"], message["method"]
                    ]
                    if readonly and not tool_readonly:
                        raise PermissionError(
                            "Write tool is forbidden in readonly execution"
                        )
                    args, kwargs = decode(message["args"]), decode(message["kwargs"])
                    if not tool_readonly:
                        state.write_attempted = True
                    value = function(*args, **kwargs)
                    if inspect.isawaitable(value):
                        value = await value
                    reply = {"event": "tool_result", "ok": True, "value": encode(value)}
                except Exception as error:
                    reply = {
                        "event": "tool_result",
                        "ok": False,
                        "error": str(error)[:2048],
                        "error_type": type(error).__name__,
                    }
                await worker.send(reply)

        try:
            return await asyncio.wait_for(conversation(), timeout=timeout)
        except TimeoutError as error:
            raise CodeExecutionTimeout(
                f"Code execution timeout: exceeded {timeout:g} seconds limit",
                state.write_attempted,
            ) from error
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Invalid framing/EOF must retire this worker before returning an
            # error to the caller; it can never be reused for another request.
            self_error = {
                "success": False,
                "results": {},
                "output": "",
                "print_outputs": [],
                "error": str(error),
                "error_type": type(error).__name__,
                "write_attempted": state.write_attempted,
            }
            raise WorkerProtocolError(self_error) from error


class WorkerProtocolError(RuntimeError):
    def __init__(self, result):
        super().__init__(result["error"])
        self.result = result
        self.write_attempted = result["write_attempted"]
