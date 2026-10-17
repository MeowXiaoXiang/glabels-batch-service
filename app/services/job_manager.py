"""Job admission, persistence, supervision and short-lived artifact ownership."""

import asyncio
import math
import shutil
from collections import deque
from datetime import UTC, datetime
from typing import Any, BinaryIO, cast
from uuid import UUID, uuid4

from loguru import logger

from app.config import Settings
from app.schema import JobError, JobProgress, JobStatusResponse, LabelRequest
from app.services.job_pipeline import JobPipeline, batch_shape
from app.services.job_store import JobStore, now_ms
from app.services.pdf_merger import PdfMerger, WorkerUnavailable
from app.services.resource_scheduler import ResourceScheduler
from app.services.template_service import TemplateService
from app.utils.cpu_detect import get_cpu_capacity
from app.utils.files import remove_workspace
from app.utils.glabels_engine import GlabelsEngine
from app.utils.tasks import io, settle


class CapacityError(RuntimeError):
    pass


class ArtifactError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class JobManager:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        budget = max(1, math.floor(get_cpu_capacity()) - cfg.API_CPU_RESERVE)
        if cfg.WORK_TOKENS:
            budget = min(budget, cfg.WORK_TOKENS)
        self.scheduler = ResourceScheduler(budget, cfg.MERGE_COST)
        self.renderer = GlabelsEngine(
            glabels_bin=cfg.GLABELS_EXECUTABLE,
            default_timeout=cfg.GLABELS_TIMEOUT,
            reap_timeout=cfg.PROCESS_REAP_TIMEOUT,
        )
        self.merger = PdfMerger(
            timeout=cfg.MERGE_TIMEOUT,
            reap_timeout=cfg.PROCESS_REAP_TIMEOUT,
            max_bytes=cfg.MAX_PDF_BYTES,
            max_pages=cfg.MAX_PDF_PAGES,
        )
        self.store = JobStore(
            cfg.STATE_DIR / "jobs.sqlite3", retention_hours=cfg.RETENTION_HOURS
        )
        self.catalog = TemplateService(cfg.TEMPLATES_DIR)
        self.progress: dict[str, JobProgress] = {}
        self.pipeline = JobPipeline(
            cfg,
            self.store,
            self.scheduler,
            self.renderer,
            self.merger,
            self.catalog,
            self.progress,
        )
        self.pending: deque[tuple[str, LabelRequest]] = deque()
        self.active: dict[str, asyncio.Task[None]] = {}
        self._admission = asyncio.Lock()
        self._artifacts = asyncio.Lock()
        self._downloads: dict[str, int] = {}
        self._cleanup_cursor: tuple[int, str] = (0, "")
        self._idle = asyncio.Event()
        self._idle.set()
        self._cleanup: asyncio.Task[None] | None = None
        self.accepting = False
        self.healthy = True
        self.submitted = 0
        self.completed = 0
        self.failed = 0
        self.cleanup_failures = 0

    @property
    def ready(self) -> bool:
        return (
            self.accepting
            and self.healthy
            and self.scheduler.healthy
            and self.merger.healthy
            and self.renderer.healthy
            and self.store.healthy
        )

    async def start(self) -> None:
        try:
            for root in (self.cfg.TEMP_DIR, self.cfg.OUTPUT_DIR, self.cfg.STATE_DIR):
                await io(root.mkdir, parents=True, exist_ok=True)
            self.renderer.verify()
            await self.store.open()
            await self.merger.start()
            rows = await self.store.rows(
                "SELECT * FROM jobs WHERE status NOT IN ('done','failed')"
            )
            for row in rows:
                await self._recover(row, "interrupted")
            await self.cleanup()
            self.accepting = True
            self._cleanup = asyncio.create_task(self._cleanup_loop())
        except BaseException:
            self.accepting = False
            try:
                await self.merger.close()
            finally:
                await self.store.close()
            raise

    async def submit_job(self, req: LabelRequest) -> str:
        task = asyncio.create_task(self._submit(req))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Once metadata commits, enqueue must still complete. A disconnected
            # caller is an observer, not the owner of accepted work.
            await settle(task)
            raise

    async def _submit(self, req: LabelRequest) -> str:
        async with self._admission:
            if not self.ready or len(self.pending) >= self.cfg.MAX_PENDING_JOBS:
                raise CapacityError("Service busy or not ready")
            await io(self.catalog.get_template_path, req.template_name)
            _, count = batch_shape(req, self.cfg)
            for root in (self.cfg.TEMP_DIR, self.cfg.OUTPUT_DIR):
                if (
                    await io(shutil.disk_usage, root)
                ).free < self.cfg.MIN_FREE_DISK_BYTES:
                    raise CapacityError("Insufficient disk capacity")
            identifier = str(uuid4())
            try:
                await self.store.create(
                    identifier,
                    req.template_name,
                    len(req.data),
                    req.copies,
                    count,
                    copy_order=req.copy_order,
                    labels_per_page=req.labels_per_page,
                )
            except Exception:
                self.healthy = False
                raise
            self.pending.append((identifier, req))
            self.submitted += 1
            self._idle.clear()
            self._pump()
            return identifier

    def _pump(self) -> None:
        while (
            self.pending
            and len(self.active) < self.cfg.MAX_INFLIGHT_JOBS
            and self.healthy
            and self.scheduler.healthy
        ):
            identifier, request = self.pending.popleft()
            task = asyncio.create_task(self._execute(identifier, request))
            self.active[identifier] = task

            def finished(result: asyncio.Task[None], job_id: str = identifier) -> None:
                self._finished(job_id, result)

            task.add_done_callback(finished)
        if not self.pending and not self.active:
            self._idle.set()

    def _finished(self, identifier: str, task: asyncio.Task[None]) -> None:
        self.active.pop(identifier, None)
        self.progress.pop(identifier, None)
        if not task.cancelled() and task.exception() is not None:
            self.healthy = False
            logger.error("Job supervision failed: {}", type(task.exception()).__name__)
        self._pump()

    async def _execute(self, identifier: str, request: LabelRequest) -> None:
        try:
            await self.pipeline.run(identifier, request)
            self.completed += 1
        except asyncio.CancelledError:
            await self._recover_current(identifier, "shutdown_cancelled")
            raise
        except Exception as exc:
            logger.opt(exception=exc).error("Job {} failed", identifier)
            self.failed += 1
            if (
                not self.merger.healthy
                or not self.renderer.healthy
                or not self.scheduler.healthy
            ):
                self.healthy = False
            await self._recover_current(identifier, "generation_failed")

    async def _recover_current(self, identifier: str, code: str) -> None:
        rows = await self.store.rows("SELECT * FROM jobs WHERE job_id=?", (identifier,))
        if rows and rows[0]["status"] not in ("done", "failed"):
            await self._recover(rows[0], code)

    async def _recover(self, row: dict[str, Any], code: str) -> None:
        identifier = row["job_id"]
        if str(UUID(identifier)) != identifier:
            raise RuntimeError("Invalid persisted job identifier")
        final = self.cfg.OUTPUT_DIR / f"{identifier}.pdf"
        if (
            row["publication_intent_at"] is not None
            and row["final_name"] == final.name
            and final.is_file()
        ):
            if row["expires_at"] > now_ms():
                try:
                    async with await self.scheduler.acquire("merge", identifier):
                        await self.merger.merge([final], None)
                except WorkerUnavailable:
                    raise
                except Exception:
                    logger.warning(
                        "Published artifact validation failed for {}", identifier
                    )
                else:
                    await self.store.done(identifier)
                    return
        await self.store.fail(
            identifier, code, "Job did not complete; submit a new request if needed"
        )

    def _response(self, row: dict[str, Any]) -> JobStatusResponse:
        def timestamp(name: str) -> datetime | None:
            value = row[name]
            return (
                datetime.fromtimestamp(value / 1000, UTC) if value is not None else None
            )

        progress = self.progress.get(row["job_id"])
        if row["status"] == "done":
            progress = JobProgress(
                rendered_batches=row["batch_count"], total_batches=row["batch_count"]
            )
        return JobStatusResponse(
            job_id=row["job_id"],
            status=row["status"],
            template_name=row["template_name"],
            record_count=row["record_count"],
            copies=row["copies"],
            copy_order=row["copy_order"],
            labels_per_page=row["labels_per_page"],
            progress=progress,
            created_at=datetime.fromtimestamp(row["created_at"] / 1000, UTC),
            started_at=timestamp("started_at"),
            finished_at=timestamp("finished_at"),
            expires_at=timestamp("expires_at"),
            download_url=f"/labels/jobs/{row['job_id']}/download"
            if row["status"] == "done"
            else None,
            error=JobError(
                code=row["error_code"], message=row["error_message"] or "Job failed"
            )
            if row["error_code"]
            else None,
        )

    async def get_job(self, identifier: str) -> JobStatusResponse | None:
        row = await self.store.get(identifier)
        return self._response(row) if row else None

    async def list_jobs(self, limit: int = 10) -> list[JobStatusResponse]:
        return [self._response(row) for row in await self.store.recent(limit)]

    async def open_download(self, identifier: str) -> BinaryIO:
        async with self._artifacts:
            row = await self.store.get(identifier)
            if row is None:
                raise ArtifactError(404, "Job not found or expired")
            if row["status"] != "done":
                raise ArtifactError(409, "Job is not complete")
            path = self.cfg.OUTPUT_DIR / row["final_name"]
            if not path.resolve().is_relative_to(self.cfg.OUTPUT_DIR.resolve()):
                raise ArtifactError(410, "Artifact unavailable")
            try:
                opening = asyncio.create_task(io(path.open, "rb"))
                try:
                    handle = await asyncio.shield(opening)
                except asyncio.CancelledError:
                    handle = await settle(opening)
                    await io(handle.close)
                    raise
            except FileNotFoundError:
                raise ArtifactError(410, "Artifact missing")
            self._downloads[identifier] = self._downloads.get(identifier, 0) + 1
            return cast(BinaryIO, handle)

    async def release_download(self, identifier: str, handle: BinaryIO) -> None:
        await io(handle.close)
        async with self._artifacts:
            self._downloads[identifier] -= 1
            if self._downloads[identifier] == 0:
                del self._downloads[identifier]

    async def cleanup(self) -> None:
        async with self._artifacts:
            rows = await self.store.rows(
                "SELECT job_id,expires_at FROM jobs WHERE expires_at<=? AND (expires_at,job_id)>(?,?) "
                "ORDER BY expires_at,job_id LIMIT ?",
                (now_ms(), *self._cleanup_cursor, self.cfg.CLEANUP_BATCH_SIZE),
            )
            if not rows and self._cleanup_cursor != (0, ""):
                self._cleanup_cursor = (0, "")
                rows = await self.store.rows(
                    "SELECT job_id,expires_at FROM jobs WHERE expires_at<=? ORDER BY expires_at,job_id LIMIT ?",
                    (now_ms(), self.cfg.CLEANUP_BATCH_SIZE),
                )
            for row in rows:
                identifier = row["job_id"]
                self._cleanup_cursor = (row["expires_at"], identifier)
                if self._downloads.get(identifier) or identifier in self.active:
                    continue
                if str(UUID(identifier)) != identifier:
                    raise RuntimeError("Invalid persisted job identifier")
                try:
                    for suffix in (".pdf", ".part"):
                        await io(
                            (self.cfg.OUTPUT_DIR / (identifier + suffix)).unlink,
                            missing_ok=True,
                        )
                    workspace = self.cfg.TEMP_DIR / identifier
                    if workspace.is_dir():
                        await io(remove_workspace, self.cfg.TEMP_DIR, identifier)
                except OSError:
                    self.cleanup_failures += 1
                    continue
                await self.store.execute(
                    "DELETE FROM jobs WHERE job_id=? AND expires_at<=?",
                    (identifier, now_ms()),
                )

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.CLEANUP_INTERVAL)
            try:
                await self.cleanup()
            except Exception:
                self.cleanup_failures += 1
                self.healthy = False
                logger.exception("Job cleanup/store unavailable")

    async def stop(self) -> None:
        async with self._admission:
            self.accepting = False
        try:
            await asyncio.wait_for(self._idle.wait(), self.cfg.SHUTDOWN_TIMEOUT)
        except TimeoutError:
            while self.pending:
                identifier, _ = self.pending.popleft()
                await self.store.fail(
                    identifier, "shutdown_cancelled", "Service stopped before execution"
                )
            tasks = list(self.active.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if self._cleanup:
                self._cleanup.cancel()
                await asyncio.gather(self._cleanup, return_exceptions=True)
            try:
                await self.merger.close()
            finally:
                await self.store.close()
