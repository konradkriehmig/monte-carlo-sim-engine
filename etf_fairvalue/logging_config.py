"""
Shared logging configuration for the etf_fairvalue package.

Call ``setup_logging()`` once at the start of each entry-point (fetch, worker,
aggregate) to configure console + optional file logging for the whole package.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def setup_logging(
    level: int | str = logging.INFO,
    log_file: Path | str | None = None,
) -> None:
    """Configure package-level logging.

    Args:
        level: Logging level as an int or case-insensitive string
               (``"debug"``, ``"info"``, ``"warning"``, ``"error"``).
        log_file: Optional file path.  The parent directory is created
                  automatically.  Messages are appended.
    """
    if isinstance(level, str):
        level = _LEVELS.get(level.lower(), logging.INFO)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    pkg_logger = logging.getLogger("etf_fairvalue")
    pkg_logger.setLevel(level)

    # Guard against duplicate handlers when setup_logging() is called more than once.
    if pkg_logger.handlers:
        return

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    pkg_logger.addHandler(console_handler)

    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        pkg_logger.addHandler(file_handler)
