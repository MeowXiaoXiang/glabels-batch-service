"""One persistent spawn worker; no executor backlog or private pool access."""

import asyncio
import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing.connection import wait
from multiprocessing.process import BaseProcess
from pathlib import Path

from app.core.errors import ExecutionUnavailable
from app.utils.pdf_worker import assemble_pdf, worker_identity
from app.utils.tasks import owned, settle


class PdfMerger:
    def __init__(
        self,
        *,
        timeout: float = 120,
        reap_timeout: float = 5,
        max_bytes: int = 256_000_000,
        max_pages: int = 10_000,
    ) -> None:
        self.timeout = timeout
        self.reap_timeout = reap_timeout
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self._pool: ProcessPoolExecutor | None = None
        self._child: BaseProcess | None = None
        self._lock = asyncio.Lock()
        self.healthy = True
        self.restarts = 0

    async def start(self) -> None:
        async with self._lock:
            if self._pool is None:
                await self._start()

    async def _start(self) -> None:
        if not self.healthy:
            raise ExecutionUnavailable("Merge worker could not be safely recovered")
        pool = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
        self._pool = pool
        try:
            future = pool.submit(worker_identity)
            # In supported CPython, spawn submit registers the child before it
            # returns. Retain its handle now: active_children prunes exited ones.
            children = {p.pid: p for p in mp.active_children()}
            pid = await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(future)), 15
            )
            self._child = children[pid]
        except BaseException:
            self.healthy = False
            # No work lease was issued yet. Do not claim startup recovery if
            # the identity handshake failed; startup must fail closed.
            await asyncio.to_thread(pool.kill_workers)
            raise

    async def merge(
        self,
        paths: list[Path],
        destination: Path | None,
        *,
        expected_pages: list[int] | None = None,
    ) -> int:
        return await owned(
            asyncio.create_task(self._merge(paths, destination, expected_pages))
        )

    async def _merge(
        self,
        paths: list[Path],
        destination: Path | None,
        expected_pages: list[int] | None,
    ) -> int:
        async with self._lock:
            if self._pool is None:
                await self._start()
            if self._pool is None:
                raise ExecutionUnavailable("Merge worker did not start")
            try:
                future = self._pool.submit(
                    assemble_pdf,
                    [str(p) for p in paths],
                    str(destination) if destination is not None else None,
                    self.max_bytes,
                    self.max_pages,
                    expected_pages,
                )
                wrapped = asyncio.wrap_future(future)
                # wait() times out without cancelling the OS operation or its
                # completion observer. Always consume late failure on hard kill.
                wrapped.add_done_callback(
                    lambda f: None if f.cancelled() else f.exception()
                )
                completed, _ = await asyncio.wait([wrapped], timeout=self.timeout)
                if not completed:
                    raise TimeoutError("PDF operation exceeded its deadline")
                return wrapped.result()
            except TimeoutError, BrokenProcessPool, asyncio.CancelledError:
                cleanup = asyncio.create_task(self._stop(hard=True))
                await settle(cleanup)
                self.restarts += 1
                # Replacement is lazy and happens before the next submission.
                raise

    async def _stop(self, *, hard: bool) -> None:
        pool, child = self._pool, self._child
        if pool is None:
            return
        if child is None:
            self.healthy = False
            raise ExecutionUnavailable("Worker identity unavailable")
        if hard:
            await asyncio.to_thread(pool.kill_workers)
        else:
            # Join the live process independently; do not block this event loop.
            pool.shutdown(wait=False, cancel_futures=True)
        # Concurrent waitpid/join by the executor manager races on POSIX. Wait
        # for the public OS exit sentinel first, then allow its reap to settle.
        exited = await asyncio.to_thread(
            lambda: bool(wait([child.sentinel], self.reap_timeout))
        )
        deadline = time.monotonic() + self.reap_timeout
        while exited and child.exitcode is None and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        if exited:
            await asyncio.to_thread(child.join, self.reap_timeout)
        if child.is_alive() or child.exitcode is None:
            self.healthy = False
            raise ExecutionUnavailable("Merge process exit not confirmed")
        # Do not child.close(): executor manager can still inspect its handle
        # during BrokenProcessPool cleanup. Let its own references retire.
        self._pool = None
        self._child = None

    async def close(self) -> None:
        async with self._lock:
            await self._stop(hard=False)
