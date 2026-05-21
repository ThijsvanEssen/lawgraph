from __future__ import annotations

import json
import logging
import os
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

COLOR_RESET = "\033[0m"
LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[41m",  # red background
}


def _use_color() -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    is_tty = getattr(sys.stderr, "isatty", lambda: False)()
    return is_tty


class ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        color = LEVEL_COLORS.get(record.levelno)
        if not color:
            return base
        return f"{color}{base}{COLOR_RESET}"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _get_level_from_env() -> int:
    level_str = os.getenv("LAWGRAPH_LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_str, logging.INFO)


def setup_logging(level: int | None = None) -> None:
    """Configure the root logger once. No-ops when handlers are already attached."""
    root = logging.getLogger()
    if root.handlers:
        return

    if level is None:
        level = _get_level_from_env()

    root.setLevel(level)

    use_json = os.getenv("LAWGRAPH_LOG_FORMAT", "").lower() == "json"
    if use_json:
        formatter: logging.Formatter = _JsonFormatter()
    elif _use_color():
        formatter = ColorFormatter(LOG_FORMAT)
    else:
        formatter = logging.Formatter(LOG_FORMAT)

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call setup_logging() from your entry point first."""
    return logging.getLogger(name)
