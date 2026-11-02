"""验证命令超时和取消都会终止普通后代进程，防止迟到写入。"""

import asyncio
import os
import sys

import pytest

from agentsociety2.agent.base.workspace_fs import WorkspaceFS


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="进程组清理使用 POSIX 信号")
@pytest.mark.parametrize("cancel", [False, True])
async def test_command_stops_descendants_on_timeout_or_cancel(tmp_path, cancel):
    """返回后父子进程均已终止，子进程不能继续写文件。"""
    late = tmp_path / "late-child.txt"
    started = tmp_path / "started"
    child = (
        "import time; from pathlib import Path; time.sleep(1.5); "
        f"Path({str(late)!r}).write_text('late')"
    )
    script = tmp_path / "spawn.py"
    script.write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        f"Path({str(started)!r}).touch()\n"
        "time.sleep(60)\n"
    )
    task = asyncio.create_task(
        WorkspaceFS(tmp_path).run_command([sys.executable, str(script)], timeout_sec=1)
    )
    try:
        async with asyncio.timeout(3):
            while not started.exists():
                await asyncio.sleep(0.01)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.error_type == "timeout"
        await asyncio.sleep(1.7)
        assert not late.exists()
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
