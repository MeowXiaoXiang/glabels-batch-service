"""Bounded render batches, ordered isolated merge and parent publication."""

import asyncio
import os
import shutil
from pathlib import Path

from app.config import Settings
from app.schema import JobProgress, LabelRequest
from app.services.job_store import JobStore
from app.services.label_print import batch_rows, fieldnames, write_csv
from app.services.pdf_merger import PdfMerger
from app.services.resource_scheduler import ResourceScheduler
from app.services.template_service import TemplateService
from app.utils.files import remove_workspace
from app.utils.glabels_engine import GlabelsEngine
from app.utils.tasks import io


def batch_shape(req: LabelRequest, settings: Settings) -> tuple[int, int]:
    total = len(req.data) * req.copies
    if (
        len(req.data) > settings.MAX_LABELS_PER_JOB
        or req.copies > settings.MAX_COPIES
        or total > settings.MAX_EFFECTIVE_LABELS
    ):
        raise ValueError("Record, copies or effective label limit exceeded")
    limit = settings.MAX_LABELS_PER_BATCH
    size = total
    if limit and total > limit:
        if req.labels_per_page is None:
            raise ValueError("labels_per_page is required when a job needs batching")
        size = limit // req.labels_per_page * req.labels_per_page
        if size == 0:
            raise ValueError("One declared page exceeds the per-batch label limit")
    count = (total + size - 1) // size
    if count > settings.MAX_BATCHES_PER_JOB:
        raise ValueError("Batch count limit exceeded")
    if (
        req.labels_per_page is not None
        and (total + req.labels_per_page - 1) // req.labels_per_page
        > settings.MAX_PDF_PAGES
    ):
        raise ValueError("Declared PDF page count exceeds the page limit")
    return size, count


class JobPipeline:
    def __init__(
        self,
        cfg: Settings,
        store: JobStore,
        scheduler: ResourceScheduler,
        renderer: GlabelsEngine,
        merger: PdfMerger,
        catalog: TemplateService,
        progress: dict[str, JobProgress],
    ) -> None:
        self.cfg, self.store, self.scheduler = cfg, store, scheduler
        self.renderer, self.merger, self.catalog = renderer, merger, catalog
        self.progress = progress
        self.workspace_bytes: dict[str, int] = {}

    def check_space(self, workspace: Path) -> int:
        size = 0
        for path in workspace.rglob("*"):
            try:
                if path.is_file():
                    size += path.stat().st_size
            except FileNotFoundError:
                continue  # A completed batch may concurrently remove its CSV.
        if size > self.cfg.MAX_WORKSPACE_BYTES:
            raise ValueError("Workspace byte limit exceeded")
        for root in (self.cfg.TEMP_DIR, self.cfg.OUTPUT_DIR):
            if shutil.disk_usage(root).free < self.cfg.MIN_FREE_DISK_BYTES:
                raise OSError("Insufficient free disk space")
        return size

    async def run(self, job_id: str, req: LabelRequest) -> None:
        workspace = self.cfg.TEMP_DIR / job_id
        staging = self.cfg.OUTPUT_DIR / f"{job_id}.part"
        await io(workspace.mkdir, parents=True, exist_ok=False)

        async def monitor() -> None:
            while True:
                self.workspace_bytes[job_id] = await io(self.check_space, workspace)
                await asyncio.sleep(0.25)

        try:
            async with asyncio.TaskGroup() as group:
                watchdog = group.create_task(monitor())
                await self._body(job_id, req, workspace, staging)
                watchdog.cancel()
        finally:
            if self.scheduler.healthy and self.renderer.healthy and self.merger.healthy:
                await io(remove_workspace, self.cfg.TEMP_DIR, job_id)
                await io(staging.unlink, missing_ok=True)
                self.workspace_bytes.pop(job_id, None)

    async def _body(
        self, job_id: str, req: LabelRequest, workspace: Path, staging: Path
    ) -> None:
        template = await io(self.catalog.get_template_path, req.template_name)
        size, count = batch_shape(req, self.cfg)
        columns = fieldnames(req.data)
        progress = self.progress[job_id] = JobProgress(
            rendered_batches=0, total_batches=count
        )
        await self.store.stage(job_id, "rendering")
        batches = iter(range(count))
        paths = [workspace / f"batch-{index:06d}.pdf" for index in range(count)]
        started = False

        async def render_batches() -> None:
            nonlocal started
            for index in batches:
                async with await self.scheduler.acquire("render", job_id):
                    if not started:
                        started = True
                        await self.store.started(job_id)
                    csv_path = workspace / f"batch-{index:06d}.csv"
                    await io(
                        write_csv,
                        batch_rows(req, index * size, (index + 1) * size),
                        csv_path,
                        columns,
                    )
                    await self.renderer.run_batch(
                        output_pdf=paths[index],
                        template_path=template,
                        csv_path=csv_path,
                        copies=1,
                    )
                    await io(self.check_space, workspace)
                    await io(csv_path.unlink)
                    progress.rendered_batches += 1

        async with asyncio.TaskGroup() as renders:
            for _ in range(min(count, self.scheduler.budget)):
                renders.create_task(render_batches())
        if count > 1:
            await self.store.stage(job_id, "merging")
        assembled = workspace / "assembled.pdf"
        expected_pages = (
            [
                (
                    min(size, len(req.data) * req.copies - index * size)
                    + req.labels_per_page
                    - 1
                )
                // req.labels_per_page
                for index in range(count)
            ]
            if req.labels_per_page is not None
            else None
        )
        async with await self.scheduler.acquire("merge", job_id):
            await self.merger.merge(paths, assembled, expected_pages=expected_pages)
        await io(self.check_space, workspace)
        await io(shutil.copyfile, assembled, staging)
        await self.store.intent(job_id)
        await io(os.replace, staging, self.cfg.OUTPUT_DIR / f"{job_id}.pdf")
        await self.store.done(job_id)
