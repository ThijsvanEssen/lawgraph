from __future__ import annotations

import json
import logging
import sys

from lawgraph.config.settings import LOG_JSON, LOG_LEVEL, LOG_NO_COLOR

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
    return not LOG_NO_COLOR and getattr(sys.stderr, "isatty", lambda: False)()


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


_LAWGRAPH_HANDLER_ATTR = "_lawgraph_handler_installed"


def setup_logging(level: int | None = None) -> None:
    """Configure the root logger once. No-ops when a LawGraph handler is already attached."""
    root = logging.getLogger()
    if getattr(root, _LAWGRAPH_HANDLER_ATTR, False):
        return

    if level is None:
        level = getattr(logging, LOG_LEVEL, logging.INFO)

    root.setLevel(level)

    if LOG_JSON:
        formatter: logging.Formatter = _JsonFormatter()
    elif _use_color():
        formatter = ColorFormatter(LOG_FORMAT)
    else:
        formatter = logging.Formatter(LOG_FORMAT)

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    setattr(root, _LAWGRAPH_HANDLER_ATTR, True)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call setup_logging() from your entry point first."""
    return logging.getLogger(name)
