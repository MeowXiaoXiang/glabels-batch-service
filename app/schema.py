"""Public job contract; template contents belong exclusively to gLabels."""

import math
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

JobStatus = Literal["pending", "rendering", "merging", "done", "failed"]
Scalar = str | int | float | bool | None
CopyOrder = Literal["sets", "per_record"]


def safe_template_name(name: str) -> str:
    if (
        not name.lower().endswith(".glabels")
        or any(c in name for c in ("/", "\\", ":", "\x00"))
        or name in (".", "..")
        or len(name) > 255
    ):
        raise ValueError("Template must be a .glabels basename without path separators")
    return name


class LabelRequest(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "template_name": "demo.glabels",
                    "data": [{"ITEM": "A001", "CODE": "X123"}],
                    "copies": 2,
                    "copy_order": "sets",
                    "labels_per_page": 3,
                }
            ]
        },
    )
    template_name: str = Field(
        description="Configured .glabels filename, without a directory path."
    )
    data: list[dict[str, Scalar]] = Field(
        min_length=1,
        description="Label records containing scalar values; keys become CSV column names.",
    )
    copies: int = Field(
        1,
        ge=1,
        description="Copies of each record, expanded by the service before rendering.",
    )
    copy_order: CopyOrder = Field(
        "sets",
        description="sets repeats the full record sequence; per_record repeats each record before the next. Neither forces a new page.",
    )
    labels_per_page: int | None = Field(
        None,
        ge=1,
        description="Actual template capacity per page. Required for jobs split into batches; does not change the template layout.",
    )

    @model_validator(mode="after")
    def limits(self) -> Self:
        safe_template_name(self.template_name)
        keys = set().union(*(row.keys() for row in self.data))
        if not keys:
            raise ValueError("At least one CSV column is required")
        if any(not key or len(key) > 128 or "\x00" in key for key in keys):
            raise ValueError("Invalid CSV column name")
        for row in self.data:
            for value in row.values():
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Nonfinite numbers are not supported")
                if isinstance(value, str) and "\x00" in value:
                    raise ValueError("NUL characters are not supported")
        return self


class JobSubmitResponse(BaseModel):
    job_id: UUID
    status: Literal["pending"] = "pending"


class JobError(BaseModel):
    code: str
    message: str


class JobProgress(BaseModel):
    rendered_batches: int = Field(
        description="Completed render batches; this does not indicate final PDF availability."
    )
    total_batches: int = Field(
        description="Number of internal render batches for this job."
    )


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    template_name: str
    record_count: int
    copies: int
    copy_order: CopyOrder
    labels_per_page: int | None
    progress: JobProgress | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = Field(
        None,
        description="Fixed retention deadline after publication or failure. Restart and download do not extend it.",
    )
    download_url: str | None = Field(
        None,
        description="Download endpoint for a done job. Availability ends at expires_at; a missing artifact returns 410.",
    )
    error: JobError | None = None


class TemplateSummary(BaseModel):
    name: str
