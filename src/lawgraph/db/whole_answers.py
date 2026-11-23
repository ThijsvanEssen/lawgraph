"""Whole answers of the API (``api/response_cache``), on the data versions of
``version_cache``: one per key, of the version it was computed for, kept by its size in
bytes, the one used longest ago going first once together they pass ``RESPONSE_BYTES``. It
is the answer of its version, and of a newer one while the new one computes, until it is
``MAX_STALE`` (6 h) old: so never longer than that after the newer version came. One
computation per key at a time (``Computing``): by the request that asks first, in its own
deadline (``look``), or in the background (``fill``), ``FILLS`` of those at most. Nothing
is computed here: the caller computes and ``settle``s.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import threading
import time
from collections import OrderedDict
from collections.abc import Hashable
from typing import Any

from lawgraph.config import settings
from lawgraph.db import version_cache

RESPONSE_BYTES = int(settings.RESPONSE_CACHE_MB * 2**20)
# One answer larger than this part of ``RESPONSE_BYTES`` is not kept.
RESPONSE_SHARE = 64
FILLS = 2
# A computation running this long is taken for lost (its event loop ended): the next asks
# again.
LOST_AFTER = 2 * settings.API_REQUEST_TIMEOUT_MS / 1000
# How long after it was computed an answer may still be given for a newer data version
# (seconds): Thijs, 23 Nov: "Max 6 uur".
MAX_STALE = 6 * 3600.0
_now = time.monotonic  # the clock (the tests move one by hand)


@dataclasses.dataclass(frozen=True)
class Kept:
    """A whole answer (*value*, of *size* bytes) of data version *version*, computed
    *at* (``_now``)."""

    version: str
    value: Any
    size: int
    at: float = dataclasses.field(default_factory=lambda: _now())


@dataclasses.dataclass
class Computing:
    """The computation of a whole answer: *future* gets it; *background* when no request
    waits for it (``fill``), with *interim* the answer of the request that started it."""

    future: concurrent.futures.Future[Any]
    background: bool
    started: float
    interim: Any = None

    def lost(self) -> bool:
        return time.monotonic() - self.started > LOST_AFTER


@dataclasses.dataclass(frozen=True)
class Look:
    """What a request finds for its key (``look``): *kept* an answer it may give (*fresh*
    of the version now), *refresh* whether to compute the new one behind it, *computing*
    the computation of it under way, and *lead* when that was started for this request,
    which computes it and ``settle``s it."""

    kept: Kept | None
    fresh: bool = False
    refresh: bool = False
    computing: Computing | None = None
    lead: bool = False


_lock = threading.Lock()
_kept: OrderedDict[tuple[str, Hashable], Kept] = OrderedDict()
_bytes = 0
_computing: dict[tuple[str, Hashable], Computing] = {}


def look(database: str, version: str, key: Hashable) -> Look:
    """The whole answer for *key* of data version *version* of *database*: kept, of an
    earlier version computed at most ``MAX_STALE`` ago (computed again behind it, unless the
    pipelines are writing: ``version_cache.in_run``), or computed by the request that asks
    first."""
    entry = (database, key)
    with _lock:
        kept = _kept.get(entry)
        if kept is not None and kept.version == version:
            _kept.move_to_end(entry)
            return Look(kept, fresh=True)
        running = _computing.get(entry)
        if running is not None and running.lost():
            running = None
        if kept is not None and _now() - kept.at > MAX_STALE:
            kept = None
        if kept is None and running is None:
            running = _computing[entry] = _new(background=False)
            return Look(None, computing=running, lead=True)
    refresh = (
        kept is not None and running is None and not version_cache.in_run(database)
    )
    return Look(kept, refresh=refresh, computing=running)


def fill(database: str, key: Hashable, interim: Any = None) -> Computing | None:
    """A computation in the background of the whole answer for *key*, for the caller to
    run and ``settle``: none while one runs for it, or ``FILLS`` run already."""
    entry = (database, key)
    with _lock:
        running = [c for c in _computing.values() if c.background and not c.lost()]
        current = _computing.get(entry)
        if len(running) >= FILLS or (current is not None and not current.lost()):
            return None
        computing = _computing[entry] = _new(background=True, interim=interim)
        return computing


def _new(background: bool, interim: Any = None) -> Computing:
    return Computing(concurrent.futures.Future(), background, time.monotonic(), interim)


def settle(
    database: str,
    key: Hashable,
    computing: Computing,
    result: Any,
    kept: Kept | None = None,
) -> None:
    """End *computing* with *result* (what its waiters get; an exception for a failure),
    and keep *kept* for *key* when ``RESPONSE_BYTES`` holds its size."""
    global _bytes
    entry = (database, key)
    with _lock:
        if _computing.get(entry) is computing:
            del _computing[entry]
        if kept is not None and 0 < kept.size <= RESPONSE_BYTES // RESPONSE_SHARE:
            old = _kept.pop(entry, None)
            _bytes += kept.size - (old.size if old else 0)
            _kept[entry] = kept
            while _bytes > RESPONSE_BYTES:
                _, dropped = _kept.popitem(last=False)
                _bytes -= dropped.size
    if isinstance(result, BaseException):
        computing.future.set_exception(result)
    else:
        computing.future.set_result(result)


def clear() -> None:
    """Forget every kept answer (the tests)."""
    global _bytes
    with _lock:
        _kept.clear()
        _computing.clear()
        _bytes = 0
