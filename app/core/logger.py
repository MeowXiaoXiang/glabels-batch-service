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

    def _patcher(record: dict[str, Any]) -> None:
        record["extra"].setdefault("request_id", "-")

    text_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
        "| <level>{level: <8}</level> "
        "| <cyan>{file}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "| <magenta>{extra[request_id]}</magenta> "
        "- <level>{message}</level>"
    )

    # Ensure log directory exists (configurable via settings.LOG_DIR)
    log_dir = Path(settings.LOG_DIR or "logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        # If directory creation fails, fallback to console log only
        logger.add(
            sys.stdout,
            level="DEBUG",
            colorize=not use_json,
            format=None if use_json else text_format,
            serialize=use_json,
            patcher=_patcher,
        )
        logger.error(f"Failed to create log directory: {e}")
        return logger

    # Console: colored output (text) or JSON (serialize)
    logger.add(
        sys.stdout,
        level=log_level,
        colorize=not use_json,
        format=None if use_json else text_format,
        serialize=use_json,
        patcher=_patcher,
    )

    # System log: INFO and above
    try:
        logger.add(
            log_dir / "system.log",
            level="INFO",
            rotation="5 MB",
            retention=10,
            encoding="utf-8",
            format=None if use_json else "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} "
            "| {file}:{function}:{line} | {extra[request_id]} - {message}",
            serialize=use_json,
            patcher=_patcher,
        )
    except Exception as e:
        logger.error(f"Failed to create system.log: {e}")

    # Error log: ERROR and above
    try:
        logger.add(
            log_dir / "error.log",
            level="ERROR",
            rotation="5 MB",
            retention=10,
            encoding="utf-8",
            format=None if use_json else "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} "
            "| {file}:{function}:{line} | {extra[request_id]} - {message}",
            serialize=use_json,
            patcher=_patcher,
        )
    except Exception as e:
        logger.error(f"Failed to create error.log: {e}")

    logger.info(f"Logger initialized with level={log_level}")
    return logger
