"""Single-owner SQLite metadata, serialized on one dedicated I/O thread."""

import asyncio
import sqlite3
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, BinaryIO, TypeVar
from uuid import UUID

from app.utils.tasks import settle

T = TypeVar("T")

SCHEMA = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','rendering','merging','done','failed')),
    template_name TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK(record_count > 0),
    copies INTEGER NOT NULL CHECK(copies > 0),
    batch_count INTEGER NOT NULL CHECK(batch_count > 0),
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER,
    expires_at INTEGER,
    final_name TEXT CHECK(final_name IS NULL OR final_name = job_id || '.pdf'),
    publication_intent_at INTEGER,
    error_code TEXT,
    error_message TEXT,
    CHECK ((status IN ('done','failed') AND finished_at IS NOT NULL AND expires_at IS NOT NULL)
        OR (status NOT IN ('done','failed') AND finished_at IS NULL)),
    CHECK (status != 'done' OR (final_name IS NOT NULL AND publication_intent_at IS NOT NULL
        AND error_code IS NULL)),
    CHECK (status != 'failed' OR error_code IS NOT NULL)
);
CREATE INDEX jobs_created ON jobs(created_at DESC);
CREATE INDEX jobs_expiry ON jobs(expires_at) WHERE expires_at IS NOT NULL;
PRAGMA user_version = 1;
"""


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class JobStore:
    def __init__(self, path: Path, *, retention_hours: float = 24) -> None:
        self.path = path
        self.retention_ms = int(retention_hours * 3_600_000)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="job-store"
        )
        self._connection: sqlite3.Connection | None = None
        self._owner: BinaryIO | None = None
        self.healthy = True

    async def _io(self, function: Callable[[], T]) -> T:
        # Cancellation cannot abandon a transaction that will commit later.
        def checked() -> T:
            try:
                return function()
            except sqlite3.DatabaseError:
                self.healthy = False
                raise

        future = asyncio.get_running_loop().run_in_executor(self._executor, checked)

        async def wait() -> T:
            return await future

        task = asyncio.create_task(wait())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await settle(task)
            raise

    @property
    def db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("JobStore is not open")
        return self._connection

    async def open(self) -> None:
        def initialize() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            owner = self.path.with_suffix(".lock").open("a+b")
            try:
                if sys.platform == "win32":
                    import msvcrt

                    if owner.seek(0, 2) == 0:
                        owner.write(b"0")
                        owner.flush()
                    owner.seek(0)
                    msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._owner = owner
                self._connection = sqlite3.connect(self.path, timeout=5)
                self.db.row_factory = sqlite3.Row
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise RuntimeError(f"Unsupported job schema version: {version}")
                if version == 0:
                    if self.db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchone():
                        raise RuntimeError("Unrecognized existing database")
                    self.db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.execute("PRAGMA synchronous=FULL")
            except BaseException:
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None
                owner.close()
                self._owner = None
                raise

        await self._io(initialize)

    async def create(
        self, job_id: str, template: str, records: int, copies: int, batches: int
    ) -> None:
        if str(UUID(job_id)) != job_id:
            raise ValueError("Noncanonical job UUID")

        def insert() -> None:
            with self.db:
                self.db.execute(
                    "INSERT INTO jobs(job_id,status,template_name,record_count,copies,batch_count,created_at) "
                    "VALUES (?,'pending',?,?,?,?,?)",
                    (job_id, template, records, copies, batches, now_ms()),
                )

        await self._io(insert)

    async def execute(self, sql: str, parameters: tuple[Any, ...]) -> None:
        def update() -> None:
            with self.db:
                self.db.execute(sql, parameters)

        await self._io(update)

    async def stage(self, job_id: str, status: str) -> None:
        previous = "pending" if status == "rendering" else "rendering"
        if status not in ("rendering", "merging"):
            raise ValueError("Invalid stage")
        await self.execute(
            "UPDATE jobs SET status=? WHERE job_id=? AND status=?",
            (status, job_id, previous),
        )

    async def started(self, job_id: str) -> None:
        await self.execute(
            "UPDATE jobs SET started_at=COALESCE(started_at,?) WHERE job_id=? AND status='rendering'",
            (now_ms(), job_id),
        )

    async def intent(self, job_id: str) -> None:
        timestamp = now_ms()
        await self.execute(
            "UPDATE jobs SET final_name=?,publication_intent_at=?,expires_at=? "
            "WHERE job_id=? AND status IN ('rendering','merging')",
            (job_id + ".pdf", timestamp, timestamp + self.retention_ms, job_id),
        )

    async def done(self, job_id: str) -> None:
        await self.execute(
            "UPDATE jobs SET status='done',finished_at=publication_intent_at "
            "WHERE job_id=? AND status IN ('rendering','merging') AND publication_intent_at IS NOT NULL",
            (job_id,),
        )

    async def fail(self, job_id: str, code: str, message: str) -> None:
        timestamp = now_ms()
        await self.execute(
            "UPDATE jobs SET status='failed',finished_at=?,expires_at="
            "CASE WHEN publication_intent_at IS NOT NULL THEN expires_at ELSE ? END,error_code=?,error_message=? "
            "WHERE job_id=? AND status NOT IN ('done','failed')",
            (timestamp, timestamp + self.retention_ms, code, message[:500], job_id),
        )

    async def rows(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        return await self._io(
            lambda: [dict(row) for row in self.db.execute(sql, parameters).fetchall()]
        )

    async def get(self, job_id: str) -> dict[str, Any] | None:
        rows = await self.rows(
            "SELECT * FROM jobs WHERE job_id=? AND (expires_at IS NULL OR expires_at>?)",
            (job_id, now_ms()),
        )
        return rows[0] if rows else None

    async def recent(self, limit: int) -> list[dict[str, Any]]:
        return await self.rows(
            "SELECT * FROM jobs WHERE expires_at IS NULL OR expires_at>? ORDER BY created_at DESC LIMIT ?",
            (now_ms(), limit),
        )

    async def close(self) -> None:
        def release() -> None:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            if self._owner is not None:
                self._owner.close()
                self._owner = None

        try:
            await self._io(release)
        finally:
            await asyncio.to_thread(self._executor.shutdown, wait=True)
