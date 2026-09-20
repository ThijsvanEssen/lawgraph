from __future__ import annotations

import contextvars
import json
import logging
import shutil
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TextIO

from lawgraph.config.settings import LOG_FILE, LOG_JSON, LOG_LEVEL, LOG_NO_COLOR

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


class LiveStatusHandler(logging.Handler):
    """A terminal handler that keeps the progress of every running step at the bottom.

    One line per step, rewritten in place (``update``); every other log line scrolls above
    them as it always did. Only for a terminal: a pipe or a file gets the plain lines,
    progress once a minute among them. The periodic progress records (``record.status``)
    are left out here, because the block shows them, fresher.
    """

    _STATUS_COLOR = "\033[36m"

    def __init__(self, stream: TextIO | None = None, *, color: bool = True) -> None:
        super().__init__()
        self.stream = stream or sys.stderr
        self._color = color
        self._status: dict[str, str] = {}
        self._drawn = 0
        self._screen = threading.Lock()

    def update(self, step: str, line: str | None) -> None:
        """Show *line* as the progress of *step*; ``None`` takes the step off the screen."""
        with self._screen:
            if line is None:
                self._status.pop(step, None)
            else:
                self._status[step] = f"[{step}] {line}" if step else line
            self._erase()
            self._draw()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "status", False):
            return
        try:
            text = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with self._screen:
            self._erase()
            self.stream.write(text + "\n")
            self._draw()

    def clear(self) -> None:
        """Take the block off the screen (before a traceback, and at the end)."""
        with self._screen:
            self._erase()
            self.stream.flush()

    def close(self) -> None:
        self.clear()
        super().close()

    def _erase(self) -> None:
        if self._drawn:
            # up over the block, to the start of the line, clear to the end of the screen
            self.stream.write(f"\033[{self._drawn}A\r\033[J")
            self._drawn = 0

    def _draw(self) -> None:
        size = shutil.get_terminal_size()
        lines = list(self._status.values())[-max(1, size.lines - 2) :]
        for line in lines:
            # A line that wraps takes two rows and breaks "up n lines": cut it to the width.
            if len(line) >= size.columns:
                line = line[: max(1, size.columns - 2)] + "…"
            if self._color:
                line = f"{self._STATUS_COLOR}{line}{COLOR_RESET}"
            self.stream.write(line + "\n")
        self._drawn = len(lines)
        self.stream.flush()


_live: LiveStatusHandler | None = None


def live_status(step: str, line: str | None) -> bool:
    """Show the progress of *step* in the terminal; ``False`` when there is no live terminal."""
    if _live is None:
        return False
    _live.update(step, line)
    return True


def _terminal_is_live() -> bool:
    return not LOG_JSON and getattr(sys.stderr, "isatty", lambda: False)()


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

    global _live
    handler: logging.Handler
    if _terminal_is_live():
        handler = _live = LiveStatusHandler(color=_use_color())
        _clear_before_a_traceback(_live)
    else:
        handler = logging.StreamHandler()
    handler.addFilter(_StepFilter())
    handler.setFormatter(formatter)
    root.addHandler(handler)
    if LOG_FILE:
        log_file = logging.FileHandler(LOG_FILE, encoding="utf-8")
        log_file.addFilter(_StepFilter())
        log_file.setFormatter(
            _JsonFormatter() if LOG_JSON else logging.Formatter(LOG_FORMAT)
        )
        root.addHandler(log_file)
    setattr(root, _LAWGRAPH_HANDLER_ATTR, True)

    # urllib3 warns three times per attempt to reach a database that is down; the store
    # says it once per retry (db/store.py) and the step ends with the error.
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.WARNING)


def _clear_before_a_traceback(live: LiveStatusHandler) -> None:
    """An uncaught exception writes to stderr past the handler: take the block away first."""
    previous = sys.excepthook

    def hook(*args: Any) -> None:
        live.clear()
        previous(*args)

    sys.excepthook = hook


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call setup_logging() from your entry point first."""
    return logging.getLogger(name)
