from __future__ import annotations

import contextvars
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from lawgraph.config.settings import LOG_JSON, LOG_LEVEL, LOG_NO_COLOR

# ``step`` is the command a line belongs to ("retrieve staatscourant"), so lines of steps that
# run side by side can be told apart; ``short_name`` is the logger without ``lawgraph.``.
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(step_tag)s%(short_name)s: %(message)s"

_step: contextvars.ContextVar[str] = contextvars.ContextVar("lawgraph_step", default="")


@contextmanager
def log_step(label: str) -> Iterator[None]:
    """Mark every log line written inside the block (and by this thread) as part of *label*."""
    token = _step.set(label)
    try:
        yield
    finally:
        _step.reset(token)


def current_step() -> str:
    return _step.get()


class _StepFilter(logging.Filter):
    """Adds the current step and the short logger name to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        step = _step.get()
        record.step = step
        record.step_tag = f"[{step}] " if step else ""
        record.short_name = record.name.removeprefix("lawgraph.")
        return True


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
            "step": getattr(record, "step", ""),
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
    handler.addFilter(_StepFilter())
    handler.setFormatter(formatter)
    root.addHandler(handler)
    setattr(root, _LAWGRAPH_HANDLER_ATTR, True)

    # urllib3 warns three times per attempt to reach a database that is down; the store
    # says it once per retry (db/store.py) and the step ends with the error.
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call setup_logging() from your entry point first."""
    return logging.getLogger(name)
