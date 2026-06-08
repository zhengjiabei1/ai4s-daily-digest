"""Logging setup with file rotation using loguru."""

import sys
from pathlib import Path

from loguru import logger


LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)


def setup_logging(log_dir: str = "logs", level: str = "INFO") -> None:
    """Configure loguru logger with file rotation and console output.

    Args:
        log_dir: Directory for log files.
        level: Minimum log level.
    """
    # Remove default handler
    logger.remove()

    # Console output
    logger.add(
        sys.stderr,
        format=LOG_FORMAT,
        level=level,
        colorize=True,
    )

    # File output with daily rotation, 30-day retention
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path / "digest_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",
        rotation="00:00",  # Rotate at midnight
        retention="30 days",
        encoding="utf-8",
        enqueue=True,  # Thread-safe
    )

    logger.info("Logging initialized")
