import asyncio

import pytest

from app.services.resource_scheduler import ResourceScheduler


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [1, 2, 3, 7])
async def test_merge_reserve_and_small_cpu_clamp(budget):
    scheduler = ResourceScheduler(budget)
    running = [await scheduler.acquire("render", "old") for _ in range(budget)]
    merge = asyncio.create_task(scheduler.acquire("merge", "finishing"))
    render = asyncio.create_task(scheduler.acquire("render", "new"))
    await asyncio.sleep(0)
    for lease in running[: scheduler.merge_cost]:
        lease.release()
        assert scheduler.used <= budget
    finishing = await asyncio.wait_for(merge, 1)
    assert not render.done()
    finishing.release()
    fresh = await asyncio.wait_for(render, 1)
    fresh.release()
    for lease in running:
        lease.release()
    assert scheduler.used == 0


@pytest.mark.asyncio
async def test_round_robin_and_cancel_after_grant_does_not_leak():
    scheduler = ResourceScheduler(1)
    first = await scheduler.acquire("render", "first")
    tasks = [
        asyncio.create_task(scheduler.acquire("render", job)) for job in ("A", "A", "B")
    ]
    await asyncio.sleep(0)
    first.release()
    a = await tasks[0]
    a.release()
    b = await tasks[2]
    assert not tasks[1].done()
    b.release()
    tasks[1].cancel()
    with pytest.raises(asyncio.CancelledError):
        await tasks[1]
    assert scheduler.used == 0


@pytest.mark.asyncio
async def test_running_merge_does_not_reserve_a_second_merges_capacity():
    scheduler = ResourceScheduler(3)
    merge = await scheduler.acquire("merge", "A")
    pending = asyncio.create_task(scheduler.acquire("merge", "B"))
    await asyncio.sleep(0)
    render = await asyncio.wait_for(scheduler.acquire("render", "C"), 1)
    assert scheduler.used == 3
    render.release()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    merge.release()
    assert scheduler.used == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [1, 2])
async def test_continuous_merges_allow_render_to_progress_on_small_budget(budget):
    scheduler = ResourceScheduler(budget)
    initial = await scheduler.acquire("merge", "A")
    waiting_merge = asyncio.create_task(scheduler.acquire("merge", "B"))
    render = asyncio.create_task(scheduler.acquire("render", "C"))
    await asyncio.sleep(0)
    initial.release()
    next_render = await asyncio.wait_for(render, 1)
    assert not waiting_merge.done()
    next_render.release()
    final = await asyncio.wait_for(waiting_merge, 1)
    final.release()
    assert scheduler.used == 0
