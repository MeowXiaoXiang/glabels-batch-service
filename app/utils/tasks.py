"""Keep ownership of cleanup even when an observer is cancelled repeatedly."""

import asyncio
from collections.abc import Callable
from functools import partial


async def settle[T](task: asyncio.Task[T]) -> T:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def owned[T](task: asyncio.Task[T]) -> T:
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
    task = asyncio.create_task(asyncio.to_thread(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await settle(task)
        raise
