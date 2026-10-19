"""One public job per final PDF; internal render batches are not API jobs."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.limiter import RATE_LIMIT, limiter
from app.schema import (
    JobStatusResponse,
    JobSubmitResponse,
    LabelRequest,
    TemplateSummary,
)
from app.services.job_manager import ArtifactError, CapacityError, JobManager
from app.utils.tasks import io, settle

router = APIRouter(prefix="/labels", tags=["Labels"])


def manager(request: Request) -> JobManager:
    result: JobManager = request.app.state.job_manager
    return result


@router.post("/print", response_model=JobSubmitResponse, status_code=202)
@limiter.limit(RATE_LIMIT)
async def submit_labels(request: Request, req: LabelRequest) -> JobSubmitResponse:
    try:
        identifier = await manager(request).submit_job(req)
    except CapacityError as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": "5"})
    except FileNotFoundError:
        raise HTTPException(404, "Template not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return JobSubmitResponse(job_id=UUID(identifier))


@router.get("/jobs", response_model=list[JobStatusResponse])
async def list_jobs(
    request: Request, limit: int = Query(10, ge=1, le=100)
) -> list[JobStatusResponse]:
    return await manager(request).list_jobs(limit)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: UUID, request: Request) -> JobStatusResponse:
    job = await manager(request).get_job(str(job_id))
    if job is None:
        raise HTTPException(404, "Job not found or expired")
    return job


@router.get("/jobs/{job_id}/stream")
async def stream_job_status(job_id: UUID, request: Request) -> StreamingResponse:
    jobs = manager(request)
    await get_job_status(job_id, request)

    async def events() -> AsyncIterator[str]:
        previous = ""
        while jobs.accepting and not await request.is_disconnected():
            job = await jobs.get_job(str(job_id))
            if job is None:
                yield 'event: error\ndata: {"code":"not_found"}\n\n'
                return
            payload = job.model_dump_json()
            if payload != previous:
                yield f"event: status\ndata: {payload}\n\n"
                previous = payload
            else:
                yield ": keepalive\n\n"
            if job.status in ("done", "failed"):
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/download")
async def download_job_pdf(
    job_id: UUID, request: Request, preview: bool = False
) -> StreamingResponse:
    jobs, identifier = manager(request), str(job_id)
    try:
        handle = await jobs.open_download(identifier)
    except ArtifactError as exc:
        raise HTTPException(exc.status, str(exc))

    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await io(handle.read, 65536):
            yield chunk

    class DownloadResponse(StreamingResponse):
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            try:
                await super().__call__(scope, receive, send)
            finally:
                await settle(
                    asyncio.create_task(jobs.release_download(identifier, handle))
                )

    disposition = "inline" if preview else "attachment"
    return DownloadResponse(
        chunks(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{identifier}.pdf"'},
    )


@router.get("/templates", response_model=list[TemplateSummary])
async def list_templates(request: Request) -> list[TemplateSummary]:
    return await io(manager(request).catalog.list_templates)


@router.get("/templates/{template_name}", response_model=TemplateSummary)
async def get_template(template_name: str, request: Request) -> TemplateSummary:
    try:
        await io(manager(request).catalog.get_template_path, template_name)
    except ValueError, FileNotFoundError:
        raise HTTPException(404, "Template not found")
    return TemplateSummary(name=template_name)
