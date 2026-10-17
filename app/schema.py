"""Public job contract; template contents belong exclusively to gLabels."""

import math
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings

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
    model_config = ConfigDict(strict=True, extra="forbid")
    template_name: str
    data: list[dict[str, Scalar]] = Field(min_length=1)
    copies: int = Field(1, ge=1)
    copy_order: CopyOrder = "sets"
    labels_per_page: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def limits(self) -> Self:
        safe_template_name(self.template_name)
        if (
            len(self.data) > settings.MAX_LABELS_PER_JOB
            or self.copies > settings.MAX_COPIES
        ):
            raise ValueError("Record or copies limit exceeded")
        if len(self.data) * self.copies > settings.MAX_EFFECTIVE_LABELS:
            raise ValueError("Effective label limit exceeded")
        keys = set().union(*(row.keys() for row in self.data))
        if not keys or len(keys) > settings.MAX_FIELDS_PER_LABEL:
            raise ValueError("CSV column limit exceeded or no columns")
        if any(not key or len(key) > 128 or "\x00" in key for key in keys):
            raise ValueError("Invalid CSV column name")
        for row in self.data:
            for value in row.values():
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Nonfinite numbers are not supported")
                if isinstance(value, str) and (
                    len(value) > settings.MAX_FIELD_LENGTH or "\x00" in value
                ):
                    raise ValueError(
                        "Field value limit exceeded or invalid NUL character"
                    )
        return self


class JobSubmitResponse(BaseModel):
    job_id: UUID
    status: Literal["pending"] = "pending"


class JobError(BaseModel):
    code: str
    message: str


class JobProgress(BaseModel):
    rendered_batches: int
    total_batches: int


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    template_name: str
    record_count: int
    copies: int
    copy_order: Literal["sets", "per_record", "renderer_native"]
    labels_per_page: int | None
    progress: JobProgress | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    download_url: str | None = None
    error: JobError | None = None


class TemplateSummary(BaseModel):
    name: str
