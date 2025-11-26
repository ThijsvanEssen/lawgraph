# src/lawgraph/logging.py
# Structural changes:
# - Clarified colorized formatter and setup logging constraints for consistent use.

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

COLOR_RESET = "\033[0m"
LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",    # cyan
    logging.INFO: "\033[32m",     # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",    # red
    logging.CRITICAL: "\033[41m",  # red background
}


def _use_color() -> bool:
    """
    Determine whether to enable colored logging.

    - Disabled if NO_COLOR is set in the environment.
    - Disabled if stderr is not a TTY.
    """
    if os.getenv("NO_COLOR") is not None:
        return False
    # On some environments, sys.stderr may not have isatty; be defensive.
    is_tty = getattr(sys.stderr, "isatty", lambda: False)()
    return is_tty


class ColorFormatter(logging.Formatter):
    """
    Simple formatter that wraps the entire log line in a color based on level.

    Falls back to plain formatting if no color is defined for the level.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        color = LEVEL_COLORS.get(record.levelno)
        if not color:
            return base
        return f"{color}{base}{COLOR_RESET}"


def _get_level_from_env() -> int:
    load_dotenv()
    level_str = os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
    return {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }.get(level_str, logging.INFO)


def setup_logging(level: Optional[int] = None) -> None:
    """
    Configureer de root logger één keer.
    Als er al handlers zijn, doen we niets (zodat tests/embedded gebruik niet stukgaat).
    """
    root = logging.getLogger()
    if root.handlers:
        # Al geconfigureerd
        return

    if level is None:
        level = _get_level_from_env()

    root.setLevel(level)

    if _use_color():
        formatter: logging.Formatter = ColorFormatter(LOG_FORMAT)
    else:
        formatter = logging.Formatter(LOG_FORMAT)

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Optioneel: externe libs iets stiller zetten
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Haal een logger voor een module. Zorgt dat logging-config bestaat.
    """
    setup_logging()
    return logging.getLogger(name)
