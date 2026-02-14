# app/schema.py
# Pydantic Schema Models
# - LabelRequest: Print job request schema
# - JobSubmitResponse: Job submission response schema
# - JobStatusResponse: Job status query response schema
# - TemplateSummary: Template summary for listing (lightweight)
# - TemplateInfo: Template detailed information

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings


class LabelRequest(BaseModel):
    """
    Request model for submitting a print job.
    """

    template_name: str = Field(
        ..., description="gLabels template filename (must end with .glabels)"
    )
    data: list[dict[str, Any]] = Field(
        ...,
        description="List of label data objects; each object represents one label, keys must match template fields",
    )
    copies: int = Field(
        1, ge=1, description="Number of copies per record (maps to glabels --copies)"
    )

    # Pydantic v2: provide general example
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_name": "demo.glabels",
                "data": [
                    {"ITEM": "A001", "CODE": "X123"},
                    {"ITEM": "A002", "CODE": "X124"},
                ],
                "copies": 2,
            }
        }
    )

    @field_validator("template_name")
    @classmethod
    def validate_template_name(cls, v: str) -> str:
        if not v.lower().endswith(".glabels"):
            raise ValueError("template_name must have .glabels extension")
        if not v.endswith(".glabels"):  # normalize extension case
            v = v[:-8] + ".glabels"
        return v

    @field_validator("data")
    @classmethod
    def validate_data_limits(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not v:
            raise ValueError("data must not be empty")
        if len(v) > settings.MAX_LABELS_PER_JOB:
            raise ValueError(
                f"data length exceeds MAX_LABELS_PER_JOB={settings.MAX_LABELS_PER_JOB}"
            )
        for row in v:
            if len(row) > settings.MAX_FIELDS_PER_LABEL:
                raise ValueError(
                    f"label field count exceeds MAX_FIELDS_PER_LABEL={settings.MAX_FIELDS_PER_LABEL}"
                )
            for value in row.values():
                if isinstance(value, str) and len(value) > settings.MAX_FIELD_LENGTH:
                    raise ValueError(
                        f"field length exceeds MAX_FIELD_LENGTH={settings.MAX_FIELD_LENGTH}"
                    )
        return v


class JobSubmitResponse(BaseModel):
    """
    Response model for job submission.
    """

    job_id: str
    message: str = "Job submitted successfully"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "message": "Job submitted successfully",
            }
        }
    )


class JobStatusResponse(BaseModel):
    """
    Response model for job status query and listing.
    """

    job_id: str
    status: str = Field(
        ..., description="Job status: pending | running | done | failed"
    )
    template: str = Field(..., description="The gLabels template filename used")
    filename: str = Field(
        ..., description="Expected output PDF filename (present even if job failed)"
    )
    error: str | None = Field(
        None, description="Error message if job failed; null if succeeded"
    )
    created_at: datetime = Field(..., description="Job submission timestamp")
    started_at: datetime | None = Field(
        None, description="When worker started processing (null if pending)"
    )
    finished_at: datetime | None = Field(
        None, description="When job completed or failed (null if not finished)"
    )

    # Provide a general example; detailed cases are defined in routes
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "done",
                "template": "demo.glabels",
                "filename": "demo_20250919_123456.pdf",
                "error": None,
                "created_at": "2025-09-19T10:00:00",
                "started_at": "2025-09-19T10:00:01",
                "finished_at": "2025-09-19T10:00:05",
            }
        }
    )


class TemplateSummary(BaseModel):
    """
    Lightweight template summary for list endpoints.
    Used in GET /templates for compact listing with pagination support.
    """

    name: str = Field(..., description="Template filename (e.g., 'demo.glabels')")
    field_count: int = Field(..., description="Number of fields in the template")
    has_headers: bool = Field(
        ..., description="Whether the template expects CSV with header row"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "demo.glabels",
                "field_count": 2,
                "has_headers": True,
            }
        }
    )


class TemplateInfo(BaseModel):
    """
    Detailed template information for GET /templates/{template_name} endpoint.
    Returns comprehensive metadata including all fields and format information.
    """

    name: str = Field(..., description="Template filename (e.g., 'demo.glabels')")
    format_type: str = Field(..., description="Template format type (e.g., 'CSV')")
    has_headers: bool = Field(
        ..., description="Whether the template expects CSV with header row"
    )
    fields: list[str] = Field(
        ...,
        description="List of field names or positions (e.g., ['CODE', 'ITEM'] or ['1', '2'])",
    )
    field_count: int = Field(..., description="Number of fields in the template")
    merge_type: str | None = Field(
        None, description="Internal gLabels merge type (e.g., 'Text/Comma/Line1Keys')"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "demo.glabels",
                "format_type": "CSV",
                "has_headers": True,
                "fields": ["CODE", "ITEM"],
                "field_count": 2,
                "merge_type": "Text/Comma/Line1Keys",
            }
        }
    )
