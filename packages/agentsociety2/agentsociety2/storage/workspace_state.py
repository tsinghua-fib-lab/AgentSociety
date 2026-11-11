"""Workspace 状态持久化的共享原子写工具（agent / env / society 复用）。

放在 storage 下是为了避免 ``env`` 与 ``agent.base`` 之间的循环导入——
本模块只依赖标准库，不导入 env / agent / society，因此任一侧都可安全引入。

- :func:`atomic_write_text` — 先写临时文件再 ``os.replace`` ，崩溃不会留下截断文件。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "atomic_write_text",
]


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """原子地写入文本文件：写 ``path.tmp`` 再 ``os.replace`` 。

    ``os.replace`` 在同一文件系统内是原子的，故进程在写盘中途被杀死也只会留下
    完整的旧文件或完整的新文件，不会出现截断的 checkpoint。

    :param path: 目标文件路径（父目录会自动创建）。
    :param content: 文本内容。
    :param encoding: 编码，默认 utf-8。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, path)
