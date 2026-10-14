"""A step that runs long says what it is doing. Every ``LAWGRAPH_WATCHDOG_MINUTES`` one
thread per process logs the steps that are running and how long, and every statement of the
process that has run for over a minute (its state, what it waits on, its text): a query that
never ends is then in the log with its plan's statement, not only in ``pg_stat_activity``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import count
from time import monotonic as _clock  # its own: a test that fakes time.monotonic

from lawgraph.config.settings import WATCHDOG_MINUTES
from lawgraph.core.logging import get_logger, log_step
from lawgraph.core.time import format_duration
from lawgraph.db.store import own_activity

logger = get_logger(__name__)

# A statement is named once it has run this long.
LONG_STATEMENT_SECONDS = 60.0

_running: dict[int, tuple[str, float]] = {}
_ids = count()
_lock = threading.Lock()
_thread: threading.Thread | None = None


@contextmanager
def watched(label: str) -> Iterator[None]:
    """Count the block as the step *label* while it runs."""
    step = next(_ids)
    with _lock:
        _running[step] = (label, _clock())
        _start()
    try:
        yield
    finally:
        with _lock:
            _running.pop(step, None)


def report(now: float | None = None) -> None:
    """Log the running steps and the long statements of this process, when a step runs."""
    now = _clock() if now is None else now
    with _lock:
        steps = sorted(_running.values(), key=lambda step: step[1])
    if not steps:
        return
    logger.info(
        "Still running: %s.",
        ", ".join(
            f"{label} for {format_duration(now - began)}" for label, began in steps
        ),
    )
    for row in own_activity(LONG_STATEMENT_SECONDS):
        logger.info(
            "Statement %s for %s (%s%s): %s",
            row["pid"],
            format_duration(row["seconds"]),
            row["state"],
            f", waits on {row['wait']}" if row["wait"] else "",
            row["query"],
        )


def report_safely(*, first_failure: bool) -> bool:
    """``report()``, which never ends a run: a failure is logged with its traceback, as a
    warning when it is the *first_failure*. Whether it reported."""
    try:
        report()
    except Exception:  # noqa: BLE001 — the watchdog never ends a run
        level = logging.WARNING if first_failure else logging.DEBUG
        logger.log(level, "The watchdog could not report.", exc_info=True)
        return False
    return True


def _start() -> None:
    """The one thread of the process (``_lock`` held)."""
    global _thread
    if _thread is not None:
        return

    def watch_forever() -> None:
        with log_step("watchdog"):
            failed_before = False
            while True:
                time.sleep(WATCHDOG_MINUTES * 60)
                if not report_safely(first_failure=not failed_before):
                    failed_before = True

    _thread = threading.Thread(
        target=watch_forever, name="lawgraph-watchdog", daemon=True
    )
    _thread.start()
