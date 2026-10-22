"""Deployment configuration; renderer paths are never supplied by API clients."""

from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "production"
    HOST: str = "0.0.0.0"  # nosec B104
    PORT: int = Field(8000, ge=1, le=65535)
    RELOAD: bool = False
    GLABELS_EXECUTABLE: str = "glabels-3-batch"
    GLABELS_TIMEOUT: float = Field(600, gt=0)
    MERGE_TIMEOUT: float = Field(120, gt=0)
    PROCESS_REAP_TIMEOUT: float = Field(5, gt=0)
    WORK_TOKENS: int = Field(0, ge=0)
    API_CPU_RESERVE: int = Field(1, ge=0)
    MERGE_COST: int = Field(2, ge=1)
    MAX_PENDING_JOBS: int = Field(32, ge=1)
    MAX_INFLIGHT_JOBS: int = Field(4, ge=1)
    MAX_LABELS_PER_BATCH: int = Field(300, ge=0)
    MAX_LABELS_PER_JOB: int = Field(2000, ge=1)
    MAX_COPIES: int = Field(100, ge=1)
    MAX_EFFECTIVE_LABELS: int = Field(20_000, ge=1)
    MAX_BATCHES_PER_JOB: int = Field(100, ge=1)
    MAX_REQUEST_BYTES: int = Field(5_000_000, ge=1)
    MAX_FIELDS_PER_LABEL: int = Field(50, ge=1)
    MAX_FIELD_LENGTH: int = Field(2048, ge=1)
    MAX_PDF_BYTES: int = Field(256_000_000, ge=1)
    MAX_PDF_PAGES: int = Field(10_000, ge=1)
    MAX_WORKSPACE_BYTES: int = Field(512_000_000, ge=1)
    MIN_FREE_DISK_BYTES: int = Field(128_000_000, ge=0)
    RETENTION_HOURS: float = Field(24, gt=0)
    CLEANUP_INTERVAL: float = Field(60, gt=0)
    CLEANUP_BATCH_SIZE: int = Field(100, ge=1)
    SHUTDOWN_TIMEOUT: float = Field(30, gt=0)
    TEMPLATES_DIR: Path = Path("templates")
    OUTPUT_DIR: Path = Path("output")
    TEMP_DIR: Path = Path("temp")
    STATE_DIR: Path = Path("state")
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"
    LOG_DIR: str = "logs"
    REQUEST_ID_HEADER: str = "X-Request-ID"
    RATE_LIMIT: str = "60/minute"
    ENABLE_METRICS: bool = True
    CORS_ALLOW_ORIGINS: str = ""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def safety(self) -> Self:
        if self.ENVIRONMENT == "production" and self.RELOAD:
            raise ValueError("RELOAD must be false in production")
        if not self.GLABELS_EXECUTABLE.strip():
            raise ValueError("GLABELS_EXECUTABLE must name an executable or wrapper")
        roots = [
            p.resolve()
            for p in (
                self.OUTPUT_DIR,
                self.TEMP_DIR,
                self.STATE_DIR,
                self.TEMPLATES_DIR,
            )
        ]
        if any(
            a == b or a.is_relative_to(b) or b.is_relative_to(a)
            for i, a in enumerate(roots)
            for b in roots[i + 1 :]
        ):
            raise ValueError(
                "Template, output, temp and state roots must be separate directories"
            )
        return self


settings = Settings()
