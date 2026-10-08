"""LawGraph store on PostgreSQL: the connections, the writes of every pipeline, the reads.

The class keeps the name ``GraphStore`` until the switch (D5); what it does is the same:
queries stream, writes are upserts that can be sent again after a restart, and an upsert
that would change nothing writes nothing.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import datetime as dt
import hashlib
import os
import re
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from typing import Any, TypeVar
from urllib.parse import unquote, urlsplit, urlunsplit

import psycopg
from psycopg import sql
from psycopg.rows import RowMaker
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool, PoolTimeout

from lawgraph.config.constants import (
    COLLECTION_EDGES,
    COLLECTION_PIPELINE_STATE,
    COLLECTION_RAW_SOURCES,
)
from lawgraph.config.settings import (
    ALLOW_COLLATION,
    DB_BACKGROUND_POOL_SIZE,
    DB_NAME,
    DB_POOL_SIZE,
    DB_URL,
    PAYLOAD_STORE,
    READ_TIMEOUT_MS,
    S3_ACCESS_KEY,
    S3_ENDPOINT,
    S3_REGION,
    S3_SECRET_KEY,
    WRITE_TIMEOUT_MS,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node
from lawgraph.core.time import iso_timestamp
from lawgraph.db._rows import node_doc, split_edge, split_node
from lawgraph.db.payloads import (
    PayloadMissing,
    PayloadStore,
    decode,
    encode,
    open_payload_store,
)
from lawgraph.db.schema import NODE_COLLECTIONS, create_database_sql, ensure_schema

logger = get_logger(__name__)

T = TypeVar("T")
Params = dict[str, Any] | Sequence[Any] | None
Statement = str | sql.SQL | sql.Composed


def edge_key(from_id: str, relation: str, to_id: str) -> str:
    """Deterministic SHA-1 edge key — single scheme used everywhere."""
    return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()


def raw_key(source: str, kind: str, external_id: str) -> str:
    """The key of the raw_sources document of (source, kind, external_id)."""
    return hashlib.sha1(f"{source}:{kind}:{external_id}".encode()).hexdigest()


# What the API serves: a write to raw_sources or pipeline_state leaves ``data_version``.
_SERVED = (*NODE_COLLECTIONS, COLLECTION_EDGES)

# Payloads read or written at once (a thread and a connection each).
PAYLOAD_THREADS = 16


def payload_name(doc: dict[str, Any]) -> str:
    """The name of the object of a raw record's text payload.

    It starts with the database, so two databases (a test database next to the real one)
    never share an object; ``raw_sources`` keeps the name, so a copy under another name
    still finds its objects.
    """
    return f"{DB_NAME}/{doc['source']}/{doc['kind']}/{doc['_key']}.gz"


def raw_source_doc(
    *,
    source: str,
    kind: str,
    external_id: str | None,
    payload_json: dict | list | None = None,
    payload_text: str | None = None,
    meta: dict | None = None,
) -> dict[str, Any]:
    """The raw_sources document of one record, keyed by (source, kind, external_id).

    ``fetched_at`` is the moment of this call: when the record was fetched, not when a
    buffered write stores it.
    """
    if external_id is not None:
        key = raw_key(source, kind, external_id)
    else:
        key = str(uuid.uuid4())
    return {
        "_key": key,
        "source": source,
        "kind": kind,
        "external_id": external_id,
        "fetched_at": iso_timestamp(
            dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        ),
        "payload_json": payload_json,
        "payload_text": payload_text,
        "meta": dict(meta or {}),
    }


# A bulk write is an upsert, so it can be sent again: a database that restarts (a second or
# two) or is still starting up must not cost a run of hours its buffer. After these waits the
# failure is real and is raised.
WRITE_RETRY_WAITS = (2.0, 10.0, 30.0)

# The server cannot be reached, is starting up or shutting down; not: it refused the query,
# nor cancelled it (``57014``, a statement that ran past ``LAWGRAPH_WRITE_TIMEOUT_MS``: sent
# again, it would run as long).
_UNREACHABLE_STATES = frozenset({"57P01", "57P02", "57P03", "08000", "08003", "08006"})


def _is_unreachable(exc: Exception) -> bool:
    if isinstance(exc, psycopg.OperationalError):
        return exc.sqlstate is None or exc.sqlstate in _UNREACHABLE_STATES
    return isinstance(exc, ConnectionError)


def _retry_write(what: str, write: Callable[[], T]) -> T:
    for wait in WRITE_RETRY_WAITS:
        try:
            return write()
        except Exception as exc:
            if not _is_unreachable(exc):
                raise
            logger.warning(
                "The database is unreachable (%s); writing %s again in %.0fs.",
                type(exc).__name__,
                what,
                wait,
            )
            _sleep(wait)
    return write()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


# A statement with one of these changes data (SQL keywords are written in capitals
# throughout the code); it runs to the end at once, in a transaction of its own.
_WRITES = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE)\b")


def _rows(cursor: psycopg.Cursor[Any]) -> RowMaker[Any]:
    """A row as the code reads it: the value itself when the query selects one column (a
    document, a count, a key), otherwise a dict of the columns."""
    names = [c.name for c in cursor.description or ()]
    if len(names) == 1:
        return lambda values: values[0]
    return lambda values: dict(zip(names, values, strict=True))


def _server_url(database: str) -> str:
    return f"{DB_URL.rstrip('/')}/{database}"


def redacted(text: str, url: str | None = None) -> str:
    """*text* with the credentials of *url* (``DB_URL`` by default) masked: the URL itself as
    ``scheme://***@host:port`` and its password wherever else it appears (an error message
    that repeats it)."""
    url = DB_URL if url is None else url
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return text
    host = parts.netloc.rpartition("@")[2]
    text = text.replace(url, urlunsplit(parts._replace(netloc=f"***@{host}")))
    password = parts.password
    if password:
        # As written in the URL (quoted) and as a message may repeat it (decoded).
        for secret in {password, unquote(password)}:
            text = text.replace(secret, "***")
    return text


def _create_database_if_missing() -> None:
    """Create ``DB_NAME`` when it is absent and the user may create databases."""
    try:
        with psycopg.connect(_server_url("postgres"), autocommit=True) as admin:
            found = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
            ).fetchone()
            if found is None:
                admin.execute(create_database_sql(DB_NAME).encode())
                logger.info("Created database %s.", DB_NAME)
    except psycopg.Error:
        return  # no access to the server's own database: ours must already exist


def _configure(conn: psycopg.Connection[Any]) -> None:
    """Every connection of the pool, as it opens: without JIT compilation. PostgreSQL 18
    compiles a statement above ``jit_above_cost``; for the statements of this API that
    costs more than it gains (a feed page 249 ms against 17 ms without, a page with facets
    4.45 s against 1.31 s), whatever the server is configured with.

    And a server-side cursor planned as the query it reads: ``query`` reads every
    statement through one (``DECLARE``), and by default the planner plans a cursor for its
    first tenth (``cursor_tuple_fraction`` 0.1). For a statement with ``ORDER BY … LIMIT``
    that picks a plan which walks a table in the order of an index until enough rows pass
    the conditions: a rare name of a judgment in date order, or the ``nodes`` view in the
    order of its ids. On the full graph that read nearly every row (the article detail and
    the search of the judgments, 30 s), while the statement itself takes milliseconds.
    Every row of a cursor is read, so it is planned for all of them."""
    conn.execute("SET jit = off")
    conn.execute("SET cursor_tuple_fraction = 1.0")
    conn.commit()


# The name of every connection of this process (``pg_stat_activity.application_name``): the
# watchdog finds the statements of its own process by it.
APPLICATION_NAME = f"lawgraph-{os.getpid()}"


# The statement of every server-side cursor open in this process, by its name: a streamed
# read shows in ``pg_stat_activity`` as ``FETCH FORWARD 1000 FROM "lg_…"`` alone.
_open_cursors: dict[str, str] = {}
_CURSOR_NAME = re.compile(r'FROM "?(lg_[0-9a-f]{32})"?')


# When the reads of the current request must end (``time.monotonic``); None outside a
# request. The API sets it per request (``read_deadline``); a statement then gets what is left.
_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "lawgraph_read_deadline", default=None
)


def set_read_deadline(seconds: float) -> contextvars.Token[float | None]:
    """From now, the reads of this context end within *seconds*; ``reset_read_deadline``
    with the token ends that."""
    return _deadline.set(time.monotonic() + seconds)


def reset_read_deadline(token: contextvars.Token[float | None]) -> None:
    _deadline.reset(token)


# Whether the reads of the current context are computed in the background (the API's warm-up
# and kept answers, ``in_background``): they take a connection of the store's background
# pool, not one of the requests.
_background: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "lawgraph_background", default=False
)


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
        server to take it, so not on the event loop)."""
        with self._lock:
            self.cancelled = True
            running = list(self._connections)
        for conn in running:
            with contextlib.suppress(psycopg.Error):
                conn.cancel_safe(timeout=5.0)

    @contextlib.contextmanager
    def reading(self, conn: psycopg.Connection[Any]) -> Iterator[None]:
        with self._lock:
            if self.cancelled:
                raise RequestCancelled("The client went away before this read.")
            self._connections.add(conn)
        try:
            yield
        finally:
            with self._lock:
                self._connections.discard(conn)


# The reads of the current request, to cancel when its client goes away (the API sets one
# per request); None outside a request. Copied into the threads a request runs queries on,
# not into a computation of the cache, which goes on for the next request.
_cancellation: contextvars.ContextVar[Cancellation | None] = contextvars.ContextVar(
    "lawgraph_cancellation", default=None
)


def set_cancellation(
    cancellation: Cancellation,
) -> contextvars.Token[Cancellation | None]:
    return _cancellation.set(cancellation)


def reset_cancellation(token: contextvars.Token[Cancellation | None]) -> None:
    _cancellation.reset(token)


@contextlib.contextmanager
def no_read_deadline() -> Iterator[None]:
    """The reads of the block have the ceiling alone, not the deadline of the request: for
    an answer computed once for every visitor (``version_cache``), which a request's
    deadline would cut off each time it is first asked."""
    token = _deadline.set(None)
    try:
        yield
    finally:
        _deadline.reset(token)


def read_time_left() -> float | None:
    """The seconds the reads of the current request have left (at least 0); None outside
    a request."""
    deadline = _deadline.get()
    return None if deadline is None else max(0.0, deadline - time.monotonic())


def _read_budget_ms() -> int:
    """The ``statement_timeout`` of the next read: ``LAWGRAPH_READ_TIMEOUT_MS``, or the time
    left before the deadline of the request when that is less. ``ReadTimedOut`` when none
    is left."""
    deadline = _deadline.get()
    if deadline is None:
        return READ_TIMEOUT_MS
    left = int((deadline - time.monotonic()) * 1000)
    if left <= 0:
        raise ReadTimedOut("The request ran past its deadline before this read.")
    return min(READ_TIMEOUT_MS, left)


class ReadTimedOut(RuntimeError):
    """A statement that reads ran past ``LAWGRAPH_READ_TIMEOUT_MS`` and was cancelled."""


class RequestCancelled(ReadTimedOut):
    """The client of the request went away: its reads were cancelled."""


def own_activity(min_seconds: float) -> list[dict[str, Any]]:
    """The statements of this process that have run for over *min_seconds*: ``{pid, state,
    seconds, wait, query}``, the longest first. On a connection of its own, so a pool whose
    connections are all busy does not keep it waiting; empty when the server cannot be
    reached."""
    try:
        with psycopg.connect(
            _server_url(DB_NAME),
            application_name="lawgraph-watchdog",
            connect_timeout=10,
            autocommit=True,
        ) as conn:
            rows = conn.execute(
                """
                SELECT pid, state,
                       extract(epoch FROM now() - query_start)::int AS seconds,
                       concat_ws(':', wait_event_type, wait_event) AS wait,
                       left(regexp_replace(query, '\\s+', ' ', 'g'), 300) AS query
                FROM pg_stat_activity
                WHERE application_name = %(name)s AND state <> 'idle'
                  AND now() - query_start > make_interval(secs => %(min)s)
                ORDER BY query_start NULLS LAST
                """,
                {"name": APPLICATION_NAME, "min": min_seconds},
            ).fetchall()
    except psycopg.Error as exc:
        logger.debug("No activity from the server: %s", exc)
        return []
    names = ("pid", "state", "seconds", "wait", "query")
    found = [dict(zip(names, row, strict=True)) for row in rows]
    for row in found:
        cursor = _CURSOR_NAME.search(row["query"] or "")
        if cursor and (read := _open_cursors.get(cursor.group(1))):
            row["query"] = f"{row['query']}, a read of: {read}"
    return found


# The stores still open: closed at exit, while the interpreter can still join the threads
# of their pools (a pool left to its finalizer cannot, and says so on every command).
_OPEN: weakref.WeakSet[GraphStore] = weakref.WeakSet()


@atexit.register
def _close_open_stores() -> None:
    for store in list(_OPEN):
        store.close()


class GraphStore:
    """The PostgreSQL database of the graph: connections, reads, upserts."""

    def __init__(self) -> None:
        self.name = DB_NAME
        _create_database_if_missing()
        try:
            # Every connection is opened at the start: no request waits for a new one.
            self.pool = ConnectionPool(
                _server_url(DB_NAME),
                min_size=DB_POOL_SIZE,
                max_size=DB_POOL_SIZE,
                open=True,
                timeout=60,
                name="lawgraph",
                configure=_configure,
                kwargs={"application_name": APPLICATION_NAME},
            )
            self._background_pool: ConnectionPool | None = None
            self._background_lock = threading.Lock()
            with self.pool.connection() as conn:
                ensure_schema(conn, allowed_collation=ALLOW_COLLATION)
        except Exception as exc:
            if getattr(self, "pool", None) is not None:
                self.pool.close()  # its workers would go on connecting
            raise ConnectionError(
                redacted(
                    f"Cannot connect to PostgreSQL at {DB_URL} (db={DB_NAME}). "
                    f"Original error: {exc}"
                )
            ) from exc

        self.payloads: PayloadStore = open_payload_store(
            PAYLOAD_STORE,
            s3_endpoint=S3_ENDPOINT,
            s3_region=S3_REGION,
            s3_access_key=S3_ACCESS_KEY,
            s3_secret_key=S3_SECRET_KEY,
        )
        # Objects are written and read side by side: a request each, most of it waiting.
        self._payload_io = ThreadPoolExecutor(
            max_workers=PAYLOAD_THREADS, thread_name_prefix="payload"
        )
        _OPEN.add(self)

    def close(self) -> None:
        _OPEN.discard(self)
        self.pool.close()
        if self._background_pool is not None:
            self._background_pool.close()
        self._payload_io.shutdown(wait=False)

    def _reading_pool(self) -> ConnectionPool:
        """The pool a read of the current context takes its connection from."""
        if not _background.get():
            return self.pool
        with self._background_lock:
            if self._background_pool is None:
                self._background_pool = ConnectionPool(
                    _server_url(self.name),
                    min_size=DB_BACKGROUND_POOL_SIZE,
                    max_size=DB_BACKGROUND_POOL_SIZE,
                    open=True,
                    timeout=60,
                    name="lawgraph-background",
                    configure=_configure,
                    kwargs={"application_name": APPLICATION_NAME},
                )
            return self._background_pool

    def pool_usage(self) -> dict[str, dict[str, int] | None]:
        """Per pool (``requests``, ``background``; null before the background one opened)
        its connections, how many are free and how many reads wait for one."""

        def usage(pool: ConnectionPool | None) -> dict[str, int] | None:
            if pool is None:
                return None
            stats = pool.get_stats()
            return {
                "size": stats.get("pool_size", 0),
                "free": stats.get("pool_available", 0),
                "waiting": stats.get("requests_waiting", 0),
            }

        return {
            "requests": usage(self.pool),
            "background": usage(self._background_pool),
        }

    def ping(self) -> None:
        """Raise when the database cannot be reached."""
        with self.pool.connection() as conn:
            conn.execute("SELECT 1")

    @staticmethod
    def _node_table(collection: str) -> sql.Identifier:
        if collection not in NODE_COLLECTIONS:
            raise ValueError(f"Unknown collection: {collection!r}")
        return sql.Identifier(collection)

    def has_node(self, collection: str, key: str) -> bool:
        """Is *key* a document of *collection*, one of ours? A primary-key lookup."""
        if collection not in NODE_COLLECTIONS:
            return False
        statement = sql.SQL("SELECT 1 FROM {} WHERE key = %(key)s").format(
            sql.Identifier(collection)
        )
        return next(self.query(statement, {"key": key}), None) is not None

    def get_document(self, collection: str, key: str) -> dict[str, Any] | None:
        """The document of *key* in the node collection *collection*, or ``None``."""
        statement = sql.SQL(
            "SELECT id, key, type, labels, props FROM {} WHERE key = %(key)s"
        ).format(self._node_table(collection))
        rows = list(self.query(statement, {"key": key}))
        return node_doc(rows[0]) if rows else None

    def count(self, collection: str) -> int:
        """How many documents *collection* holds (a node collection or the edges)."""
        if collection not in _SERVED:
            raise ValueError(f"Unknown collection: {collection!r}")
        statement = sql.SQL("SELECT count(*)::int FROM {}").format(
            sql.Identifier(collection)
        )
        return int(next(self.query(statement)))

    def data_version(self) -> str:
        """A stamp of what the API serves: it changes with every statement that changes a
        table of the graph (``lg_data_version``), and not with a retrieve."""
        digest = hashlib.sha1(usedforsecurity=False)
        rows = self.query(
            "SELECT collection, version FROM lg_data_version"
            ' WHERE collection = ANY(%(served)s) ORDER BY collection COLLATE "C"',
            {"served": list(_SERVED)},
        )
        for row in rows:
            digest.update(f"{row['collection']}:{row['version']};".encode())
        return digest.hexdigest()[:16]

    def vacuum_analyze(self) -> None:
        """``VACUUM (ANALYZE)`` of the database: after a build, so the planner knows the
        tables and an index-only read need not visit every row (the first requests after a
        fresh build are slow without it)."""
        with self.pool.connection() as conn:
            conn.autocommit = True
            try:
                conn.execute("VACUUM (ANALYZE)")
            finally:
                conn.autocommit = False

    # ── Size ───────────────────────────────────────────────────────────────────

    def disk_usage(self) -> dict[str, Any]:
        """``bytesUsed``: the size of the database on disk (PostgreSQL has no license
        limit; ``lawgraph check`` alerts at ``DB_SIZE_ALERT_GIB``)."""
        used = next(self.query("SELECT pg_database_size(current_database())"))
        return {"bytesUsed": int(used), "status": "good"}

    def collection_sizes(self) -> dict[str, int]:
        """Bytes on disk per table: its rows, its TOAST and its indexes."""
        tables = [*_SERVED, COLLECTION_RAW_SOURCES, COLLECTION_PIPELINE_STATE]
        rows = self.query(
            "SELECT t AS name, pg_total_relation_size(t::regclass) AS size"
            " FROM unnest(%(tables)s::text[]) AS t",
            {"tables": tables},
        )
        return {row["name"]: int(row["size"]) for row in rows}

    # ── Query ──────────────────────────────────────────────────────────────────

    def query(
        self,
        statement: Statement,
        params: Params = None,
        *,
        batch_size: int = 1000,
        indexes_only: bool = False,
        hash_joins: bool = False,
    ) -> Iterator[Any]:
        """Run a statement; one that only reads streams its result.

        A row is the value of the one column a query selects (a document, a count, a key),
        or a dict of its columns. A read runs on a server-side cursor, so ``batch_size``
        rows are in flight however large the result (41,000 BWB toestanden of 80 KB are
        3 GB); its connection is held until the reader stops, however it stops. A statement
        that writes runs to the end at once (``execute``).

        ``indexes_only`` keeps the planner from reading a whole table where an index can
        find the rows (``SET LOCAL enable_seqscan = off``, for this statement's transaction
        alone). An emergency brake, for one reason: the planner does not count the cost of
        detoasting. A condition on a large column (the words of every article, a judgment's
        summary) unpacks that column from its TOAST table for every row it tests; the
        planner prices the test as if the value were at hand, and takes a scan of the whole
        table for cheaper than the indexes when a word is common. The search uses it for
        its ranking and its document frequencies; ``tests/pg/test_query_plans.py`` checks
        that it still does.

        ``hash_joins`` keeps the planner from nested loops where it can join otherwise
        (``SET LOCAL enable_nestloop = off``, for this statement alone): for a statement
        that joins sets the planner cannot count (a CTE over a condition on props, which
        it takes for a row or twenty where there are thousands), and that a nested loop
        over them makes run for hours. A loop over ``generate_series`` stays one.
        """
        if _WRITES.search(_text(statement)):
            return iter(self.execute(statement, params))
        return self._stream(statement, params, batch_size, indexes_only, hash_joins)

    def _stream(
        self,
        statement: Statement,
        params: Params,
        batch_size: int,
        indexes_only: bool = False,
        hash_joins: bool = False,
    ) -> Iterator[Any]:
        budget = _read_budget_ms()
        try:
            # a request waits for a connection of the pool no longer than it has left; a
            # computation in the background waits its turn
            pool = self._reading_pool()
            wait = budget / 1000 if _background.get() else min(60.0, budget / 1000)
            cancellation = _cancellation.get()
            with (
                pool.connection(timeout=wait) as conn,
                (
                    cancellation.reading(conn)
                    if cancellation is not None
                    else contextlib.nullcontext()
                ),
            ):
                yield from self._read(
                    conn,
                    statement,
                    params,
                    batch_size,
                    budget,
                    indexes_only,
                    hash_joins,
                )
        except PoolTimeout as exc:
            raise ReadTimedOut(
                "No connection of the pool came free before the deadline of the request."
            ) from exc

    def _read(
        self,
        conn: psycopg.Connection[Any],
        statement: Statement,
        params: Params,
        batch_size: int,
        budget: int,
        indexes_only: bool,
        hash_joins: bool,
    ) -> Iterator[Any]:
        # a ceiling for each statement (the DECLARE, every FETCH), not for the stream; in
        # a request of the API no more than the request has left
        conn.execute(f"SET LOCAL statement_timeout = {budget}")
        if indexes_only:
            # The planner prices detoasting at nothing (see ``query``).
            conn.execute("SET LOCAL enable_seqscan = off")
        if hash_joins:
            # The planner cannot count the rows of the sets it joins (see ``query``).
            conn.execute("SET LOCAL enable_nestloop = off")
        name = f"lg_{uuid.uuid4().hex}"
        text = re.sub(r"\s+", " ", _text(statement)).strip()
        _open_cursors[name] = text[:300]
        try:
            with conn.cursor(name=name, row_factory=_rows) as cursor:
                cursor.itersize = batch_size
                cursor.execute(_query(statement), params)
                yield from cursor
        except psycopg.errors.QueryCanceled as exc:
            cancellation = _cancellation.get()
            if cancellation is not None and cancellation.cancelled:
                raise RequestCancelled(
                    f"The client went away; its read was cancelled: {text[:300]}"
                ) from exc
            raise ReadTimedOut(
                f"A read ran for over {budget / 1000:.0f} s (LAWGRAPH_READ_TIMEOUT_MS, "
                f"or what the request had left) and was cancelled: {text[:300]}"
            ) from exc
        finally:
            _open_cursors.pop(name, None)

    def execute(self, statement: Statement, params: Params = None) -> list[Any]:
        """Run a statement that writes, in a transaction of its own, sent again when the
        database was unreachable; the rows it returns (``RETURNING``)."""

        def run() -> list[Any]:
            with self.pool.connection() as conn:
                conn.execute(f"SET LOCAL statement_timeout = {WRITE_TIMEOUT_MS}")
                with conn.cursor(row_factory=_rows) as cursor:
                    cursor.execute(_query(statement), params)
                    return cursor.fetchall() if cursor.description else []

        return _retry_write("a statement", run)

    def execute_together(self, statements: list[tuple[Statement, Params]]) -> None:
        """Run statements that write in one transaction: a reader sees all of them or
        none (a table emptied and filled again). Sent again when the database was
        unreachable."""

        def run() -> None:
            with self.pool.connection() as conn:
                conn.execute(f"SET LOCAL statement_timeout = {WRITE_TIMEOUT_MS}")
                for statement, params in statements:
                    conn.execute(_query(statement), params)

        _retry_write("statements together", run)

    # ── Raw sources ────────────────────────────────────────────────────────────

    def insert_raw_sources(
        self, docs: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], str]]:
        """Upsert raw source documents (see ``raw_source_doc``) in one statement.

        A text payload is written to the payload store first (``_put_payloads``). A stored
        document with the same key is replaced. Returns the documents that were refused,
        each with the reason: none, a statement is written whole or raises (as does a
        failure of the payload store).
        """
        if not docs:
            return []
        stored = _last_per_key(self._put_payloads(docs))
        rows = [
            {"key": d["_key"], "doc": {k: v for k, v in d.items() if k != "_key"}}
            for d in stored
        ]
        self.execute(
            f"""
            INSERT INTO {COLLECTION_RAW_SOURCES} (key, doc)
            SELECT r.key, r.doc
            FROM json_to_recordset(%(rows)s::json) AS r(key text, doc json)
            ORDER BY r.key
            ON CONFLICT (key) DO UPDATE SET doc = EXCLUDED.doc
            """,
            {"rows": Json(rows)},
        )
        return []

    def _put_payloads(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Write the text payload of every document to the payload store, and return the
        documents as ``raw_sources`` keeps them: ``payload_ref`` in place of ``payload_text``.

        A payload that cannot be written raises: the store is full, gone or refuses our
        keys, which is no fault of one record, and fetching on would store nothing.
        """

        def put(doc: dict[str, Any]) -> dict[str, Any]:
            text = doc.get("payload_text")
            if text is None:
                return doc
            name = payload_name(doc)
            self.payloads.put(name, encode(text))
            stored = {k: v for k, v in doc.items() if k != "payload_text"}
            return {**stored, "payload_ref": name, "payload_chars": len(text)}

        return list(self._payload_io.map(put, docs))

    def with_payloads(
        self, records: Iterable[dict[str, Any]], *, batch_size: int = PAYLOAD_THREADS
    ) -> Iterator[dict[str, Any]]:
        """*records* of ``raw_sources`` in the same order, each with its ``payload_text``
        read from the payload store (``None`` when its object is missing, which is logged:
        the record is then skipped like one without a payload)."""

        def read(record: dict[str, Any]) -> dict[str, Any]:
            name = record.get("payload_ref")
            if not name:
                return record
            try:
                text: str | None = decode(self.payloads.get(name))
            except PayloadMissing:
                logger.warning(
                    "The payload of %s/%s/%s is missing in %s (%s).",
                    record.get("source"),
                    record.get("kind"),
                    record.get("external_id"),
                    self.payloads.location,
                    name,
                )
                text = None
            return {**record, "payload_text": text}

        rows = iter(records)
        while chunk := list(islice(rows, batch_size)):
            yield from self._payload_io.map(read, chunk)

    # ── Nodes ──────────────────────────────────────────────────────────────────

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        """Upsert a Node using its deterministic key; returns (stored node, created).

        On INSERT: stores the full document as-is.
        On UPDATE: merges props so neither pipeline overwrites the other's fields,
        and unions labels arrays so domain labels survive across pipeline runs.
        """
        if node.key is None:
            raise ValueError("Node must have a deterministic key.")
        table = self._node_table(node.collection)
        row = split_node(node.to_document(), node.collection)
        statement = sql.SQL(
            """
            INSERT INTO {table} AS t (id, type, labels, props)
            VALUES (%(id)s, %(type)s, %(labels)s, %(props)s)
            ON CONFLICT (id) DO UPDATE SET
                type = EXCLUDED.type,
                labels = lg_array_union(t.labels, EXCLUDED.labels),
                props = lg_update(t.props, EXCLUDED.props)
            RETURNING id, key, type, labels, props, (xmax = 0) AS created
            """
        ).format(table=table)
        stored = self.execute(statement, {**row, "props": Json(row["props"])})[0]
        node_stored = Node.from_document(node.collection, node_doc(stored))
        return node_stored, bool(stored["created"])

    def bulk_insert_or_update_nodes(
        self,
        collection: str,
        docs: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Batch-upsert node documents. Returns (created, updated); a document the update
        would not change is not written or counted.

        ``type`` is the new one, ``labels`` the union of both (first occurrence first),
        ``props`` merged one level deep with its keys in order (``lg_update``, D11). "Would
        not change" is as ArangoDB compared (``lg_same``): a prop set to null is the same as a
        missing one, so an update that only adds nulls is not written. A key
        that occurs more than once is applied in its order, a statement per occurrence, as
        ArangoDB's loop over the batch did.
        """
        table = self._node_table(collection)
        statement = sql.SQL(
            """
            INSERT INTO {table} AS t (id, type, labels, props)
            SELECT d.id, d.type, lg_text_array(d.labels), d.props
            FROM json_to_recordset(%(rows)s::json)
                AS d(id text, type text, labels json, props json)
            ORDER BY d.id
            ON CONFLICT (id) DO UPDATE SET
                type = EXCLUDED.type,
                labels = lg_array_union(t.labels, EXCLUDED.labels),
                props = lg_update(t.props, EXCLUDED.props)
            WHERE (t.type, t.labels) IS DISTINCT FROM (
                EXCLUDED.type, lg_array_union(t.labels, EXCLUDED.labels)
            ) OR NOT lg_same(t.props::jsonb, lg_update(t.props, EXCLUDED.props)::jsonb)
            RETURNING (xmax = 0) AS created
            """
        ).format(table=table)
        rows = [split_node(doc, collection) for doc in docs]
        return self._upsert_rounds(f"documents of {collection}", statement, rows, "id")

    def _upsert_rounds(
        self, what: str, statement: Statement, rows: list[dict[str, Any]], key: str
    ) -> tuple[int, int]:
        created = updated = 0
        for batch in _rounds(rows, key):
            answer = _retry_write(
                f"{len(batch)} {what}",
                lambda batch=batch: self.execute(statement, {"rows": Json(batch)}),  # type: ignore[misc]
            )
            new = sum(1 for was_new in answer if was_new)
            created += new
            updated += len(answer) - new
        return created, updated

    def existing_keys(
        self,
        collection: str,
        keys: Iterable[str],
        *,
        chunk_size: int = 5000,
    ) -> set[str]:
        """Return the subset of *keys* that exist in *collection*: one index lookup per
        ``chunk_size`` keys."""
        table = self._node_table(collection)
        statement = sql.SQL("SELECT key FROM {} WHERE key = ANY(%(keys)s)").format(
            table
        )
        wanted = list(set(keys))
        found: set[str] = set()
        for start in range(0, len(wanted), chunk_size):
            chunk = wanted[start : start + chunk_size]
            found.update(self.query(statement, {"keys": chunk}))
        return found

    def ensure_stub_node(
        self,
        collection: str,
        key: str,
        node_type: Any,
        props: dict[str, Any],
    ) -> Node | None:
        """Return the node if it exists, otherwise insert a minimal stub.

        Used by semantic pipelines to keep the graph connected when a
        referenced node hasn't been fully imported yet (e.g., a cited ECLI
        that isn't in the corpus). The stub carries ``props.stub=True`` so
        the frontend can surface it as a pending import.
        """
        table = self._node_table(collection)
        node_type_val = (
            node_type.value if hasattr(node_type, "value") else str(node_type)
        )
        statement = sql.SQL(
            """
            INSERT INTO {} (id, type, labels, props)
            VALUES (%(id)s, %(type)s, '{{}}', %(props)s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id, key, type, labels, props
            """
        ).format(table)
        params = {
            "id": f"{collection}/{key}",
            "type": node_type_val,
            "props": Json({**props, "stub": True}),
        }
        inserted = self.execute(statement, params)
        if inserted:
            return Node.from_document(collection, node_doc(inserted[0]))
        return self.get_node(collection, key)

    def get_node(self, collection: str, key: str) -> Node | None:
        """Fetch a Node by collection and key. Returns None if not found."""
        doc = self.get_document(collection, key)
        return Node.from_document(collection, doc) if doc is not None else None

    # ── Edges ──────────────────────────────────────────────────────────────────

    def bulk_insert_or_update_edges(
        self,
        docs: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Batch-upsert edges. Returns (created, updated).

        On update ``confidence``, ``source`` and ``status`` are the new ones (``null`` when
        the new edge has none) and ``meta`` is merged one level deep; ``created_at`` and
        every other attribute stay. An edge the update would not change is not written or
        counted; in ``meta`` an attribute set to null is the same as a missing one
        (``lg_same``), as ArangoDB compared.
        """
        statement = sql.SQL(
            f"""
            INSERT INTO {COLLECTION_EDGES} AS t (key, from_id, to_id, doc)
            SELECT e.key, e.from_id, e.to_id, e.doc
            FROM json_to_recordset(%(rows)s::json)
                AS e(key text, from_id text, to_id text, doc json)
            ORDER BY e.key
            ON CONFLICT (key) DO UPDATE SET doc = lg_merge(t.doc, json_build_object(
                'confidence', EXCLUDED.doc -> 'confidence',
                'source', EXCLUDED.doc -> 'source',
                'status', EXCLUDED.doc -> 'status',
                'meta', lg_update(t.doc -> 'meta', EXCLUDED.doc -> 'meta')
            ))
            WHERE (
                coalesce((t.doc -> 'confidence')::jsonb, 'null'),
                coalesce((t.doc -> 'source')::jsonb, 'null'),
                coalesce((t.doc -> 'status')::jsonb, 'null')
            ) IS DISTINCT FROM (
                coalesce((EXCLUDED.doc -> 'confidence')::jsonb, 'null'),
                coalesce((EXCLUDED.doc -> 'source')::jsonb, 'null'),
                coalesce((EXCLUDED.doc -> 'status')::jsonb, 'null')
            ) OR NOT lg_same(
                coalesce((t.doc -> 'meta')::jsonb, 'null'),
                lg_update(t.doc -> 'meta', EXCLUDED.doc -> 'meta')::jsonb
            )
            RETURNING (xmax = 0) AS created
            """
        )
        rows = [split_edge(doc) for doc in docs]
        return self._upsert_rounds("edges", statement, rows, "key")


def _text(statement: Statement) -> str:
    if isinstance(statement, str):
        return statement
    return statement.as_string(None)


def _query(statement: Statement) -> sql.SQL | sql.Composed:
    if isinstance(statement, str):
        return sql.SQL(statement)  # type: ignore[arg-type]  # the code's own text
    return statement


def _rounds(rows: list[dict[str, Any]], key: str) -> Iterator[list[dict[str, Any]]]:
    """*rows* in rounds in which every key occurs once: the first occurrence of each key,
    then the second, and so on (one statement cannot write a row twice)."""
    rounds: list[list[dict[str, Any]]] = []
    seen: dict[str, int] = {}
    for row in rows:
        n = seen.get(row[key], 0)
        seen[row[key]] = n + 1
        if n == len(rounds):
            rounds.append([])
        rounds[n].append(row)
    yield from rounds


def _last_per_key(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A replace of the same key twice in one batch: the last one stays."""
    return list({doc["_key"]: doc for doc in docs}.values())
