# app/core/logger.py
# Logger initialization: integrates console / system / error log
# - Supports LOG_LEVEL from .env
# - Automatically creates logs/ directory to avoid FileNotFoundError
# - Fallback: if log files cannot be created, at least ensure console output

import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings


def setup_logger(level: str | None = None, log_format: str | None = None) -> Any:
    """
    Initialize global logger.
    :param level: log level (DEBUG / INFO / WARNING / ERROR)
    """
    logger.remove()

    log_level = (level or settings.LOG_LEVEL).upper()
    log_format_value = (log_format or settings.LOG_FORMAT).lower()
    use_json = log_format_value == "json"

    text_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
        "| <level>{level: <8}</level> "
        "| <cyan>{file}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "| <magenta>{extra[request_id]}</magenta> "
        "- <level>{message}</level>"
    )

    logger.configure(extra={"request_id": "-"})

    def _add_console(level: str) -> None:
        if use_json:
            logger.add(sys.stdout, level=level, colorize=False, serialize=True)
        else:
            logger.add(
                sys.stdout,
                level=level,
                colorize=True,
                format=text_format,
                serialize=False,
            )

    def _add_file(path: Path, level: str) -> None:
        if use_json:
            logger.add(
                path,
                level=level,
                rotation="5 MB",
                retention=10,
                encoding="utf-8",
                serialize=True,
            )
        else:
            logger.add(
                path,
                level=level,
                rotation="5 MB",
                retention=10,
                encoding="utf-8",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} "
                "| {file}:{function}:{line} | {extra[request_id]} - {message}",
                serialize=False,
            )

    # Ensure log directory exists (configurable via settings.LOG_DIR)
    log_dir = Path(settings.LOG_DIR or "logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        # If directory creation fails, fallback to console log only
        _add_console("DEBUG")
        logger.error(f"Failed to create log directory: {e}")
        return logger

    # Console: colored output (text) or JSON (serialize)
    _add_console(log_level)

    # System log: INFO and above
    try:
        _add_file(log_dir / "system.log", "INFO")
    except Exception as e:
        logger.error(f"Failed to create system.log: {e}")

    # Error log: ERROR and above
    try:
        _add_file(log_dir / "error.log", "ERROR")
    except Exception as e:
        logger.error(f"Failed to create error.log: {e}")

    logger.info(f"Logger initialized with level={log_level}")
    return logger
