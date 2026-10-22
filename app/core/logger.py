"""Console and rotating file logging, with console fallback on file errors."""

import sys
from pathlib import Path

from loguru import logger


def setup_logger(level: str, log_format: str, directory: str) -> None:
    log_level = logger.level(level.upper()).no
    use_json = log_format.lower() == "json"
    logger.remove()

    text_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
        "| <level>{level: <8}</level> "
        "| <cyan>{file}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "| <magenta>{extra[request_id]}</magenta> "
        "- <level>{message}</level>"
    )

    logger.configure(extra={"request_id": "-"})

    def _add_console(level: int) -> None:
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

    def _add_file(path: Path, level: int) -> None:
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

    log_dir = Path(directory)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        _add_console(log_level)
        logger.error(f"Failed to create log directory: {e}")
        return

    _add_console(log_level)

    try:
        _add_file(log_dir / "system.log", max(log_level, logger.level("INFO").no))
    except Exception as e:
        logger.error(f"Failed to create system.log: {e}")

    try:
        _add_file(log_dir / "error.log", max(log_level, logger.level("ERROR").no))
    except Exception as e:
        logger.error(f"Failed to create error.log: {e}")

    logger.info(f"Logger initialized with level={log_level}")
    return
