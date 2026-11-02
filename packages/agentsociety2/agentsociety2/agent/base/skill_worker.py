"""自定义技能函数的单次子进程入口，由父进程管理超时与回收。

每次调用独立导入模块；跨调用状态应写入工作区，不依赖模块全局变量。
启动和导入均计入调用超时。本模块保持标准库入口，仅按需导入 SDK 上下文。
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any


async def _invoke(request: dict[str, Any]) -> str:
    """导入并执行单次函数，保持入口参数及 hook 上下文契约。

    :param request: 父进程传入的脚本路径、函数名和调用参数。
    :returns: 按技能函数返回值约定生成的标准输出。
    """
    path = Path(request["path"])
    spec = importlib.util.spec_from_file_location("_skill_worker_script", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load skill script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    fn = getattr(module, request["name"])
    argv = request["argv"]
    if request["name"] == "entrypoint":
        params = [
            p
            for p in inspect.signature(fn).parameters.values()
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(params) >= 2:
            from agentsociety2.agent.base.skill_script_context import SkillScriptContext

            ctx = SkillScriptContext(
                workspace_root=Path.cwd(),
                skill_dir=Path(os.environ["SKILL_DIR"]),
                skill_id=request["skill_id"],
                skill_name=request["skill_name"],
                env=dict(os.environ),
            )
            result = fn(argv, ctx)
        else:
            result = fn(argv)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, str):
            return result
        if isinstance(result, tuple) and result and isinstance(result[0], str):
            return result[0]
        return ""

    from agentsociety2.agent.base.skill_hook_context import (
        HookContext,
        _reset_hook_context,
        _set_hook_context,
    )

    payload = {}
    if len(argv) >= 2 and argv[0] == "--args-json":
        loaded = json.loads(argv[1])
        if isinstance(loaded, dict):
            payload = loaded
    token = _set_hook_context(
        HookContext(
            workspace_root=Path.cwd(),
            skill_dir=Path(os.environ["SKILL_DIR"]),
            skill_id=request["skill_id"],
            hook_type=request["name"],
            payload=payload,
        )
    )
    try:
        result = fn()
        if inspect.isawaitable(result):
            result = await result
        return (
            result
            if isinstance(result, str)
            else (
                json.dumps(result, ensure_ascii=False, default=str)
                if result is not None
                else ""
            )
        )
    finally:
        _reset_hook_context(token)


def main() -> None:
    """执行函数并输出结构化结果；技能自身的打印输出进入 stderr。"""
    try:
        with redirect_stdout(sys.stderr):
            stdout = asyncio.run(_invoke(json.load(sys.stdin)))
        result = {
            "ok": True,
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
            "error_type": "none",
        }
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        result = {
            "ok": code == 0,
            "exit_code": code,
            "stdout": "",
            "stderr": "",
            "error_type": "systemexit",
        }
    except Exception:
        result = {
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": traceback.format_exc(),
            "error_type": "runtime",
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
