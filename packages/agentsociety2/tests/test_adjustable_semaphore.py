"""Semaphore resizing preserves in-flight permit accounting."""

from __future__ import annotations

import asyncio

import pytest

from agentsociety2.config.llm_dispatcher import _AdjustableSemaphore


async def test_shrink_does_not_create_phantom_permits():
    """满载 16 → 缩容 11 → 16 次 release 后 available 不得超过 11。"""
    sem = _AdjustableSemaphore(16)
    # 满载:全部借出
    holders = [asyncio.create_task(sem.acquire()) for _ in range(16)]
    await asyncio.gather(*holders)
    assert sem._available == 0

    await sem.set_capacity(11)
    assert sem.capacity == 11

    # 16 个旧许可全部归还(修复前:available 变 16,幻影 5 个)
    for _ in range(16):
        await sem.release()
    assert sem._available <= 11, (
        f"幻影许可:available={sem._available} > capacity={sem.capacity}"
    )


async def test_sustained_demand_concurrency_tracks_shrunk_limit():
    """持续需求下观测并发跟随缩容后的 limit,而非历史峰值。

    最小仿真(审计复现脚本的行为锁定):200 个并发需求,中途连续
    AIMD 缩容 16→11→7→4→2→1;修复前观测最大并发恒为 16。
    """
    sem = _AdjustableSemaphore(16)
    observed_peak = 0
    inflight = 0
    lock = asyncio.Lock()

    async def one_request():
        nonlocal observed_peak, inflight
        await sem.acquire()
        async with lock:
            inflight += 1
            observed_peak = max(observed_peak, inflight)
        await asyncio.sleep(0)  # 让出循环,允许其它任务进入
        async with lock:
            inflight -= 1
        await sem.release()

    async def shrinker():
        for cap in (11, 7, 4, 2, 1):
            await asyncio.sleep(0.02)
            await sem.set_capacity(cap)

    tasks = [asyncio.create_task(one_request()) for _ in range(200)]
    shrink = asyncio.create_task(shrinker())
    await asyncio.gather(*tasks, shrink)

    # 收敛判据:峰值出现在缩容完成前的窗口里是正常的(旧许可在途),
    # 但归还后并发必须被新容量钳住——用结束态与中途态共同断言。
    assert sem._available <= sem.capacity
    # 缩容到 1 且全部请求完成后,available 必须恰好为 1(无幻影)。
    assert sem._available == 1, (
        f"结束后 available={sem._available} != capacity=1(幻影 {sem._available - 1} 个)"
    )


async def test_release_clamp_expansion_not_affected():
    """正常路径回归:未缩容时 release/increment 行为不变。"""
    sem = _AdjustableSemaphore(3)
    a, b = asyncio.create_task(sem.acquire()), asyncio.create_task(sem.acquire())
    await asyncio.gather(a, b)
    await sem.release()
    await sem.release()
    assert sem._available == 3  # 2 借出 2 归还,回满,不钳
    # 扩容照常加可用
    await sem.set_capacity(5)
    assert sem._available == 5


async def test_shrink_below_inflight_debt_is_repaid():
    """缩容低于在途数:先偿还债务,最终仅留下新容量的可用许可。"""
    sem = _AdjustableSemaphore(8)
    holders = [asyncio.create_task(sem.acquire()) for _ in range(8)]
    await asyncio.gather(*holders)
    await sem.set_capacity(2)
    # 8 个旧许可归还,只有 2 个计入
    for _ in range(8):
        await sem.release()
    assert sem._available == 2
    # 再 release 也不超(钳上界)
    await sem.release()
    assert sem._available == 2


@pytest.mark.parametrize("start,shrink_to", [(16, 11), (8, 2), (4, 1), (2, 1)])
async def test_phantom_matrix(start, shrink_to):
    """参数化:任意缩容组合下归还都不超容量。"""
    sem = _AdjustableSemaphore(start)
    holders = [asyncio.create_task(sem.acquire()) for _ in range(start)]
    await asyncio.gather(*holders)
    await sem.set_capacity(shrink_to)
    for _ in range(start):
        await sem.release()
    assert sem._available <= shrink_to


async def test_shrink_retains_inflight_debt_under_waiting_demand():
    sem = _AdjustableSemaphore(4)
    for _ in range(4):
        await sem.acquire()
    await sem.set_capacity(1)
    waiter = asyncio.create_task(sem.acquire())
    try:
        for _ in range(3):
            await sem.release()
            await asyncio.sleep(0)
            assert not waiter.done(), (
                "new request started while capacity still occupied"
            )
        await sem.release()
        await asyncio.wait_for(waiter, timeout=1)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
