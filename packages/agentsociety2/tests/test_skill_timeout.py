"""技能超时回归测试。

普通脚本以可终止子进程执行，超时不得留下迟到写入或污染父进程。
自定义入口及 hooks 的导入、调用均在可回收子进程中执行。
"""

from pathlib import Path

import pytest

from agentsociety2.agent.base.skill_registry import SkillRegistry
from agentsociety2.agent.base.skill_runtime import AgentSkillRuntime
from agentsociety2.agent.base.workspace_fs import WorkspaceFS
from agentsociety2.trace import JsonlTraceWriter, ShardedTraceWriter

_RELEASE_FLAG = "release.now"


def _bind_runtime_workspace(runtime, tmp_path, agent_id=99):
    workspace = tmp_path / "agents" / f"agent_{agent_id:04d}"
    workspace.mkdir(parents=True)
    for rel in ("state", "memory"):
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    runtime.bind_workspace(
        workspace_root=workspace,
        fs=WorkspaceFS(workspace),
        trace_writer=JsonlTraceWriter(
            agent_id=agent_id,
            sharded_writer=ShardedTraceWriter(tmp_path / "trace"),
        ),
    )
    return workspace


def _hang_script_text(release: Path) -> str:
    """可释放的挂死循环:等 release 文件出现,或 60s 硬上限。"""
    return (
        "import os, time\n"
        f"release = {str(release)!r}\n"
        "deadline = time.time() + 60\n"
        "while time.time() < deadline and not os.path.exists(release):\n"
        "    time.sleep(0.2)\n"
    )


def _make_skill(tmp_path: Path, name: str, body: str) -> None:
    skill_root = tmp_path / "skills" / name
    (skill_root / "scripts").mkdir(parents=True)
    (skill_root / "scripts" / "run.py").write_text(body, encoding="utf-8")
    (skill_root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: timeout test skill\n---\n",
        encoding="utf-8",
    )


def _runtime_for(tmp_path: Path, name: str) -> AgentSkillRuntime:
    registry = SkillRegistry()
    registry.scan_custom(tmp_path / "skills")
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path)
    runtime.set_visible_skills([f"custom@{name}"])
    return runtime


@pytest.mark.asyncio
async def test_hanging_dynamic_script_times_out_and_allows_next_script(tmp_path):
    """普通脚本超时退出后，下一个脚本仍可正常执行。"""
    release = tmp_path / _RELEASE_FLAG
    _make_skill(tmp_path, "hangdyn", _hang_script_text(release))
    _make_skill(tmp_path, "fast", "print('fast-ok')\n")
    # 两个技能共用 runtime，验证超时不会阻塞后续调用。
    registry = SkillRegistry()
    registry.scan_custom(tmp_path / "skills")
    runtime = AgentSkillRuntime(registry=registry)
    _bind_runtime_workspace(runtime, tmp_path)
    runtime.set_visible_skills(["custom@hangdyn", "custom@fast"])

    try:
        result = await runtime.run_skill_script(
            "custom@hangdyn", "scripts/run.py", [], timeout_sec=1
        )
        assert result.ok is False
        assert result.error_type == "timeout"
        assert "timed out after 1s" in result.stderr

        # 快速技能可继续执行。
        fast = await runtime.run_skill_script(
            "custom@fast", "scripts/run.py", [], timeout_sec=10
        )
        assert fast.ok is True
        assert "fast-ok" in fast.stdout
    finally:
        release.write_text("", encoding="utf-8")  # 防止回归时测试遗留活动线程


@pytest.mark.asyncio
async def test_custom_sync_entrypoint_hang_is_isolated(tmp_path):
    """自定义同步入口挂起时终止子进程并返回超时。"""
    release = tmp_path / _RELEASE_FLAG
    body = (
        "import os, time\n"
        f"release = {str(release)!r}\n"
        "def entrypoint(argv):\n"
        "    deadline = time.time() + 60\n"
        "    while time.time() < deadline and not os.path.exists(release):\n"
        "        time.sleep(0.2)\n"
        "    return 'never'\n"
    )
    _make_skill(tmp_path, "hangentry", body)
    runtime = _runtime_for(tmp_path, "hangentry")

    try:
        result = await runtime.run_skill_script(
            "custom@hangentry", "scripts/run.py", [], timeout_sec=1
        )
        assert result.ok is False
        assert result.error_type == "timeout"
    finally:
        release.write_text("", encoding="utf-8")


@pytest.mark.asyncio
async def test_custom_async_hook_hang_times_out(tmp_path):
    """自定义异步 hook 挂起时终止子进程，事件循环无损。"""
    body = "import asyncio\nasync def pre_step():\n    await asyncio.sleep(999)\n"
    skill_root = tmp_path / "skills" / "asynchook"
    (skill_root / "scripts").mkdir(parents=True)
    (skill_root / "scripts" / "hook.py").write_text(body, encoding="utf-8")
    (skill_root / "SKILL.md").write_text(
        "---\n"
        "name: asynchook\n"
        "description: async hook timeout test\n"
        "hooks:\n"
        "  pre_step: scripts/hook.py\n"
        "---\n",
        encoding="utf-8",
    )
    runtime = _runtime_for(tmp_path, "asynchook")

    result = await runtime.run_skill_hook(
        "custom@asynchook", "pre_step", [], timeout_sec=1
    )
    assert result.ok is False
    assert result.error_type == "timeout"
    assert "timed out after 1s" in result.stderr


@pytest.mark.asyncio
async def test_fast_custom_entrypoint_unaffected(tmp_path):
    """快速 custom entrypoint 照常工作(超时只在挂死时介入)。"""
    body = "def entrypoint(argv):\n    return 'quick:' + '-'.join(argv)\n"
    _make_skill(tmp_path, "quick", body)
    runtime = _runtime_for(tmp_path, "quick")

    result = await runtime.run_skill_script(
        "custom@quick", "scripts/run.py", ["a", "b"], timeout_sec=10
    )
    assert result.ok is True
    assert "quick:a-b" in result.stdout


@pytest.mark.asyncio
async def test_entrypointless_top_level_runs_exactly_once(tmp_path):
    """双执行回归:entrypoint-less 脚本顶层副作用只执行一次。

    修复前:``_load_script_module`` 的 exec_module 在事件循环线程上先
    跑一遍顶层代码(不受超时保护),``_exec_source_sync`` 又跑第二遍。
    """
    # 计数文件放脚本同目录(__file__ 在 import 期与动态执行期均成立;
    # 用 AGENT_WORK_DIR 的话 import 期会因缺环境变量 KeyError,反而
    # 触发子进程回退、测不到双执行)。
    body = (
        "import os\n"
        "p = os.path.join(os.path.dirname(__file__), 'runs.txt')\n"
        "n = 0\n"
        "if os.path.exists(p):\n"
        "    n = int(open(p).read() or 0)\n"
        "open(p, 'w').write(str(n + 1))\n"
        "print('exec-pass')\n"
    )
    _make_skill(tmp_path, "onceonly", body)
    runtime = _runtime_for(tmp_path, "onceonly")

    result = await runtime.run_skill_script(
        "custom@onceonly", "scripts/run.py", [], timeout_sec=10
    )
    assert result.ok is True
    counter = (tmp_path / "skills" / "onceonly" / "scripts" / "runs.txt").read_text(
        encoding="utf-8"
    )
    assert counter.strip() == "1", f"顶层代码执行了 {counter} 次,应为 1 次"
    assert result.stdout.count("exec-pass") == 1


@pytest.mark.asyncio
async def test_hang_script_does_not_steal_process_stdout(tmp_path):
    """普通脚本超时前后均不替换父进程 stdout。"""
    release = tmp_path / _RELEASE_FLAG
    _make_skill(tmp_path, "stdoutthief", _hang_script_text(release))
    runtime = _runtime_for(tmp_path, "stdoutthief")
    import sys as _sys

    before_stdout = _sys.stdout
    try:
        result = await runtime.run_skill_script(
            "custom@stdoutthief", "scripts/run.py", [], timeout_sec=1
        )
        assert result.error_type == "timeout"
        # 子进程已终止，父进程输出对象应始终保持原样。
        assert _sys.stdout is before_stdout
    finally:
        release.write_text("", encoding="utf-8")


@pytest.mark.asyncio
async def test_dynamic_timeout_stops_late_writes(tmp_path):
    """超时返回后，脚本不能继续写入工作区。"""
    import asyncio

    late = tmp_path / "late.txt"
    _make_skill(
        tmp_path,
        "late",
        f"import time\nfrom pathlib import Path\ntime.sleep(1.3)\nPath({str(late)!r}).write_text('late')\n",
    )
    runtime = _runtime_for(tmp_path, "late")
    result = await runtime.run_skill_script(
        "custom@late", "scripts/run.py", [], timeout_sec=1
    )
    assert result.error_type == "timeout"
    await asyncio.sleep(0.5)
    assert not late.exists()


@pytest.mark.asyncio
async def test_dynamic_execution_preserves_parent_process_state(tmp_path):
    """脚本运行期间也不能改变父进程的 cwd、argv 和环境变量。"""
    import asyncio
    import os
    import sys

    started = tmp_path / "started"
    _make_skill(
        tmp_path,
        "state",
        f"from pathlib import Path\nimport time\nPath({str(started)!r}).touch()\ntime.sleep(0.5)\n",
    )
    runtime = _runtime_for(tmp_path, "state")
    before = (Path.cwd(), list(sys.argv), os.environ.get("AGENT_WORK_DIR"))
    task = asyncio.create_task(
        runtime.run_skill_script(
            "custom@state", "scripts/run.py", ["test"], timeout_sec=5
        )
    )
    try:
        async with asyncio.timeout(3):
            while not started.exists():
                await asyncio.sleep(0.01)
        assert (Path.cwd(), sys.argv, os.environ.get("AGENT_WORK_DIR")) == before
    finally:
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["entrypoint", "hook", "import"])
async def test_custom_callable_timeout_prevents_late_write(tmp_path, kind):
    """包含导入阶段在内，自定义函数超时后不得继续写入。"""
    import asyncio

    started, late = tmp_path / "started", tmp_path / "late"
    effect = (
        f"Path({str(started)!r}).touch()\ntime.sleep(6)\nPath({str(late)!r}).touch()\n"
    )
    if kind == "import":
        body = effect + "def entrypoint(argv):\n    return 'done'\n"
    else:
        signature = "pre_step()" if kind == "hook" else "entrypoint(argv)"
        body = f"def {signature}:\n" + "".join(
            "    " + line + "\n" for line in effect.splitlines()
        )
    _make_skill(tmp_path, "effect", "import time\nfrom pathlib import Path\n" + body)
    if kind == "hook":
        (tmp_path / "skills/effect/SKILL.md").write_text(
            "---\nname: effect\ndescription: hook\nhooks:\n  pre_step: scripts/run.py\n---\n"
        )
    runtime = _runtime_for(tmp_path, "effect")
    if kind == "hook":
        result = await runtime.run_skill_hook(
            "custom@effect", "pre_step", [], timeout_sec=5
        )
    else:
        result = await runtime.run_skill_script(
            "custom@effect", "scripts/run.py", [], timeout_sec=5
        )
    assert started.exists(), "必须确认技能实际开始，不能只测到进程启动超时"
    assert result.error_type == "timeout"
    await asyncio.sleep(6)
    assert not late.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["entrypoint", "hook"])
async def test_custom_callable_cancellation_prevents_late_write(tmp_path, kind):
    """调用方取消时也必须回收函数进程。"""
    import asyncio

    started, late = tmp_path / "started", tmp_path / "late"
    signature = "pre_step()" if kind == "hook" else "entrypoint(argv)"
    _make_skill(
        tmp_path,
        "cancel",
        (
            "import time\nfrom pathlib import Path\n"
            f"def {signature}:\n"
            f"    Path({str(started)!r}).touch()\n"
            "    time.sleep(1)\n"
            f"    Path({str(late)!r}).touch()\n"
        ),
    )
    if kind == "hook":
        (tmp_path / "skills/cancel/SKILL.md").write_text(
            "---\nname: cancel\ndescription: hook\nhooks:\n  pre_step: scripts/run.py\n---\n"
        )
    runtime = _runtime_for(tmp_path, "cancel")
    call = (
        runtime.run_skill_hook("custom@cancel", "pre_step", [], timeout_sec=15)
        if kind == "hook"
        else runtime.run_skill_script(
            "custom@cancel", "scripts/run.py", [], timeout_sec=15
        )
    )
    task = asyncio.create_task(call)
    try:
        async with asyncio.timeout(10):
            while not started.exists():
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await asyncio.sleep(1.2)
    assert not late.exists()


@pytest.mark.asyncio
async def test_custom_hook_context_and_sync_returned_awaitable(tmp_path):
    """子进程保留 hook 上下文，并等待同步函数返回的 awaitable。"""
    import json

    _make_skill(
        tmp_path,
        "context",
        """from agentsociety2.agent.base.skill_hook_context import get_hook_context
async def result():
    ctx = get_hook_context()
    return {"id": ctx.skill_id, "payload": ctx.payload, "root": str(ctx.workspace_root)}
def pre_step():
    return result()
""",
    )
    (tmp_path / "skills/context/SKILL.md").write_text(
        "---\nname: context\ndescription: hook\nhooks:\n  pre_step: scripts/run.py\n---\n"
    )
    runtime = _runtime_for(tmp_path, "context")
    result = await runtime.run_skill_hook(
        "custom@context", "pre_step", ["--args-json", '{"tick": 3}'], timeout_sec=15
    )
    assert result.ok, result.stderr
    assert json.loads(result.stdout) == {
        "id": "custom@context",
        "payload": {"tick": 3},
        "root": str(runtime.workspace_root()),
    }


@pytest.mark.asyncio
async def test_custom_entrypoint_context_and_sync_returned_awaitable(
    tmp_path, monkeypatch
):
    """入口上下文跨进程传递，返回 awaitable 时不得误报成功或丢失结果。"""
    monkeypatch.setenv("SKILL_TEST_CUSTOM_CONFIG", "inherited")
    _make_skill(
        tmp_path,
        "awaitable",
        """async def result(argv, ctx):
    import os
    assert os.environ["SKILL_TEST_CUSTOM_CONFIG"] == "inherited"
    assert len(argv[1]) == 262144
    assert ctx.skill_id == "custom@awaitable"
    assert ctx.env["AGENT_WORK_DIR"] == str(ctx.workspace_root)
    return "done:" + argv[0]
def entrypoint(argv, ctx):
    return result(argv, ctx)
""",
    )
    runtime = _runtime_for(tmp_path, "awaitable")
    result = await runtime.run_skill_script(
        "custom@awaitable", "scripts/run.py", ["value", "x" * 262144], timeout_sec=15
    )
    assert result.ok, result.stderr
    assert result.stdout == "done:value"


@pytest.mark.asyncio
async def test_custom_import_failure_is_not_executed_again(tmp_path):
    """导入失败保留诊断，且不能回退到脚本路径重复执行副作用。"""
    counter = tmp_path / "imports"
    _make_skill(
        tmp_path,
        "broken",
        (
            "from pathlib import Path\n"
            f"p = Path({str(counter)!r})\n"
            "p.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"
            "raise RuntimeError('import failed deliberately')\n"
            "def entrypoint(argv):\n    return 'unreachable'\n"
        ),
    )
    runtime = _runtime_for(tmp_path, "broken")
    result = await runtime.run_skill_script(
        "custom@broken", "scripts/run.py", [], timeout_sec=10
    )
    assert not result.ok
    assert result.error_type == "runtime"
    assert "import failed deliberately" in result.stderr
    assert counter.read_text() == "x"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [0, 3])
async def test_custom_systemexit_and_diagnostic_output(tmp_path, code):
    """函数打印不污染结果协议，SystemExit 保留真实退出码。"""
    _make_skill(
        tmp_path,
        "exit",
        (
            "def entrypoint(argv):\n"
            "    print('skill diagnostic')\n"
            f"    raise SystemExit({code})\n"
        ),
    )
    runtime = _runtime_for(tmp_path, "exit")
    result = await runtime.run_skill_script(
        "custom@exit", "scripts/run.py", [], timeout_sec=10
    )
    assert result.ok == (code == 0)
    assert result.exit_code == code
    assert result.error_type == "systemexit"
    assert "skill diagnostic" in result.stderr
