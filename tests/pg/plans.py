"""What a test of the queries reads of the database: the statements a store runs, the plans
PostgreSQL makes for them, and a cache whose pool is busy."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, Literal, NamedTuple, cast

import pytest
from psycopg import sql

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.store import Statement, _query, statement_text


class Call(NamedTuple):
    """One statement a store ran: the statement, its parameters, and the other arguments
    of the call (``indexes_only`` and the like of ``query``; ``batch_size`` and the brakes
    of ``_stream``, by position)."""

    statement: Statement
    params: Any
    args: tuple[Any, ...]
    options: dict[str, Any]

    @property
    def text(self) -> str:
        return statement_text(self.statement)


def recorded(
    store: GraphStore,
    monkeypatch: pytest.MonkeyPatch,
    method: Literal["query", "_stream"] = "query",
) -> list[Call]:
    """The statements *store* runs through *method* from now on, in order, until the test
    ends. ``_stream`` sees the reads alone, past a cache of ``query`` and its writes."""
    calls: list[Call] = []
    run = getattr(store, method)

    def recording(
        statement: Statement, params: Any = None, *args: Any, **options: Any
    ) -> Any:
        calls.append(Call(statement, params, args, options))
        return run(statement, params, *args, **options)

    monkeypatch.setattr(store, method, recording)
    return calls


def explain(
    store: GraphStore,
    statement: Statement,
    params: Any = None,
    *,
    disable: Iterable[str] = (),
    analyze: bool = False,
) -> dict[str, Any]:
    """The plan of *statement* (its top node, ``EXPLAIN (FORMAT JSON)``), with each planner
    method of *disable* off for it (``seqscan`` sets ``enable_seqscan = off``). With
    *analyze* the statement runs, and the plan has what each node read."""
    options = sql.SQL("ANALYZE, FORMAT JSON" if analyze else "FORMAT JSON")
    with store.pool.connection() as conn, conn.transaction():
        for method in disable:
            conn.execute(
                sql.SQL("SET LOCAL {} = off").format(sql.Identifier(f"enable_{method}"))
            )
        row = conn.execute(
            sql.SQL("EXPLAIN ({}) {}").format(options, _query(statement)), params
        ).fetchone()
    assert row is not None
    return cast(dict[str, Any], row[0][0]["Plan"])


def plan_nodes(plan: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every node of *plan*, the top one first, depth first."""
    yield plan
    for child in plan.get("Plans", []):
        yield from plan_nodes(child)


@contextmanager
def pool_busy() -> Iterator[None]:
    """Every worker of the pool of the cache busy, as with a warm-up and the counts of the
    feed, until the block ends."""
    release = threading.Event()
    started = threading.Barrier(version_cache.WORKERS + 1)

    def hold() -> None:
        started.wait()
        release.wait(60)

    for _ in range(version_cache.WORKERS):
        version_cache._pool.submit(hold)
    started.wait(10)
    try:
        yield
    finally:
        release.set()


_SCANS = ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan")
# The conditions of a whole list hold for nearly every row, they do not find rows: a test
# of a flag (``same_as IS NULL``, ``stub IS NOT TRUE``) and every instrument but the
# publications.
_LIST_TEST = re.compile(
    r"^(\w+\.)?\w+ IS (NOT )?(NULL|TRUE|FALSE)$"
    r"|^(\w+\.)?kind IS DISTINCT FROM 'publicatie'::text$"
)


def _flags_only(condition: str) -> bool:
    if not condition:
        return True
    parts = re.split(r"\s+AND\s+", condition)
    return all(_LIST_TEST.match(part.strip(" ()")) for part in parts)


def _narrowed(node: dict[str, Any], partial: frozenset[str]) -> bool:
    """Whether a condition of the scan, or the condition of the partial index it reads
    (``WHERE semantic_type IS NOT NULL``), finds its rows."""
    indexes = {node.get("Index Name")} | {
        child.get("Index Name") for child in node.get("Plans", [])
    }
    if indexes & partial:
        return True
    condition = node.get("Index Cond") or node.get("Recheck Cond")
    if not condition:
        return False
    return not _flags_only(condition)


def _skipped(
    node: dict[str, Any], leading: dict[str, str], partial: frozenset[str]
) -> bool:
    """Whether the scan's condition leaves out the first column of its index: a skip scan
    over every value of it (``to_id`` through ``(created_at, to_id)`` reads the whole index
    on the full database). A partial index holds only the rows of its condition."""
    if node.get("Index Name") in partial:
        return False
    column = leading.get(node.get("Index Name") or "")
    condition = node.get("Index Cond") or ""
    return (
        bool(column and condition)
        and not _flags_only(condition)
        and not re.search(rf"\b{column}\b", condition)
    )


# Nodes that read all of their input before they give a row: below them a limit above
# stops nothing early.
READS_ALL = ("Sort", "Incremental Sort", "Hash", "Materialize", "Aggregate", "Unique")


def plan_faults(
    node: dict[str, Any],
    partial: frozenset[str] = frozenset(),
    limited: bool = False,
    grouped: bool = False,
    leading: dict[str, str] | None = None,
) -> list[str]:
    """The whole reads in the plan *node*: a sequential scan, and a scan that nothing
    narrows, unless it only tests flags and is either cut short by a limit (a page read
    in the order of an index) or counted (a total or the facets of a list)."""
    kind = node["Node Type"]
    if kind in READS_ALL:
        limited = False
    if kind == "Limit":
        limited = True
    found = []
    if kind == "Seq Scan":
        found.append(f"Seq Scan on {node.get('Relation Name')}")
    elif kind in _SCANS and _skipped(node, leading or {}, partial):
        found.append(
            f"{kind} on {node.get('Relation Name')} skips the first column of"
            f" {node.get('Index Name')}"
        )
    elif kind in _SCANS and not _narrowed(node, partial):
        filtered = node.get("Filter", "")
        if not (_flags_only(filtered) and (limited or grouped)):
            found.append(
                f"{kind} on {node.get('Relation Name')} read whole"
                + (f", filtered by {filtered}" if filtered else "")
            )
    for child in node.get("Plans", []):
        found += plan_faults(
            child, partial, limited, grouped or kind == "Aggregate", leading
        )
    return found
