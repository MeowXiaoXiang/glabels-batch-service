"""Keep ownership of cleanup even when an observer is cancelled repeatedly."""

import asyncio
from collections.abc import Callable
from functools import partial


async def settle[T](task: asyncio.Task[T]) -> T:
    """Wait through observer cancellation; return or raise the owned task result."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def owned[T](task: asyncio.Task[T]) -> T:
    """Propagate cancellation only after the cancelled child finishes cleanup."""
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.cancel()
        try:
            await settle(task)
        except asyncio.CancelledError:
            pass
        raise


async def io[T](function: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Finish thread I/O before propagating cancellation; threads cannot be cancelled."""
    task = asyncio.create_task(asyncio.to_thread(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await settle(task)
        raise
