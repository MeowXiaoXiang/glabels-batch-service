# app/api/print_jobs.py
# Labels API Router
# - Submit print jobs
# - Query job status (polling + SSE streaming)
# - Download generated PDFs
# - List recent jobs
# - Template discovery and information

import asyncio
from pathlib import Path
from typing import List

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from app.config import settings
from app.schema import (JobStatusResponse, JobSubmitResponse, LabelRequest,
                        TemplateInfo)

# Create router - all APIs will be mounted under /labels
router = APIRouter(prefix="/labels", tags=["Labels"])


# Submit Print Job
@router.post(
    "/print",
    response_model=JobSubmitResponse,
    summary="Submit a label print job",
    responses={
        200: {
            "description": "Job submitted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "123e4567-e89b-12d3-a456-426614174000",
                        "message": "Job submitted successfully",
                    }
                }
            },
        },
        422: {
            "description": "Request validation failed",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_template": {
                            "summary": "Invalid template filename",
                            "value": {
                                "detail": [
                                    {
                                        "type": "value_error",
                                        "loc": ["body", "template_name"],
                                        "msg": "template_name must have .glabels extension",
                                        "input": "invalid.txt",
                                    }
                                ]
                            },
                        },
                        "invalid_copies": {
                            "summary": "Invalid copies count",
                            "value": {
                                "detail": [
                                    {
                                        "type": "greater_than_equal",
                                        "loc": ["body", "copies"],
                                        "msg": "Input should be greater than or equal to 1",
                                        "input": 0,
                                    }
                                ]
                            },
                        },
                    }
                }
            },
        },
    },
)
async def submit_labels(
    request: Request,
    req: LabelRequest = Body(
        ...,
        examples={
            "basic": {
                "summary": "Basic example",
                "description": "Use demo.glabels template with 2 records, each printed 2 times.",
                "value": {
                    "template_name": "demo.glabels",
                    "data": [
                        {"ITEM": "A001", "CODE": "X123"},
                        {"ITEM": "A002", "CODE": "X124"},
                    ],
                    "copies": 2,
                },
            }
        },
    ),
):
    """
    Submit a new label print job. The server will enqueue the task and process it asynchronously.

    ## Job Status Flow

    | Status | Description | Action |
    |--------|-------------|--------|
    | `pending` | Job submitted, waiting to be processed | Wait for processing |
    | `running` | PDF generation is in progress | Monitor status |
    | `done` | Job completed successfully | Download PDF |
    | `failed` | Job failed during processing | Check error details |

    ## Usage

    1. **Submit** your job with template and data
    2. **Monitor** job status using `/jobs/{job_id}`
    3. **Download** PDF when status becomes `done`

    ## Data Format Requirements

    - **Template Name**: Must end with `.glabels` extension
    - **Data Array**: Each object represents one label
    - **Field Keys**: Must match template field names exactly
    - **Copies**: Number of copies per record (minimum 1)

    > **Note**: Use `/templates` endpoint to discover available templates and their required fields.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")

    job_manager = request.app.state.job_manager
    job_id = await job_manager.submit_job(req)
    return JobSubmitResponse(job_id=job_id)


# Query Job Status
@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    responses={
        200: {
            "description": "Job status information",
            "content": {
                "application/json": {
                    "examples": {
                        "done": {
                            "summary": "Completed job",
                            "value": {
                                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                                "status": "done",
                                "template": "demo.glabels",
                                "filename": "demo_20250919_123456.pdf",
                                "error": None,
                                "created_at": "2025-09-19T10:00:00",
                                "started_at": "2025-09-19T10:00:01",
                                "finished_at": "2025-09-19T10:00:05",
                            },
                        },
                        "failed": {
                            "summary": "Failed job",
                            "value": {
                                "job_id": "223e4567-e89b-12d3-a456-426614174111",
                                "status": "failed",
                                "template": "demo.glabels",
                                "filename": "demo_20250919_123457.pdf",
                                "error": "PDF generation failed (rc=1)",
                                "created_at": "2025-09-19T10:01:00",
                                "started_at": "2025-09-19T10:01:01",
                                "finished_at": "2025-09-19T10:01:03",
                            },
                        },
                        "running": {
                            "summary": "Running job",
                            "value": {
                                "job_id": "323e4567-e89b-12d3-a456-426614174222",
                                "status": "running",
                                "template": "demo.glabels",
                                "filename": "demo_20250919_123458.pdf",
                                "error": None,
                                "created_at": "2025-09-19T10:02:00",
                                "started_at": "2025-09-19T10:02:01",
                                "finished_at": None,
                            },
                        },
                        "pending": {
                            "summary": "Pending job",
                            "value": {
                                "job_id": "423e4567-e89b-12d3-a456-426614174333",
                                "status": "pending",
                                "template": "demo.glabels",
                                "filename": "demo_20250919_123459.pdf",
                                "error": None,
                                "created_at": "2025-09-19T10:03:00",
                                "started_at": None,
                                "finished_at": None,
                            },
                        },
                    }
                }
            },
        },
        404: {"description": "Job not found"},
    },
)
async def get_job_status(job_id: str, request: Request):
    """
    Query the status and related information of a print job by job_id.

    ## Status Types

    | Status | State | Description |
    |--------|-------|-------------|
    | `pending` | Queued | Waiting to be processed (in queue) |
    | `running` | Active | Processing (generating PDF) |
    | `done` | Complete | PDF available for download |
    | `failed` | Error | Check error field for details |

    ## Response Fields

    - **job_id**: Unique job identifier
    - **status**: Current job status (see table above)
    - **template**: gLabels template filename used
    - **filename**: Expected output PDF filename
    - **error**: Error message (null if successful)
    - **created_at**: Job submission timestamp
    - **started_at**: When worker started processing (null if pending)
    - **finished_at**: When job completed or failed (null if not finished)

    > **Tip**: Use the `/jobs/{job_id}/download` endpoint when status is `done`
    """
    job_manager = request.app.state.job_manager
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(job_id=job_id, **job)


# Stream Job Status (SSE)
@router.get(
    "/jobs/{job_id}/stream",
    summary="Stream job status updates (SSE)",
    responses={
        200: {
            "description": "Server-Sent Events stream",
            "content": {"text/event-stream": {}},
        },
        404: {"description": "Job not found"},
    },
)
async def stream_job_status(job_id: str, request: Request):
    """
    Stream real-time job status updates using Server-Sent Events (SSE).

    ## Connection

    Opens a persistent HTTP connection that pushes status updates as they occur.
    The stream automatically closes when the job reaches a terminal state (`done` or `failed`).

    ## Event Format

    ```
    event: status
    data: {"job_id": "...", "status": "running", ...}

    event: status
    data: {"job_id": "...", "status": "done", ...}
    ```

    ## Event Types

    | Event | Description |
    |-------|-------------|
    | `status` | Job status update (JSON payload) |
    | `error` | Error occurred (e.g., job not found) |

    ## Client Example (JavaScript)

    ```javascript
    const eventSource = new EventSource('/labels/jobs/{job_id}/stream');

    eventSource.addEventListener('status', (e) => {
        const job = JSON.parse(e.data);
        console.log('Status:', job.status);
        if (job.status === 'done' || job.status === 'failed') {
            eventSource.close();
        }
    });

    eventSource.addEventListener('error', (e) => {
        console.error('SSE Error:', e.data);
        eventSource.close();
    });
    ```

    ## Polling Interval

    Status is checked every **1 second** and pushed only when status changes
    or until a terminal state is reached.

    > **Tip**: Use this instead of polling `/jobs/{job_id}` for real-time updates
    """
    job_manager = request.app.state.job_manager

    # Check job exists before starting stream
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        last_status = None
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.debug(f"[SSE] Client disconnected for job {job_id}")
                break

            job = job_manager.get_job(job_id)
            if not job:
                yield f"event: error\ndata: Job not found or expired\n\n"
                break

            current_status = job["status"]

            # Send update if status changed or first message
            if current_status != last_status:
                response = JobStatusResponse(job_id=job_id, **job)
                yield f"event: status\ndata: {response.model_dump_json()}\n\n"
                last_status = current_status

            # Stop streaming on terminal states
            if current_status in ("done", "failed"):
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# Download Generated PDF
@router.get(
    "/jobs/{job_id}/download",
    summary="Download generated PDF",
    responses={
        200: {"description": "PDF file returned successfully"},
        404: {"description": "Job not found"},
        409: {"description": "Job not finished or file unavailable (status not done)"},
        410: {"description": "File has been deleted"},
    },
)
async def download_job_pdf(job_id: str, request: Request, preview: bool = False):
    """
    Download the generated PDF file when job status is `done`.

    ## Prerequisites

    | Requirement | Status Check |
    |-------------|--------------|
    | Job exists | Job ID must be valid |
    | Status is `done` | PDF generation completed |
    | File available | PDF not deleted by cleanup |

    ## Download Process

    1. **Verify** job exists and is completed
    2. **Locate** PDF file in output directory
    3. **Stream** file as `application/pdf`

    ## Error Scenarios

    - **404**: Job ID not found
    - **409**: Job not finished (status ≠ `done`)
    - **410**: PDF file has been deleted

    > **Note**: PDF files may be automatically deleted by the cleanup policy after some time.
    """
    job_manager = request.app.state.job_manager
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(
            status_code=409, detail="Job not finished or file unavailable"
        )

    output_dir = Path("output")
    file_path = output_dir / job["filename"]

    if not file_path.exists():
        raise HTTPException(status_code=410, detail="File has been deleted")

    headers = None
    if preview:
        headers = {"Content-Disposition": f'inline; filename="{file_path.name}"'}

    return FileResponse(
        file_path,
        filename=file_path.name,
        media_type="application/pdf",
        headers=headers,
    )


# List Recent Jobs
@router.get(
    "/jobs",
    response_model=List[JobStatusResponse],
    summary="List recent jobs",
    responses={
        200: {
            "description": "List of jobs",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "job_id": "123e4567-e89b-12d3-a456-426614174000",
                            "status": "done",
                            "template": "demo.glabels",
                            "filename": "demo_20250919_123456.pdf",
                            "error": None,
                            "created_at": "2025-09-19T10:00:00",
                            "started_at": "2025-09-19T10:00:01",
                            "finished_at": "2025-09-19T10:00:05",
                        },
                        {
                            "job_id": "223e4567-e89b-12d3-a456-426614174111",
                            "status": "failed",
                            "template": "demo.glabels",
                            "filename": "demo_20250919_123457.pdf",
                            "error": "PDF generation failed (rc=1)",
                            "created_at": "2025-09-19T10:01:00",
                            "started_at": "2025-09-19T10:01:01",
                            "finished_at": "2025-09-19T10:01:03",
                        },
                    ]
                }
            },
        }
    },
)
async def list_jobs(request: Request, limit: int = 10):
    """
    List the most recent N jobs, ordered by creation time (newest first).

    ## Query Parameters

    | Parameter | Type | Default | Description |
    |-----------|------|---------|-------------|
    | `limit` | integer | 10 | Maximum number of jobs to return |

    ## Response Data

    Returns an array of job objects, each containing:

    - **job_id**: Unique identifier
    - **status**: Current job state (`pending`/`running`/`done`/`failed`)
    - **template**: Template filename used
    - **filename**: Output PDF filename
    - **error**: Error message (if failed)
    - **created_at**: Job submission timestamp
    - **started_at**: When processing started
    - **finished_at**: When job finished

    ## Job Status Reference

    | Status | Icon | Meaning |
    |--------|------|---------|
    | `pending` | Waiting in queue |
    | `running` | Processing |
    | `done` | Ready for download |
    | `failed` | Processing error |

    > **Tip**: Use `limit=50` to see more job history
    """
    job_manager = request.app.state.job_manager
    jobs = job_manager.list_jobs(limit=limit)
    return [JobStatusResponse(**j) for j in jobs]


# List Available Templates
@router.get(
    "/templates",
    response_model=List[TemplateInfo],
    summary="List available templates",
    responses={
        200: {
            "description": "List of available templates",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "name": "demo.glabels",
                            "format_type": "CSV",
                            "has_headers": True,
                            "fields": ["CODE", "ITEM"],
                            "field_count": 2,
                            "merge_type": "Text/Comma/Line1Keys",
                        },
                        {
                            "name": "non_head_demo.glabels",
                            "format_type": "CSV",
                            "has_headers": False,
                            "fields": ["1", "2"],
                            "field_count": 2,
                            "merge_type": "Text/Comma",
                        },
                    ]
                }
            },
        },
        500: {"description": "Server error while reading templates"},
    },
)
async def list_templates():
    """
    Discover all available gLabels template files with detailed field information.

    ## Template Information

    Each template includes comprehensive metadata:

    | Field | Type | Description |
    |-------|------|-------------|
    | `name` | string | Template filename (e.g., `demo.glabels`) |
    | `format_type` | string | Always `"CSV"` for current implementation |
    | `has_headers` | boolean | Whether CSV should include header row |
    | `fields` | array | Field names or positions |
    | `field_count` | integer | Total number of fields |
    | `merge_type` | string | Internal gLabels format identifier |

    ## Format Types

    | Headers | `has_headers` | `fields` Example | Usage |
    |---------|---------------|------------------|--------|
    | With Headers | `true` | `["CODE", "ITEM"]` | CSV with header row |
    | No Headers | `false` | `["1", "2"]` | CSV with position-based fields |

    > **Note**: All templates currently return `format_type: "CSV"` regardless of header configuration

    ## Field Matching

    - **Header format**: Your JSON data keys must match field names exactly
    - **No-header format**: Your JSON data will be mapped by position

    ### Example Data Format

    ```json
    // For template with fields: ["CODE", "ITEM"]
    {
        "template_name": "demo.glabels",
        "data": [
            {"CODE": "X123", "ITEM": "A001"},
            {"CODE": "X124", "ITEM": "A002"}
        ]
    }
    ```

    > **Pro Tip**: Always check template field requirements before submitting print jobs!
    """
    from app.services.template_service import TemplateService

    template_service = TemplateService()
    try:
        templates = template_service.list_templates()
        return templates
    except Exception as e:
        logger.error(f"[API] Failed to list templates: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to read templates: {str(e)}"
        )


# Get Specific Template Information
@router.get(
    "/templates/{template_name}",
    response_model=TemplateInfo,
    summary="Get template information",
    responses={
        200: {
            "description": "Template information",
            "content": {
                "application/json": {
                    "example": {
                        "name": "demo.glabels",
                        "format_type": "CSV",
                        "has_headers": True,
                        "fields": ["CODE", "ITEM"],
                        "field_count": 2,
                        "merge_type": "Text/Comma/Line1Keys",
                    }
                }
            },
        },
        404: {"description": "Template not found"},
        500: {"description": "Server error while reading template"},
    },
)
async def get_template_info(template_name: str):
    """
    Get detailed information for a specific gLabels template file.

    ## Path Parameters

    | Parameter | Type | Required | Description |
    |-----------|------|----------|-------------|
    | `template_name` | string | Yes | Template filename (e.g., `"demo.glabels"`) |

    ## Response Details

    Returns complete template metadata including:

    ### Basic Information
    - **name**: Template filename
    - **format_type**: Output format (`"CSV"`)
    - **field_count**: Total number of fields

    ### Field Configuration
    - **has_headers**: Whether CSV expects header row
    - **fields**: Array of field names or positions
    - **merge_type**: Internal gLabels format identifier

    ## Field Types Explained

    | Type | `has_headers` | Fields Format | Your Data Format |
    |------|---------------|---------------|------------------|
    | Named Fields | `true` | `["CODE", "ITEM"]` | `{"CODE": "X123", "ITEM": "A001"}` |
    | Position Fields | `false` | `["1", "2"]` | Data mapped by array position |

    ## Common Use Cases

    1. **Before submitting jobs** - Verify required field names
    2. **Data validation** - Ensure your JSON matches template structure
    3. **Integration** - Programmatically discover template capabilities

    > **Example**: For `demo.glabels`, expect fields `["CODE", "ITEM"]` with headers enabled
    """
    from app.services.template_service import TemplateService

    template_service = TemplateService()
    try:
        template_info = template_service.get_template_info(template_name)
        return template_info
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Template file not found: {template_name}"
        )
    except Exception as e:
        logger.error(f"[API] Failed to get template info {template_name}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to read template: {str(e)}"
        )
