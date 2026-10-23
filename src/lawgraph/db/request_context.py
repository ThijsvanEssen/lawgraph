"""What the current request allows its reads: a deadline, a pool, a cancellation.

The API sets these per request (``set_read_deadline``, ``set_cancellation``) and per
computation in the background (``in_background``); the store reads them for every
statement it streams. Context variables, so the threads a request runs queries on inherit
them.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import threading
import time
from collections.abc import Iterator
from typing import Any

import psycopg

from lawgraph.config.settings import READ_TIMEOUT_MS
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)


# When the reads of the current request must end (``_now``); None outside a request. The API
# sets it per request (``read_deadline``); a statement then gets what is left.
_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "lawgraph_read_deadline", default=None
)
_now = time.monotonic  # the clock of the deadline (the tests move one by hand)


def set_read_deadline(seconds: float) -> contextvars.Token[float | None]:
    """From now, the reads of this context end within *seconds*; ``reset_read_deadline``
    with the token ends that."""
    return _deadline.set(_now() + seconds)


def reset_read_deadline(token: contextvars.Token[float | None]) -> None:
    _deadline.reset(token)


# Whether the reads of the current context are computed in the background (the API's warm-up
# and kept answers, ``in_background``): they take a connection of the store's background
# pool, not one of the requests.
_background: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "lawgraph_background", default=False
)


def reads_in_background() -> bool:
    """Whether the reads of the current context take the background pool."""
    return _background.get()


@contextlib.contextmanager
def in_background() -> Iterator[None]:
    """The reads of the block take connections of the background pool
    (``LAWGRAPH_DB_BACKGROUND_POOL_SIZE``): what the API computes for every visitor waits
    for those, and leaves the connections of the requests free."""
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


class Cancellation:
    """The reads of one request, to cancel when its client went away: the connections it
    reads on now, and whether it was cancelled (``cancel``). A request starts no read after
    that, and the ones it runs end at once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: set[psycopg.Connection[Any]] = set()
        self.cancelled = False

    def cancel(self) -> None:
        """Cancel every read running for the request (``cancel_safe``: it waits for the
        server to take it, so not on the event loop). Under the lock: a read that ends
        meanwhile gives its connection back after it (``end``), so no cancel reaches the
        read of another request on it."""
        with self._lock:
            self.cancelled = True
            for conn in self._connections:
                with contextlib.suppress(psycopg.Error):
                    conn.cancel_safe(timeout=5.0)

    def start(self, conn: psycopg.Connection[Any]) -> None:
        """A read of the request on *conn* begins; ``RequestCancelled`` once cancelled."""
        with self._lock:
            if self.cancelled:
                raise RequestCancelled("The client went away before this read.")
            self._connections.add(conn)

    def end(self, conn: psycopg.Connection[Any]) -> None:
        """The read on *conn* ended: from now on its connection is not the request's."""
        with self._lock:
            self._connections.discard(conn)


# The reads of the current request, to cancel when its client goes away (the API sets one
# per request); None outside a request. Copied into the threads a request runs queries on,
# not into a computation of the cache, which goes on for the next request.
_cancellation: contextvars.ContextVar[Cancellation | None] = contextvars.ContextVar(
    "lawgraph_cancellation", default=None
)


def current_cancellation() -> Cancellation | None:
    """The reads of the current request, to cancel; None outside a request."""
    return _cancellation.get()


def set_cancellation(
    cancellation: Cancellation,
) -> contextvars.Token[Cancellation | None]:
    return _cancellation.set(cancellation)


def reset_cancellation(token: contextvars.Token[Cancellation | None]) -> None:
    _cancellation.reset(token)


def read_time_left() -> float | None:
    """The seconds the reads of the current request have left (at least 0); None outside
    a request."""
    deadline = _deadline.get()
    return None if deadline is None else max(0.0, deadline - _now())


def read_budget_ms() -> int:
    """The ``statement_timeout`` of the next read: ``LAWGRAPH_READ_TIMEOUT_MS``, or the time
    left before the deadline of the request when that is less. ``ReadTimedOut`` when none
    is left."""
    deadline = _deadline.get()
    if deadline is None:
        return READ_TIMEOUT_MS
    left = int((deadline - _now()) * 1000)
    if left <= 0:
        raise ReadTimedOut("The request ran past its deadline before this read.")
    return min(READ_TIMEOUT_MS, left)


class ReadTimedOut(RuntimeError):
    """A statement that reads ran past ``LAWGRAPH_READ_TIMEOUT_MS`` and was cancelled."""


class RequestCancelled(ReadTimedOut):
    """The client of the request went away: its reads were cancelled."""


@dataclasses.dataclass
class Budget:
    """Whether the reads of a ``read_budget`` block ran past it."""

    ran_out: bool = False


@contextlib.contextmanager
def read_budget(seconds: float, what: str, *, reserve: float = 0.0) -> Iterator[Budget]:
    """The reads of the block end within *seconds*, or within what the request has left
    less *reserve* when that ends first. A block that runs past it ends there, logged:
    ``ran_out``, and the caller answers without what it read (a computation of the cache
    it waited for goes on). A request whose client went away (``RequestCancelled``) ends
    as ever."""
    left = read_time_left()
    capped = seconds if left is None else min(seconds, left - reserve)
    token = set_read_deadline(max(0.0, capped))
    budget = Budget()
    try:
        yield budget
    except RequestCancelled:
        raise
    except ReadTimedOut:
        budget.ran_out = True
        logger.info("%s took over %s s: answered without it.", what, seconds)
    finally:
        reset_read_deadline(token)
