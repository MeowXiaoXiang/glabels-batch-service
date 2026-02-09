# app/config.py
# Global configuration file: loads environment variables and .env
# Using pydantic-settings to automatically map env vars to Python attributes

from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # -------------------------
    # Environment configuration
    # -------------------------
    ENVIRONMENT: str = "production"
    # Environment mode: development / production
    # Controls safety validations and default behaviors

    # -------------------------
    # Server configuration
    # -------------------------
    HOST: str = "0.0.0.0"  # nosec: B104
    # IP address to bind (0.0.0.0 = all interfaces)

    PORT: int = 8000
    # Port number to listen on

    RELOAD: bool = False
    # Enable auto-reload (useful in development, disable in production)

    # -------------------------
    # Global control options
    # -------------------------
    KEEP_CSV: bool = False
    # True  = keep temp CSV files (for debugging)
    # False = delete temp CSV after job completion (recommended in production)

    MAX_PARALLEL: int = 0
    #  >0   = explicit number of concurrent jobs (e.g. 4)
    #  0    = auto (defaults to CPU count - 1)

    GLABELS_TIMEOUT: int = 600
    # Max timeout per job in seconds (default 600 = 10 minutes)

    MAX_LABELS_PER_BATCH: int = 300
    # Maximum labels per batch before auto-splitting and PDF merging
    # Set to 0 to disable (not recommended for large datasets)
    # Recommended: 200-300 for ARM/embedded, 500-800 for x86 servers
    MAX_LABELS_PER_JOB: int = 2000
    # Maximum labels allowed per request job
    # Prevents oversized requests from exhausting memory

    RETENTION_HOURS: int = 24
    # Hours to keep job states in memory before cleanup (avoids memory bloat)

    LOG_LEVEL: str = "INFO"
    # Logging level: DEBUG / INFO / WARNING / ERROR
    # Default INFO, recommended INFO or higher in production

    LOG_DIR: str = "logs"
    # Directory for log files. Can be relative or absolute. Default: logs

    MAX_REQUEST_BYTES: int = 5_000_000
    # Maximum allowed HTTP request body size in bytes (approx 5 MB)

    MAX_FIELDS_PER_LABEL: int = 50
    # Maximum number of fields allowed per label record

    MAX_FIELD_LENGTH: int = 2048
    # Maximum length allowed for any single field value

    # -------------------------
    # CORS settings
    # -------------------------
    CORS_ALLOW_ORIGINS: str = ""
    # Comma-separated list of allowed origins. Leave empty to disable CORS.

    # -------------------------
    # Internal settings
    # -------------------------
    # Load .env file from project root (if exists)
    model_config = SettingsConfigDict(
        env_file=".env" if Path(".env").exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context: Any) -> None:
        """Production safety validation."""
        if self.ENVIRONMENT == "production" and self.RELOAD:
            raise ValueError(
                "RELOAD must be false in production! "
                "Set RELOAD=false or ENVIRONMENT=development"
            )


# Singleton instance
settings = Settings()
