"""无入参 skill 生命周期 hook 函数的运行上下文。

中文：为无入参的 skill 生命周期 hook 函数提供运行上下文。
English: Runtime context for no-arg skill lifecycle-hook functions.

当 skill 运行时在 skill 脚本模块中检测到 hook 函数(如 ``pre_step``)时,会在
调用该函数前通过 contextvar 激活一个 :class:`HookContext`。函数用
:func:`get_hook_context` 读取它,而非接收参数,从而保持无入参签名
(sync 或 async)。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HookContext:
    """激活中的 hook 上下文。

    :param workspace_root: agent workspace 根目录(取代 AGENT_WORK_DIR)。
    :param skill_dir: skill 包根目录(取代 SKILL_DIR)。
    :param skill_id: 注册表 skill id(``namespace@name``)。
    :param hook_type: 生命周期 hook 名(``pre_step`` / ``post_step``)。
    :param payload: 生命周期 payload dict(``time``、``agent_id``、
        ``step_count``、``tick``、...)。
    """

    workspace_root: Path
    skill_dir: Path
    skill_id: str
    hook_type: str
    payload: dict[str, Any]


_hook_ctx: contextvars.ContextVar[HookContext | None] = contextvars.ContextVar(
    "skill_hook_ctx", default=None
)


def get_hook_context() -> HookContext:
    """返回激活中的 hook 上下文(在 hook 之外调用会抛错)。

    :returns: 激活中的 :class:`HookContext`。
    :raises RuntimeError: 没有 hook 处于激活状态时抛出。
    """
    ctx = _hook_ctx.get()
    if ctx is None:
        raise RuntimeError("get_hook_context() called outside a lifecycle hook")
    return ctx


def _set_hook_context(ctx: HookContext) -> contextvars.Token[HookContext | None]:
    """激活一个 hook 上下文(内部使用,由运行时调用)。

    :param ctx: 要激活的 hook 上下文。
    :returns: 一个需传给 :func:`_reset_hook_context` 的 token。
    """
    return _hook_ctx.set(ctx)


def _reset_hook_context(token: contextvars.Token[HookContext | None]) -> None:
    """停用一个 hook 上下文(内部使用,由运行时调用)。

    :param token: :func:`_set_hook_context` 返回的 token。
    :returns: 无返回值。
    """
    _hook_ctx.reset(token)
