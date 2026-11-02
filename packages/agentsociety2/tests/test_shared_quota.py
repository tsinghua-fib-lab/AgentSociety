"""跨进程共享配额门测试(评审 P0,2026-10-19)。

契约:
- 未启用(默认 env)时 acquire/release 零开销立即返回
- 启用时:上限 N,第 N+1 个获取者必须等待;释放后可用
- 进程间互斥:两个独立解释器(子进程)并发获取,合计在途 ≤ N
- 计数正确性:acquire×k 后文件计数 = k,release 归零
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _patch_env(monkeypatch, tmp_path, limit):
    monkeypatch.setattr(
        "agentsociety2.config.llm_dispatcher._SHARED_QUOTA_LIMIT", limit
    )
    monkeypatch.setattr(
        "agentsociety2.config.llm_dispatcher._SHARED_QUOTA_FILE",
        str(tmp_path / "quota.lock"),
    )
    monkeypatch.setattr("agentsociety2.config.llm_dispatcher._SHARED_QUOTA_POLL", 0.05)


@pytest.mark.asyncio
async def test_disabled_quota_is_zero_overhead(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, limit=0)
    from agentsociety2.config.llm_dispatcher import (
        _acquire_shared_quota,
        _release_shared_quota,
    )

    # 未启用:立即返回,不创建任何文件
    await asyncio.wait_for(_acquire_shared_quota(), timeout=1.0)
    _release_shared_quota()
    assert not (tmp_path / "quota.lock").exists()


@pytest.mark.asyncio
async def test_limit_enforced_and_released(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, limit=2)
    from agentsociety2.config.llm_dispatcher import (
        _acquire_shared_quota,
        _release_shared_quota,
    )

    await _acquire_shared_quota()
    await _acquire_shared_quota()
    # 第三份必须等待(0.3s 内不返回)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(_acquire_shared_quota(), timeout=0.3)
    # 释放一份后立即可用
    _release_shared_quota()
    await asyncio.wait_for(_acquire_shared_quota(), timeout=1.0)
    _release_shared_quota()
    _release_shared_quota()


def _child_worker(lock_file: str, limit: int, hold: float, out_file: str):
    """子进程工作体:获取一份配额,写入时刻,持有一段时间后释放。"""
    import asyncio
    import time

    import agentsociety2.config.llm_dispatcher as d

    d._SHARED_QUOTA_LIMIT = limit
    d._SHARED_QUOTA_FILE = lock_file
    d._SHARED_QUOTA_POLL = 0.05

    async def main():
        await d._acquire_shared_quota()
        with open(out_file, "w") as f:
            f.write(f"acquired@{time.time():.3f}")
        await asyncio.sleep(hold)
        d._release_shared_quota()

    asyncio.run(main())


@pytest.mark.asyncio
async def test_cross_process_mutual_exclusion(tmp_path):
    """三子进程并发持有配额,上限 2:直接断言不变量——任一时刻的
    在途数 ≤ 上限。比时间戳差断言更鲁棒(时间戳 margin 在系统高负载
    下会被进程启动抖动吃掉,2026-10-19 全量套件下的偶发红即此因)。"""
    import time

    lock = str(tmp_path / "q.lock")
    hold = 1.2
    env = {**os.environ}
    child_code = (
        "import asyncio, time, sys\n"
        "import agentsociety2.config.llm_dispatcher as d\n"
        "lock, limit, hold, out = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]\n"
        "d._SHARED_QUOTA_LIMIT = limit\n"
        "d._SHARED_QUOTA_FILE = lock\n"
        "d._SHARED_QUOTA_POLL = 0.05\n"
        "async def main():\n"
        "    await d._acquire_shared_quota()\n"
        "    with open(out, 'w') as f:\n"
        "        f.write('ok')\n"
        "    await asyncio.sleep(hold)\n"
        "    d._release_shared_quota()\n"
        "asyncio.run(main())\n"
    )
    procs = []
    outs = []
    for i in range(3):
        out = str(tmp_path / f"out{i}.txt")
        outs.append(out)
        procs.append(
            subprocess.Popen(
                [sys.executable, "-c", child_code, lock, "2", str(hold), out],
                env=env,
            )
        )
    # 采样持有期内的在途计数峰值:每次读锁文件须 < 2 观测上限 2
    # (锁文件在 acquire/release 之间持有计数,峰值 ≤ limit 是不变量)。
    peak = 0
    samples = 0
    import fcntl

    deadline = time.monotonic() + 20
    while any(p.poll() is None for p in procs) and time.monotonic() < deadline:
        try:
            fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                raw = os.read(fd, 64).decode("utf-8", "ignore") or "0"
                peak = max(peak, int(raw.strip() or 0))
                samples += 1
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        except OSError:
            pass  # 锁被持有中,跳过本拍采样
        await asyncio.sleep(0.05)
    for p in procs:
        rc = p.wait(timeout=30)
        assert rc == 0, f"子进程失败 rc={rc}; 转录见 {tmp_path}"
    # 三子进程全部成功(out 文件存在)且采样峰值 ≤ 2(互斥不变量)。
    for o in outs:
        assert Path(o).read_text(encoding="utf-8") == "ok"
    assert peak <= 2, f"在途峰值 {peak} 超过上限 2,互斥失效"
    assert samples >= 5, "采样过少,测试无效"


@pytest.mark.asyncio
async def test_release_survives_lock_contention(monkeypatch, tmp_path):
    """释放方遇竞争后必须归还额度，不能静默漏减。"""
    import fcntl
    import threading

    from agentsociety2.config import llm_dispatcher as d

    _patch_env(monkeypatch, tmp_path, limit=1)
    await d._acquire_shared_quota()
    entered = threading.Event()
    original_flock = fcntl.flock

    def tracked_flock(fd, operation):
        entered.set()
        return original_flock(fd, operation)

    with open(d._SHARED_QUOTA_FILE, "r+") as holder:
        original_flock(holder, fcntl.LOCK_EX)
        monkeypatch.setattr(fcntl, "flock", tracked_flock)
        release = asyncio.create_task(asyncio.to_thread(d._release_shared_quota))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
        finally:
            original_flock(holder, fcntl.LOCK_UN)
        await asyncio.wait_for(release, 2)
    assert Path(d._SHARED_QUOTA_FILE).read_text() == "0"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "cancel", "io"])
async def test_admission_failure_returns_local_capacity(monkeypatch, failure):
    """配额等待超时、取消或文件错误均不能耗尽本地信号量。"""
    from unittest.mock import AsyncMock

    from agentsociety2.config import llm_dispatcher as d

    client = d.LLMClient(
        model_name="test",
        base_url="http://localhost:1",
        api_key="test",
        model_type="default",
    )
    sem = AsyncMock()
    client._sem = sem
    client._router = AsyncMock()
    client._ensure_runtime = lambda: None
    error = {
        "timeout": TimeoutError,
        "cancel": asyncio.CancelledError,
        "io": PermissionError,
    }[failure]
    monkeypatch.setattr(d, "_acquire_shared_quota", AsyncMock(side_effect=error()))
    monkeypatch.setattr(d, "_SHARED_QUOTA_POLL", 0)
    expected = d.LLMDispatchError if failure == "timeout" else error
    with pytest.raises(expected):
        await client.call(max_retries=1)
    assert sem.acquire.await_count > 0
    assert sem.release.await_count == sem.acquire.await_count
    client._router.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_backoff_does_not_hold_capacity(monkeypatch, tmp_path):
    """限流退避时额度已归还，其他实验可以提交请求。"""
    from unittest.mock import AsyncMock, Mock

    from agentsociety2.config import llm_dispatcher as d

    _patch_env(monkeypatch, tmp_path, limit=1)
    client = d.LLMClient(
        model_name="test",
        base_url="http://localhost:1",
        api_key="test",
        model_type="default",
    )
    client._ensure_runtime = lambda: None
    sem = AsyncMock()
    sem.record_latency = Mock()
    client._sem = sem
    client._router = AsyncMock()
    client._router.acompletion.side_effect = RuntimeError(
        "Rate limit reached; try again in 0.25 seconds"
    )
    waits = []

    async def check_backoff(delay):
        waits.append(delay)
        assert Path(d._SHARED_QUOTA_FILE).read_text() == "0"
        assert sem.release.await_count == sem.acquire.await_count

    monkeypatch.setattr(d.asyncio, "sleep", check_backoff)
    with pytest.raises(d.LLMDispatchError):
        await client.call(max_retries=1, base_delay=0.25)
    assert waits == [0.25]
    assert Path(d._SHARED_QUOTA_FILE).read_text() == "0"
    assert sem.release.await_count == 2


@pytest.mark.asyncio
async def test_cancelled_request_returns_both_capacities(monkeypatch, tmp_path):
    """已发出的请求取消后，共享额度和本地容量均归还。"""
    from unittest.mock import AsyncMock

    from agentsociety2.config import llm_dispatcher as d

    _patch_env(monkeypatch, tmp_path, limit=1)
    client = d.LLMClient(
        model_name="test",
        base_url="http://localhost:1",
        api_key="test",
        model_type="default",
    )
    client._ensure_runtime = lambda: None
    client._sem = AsyncMock()
    client._router = AsyncMock()
    started = asyncio.Event()

    async def pending_request(**kwargs):
        started.set()
        await asyncio.Event().wait()

    client._router.acompletion.side_effect = pending_request
    request = asyncio.create_task(client.call())
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert Path(d._SHARED_QUOTA_FILE).read_text() == "1"
    finally:
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
    assert Path(d._SHARED_QUOTA_FILE).read_text() == "0"
    client._sem.release.assert_awaited_once_with(overloaded=False)


@pytest.mark.asyncio
async def test_connection_retry_backs_off_without_holding_capacity(monkeypatch, tmp_path):
    """短暂断连不能瞬间耗尽重试次数，等待期间也不能占用并发额度。"""
    from unittest.mock import AsyncMock, Mock

    from agentsociety2.config import llm_dispatcher as d

    _patch_env(monkeypatch, tmp_path, limit=1)
    client = d.LLMClient("test", "http://localhost:1", "test")
    client._ensure_runtime = lambda: None
    sem = AsyncMock()
    sem.record_latency = Mock()
    client._sem = sem
    client._router = AsyncMock()
    recovered = Mock(usage=None)
    client._router.acompletion.side_effect = [
        ConnectionError("temporary disconnect"),
        ConnectionError("temporary disconnect"),
        recovered,
    ]
    waits = []

    async def check_wait(delay):
        waits.append(delay)
        assert Path(d._SHARED_QUOTA_FILE).read_text() == "0"
        assert sem.release.await_count == sem.acquire.await_count

    monkeypatch.setattr(d.asyncio, "sleep", check_wait)
    assert await client.call(base_delay=1, max_delay=1.5) is recovered
    assert waits == [1, 1.5]
    assert client._router.acompletion.await_count == 3
    assert Path(d._SHARED_QUOTA_FILE).read_text() == "0"
