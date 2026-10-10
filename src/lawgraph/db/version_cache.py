"""Answers that are the same for every visitor and change only with the data: kept until
the data version changes (``lg_data_version``, which a write to a table of the graph
raises), and computed once even when many requests ask at the same moment.

On the full graph a facet count over a million judgments, the statistics of the search or
the counts of ``/api/stats`` take seconds to a minute, and the answer is the same until the
next run of the pipelines. The computation runs in a thread of its own, without the
deadline of the request that asked first (a thread of the pool does not inherit it): a
request waits for it no longer than its own deadline, then answers 503, and the
computation goes on for the next. Once the data changed a request waits ``STALE_WAIT`` for
the new answer at most, then takes the last one (of the version before): a facet count or
the statistics of the search minutes old is good, a search that hangs on every write of the
pipelines is not. ``on_new_version`` functions (the API's warm-up) run in
the background when a store shows a version it did not have. A store without
``data_version`` (a fake) keeps nothing.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import contextvars
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterator
from typing import Any, TypeVar

from lawgraph.config.settings import API_WARM_UP_MIN_INTERVAL
from lawgraph.core.logging import get_logger
from lawgraph.db.store import (
    ReadTimedOut,
    _text,
    in_background,
    read_time_left,
    version_stamp,
)

logger = get_logger(__name__)

T = TypeVar("T")

# The data version is read at most this often (seconds): a run of the pipelines shows within
# it. The tests set it to 0.
VERSION_TTL = 2.0
# Answers kept, the least recently used going first.
MAX_ENTRIES = 4096
# How long a request waits for the answer of a new data version (seconds) before it takes
# the answer of the version before, while the new one goes on computing.
STALE_WAIT = 2.0
# What a request waits at most instead (``stale_wait``): a search while typing takes the
# answer of the version before at once, as a computation after a poll would cost it seconds.
_stale_wait: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "lawgraph_stale_wait", default=None
)


@contextlib.contextmanager
def stale_wait(seconds: float) -> Iterator[None]:
    """Within it a request that has the answer of an earlier version waits *seconds* at
    most for the new one (``STALE_WAIT`` without it), then takes the earlier one; the new
    one goes on computing. An answer never computed before is waited for as ever."""
    token = _stale_wait.set(seconds)
    try:
        yield
    finally:
        _stale_wait.reset(token)


# Computations at the same time (each holds a connection of the pool while it reads).
WORKERS = 3

_lock = threading.Lock()
# database -> (data version, the version of each table or None, read at)
_versions: dict[str, tuple[str | None, dict[str, int] | None, float]] = {}
# An answer kept for the tables it reads (``cached(tables=...)``) is computed again after this
# many seconds, whatever their versions say: a safety net for a table its declaration lacks.
MAX_AGE = 3600.0
_computed_at: dict[Hashable, float] = {}  # entry key -> when its answer was computed
_values: OrderedDict[Hashable, Any] = OrderedDict()
_running: dict[tuple[tuple[str, str], Hashable], concurrent.futures.Future[Any]] = {}
# The last answer per (database, key), of whatever version: what a request takes while the
# answer of a new version computes.
_latest: OrderedDict[Hashable, Any] = OrderedDict()
_NONE = object()
# The answers of ``lasting``, with the moment each was computed (``time.monotonic``).
_lasting: dict[Hashable, tuple[Any, float]] = {}
_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=WORKERS, thread_name_prefix="lawgraph-cache"
)
# The warm-up: one worker, and per database one wanted warm-up, always of the newest data.
# A run of the pipelines raises the data version with every statement that writes; a warm-up
# starts only once the version has stood still for ``WARM_UP_SETTLE`` seconds, a newer
# version replaces the one waiting, and one that changes during a warm-up stops it
# (``superseded``) and asks for the next. The worker runs apart from the pool above: it waits
# for its computations, and would hold every worker of it if it ran there.
WARM_UP_SETTLE = 90.0
# How often the warm-up worker, while it waits for nothing, reads the data version of the
# databases it warmed (seconds): a poll is noticed also when no request reads a kept answer.
VERSION_POLL = 30.0
# Seconds from the start of one warm-up of a database to the start of the next at the least
# (``LAWGRAPH_WARM_UP_MIN_INTERVAL``, in minutes; 0: none). A warm-up that falls due sooner
# waits, still for the newest data; the first one never does.
WARM_UP_MIN_INTERVAL = API_WARM_UP_MIN_INTERVAL * 60
_warm_started: dict[str, float] = {}  # database -> when its last warm-up began
_warmers: list[Callable[[Any], None]] = []
_wanted: dict[
    str, tuple[Any, float, str | None]
] = {}  # database -> (store, due, version)
_warm_wake = threading.Condition(_lock)
_warm_worker: threading.Thread | None = None
_warming: set[str] = set()  # the databases a warm-up runs for now
_polled: dict[
    str, Any
] = {}  # database -> the store its version is read with while idle


def on_new_version(warm: Callable[[Any], None]) -> None:
    """Run *warm(store)* in the background whenever a store shows a data version this
    process did not know: the answers every visitor asks are then ready before they ask."""
    with _lock:
        _warmers.append(warm)


def warm(store: Any, *, settle: float | None = None) -> None:
    """Warm *store* up in the background, once its data version has stood still for
    *settle* seconds (``WARM_UP_SETTLE``; 0 at the start of the API). It replaces a warm-up
    of the same database that waits; one that runs finishes or stops on its own."""
    global _warm_worker
    wait = WARM_UP_SETTLE if settle is None else settle
    name = str(getattr(store, "name", ""))
    try:
        known: str | None = store.data_version()
    except Exception:  # noqa: BLE001 — the worker reads it again when it is due
        known = None
    with _lock:
        _polled[name] = store
        _wanted[name] = (store, time.monotonic() + wait, known)
        if _warm_worker is None or not _warm_worker.is_alive():
            _warm_worker = threading.Thread(
                target=_warm_forever, name="lawgraph-warm", daemon=True
            )
            _warm_worker.start()
        _warm_wake.notify()


def superseded(store: Any, version: str | None) -> bool:
    """Whether *store* holds newer data than *version* (read now): a warm-up of *version*
    stops between its parts."""
    try:
        return bool(store.data_version() != version)
    except Exception:  # noqa: BLE001 — no answer is no reason to stop
        return False


def _warm_forever() -> None:
    while True:
        with _lock:
            idle = not _wanted
            if idle:
                _warm_wake.wait(timeout=VERSION_POLL)
                idle = not _wanted
                polled = list(_polled.values())
        if idle:
            # nothing wanted: a version this process did not know asks for a warm-up
            for known in polled:
                _version(known)
            continue
        with _lock:
            if not _wanted:
                continue
            name, (store, due, version) = min(_wanted.items(), key=lambda kv: kv[1][1])
            started = _warm_started.get(name)
            if started is not None:
                due = max(due, started + WARM_UP_MIN_INTERVAL)
            left = due - time.monotonic()
            if left > 0:
                _warm_wake.wait(timeout=left)
                continue
            del _wanted[name]
        if superseded(store, version):
            # the data moved while it settled: wait for it to stand still again
            warm(store)
            continue
        with _lock:
            warmers = list(_warmers)
            _warming.add(name)
            _warm_started[name] = time.monotonic()
        try:
            for function in warmers:
                _quietly(function, store)
        finally:
            with _lock:
                _warming.discard(name)
        if superseded(store, version):
            warm(store)


def computing(store: Any) -> bool:
    """Whether anything is computed for *store* now: a warm-up that waits or runs, or an
    answer of the cache (``/api/health``: a newer version is on its way)."""
    name = str(getattr(store, "name", ""))
    with _lock:
        return (
            name in _wanted
            or name in _warming
            or any(entry[0][0] == name for entry in _running)
        )


def _quietly(function: Callable[[Any], None], store: Any) -> None:
    try:
        with in_background():
            function(store)
    except Exception as exc:  # noqa: BLE001 — a warm-up that fails is asked again later
        logger.warning(
            "Warming %s failed: %s: %s", function.__name__, type(exc).__name__, exc
        )


def _version(
    store: Any, tables: tuple[str, ...] | None = None
) -> tuple[str, str] | None:
    """``(database, data version)`` of *store*, or of *tables* of it, read at most every
    ``VERSION_TTL``; None when it has none or the database cannot be read. A data version
    this process did not know starts the warm-up. A store without versions per table (a
    fake) gives its data version for any *tables*."""
    read = getattr(store, "data_version", None)
    if read is None:
        return None
    name = str(getattr(store, "name", ""))
    now = time.monotonic()
    with _lock:
        known, per_table, read_at = _versions.get(name, (None, None, float("-inf")))
    if now - read_at >= VERSION_TTL:
        before = known
        known, per_table = _read_versions(store)
        with _lock:
            _versions[name] = (known, per_table, now)
        if known and known != before and before is not None:
            warm(store)
    if not known:
        return None
    if tables is None or per_table is None:
        return (name, known)
    return (name, f"{','.join(tables)}@{version_stamp(per_table, tables)}")


def _read_versions(store: Any) -> tuple[str | None, dict[str, int] | None]:
    """The data version of *store* and the version of each of its tables (None for a
    store that has no ``table_versions``)."""
    try:
        per_table = getattr(store, "table_versions", None)
        if per_table is None:
            return store.data_version(), None
        versions = per_table()
        return version_stamp(versions), versions
    except Exception:  # noqa: BLE001 — without a version nothing is kept
        return None, None


def cached(
    store: Any,
    key: Hashable,
    compute: Callable[[], T],
    *,
    tables: tuple[str, ...] | None = None,
    inline: bool = False,
) -> T:
    """The answer for *key* of the current data version of *store*: kept, or computed once
    in the background while this request waits for it no longer than its deadline
    (``ReadTimedOut`` then, and the computation goes on). A request that has the answer of
    an earlier version waits ``STALE_WAIT`` at most, then takes that one.

    With *tables*, the tables the computation reads, the answer is kept while those tables
    stand still, whatever is written to others, and ``MAX_AGE`` at most;
    ``tests/pg/test_cached_tables.py`` checks every such declaration against the tables
    the plans of its statements read.

    *inline*: an answer not kept is computed in the caller's thread, under its deadline,
    and kept: for a cheap one a request needs (a search's frequencies of its words), which
    must not wait behind the slow computations of the pool (a warm-up, the counts of the
    feed)."""
    version = _version(store, tables)
    if version is None:
        return compute()
    entry_key = (version, key)
    with _lock:
        if entry_key in _values and not _too_old(entry_key, tables):
            _values.move_to_end(entry_key)
            return _values[entry_key]  # type: ignore[no-any-return]
    if inline:
        return _keep(entry_key, compute())
    with _lock:
        nested = _in_cache_worker()
        future = _running.get(entry_key)
        if future is None and not nested:
            future = _pool.submit(_compute, entry_key, compute)
            _running[entry_key] = future
        last = _latest.get((version[0], key), _NONE)
    if nested:
        _nested(key)
        return _compute(entry_key, compute)
    assert future is not None
    return _answer(future, last, key)


def _too_old(entry_key: Hashable, tables: tuple[str, ...] | None) -> bool:
    """Whether a kept answer for *tables* is past ``MAX_AGE`` (one for the whole data
    version never is); the caller holds the lock."""
    if tables is None:
        return False
    return time.monotonic() - _computed_at.get(entry_key, 0.0) > MAX_AGE


def lasting(
    store: Any,
    key: Hashable,
    compute: Callable[[], T],
    max_age: float,
    *,
    inline: bool = False,
) -> T:
    """The answer for *key* of *store*, kept *max_age* seconds whatever the data does: for
    statistics that a change of the data hardly moves and that take long to compute.
    Once older, it is computed again in the background, and a request waits for that
    ``STALE_WAIT`` at most, then takes the one it had; *inline* as ``cached``."""
    if getattr(store, "data_version", None) is None:
        return compute()
    entry_key = ((str(getattr(store, "name", "")), "lasting"), key)
    with _lock:
        kept = _lasting.get(entry_key)
        if kept is not None and time.monotonic() - kept[1] < max_age:
            return kept[0]  # type: ignore[no-any-return]
    if inline:
        value = compute()
        with _lock:
            _lasting[entry_key] = (value, time.monotonic())
        return value
    with _lock:
        nested = _in_cache_worker()
        future = _running.get(entry_key)
        if future is None and not nested:
            future = _pool.submit(_compute_lasting, entry_key, compute)
            _running[entry_key] = future
    if nested:
        _nested(key)
        return _compute_lasting(entry_key, compute)
    assert future is not None
    return _answer(future, _NONE if kept is None else kept[0], key)


def _in_cache_worker() -> bool:
    """Whether the current thread is a worker of ``_pool``, computing an answer."""
    return threading.current_thread().name.startswith("lawgraph-cache")


def _nested(key: Hashable) -> None:
    """A computation of the cache asked for another answer of it: computed here, in its own
    worker. Waiting for it on the pool could wait for ever, when every worker of the pool
    waits so (on 2026-10-08 a search stood still that way); the stack names the caller."""
    logger.warning(
        "A computation of the cache asked for %r: computed in its own worker, as one "
        "that waited for the pool could wait for ever.",
        key,
        stack_info=True,
    )


def _answer(future: concurrent.futures.Future[Any], last: Any, key: Hashable) -> Any:
    """The answer *future* computes, waited for no longer than the deadline of the request;
    with an earlier answer (*last*) a request waits ``STALE_WAIT`` at most, then takes that."""
    wait = read_time_left()
    if last is not _NONE and wait is not None:
        # only a request takes an old answer; the warm-up waits for the new one
        limit = _stale_wait.get()
        wait = min(wait, STALE_WAIT if limit is None else limit)
    try:
        return future.result(timeout=wait)
    except concurrent.futures.TimeoutError as exc:
        if last is not _NONE:
            return last
        raise ReadTimedOut(
            f"The request ran past its deadline waiting for {key!r}, which goes on "
            "computing for the next."
        ) from exc


def _compute_lasting(
    entry_key: tuple[tuple[str, str], Hashable], compute: Callable[[], T]
) -> T:
    """Compute one answer of ``lasting`` and keep it with the moment it was computed."""
    try:
        with in_background(), doing(f"cache: {_kind(entry_key[1])}"):
            value = compute()
    except BaseException:
        with _lock:
            _running.pop(entry_key, None)
        raise
    with _lock:
        _lasting[entry_key] = (value, time.monotonic())
        _running.pop(entry_key, None)
    return value


# What each thread of the background (the workers of ``_pool``, the warm-up) computes now,
# and since when (``busy``).
_doing: dict[str, tuple[str, float]] = {}


@contextlib.contextmanager
def doing(label: str) -> Iterator[None]:
    """Count the block as what the current thread computes now (``busy``)."""
    thread = threading.current_thread().name
    with _lock:
        before = _doing.get(thread)
        _doing[thread] = (label, time.monotonic())
    try:
        yield
    finally:
        # an answer a computation asked for, computed in its own worker (``_nested``),
        # gives the worker back to the computation that asked
        with _lock:
            if before is None:
                _doing.pop(thread, None)
            else:
                _doing[thread] = before


def busy() -> list[dict[str, Any]]:
    """What the threads of the background compute now (``thread``, ``call``, ``seconds``),
    for ``/api/health``: of an answer of the cache only its kind, never what it was asked
    for (the words of a search are a visitor's)."""
    now = time.monotonic()
    with _lock:
        running = list(_doing.items())
    return [
        {"thread": thread, "call": label, "seconds": round(now - began, 1)}
        for thread, (label, began) in running
    ]


def _kind(key: Hashable) -> str:
    """The kind of an answer of the cache: the name its key starts with."""
    if isinstance(key, tuple) and key and isinstance(key[0], str):
        return key[0]
    return "answer"


def _compute(
    entry_key: tuple[tuple[str, str], Hashable], compute: Callable[[], T]
) -> T:
    """Compute and keep one answer (in a thread of the pool: no request deadline, the read
    ceiling alone, on a connection of the background pool); a failure is not kept, the
    next request asks again."""
    try:
        with in_background(), doing(f"cache: {_kind(entry_key[1])}"):
            value = compute()
    except BaseException:
        with _lock:
            _running.pop(entry_key, None)
        raise
    return _keep(entry_key, value)


def _keep(entry_key: tuple[tuple[str, str], Hashable], value: T) -> T:
    """Keep *value* as the answer of *entry_key*, and as the latest of its key."""
    (database, _), key = entry_key
    with _lock:
        _values[entry_key] = value
        _computed_at[entry_key] = time.monotonic()
        while len(_values) > MAX_ENTRIES:
            dropped, _ = _values.popitem(last=False)
            _computed_at.pop(dropped, None)
        _latest[(database, key)] = value
        _latest.move_to_end((database, key))
        while len(_latest) > MAX_ENTRIES:
            _latest.popitem(last=False)
        _running.pop(entry_key, None)
    return value


def cached_rows(
    store: Any,
    statement: Any,
    params: dict[str, Any] | None = None,
    *,
    tables: tuple[str, ...] | None = None,
    **options: Any,
) -> list[Any]:
    """The rows of *statement* with *params*, kept per data version (of *tables* when
    given, see ``cached``): for a count or a facet that every visitor asks the same."""
    key = (
        "rows",
        _text(statement),
        _frozen(params or {}),
        tuple(sorted(options.items())),
    )
    return cached(
        store,
        key,
        lambda: list(store.query(statement, params, **options)),
        tables=tables,
    )


def lasting_rows(
    store: Any,
    statement: Any,
    params: dict[str, Any] | None = None,
    *,
    max_age: float,
    **options: Any,
) -> list[Any]:
    """The rows of *statement* with *params*, kept *max_age* seconds whatever the data does
    (``lasting``): for a count every visitor of a filter asks, that a run of the pipelines
    hardly moves and that reads many rows."""
    key = (
        "rows",
        _text(statement),
        _frozen(params or {}),
        tuple(sorted(options.items())),
    )
    return lasting(
        store, key, lambda: list(store.query(statement, params, **options)), max_age
    )


# Per database and key: a state that was found to hold, which holds from then on.
_true: set[tuple[str, Hashable]] = set()


def once_true(store: Any, key: Hashable, check: Callable[[], bool]) -> bool:
    """*check* of *store*, until it answers True, then True without asking again: for a
    state that only ever comes to hold (a side table filled once, ``member_authored``), read
    on every request. A False is not kept: it is asked again, until it holds."""
    entry_key = (str(getattr(store, "name", "")), key)
    if entry_key in _true:
        return True
    found = check()
    if found:
        with _lock:
            _true.add(entry_key)
    return found


def clear() -> None:
    """Forget every kept answer (the tests)."""
    with _lock:
        _true.clear()
        _versions.clear()
        _values.clear()
        _computed_at.clear()
        _latest.clear()
        _lasting.clear()
        _running.clear()
        _wanted.clear()
        _warm_started.clear()
        _polled.clear()


def _frozen(value: Any) -> Hashable:
    if isinstance(value, dict):
        return tuple(sorted((k, _frozen(v)) for k, v in value.items()))
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, Hashable):
        return value
    return repr(value)
