"""LawGraph store on PostgreSQL: the connections, the writes of every pipeline, the reads.

``GraphStore``: queries stream, writes are upserts that can be sent again after a restart,
and an upsert that would change nothing writes nothing.
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import os
import queue
import re
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from typing import Any
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
    S3_ACCESS_KEY,
    S3_ENDPOINT,
    S3_REGION,
    S3_SECRET_KEY,
    WRITE_TIMEOUT_MS,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import TYPE_OF_COLLECTION, Node
from lawgraph.core.relations import META_KEYS
from lawgraph.db._rows import node_doc, split_edge, split_node
from lawgraph.db.payloads import (
    PayloadMissing,
    PayloadStore,
    decode,
    encode,
    open_payload_store,
)
from lawgraph.db.request_context import (
    Cancellation,
    ReadTimedOut,
    RequestCancelled,
    current_cancellation,
    read_budget_ms,
    read_deadline,
    reads_in_background,
    seconds_past,
)

# db/queries still imports these two through the store, until its packages switch over.
from lawgraph.db.request_context import read_budget as read_budget
from lawgraph.db.request_context import read_time_left as read_time_left
from lawgraph.db.schema import (
    DEFINITIONS_TABLE,
    NODE_COLLECTIONS,
    UNLINKED_TABLE,
    create_database_sql,
    ensure_schema,
)

logger = get_logger(__name__)

Params = dict[str, Any] | Sequence[Any] | None
Statement = str | sql.SQL | sql.Composed


# relation -> the keys of ``meta`` its model has, for the edge upsert
_META_KEYS = Json({relation: sorted(keys) for relation, keys in META_KEYS.items()})

# What the API serves: a write to raw_sources or pipeline_state leaves ``data_version``.
_SERVED = (*NODE_COLLECTIONS, COLLECTION_EDGES, DEFINITIONS_TABLE, UNLINKED_TABLE)

# Payloads read or written at once (a thread and a connection each).
PAYLOAD_THREADS = 16


def payload_name(doc: dict[str, Any]) -> str:
    """The name of the object of a raw record's text payload.

    It starts with the database, so two databases (a test database next to the real one)
    never share an object; ``raw_sources`` keeps the name, so a copy under another name
    still finds its objects.
    """
    return f"{DB_NAME}/{doc['source']}/{doc['kind']}/{doc['key']}.gz"


# A bulk write is an upsert, so it can be sent again: a database that restarts (a second or
# two) or is still starting up must not cost a run of hours its buffer. After these waits the
# failure is real and is raised.
WRITE_RETRY_WAITS = (2.0, 10.0, 30.0)

# The server cannot be reached, is starting up or shutting down; not: it refused the query,
# nor cancelled it (``57014``, a statement that ran past ``LAWGRAPH_WRITE_TIMEOUT_MS``: sent
# again, it would run as long).
_UNREACHABLE_STATES = frozenset({"57P01", "57P02", "57P03", "08000", "08003", "08006"})


class DatabaseUnavailable(ConnectionError):
    """The database cannot be reached: not running, starting up or shutting down."""


def _unavailable(exc: Exception) -> DatabaseUnavailable:
    return DatabaseUnavailable(
        redacted(f"Cannot connect to PostgreSQL at {DB_URL} (db={DB_NAME}): {exc}")
    )


def _is_unreachable(exc: Exception) -> bool:
    if isinstance(exc, psycopg.OperationalError):
        return exc.sqlstate is None or exc.sqlstate in _UNREACHABLE_STATES
    return isinstance(exc, ConnectionError)


class LockNotGranted(RuntimeError):
    """A statement waited past ``lock_timeout`` for a lock another session held (55P03):
    a migration or ops script holds the table. The next run tries again."""


def _not_granted(what: str, exc: Exception) -> LockNotGranted:
    return LockNotGranted(
        f"{what} waited past lock_timeout for a lock another session holds; "
        f"it runs again once that one is done: {str(exc).strip()}"
    )


def _retry_write[T](what: str, write: Callable[[], T]) -> T:
    try:
        return _retry_unreachable(what, write)
    except psycopg.errors.LockNotAvailable as exc:
        raise _not_granted(f"Writing {what}", exc) from exc


def _retry_unreachable[T](what: str, write: Callable[[], T]) -> T:
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


# The waits before the schema is applied again, when a statement of it waited past its
# ``lock_timeout`` or deadlocked with a running command: it gives way to that command.
SCHEMA_RETRY_WAITS = (2.0, 5.0, 10.0, 20.0)
_GIVES_WAY = (psycopg.errors.LockNotAvailable, psycopg.errors.DeadlockDetected)


def _ensure_schema(conn: psycopg.Connection[Any]) -> None:
    """``ensure_schema``, tried again after each of ``SCHEMA_RETRY_WAITS``; then
    ``LockNotGranted``."""
    for wait in SCHEMA_RETRY_WAITS:
        try:
            ensure_schema(conn, allowed_collation=ALLOW_COLLATION)
            return
        except _GIVES_WAY as exc:
            logger.warning(
                "The schema gave way to a running command (%s); trying again in %.0fs.",
                type(exc).__name__,
                wait,
            )
            _sleep(wait)
    try:
        ensure_schema(conn, allowed_collation=ALLOW_COLLATION)
    except _GIVES_WAY as exc:
        raise _not_granted("Applying the schema", exc) from exc


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
    except psycopg.Error as error:
        # no access to the server's own database: ours must already exist
        logger.info(
            "Did not create database %s: %s", DB_NAME, redacted(str(error).strip())
        )


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


# How long a read of a request may hold its connection past the deadline of its request
# before ``_reap_overdue`` takes it back (``LAWGRAPH_API_REQUEST_TIMEOUT_MS`` and this, in all).
OVERDUE_SECONDS = 30.0


class _Read:
    """One streamed read (``GraphStore.query``): the connection it took of its pool, its
    cursor, the request it reads for and that request's deadline (None outside one)."""

    def __init__(
        self,
        pool: ConnectionPool,
        conn: psycopg.Connection[Any],
        cancellation: Cancellation | None,
        deadline: float | None,
    ) -> None:
        self.pool = pool
        self.conn = conn
        self.cancellation = cancellation
        self.deadline = deadline
        self.name = f"lg_{uuid.uuid4().hex}"
        self.cursor: psycopg.ServerCursor[Any] | None = None
        self.statement = ""
        # whether it ended: by its reader, by ``_releaser``, or taken back (``reap``)
        self._ended = False
        self._ending = threading.Lock()
        self.reaped = False
        if deadline is not None:
            _request_reads[self.name] = self

    def open_cursor(self, statement: str) -> psycopg.ServerCursor[Any]:
        self.cursor = self.conn.cursor(name=self.name, row_factory=_rows)
        self.statement = statement
        _open_cursors[self.name] = statement
        return self.cursor

    def _claim(self) -> bool:
        """Whether the caller ends it: the first of its reader and ``reap`` does."""
        with self._ending:
            ended, self._ended = self._ended, True
        return not ended

    def end(self) -> None:
        """Close its cursor and give its connection back: the pool ends its transaction.
        Out of its request first, so no cancel of the request reaches the next read on
        it. Nothing when it ended already (``reap``)."""
        if not self._claim():
            return
        try:
            if self.cursor is not None:
                with contextlib.suppress(psycopg.Error):
                    self.cursor.close()
        finally:
            self._give_back()

    def reap(self) -> bool:
        """Take back the connection of a read its reader holds and no longer reads (no
        fetch of it runs now): closed, so the pool opens a new one in its place and the
        reader's next fetch fails, never reading on a connection given to another. False
        while a fetch runs (it ends at its ``statement_timeout``) or when it ended."""
        if not self.conn.lock.acquire(blocking=False):
            return False
        try:
            if not self._claim():
                return False
            self.reaped = True
            self.conn.close()
        finally:
            self.conn.lock.release()
        self._give_back()
        return True

    def _give_back(self) -> None:
        try:
            _open_cursors.pop(self.name, None)
            _request_reads.pop(self.name, None)
            if self.cancellation is not None:
                self.cancellation.end(self.conn)
        finally:
            self.pool.putconn(self.conn)


def _named_error(exc: psycopg.Error) -> Exception | None:
    """What a read raises for *exc* when the API knows it by name: a lock not granted, a
    server out of reach; None for any other error of the server, raised as it is."""
    if isinstance(exc, psycopg.errors.LockNotAvailable):
        return _not_granted("A read", exc)
    if isinstance(exc, psycopg.OperationalError) and _is_unreachable(exc):
        return _unavailable(exc)
    return None


# How long a health check waits for a connection of the pool (``GraphStore.ping``).
PING_WAIT = 5.0

# The reads of requests not yet ended, by the name of their cursor: ``_reap_overdue`` takes back
# the connection of one held past its request's deadline.
_request_reads: dict[str, _Read] = {}

# The reads their readers left before the last row, for ``_releaser`` to end.
_abandoned: queue.SimpleQueue[_Read] = queue.SimpleQueue()
_releaser: threading.Thread | None = None
_releaser_lock = threading.Lock()


def _abandon(read: _Read) -> None:
    """End *read*, left before its last row, on a thread of its own. Who leaves it may be
    the garbage collector, which closes a read in a reference cycle in whatever thread
    allocates, under whatever lock that thread holds: ending it there (under the lock of
    its request, which it takes too) once waited for ever for a lock its own thread held,
    and with it every collection of the process after it, so that every read left in a cycle
    kept its connection idle in a transaction until the pool had none (23 Oct). A
    ``SimpleQueue`` takes it without a lock."""
    _abandoned.put(read)


def _start_releaser() -> None:
    """Start ``_releaser`` once, before the first read (not from ``_abandon``)."""
    global _releaser
    if _releaser is not None:
        return
    with _releaser_lock:
        if _releaser is None:
            _releaser = threading.Thread(
                target=_end_abandoned, name="lawgraph-release", daemon=True
            )
            _releaser.start()


# How often ``_releaser`` looks for reads held past their request's deadline.
_REAP_EVERY = 1.0


def _end_abandoned() -> None:
    while True:
        with contextlib.suppress(queue.Empty):
            read = _abandoned.get(timeout=_REAP_EVERY)
            try:
                read.end()
            except Exception as exc:  # noqa: BLE001 — the next read is ended all the same
                logger.warning("A read left before its end was not ended: %s", exc)
        try:
            _reap_overdue()
        except Exception as exc:  # noqa: BLE001 — the releaser goes on
            logger.warning("A read held past its deadline was not taken back: %s", exc)


def _reap_overdue() -> None:
    """Take back the connection of every read of a request that its reader holds
    ``OVERDUE_SECONDS`` past the request's deadline: a reader that stopped without ending
    it (a thread that waits, a stream no one closes) would keep it idle in a transaction
    for ever, and eight of them drain the pool (23 Oct 19:50 UTC)."""
    for read in list(_request_reads.values()):
        if read.deadline is None or seconds_past(read.deadline) < OVERDUE_SECONDS:
            continue
        if read.reap():
            logger.warning(
                "A read of a request was held %.0f s past its deadline; its connection "
                "was taken back: %s",
                seconds_past(read.deadline),
                read.statement,
            )


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
def close_stores(database: str | None = None) -> None:
    """Close the stores still open, or those of *database*: their pools would go on
    reconnecting to a database that is dropped."""
    for store in list(_OPEN):
        if database is None or store.name == database:
            store.close()


def version_stamp(versions: dict[str, int], tables: Iterable[str] | None = None) -> str:
    """The stamp of *versions* (``GraphStore.table_versions``), or of *tables* among them: a
    table without a version (none of its rows was ever written) counts as 0."""
    names = sorted(set(versions) if tables is None else set(tables), key=str.encode)
    digest = hashlib.sha1(usedforsecurity=False)
    for name in names:
        digest.update(f"{name}:{versions.get(name, 0)};".encode())
    return digest.hexdigest()[:16]


class GraphStore:
    """The PostgreSQL database of the graph: connections, reads, upserts."""

    def __init__(self) -> None:
        self.name = DB_NAME
        _create_database_if_missing()
        self._background_pool: ConnectionPool | None = None
        self._background_lock = threading.Lock()
        try:
            # Every connection is opened at the start: no request waits for a new one.
            self.pool = self._open_pool("lawgraph", DB_POOL_SIZE)
        except psycopg.OperationalError as exc:
            raise _unavailable(exc) from exc
        try:
            with self.pool.connection() as conn:
                _ensure_schema(conn)
        except BaseException as exc:
            self.pool.close()  # its workers would go on connecting
            if isinstance(exc, psycopg.OperationalError | PoolTimeout):
                raise _unavailable(exc) from exc
            raise

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

    def _open_pool(self, name: str, size: int) -> ConnectionPool:
        """A pool of *size* connections to the database, every one opened at once."""
        return ConnectionPool(
            _server_url(self.name),
            min_size=size,
            max_size=size,
            open=True,
            timeout=60,
            name=name,
            configure=_configure,
            kwargs={"application_name": APPLICATION_NAME},
        )

    def close(self) -> None:
        _OPEN.discard(self)
        self.pool.close()
        if self._background_pool is not None:
            self._background_pool.close()
        self._payload_io.shutdown(wait=False)

    def _reading_pool(self) -> ConnectionPool:
        """The pool a read of the current context takes its connection from."""
        if not reads_in_background():
            return self.pool
        with self._background_lock:
            if self._background_pool is None:
                self._background_pool = self._open_pool(
                    "lawgraph-background", DB_BACKGROUND_POOL_SIZE
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
        """``DatabaseUnavailable`` when the database cannot be reached, or no connection
        of the pool comes free within ``PING_WAIT`` (or what the request has left): a
        health check answers at once, also when every connection is held."""
        left = read_time_left()
        wait = PING_WAIT if left is None else min(PING_WAIT, left)
        try:
            with self.pool.connection(timeout=wait) as conn:
                conn.execute("SELECT 1")
        except (psycopg.OperationalError, PoolTimeout) as exc:
            raise _unavailable(exc) from exc

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

    def table_versions(self) -> dict[str, int]:
        """The version of every table the API serves (``lg_data_version``): one that a
        statement which changed rows of that table raised, and not a retrieve."""
        rows = self.query(
            "SELECT collection, version FROM lg_data_version"
            " WHERE collection = ANY(%(served)s)",
            {"served": list(_SERVED)},
        )
        return {row["collection"]: int(row["version"]) for row in rows}

    def data_version(self, tables: Iterable[str] | None = None) -> str:
        """A stamp of what the API serves, or of *tables* alone: it changes with every
        statement that changes one of those tables, and not with a retrieve."""
        return version_stamp(self.table_versions(), tables)

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

    def analyze_changed(self) -> None:
        """``ANALYZE`` of every table with rows changed since its last analyze
        (``pg_stat_user_tables``): after a run ``--since``, which changes a few tables a
        little; autovacuum keeps the visibility map."""
        with self.pool.connection() as conn:
            conn.autocommit = True
            try:
                tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT relname FROM pg_stat_user_tables"
                        " WHERE schemaname = current_schema() AND n_mod_since_analyze > 0"
                    )
                ]
                for table in tables:
                    conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
            finally:
                conn.autocommit = False

    # ── Size ───────────────────────────────────────────────────────────────────

    def database_size(self) -> int:
        """The size of the database on disk, in bytes."""
        return int(next(self.query("SELECT pg_database_size(current_database())")))

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
        index_order: bool = False,
    ) -> Iterator[Any]:
        """Run a statement; one that only reads streams its result.

        A row is the value of the one column a query selects (a document, a count, a key),
        or a dict of its columns. A read runs on a server-side cursor, so ``batch_size``
        rows are in flight however large the result (41,000 BWB toestanden of 80 KB are
        3 GB). A result of fewer than ``batch_size`` rows gives its connection back before
        its first row; a larger one holds it until the reader stops, however it stops (one
        left before its last row is given back on a thread of its own, ``_abandon``; one a
        request holds ``OVERDUE_SECONDS`` past its deadline is taken back,
        ``_reap_overdue``). A statement that writes runs to the end at once (``execute``).

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

        ``index_order`` keeps the planner from a bitmap scan (``SET LOCAL
        enable_bitmapscan = off``, for this statement alone): for a statement that reads a
        page of the edges of each node in the order of an index (a level of paths, a page of
        a node's neighbours). The planner takes the edges of a node for ten, and then finds
        a bitmap scan of them all, sorted, as cheap as the first ten in order; of a hub it
        reads every edge and its row (689,000 for the articles of Sr).
        """
        if _WRITES.search(statement_text(statement)):
            return iter(self.execute(statement, params))
        return self._stream(
            statement, params, batch_size, (indexes_only, hash_joins, index_order)
        )

    def _stream(
        self,
        statement: Statement,
        params: Params,
        batch_size: int,
        brakes: tuple[bool, bool, bool] = (False, False, False),
    ) -> Iterator[Any]:
        budget = read_budget_ms()
        _start_releaser()
        # a request waits for a connection of the pool no longer than it has left; a
        # computation in the background waits its turn
        pool = self._reading_pool()
        wait = budget / 1000 if reads_in_background() else min(60.0, budget / 1000)
        try:
            conn = pool.getconn(timeout=wait)
        except PoolTimeout as exc:
            raise ReadTimedOut(
                "No connection of the pool came free before the deadline of the request."
            ) from exc
        except psycopg.Error as exc:
            if (named := _named_error(exc)) is None:
                raise
            raise named from exc
        read = _Read(pool, conn, current_cancellation(), read_deadline())
        try:
            yield from self._read(read, statement, params, batch_size, budget, brakes)
        except GeneratorExit:
            _abandon(read)
            raise
        except psycopg.Error as exc:
            read.end()
            if read.reaped:
                raise ReadTimedOut(
                    "A read was held past the deadline of its request; its connection "
                    "was taken back."
                ) from exc
            if (named := _named_error(exc)) is None:
                raise
            raise named from exc
        except BaseException:
            read.end()
            raise
        read.end()

    def _read(
        self,
        read: _Read,
        statement: Statement,
        params: Params,
        batch_size: int,
        budget: int,
        brakes: tuple[bool, bool, bool],
    ) -> Iterator[Any]:
        conn = read.conn
        if read.cancellation is not None:
            read.cancellation.start(conn)
        # a ceiling for each statement (the DECLARE, every FETCH), not for the stream; in
        # a request of the API no more than the request has left
        conn.execute(f"SET LOCAL statement_timeout = {budget}")
        if read.deadline is not None:
            # a read of a request whose reader stops holds no transaction (and its locks)
            # on the server past its deadline either, whatever the process does
            idle = budget + int(OVERDUE_SECONDS * 1000)
            conn.execute(f"SET LOCAL idle_in_transaction_session_timeout = {idle}")
        indexes_only, hash_joins, index_order = brakes
        if indexes_only:
            # The planner prices detoasting at nothing (see ``query``).
            conn.execute("SET LOCAL enable_seqscan = off")
        if hash_joins:
            # The planner cannot count the rows of the sets it joins (see ``query``).
            conn.execute("SET LOCAL enable_nestloop = off")
        if index_order:
            # A page of each node's edges in index order, not all of them sorted (``query``).
            conn.execute("SET LOCAL enable_bitmapscan = off")
        text = re.sub(r"\s+", " ", statement_text(statement)).strip()
        cursor = read.open_cursor(text[:300])
        try:
            cursor.execute(_query(statement), params)
            while True:
                rows = cursor.fetchmany(batch_size)
                if len(rows) < batch_size:
                    # every row is here: the connection goes back before the reader sees
                    # one, so a reader that holds the read and reads again (the one row of
                    # ``next(iter(rows))``, then the nodes it names) needs one connection,
                    # not two (23 Oct 19:50 UTC: requests that each held one and waited
                    # for a second drained the pool)
                    read.end()
                    yield from rows
                    return
                yield from rows
        except psycopg.errors.QueryCanceled as exc:
            if read.cancellation is not None and read.cancellation.cancelled:
                raise RequestCancelled(
                    f"The client went away; its read was cancelled: {text[:300]}"
                ) from exc
            raise ReadTimedOut(
                f"A read ran for over {budget / 1000:.0f} s (LAWGRAPH_READ_TIMEOUT_MS, "
                f"or what the request had left) and was cancelled: {text[:300]}"
            ) from exc

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

        def run(conn: psycopg.Connection[Any]) -> None:
            for statement, params in statements:
                conn.execute(_query(statement), params)

        self.in_transaction("statements together", run)

    def in_transaction[T](
        self, what: str, write: Callable[[psycopg.Connection[Any]], T]
    ) -> T:
        """Run *write* on a connection in one transaction, each statement under the ceiling
        of a write: for a write that needs the connection itself (a table built aside and
        swapped in, the rows a statement changed). A reader sees all of it or none. Run
        again when the database was unreachable; *what* names it in the log."""

        def run() -> T:
            with self.pool.connection() as conn, conn.transaction():
                conn.execute(f"SET LOCAL statement_timeout = {WRITE_TIMEOUT_MS}")
                return write(conn)

        return _retry_write(what, run)

    # ── Raw sources ────────────────────────────────────────────────────────────

    def insert_raw_sources(self, docs: list[dict[str, Any]]) -> None:
        """Upsert raw source documents (see ``raw_source_doc``).

        A text payload is written to the payload store first (``_put_payloads``). A stored
        document with the same key is replaced. Each document gets ``changed_at``: the
        ``fetched_at`` of the first fetch of its content. A document fetched again as it was
        (the same payload, its SHA-1 for a text, and meta) keeps the stored one, so a run
        ``--since`` of the phases after retrieve passes it by (``queries/raw.CHANGED_SINCE``).
        Written whole or raises, as does a failure of the payload store.
        """
        if not docs:
            return
        stored = _last_per_key(self._put_payloads(docs))
        rows = [
            {"key": d["key"], "doc": {k: v for k, v in d.items() if k != "key"}}
            for d in stored
        ]
        kept = {
            row["key"]: row["changed_at"]
            for row in self.query(
                f"""
                SELECT r.key, coalesce(lg_str(o.doc -> 'changed_at'), o.fetched_at)
                       AS changed_at
                FROM json_to_recordset(%(rows)s::json) AS r(key text, doc json)
                JOIN {COLLECTION_RAW_SOURCES} o ON o.key = r.key
                WHERE o.doc::jsonb - '{{fetched_at,changed_at}}'::text[]
                    = r.doc::jsonb - '{{fetched_at,changed_at}}'::text[]
                """,
                {"rows": Json(rows)},
            )
        }
        for row in rows:
            doc = row["doc"]
            doc["changed_at"] = kept.get(row["key"]) or doc.get("fetched_at")
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
            return {
                **stored,
                "payload_ref": name,
                "payload_chars": len(text),
                "payload_sha1": hashlib.sha1(text.encode()).hexdigest(),
            }

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
        ``props`` merged one level deep with its keys in order (``lg_update``). "Would
        not change" is ``lg_same``: a prop set to null is the same as a missing one, so an
        update that only adds nulls is not written. A key that occurs more than once is
        applied in its order, a statement per occurrence.
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
        return self._upsert_rounds(statement, rows, "id")

    def _upsert_rounds(
        self,
        statement: Statement,
        rows: list[dict[str, Any]],
        key: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        answer = self.execute_in_rounds(statement, rows, key, params)
        created = sum(1 for was_new in answer if was_new)
        return created, len(answer) - created

    def execute_in_rounds(
        self,
        statement: Statement,
        rows: list[dict[str, Any]],
        key: str,
        params: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Run *statement* once per round of *rows* in which every *key* occurs once (one
        statement cannot write a row twice): the first occurrence of each key, then the
        second, in the order of *rows*. A round is the parameter ``rows`` (json), beside
        *params*; the rows the statements return, of every round."""
        answer: list[Any] = []
        for batch in _rounds(rows, key):
            answer += self.execute(statement, {**(params or {}), "rows": Json(batch)})
        return answer

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
        props: dict[str, Any],
    ) -> Node | None:
        """Return the node if it exists, otherwise insert a minimal stub.

        Used by semantic pipelines to keep the graph connected when a
        referenced node hasn't been fully imported yet (e.g., a cited ECLI
        that isn't in the corpus). The stub carries ``props.stub=True`` so
        the frontend can surface it as a pending import.
        """
        table = self._node_table(collection)
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
            "type": TYPE_OF_COLLECTION[collection].value,
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
        the new edge has none) and ``meta`` is merged one level deep, into the stored keys
        the model of the relation has (``META_KEYS``): a key an earlier writer left that
        the model lacks goes, the keys of two writers of one edge stay. ``created_at`` and
        every other attribute stay. An edge the update would not change is not written or
        counted; in ``meta`` an attribute set to null is the same as a missing one
        (``lg_same``).
        """
        # the stored meta, without the keys the model of the relation lacks
        kept = """(SELECT json_object_agg(m.key, m.value)
                FROM json_each(CASE WHEN json_typeof(t.doc -> 'meta') = 'object'
                                    THEN t.doc -> 'meta' END) AS m(key, value)
                WHERE m.key = ANY((SELECT a.keys FROM allowed a
                                   WHERE a.relation = t.relation)::text[]))"""
        statement = sql.SQL(
            f"""
            WITH allowed AS MATERIALIZED (
                SELECT a.key AS relation, ARRAY(SELECT json_array_elements_text(a.value))
                    AS keys
                FROM json_each(%(meta_keys)s::json) AS a
            )
            INSERT INTO {COLLECTION_EDGES} AS t (key, from_id, to_id, doc)
            SELECT e.key, e.from_id, e.to_id, e.doc
            FROM json_to_recordset(%(rows)s::json)
                AS e(key text, from_id text, to_id text, doc json)
            ORDER BY e.key
            ON CONFLICT (key) DO UPDATE SET doc = lg_update(t.doc, json_build_object(
                'confidence', EXCLUDED.doc -> 'confidence',
                'source', EXCLUDED.doc -> 'source',
                'status', EXCLUDED.doc -> 'status',
                'meta', lg_update({kept}, EXCLUDED.doc -> 'meta')
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
                lg_update({kept}, EXCLUDED.doc -> 'meta')::jsonb
            )
            RETURNING (xmax = 0) AS created
            """
        )
        rows = [split_edge(doc) for doc in docs]
        return self._upsert_rounds(statement, rows, "key", {"meta_keys": _META_KEYS})


def statement_text(statement: Statement) -> str:
    """The text of *statement*, as the server receives it."""
    if isinstance(statement, str):
        return statement
    return statement.as_string(None)


def _query(statement: Statement) -> sql.SQL | sql.Composed:
    if isinstance(statement, str):
        return sql.SQL(statement)
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
    return list({doc["key"]: doc for doc in docs}.values())
