"""The pool's warning for every read given back in its transaction is a debug line."""

from __future__ import annotations

import logging

from lawgraph.core.logging import _routine_rollback_as_debug


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        "psycopg.pool", logging.WARNING, __file__, 1, message, (), None
    )


def test_a_routine_rollback_is_a_debug_line() -> None:
    record = _record("rolling back returned connection: <psycopg.Connection [INTRANS]>")
    kept = _routine_rollback_as_debug(record)
    assert record.levelno == logging.DEBUG
    assert kept == logging.getLogger().isEnabledFor(logging.DEBUG)


def test_another_warning_of_the_pool_stays_one() -> None:
    record = _record("discarding closed connection: <psycopg.Connection [BAD]>")
    assert _routine_rollback_as_debug(record)
    assert record.levelno == logging.WARNING
