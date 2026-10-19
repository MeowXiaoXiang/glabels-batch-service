"""Atomic weighted admission, render round robin and a single merge slot."""

import asyncio
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from types import TracebackType
from typing import Literal

from app.core.errors import ExecutionUnavailable

Kind = Literal["render", "merge"]


@dataclass
class Lease:
    scheduler: ResourceScheduler
    kind: Kind
    cost: int
    released: bool = False
    started: float = field(default_factory=time.monotonic)

    async def __aenter__(self) -> Lease:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if isinstance(exc, ExecutionUnavailable):
            # Retain accounting when the actual operation might still be alive.
            self.scheduler.healthy = False
        else:
            self.release()

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self.scheduler.used -= self.cost
        self.scheduler.active[self.kind] -= 1
        self.scheduler.run_seconds[self.kind] += time.monotonic() - self.started
        if self.kind == "merge":
            self.scheduler.render_due = True
        self.scheduler.dispatch()


@dataclass
class Waiter:
    future: asyncio.Future[Lease]
    submitted: float


class ResourceScheduler:
    def __init__(self, budget: int, merge_cost: int = 2) -> None:
        if budget < 1 or merge_cost < 1:
            raise ValueError("Work budget and merge cost must be positive")
        self.budget = budget
        self.merge_cost = min(merge_cost, budget)
        self.used = 0
        self.active: dict[Kind, int] = {"render": 0, "merge": 0}
        self.renders: OrderedDict[str, deque[Waiter]] = OrderedDict()
        self.merges: deque[Waiter] = deque()
        self.healthy = True
        self.render_due = False
        self.wait_seconds: dict[Kind, float] = {"render": 0, "merge": 0}
        self.run_seconds: dict[Kind, float] = {"render": 0, "merge": 0}

    async def acquire(self, kind: Kind, job_id: str) -> Lease:
        if not self.healthy:
            raise ExecutionUnavailable("Work scheduler is unavailable")
        waiter = Waiter(asyncio.get_running_loop().create_future(), time.monotonic())
        queue = (
            self.merges if kind == "merge" else self.renders.setdefault(job_id, deque())
        )
        queue.append(waiter)
        self.dispatch()
        try:
            return await asyncio.shield(waiter.future)
        except asyncio.CancelledError:
            if waiter.future.done() and not waiter.future.cancelled():
                waiter.future.result().release()
            else:
                waiter.future.cancel()
                self.dispatch()
            raise

    def _prune(self) -> None:
        while self.merges and self.merges[0].future.cancelled():
            self.merges.popleft()
        for job_id, queue in list(self.renders.items()):
            while queue and queue[0].future.cancelled():
                queue.popleft()
            if not queue:
                del self.renders[job_id]

    def _grant(self, waiter: Waiter, kind: Kind, cost: int) -> None:
        self.used += cost
        self.active[kind] += 1
        self.wait_seconds[kind] += time.monotonic() - waiter.submitted
        if kind == "render":
            self.render_due = False
        waiter.future.set_result(Lease(self, kind, cost))

    def dispatch(self) -> None:
        if not self.healthy:
            return
        while True:
            self._prune()
            free = self.budget - self.used
            merge_waiting = bool(self.merges) and self.active["merge"] == 0
            if (
                merge_waiting
                and self.render_due
                and self.renders
                and self.budget <= self.merge_cost
                and free > 0
            ):
                # When merge consumes the full budget, let one render advance
                # between merges so neither stage can starve the other.
                job_id, queue = self.renders.popitem(last=False)
                waiter = queue.popleft()
                if queue:
                    self.renders[job_id] = queue
                self._grant(waiter, "render", 1)
                continue
            if merge_waiting and free >= self.merge_cost:
                self._grant(self.merges.popleft(), "merge", self.merge_cost)
                continue
            reserve = self.merge_cost if merge_waiting else 0
            if free <= reserve or not self.renders:
                return
            job_id, queue = self.renders.popitem(last=False)
            waiter = queue.popleft()
            if queue:
                self.renders[job_id] = queue
            self._grant(waiter, "render", 1)

    def snapshot(self) -> dict[str, float]:
        self._prune()
        waiters = list(self.merges) + [w for q in self.renders.values() for w in q]
        return {
            "tokens_budget": self.budget,
            "merge_cost": self.merge_cost,
            "tokens_used": self.used,
            "render_active": self.active["render"],
            "merge_active": self.active["merge"],
            "render_queued": sum(len(q) for q in self.renders.values()),
            "merge_queued": len(self.merges),
            "oldest_wait_seconds": max(
                (time.monotonic() - w.submitted for w in waiters), default=0
            ),
        }
