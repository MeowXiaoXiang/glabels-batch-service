# app/services/job_manager.py
# Job Manager: Task scheduling and worker pool
# - Handles job queue, worker assignment, and job cleanup
# - info logs: submission, completion, failure
# - debug logs: worker start, job execution, cleanup

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.config import settings
from app.schema import LabelRequest
from app.services.label_print import LabelPrintService
from app.utils.cpu_detect import get_available_cpus


class JobManager:
    def __init__(self) -> None:
        # All job states (in-memory)
        self.jobs: dict[str, dict[str, Any]] = {}
        # Async queue for job scheduling
        self.queue: asyncio.Queue[tuple[str, LabelRequest, str]] = asyncio.Queue()
        # Worker task list
        self.workers: list[asyncio.Task[None]] = []
        # Scheduled cleanup task
        self.cleanup_task: Optional[asyncio.Task[None]] = None

        # Counter: total submitted jobs (lifetime, reset on restart)
        self.jobs_total: int = 0

        # Determine max concurrency
        # get_available_cpus() reads cgroup limits inside containers,
        # falling back to os.cpu_count() on bare-metal / non-Linux.
        if settings.MAX_PARALLEL in (0, None):
            self.max_parallel = max(1, get_available_cpus() - 1)
        else:
            self.max_parallel = int(settings.MAX_PARALLEL)

        # Label print service instance
        self.service = LabelPrintService(
            max_parallel=self.max_parallel,
            default_timeout=settings.GLABELS_TIMEOUT,
            keep_csv=settings.KEEP_CSV,
        )

        # Job retention period (expired jobs will be removed)
        self.retention = timedelta(hours=settings.RETENTION_HOURS)

    # --------------------------------------------------------
    # Create job record
    # --------------------------------------------------------
    def _make_job(
        self, req: LabelRequest, job_id: str, filename: str
    ) -> dict[str, Any]:
        """
        Create initial job record (pending status).
        """
        now = datetime.now(timezone.utc)
        return {
            "status": "pending",
            "filename": filename,  # output filename (PDF)
            "template": req.template_name,  # gLabels template
            "error": None,
            "created_at": now,
            "started_at": None,  # when worker starts processing
            "finished_at": None,  # when job completes or fails
            "request": req.model_dump(),
        }

    # --------------------------------------------------------
    # Worker loop
    # --------------------------------------------------------
    async def _worker(self, wid: int) -> None:
        """
        Worker loop:
        - Dequeue job
        - Call LabelPrintService.generate_pdf
        - Update job state
        """
        logger.info(f"[JobManager] Worker-{wid} started (max={self.max_parallel})")
        try:
            while True:
                job_id, req, filename = await self.queue.get()
                job = self.jobs[job_id]
                job["status"] = "running"
                job["started_at"] = datetime.now(timezone.utc)

                logger.debug(
                    f"[Worker-{wid}] START job_id={job_id}, template={req.template_name}"
                )

                try:
                    await self.service.generate_pdf(
                        job_id=job_id,
                        template_name=req.template_name,
                        data=req.data,
                        copies=req.copies,
                        filename=filename,  # target output filename
                    )
                    job["status"] = "done"
                    logger.info(
                        f"[Worker-{wid}] job_id={job_id} completed -> {filename}"
                    )
                except Exception as e:
                    job["status"] = "failed"
                    job["error"] = str(e)
                    logger.exception(f"[Worker-{wid}] job_id={job_id} failed")
                finally:
                    job["finished_at"] = datetime.now(timezone.utc)
                    self.queue.task_done()
                    self._cleanup_jobs()
        except asyncio.CancelledError:
            logger.info(f"[Worker-{wid}] stopped by cancel()")
            raise

    # --------------------------------------------------------
    # Cleanup expired jobs and PDFs
    # --------------------------------------------------------
    def _cleanup_jobs(self) -> None:
        """
        Cleanup expired job records and scan output/ to delete old PDFs.
        Uses file modification time to handle orphaned files as well.
        """
        cutoff = datetime.now(timezone.utc) - self.retention

        # 1. Cleanup expired job records from memory (only finished jobs)
        old_jobs = [
            jid
            for jid, job in self.jobs.items()
            if job.get("finished_at") is not None and job["finished_at"] < cutoff
        ]
        for jid in old_jobs:
            logger.debug(f"[JobManager] cleanup expired job_id={jid}")
            self.jobs.pop(jid, None)

        # 2. Scan output/ to delete all expired PDFs (including orphaned files)
        output_dir = Path("output")
        if not output_dir.exists():
            return

        cutoff_timestamp = cutoff.timestamp()
        for pdf in output_dir.glob("*.pdf"):
            try:
                if pdf.stat().st_mtime < cutoff_timestamp:
                    pdf.unlink()
                    logger.debug(f"[JobManager] deleted old PDF: {pdf.name}")
            except OSError as e:
                logger.warning(f"[JobManager] cannot delete PDF {pdf.name}: {e}")

    # --------------------------------------------------------
    # Scheduled cleanup (runs every hour)
    # --------------------------------------------------------
    async def _cleanup_scheduler(self) -> None:
        """
        Background task that runs cleanup periodically.
        Ensures expired jobs and PDFs are removed even when idle.
        """
        try:
            while True:
                await asyncio.sleep(3600)  # 1 hour
                self._cleanup_jobs()
                logger.debug("[JobManager] ⏰ Scheduled cleanup completed")
        except asyncio.CancelledError:
            logger.debug("[JobManager] ⏰ Cleanup scheduler stopped")
            raise

    # --------------------------------------------------------
    # Worker pool management
    # --------------------------------------------------------
    def start_workers(self) -> None:
        """
        Start all workers and scheduled cleanup task.
        """
        # Run cleanup once at startup
        self._cleanup_jobs()

        # Start worker pool
        for wid in range(self.max_parallel):
            task = asyncio.create_task(self._worker(wid))
            self.workers.append(task)

        # Start scheduled cleanup (hourly)
        self.cleanup_task = asyncio.create_task(self._cleanup_scheduler())

        logger.info(f"[JobManager] started with {self.max_parallel} workers")

    async def stop_workers(self) -> None:
        """
        Stop all workers and cleanup scheduler.
        """
        # Drain queue before shutdown (best effort)
        try:
            await asyncio.wait_for(
                self.queue.join(), timeout=settings.SHUTDOWN_TIMEOUT
            )
            logger.info("[JobManager] queue drained before shutdown")
        except asyncio.TimeoutError:
            logger.warning(
                "[JobManager] shutdown timeout reached, canceling workers"
            )

        # Stop cleanup scheduler
        if self.cleanup_task:
            self.cleanup_task.cancel()
            await asyncio.gather(self.cleanup_task, return_exceptions=True)
            self.cleanup_task = None

        # Stop all workers
        for task in self.workers:
            task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        logger.info("[JobManager] stopped")

    # --------------------------------------------------------
    # Public API methods
    # --------------------------------------------------------
    async def submit_job(self, req: LabelRequest) -> str:
        """
        Submit a new print job:
        - Generate job_id
        - Create output filename
        - Create job record
        - Enqueue for worker processing
        """
        job_id = str(uuid.uuid4())
        filename = self.service.make_output_filename(req.template_name)
        self.jobs[job_id] = self._make_job(req, job_id, filename)

        # Increment total submitted jobs counter
        self.jobs_total += 1

        await self.queue.put((job_id, req, filename))
        logger.info(
            f"[JobManager] submitted job_id={job_id}, template={req.template_name}"
        )
        return job_id

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve a single job by job_id.
        """
        return self.jobs.get(job_id)

    def list_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        List the most recent N jobs.
        """
        items = list(self.jobs.items())
        items.sort(key=lambda kv: kv[1]["created_at"], reverse=True)
        return [dict(job_id=jid, **data) for jid, data in items[:limit]]
