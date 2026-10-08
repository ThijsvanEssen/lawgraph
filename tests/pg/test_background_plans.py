"""What the API computes in the background (the warm-up, the answers it keeps per data
version or for hours, the heat) reads no large table whole, on data shaped like the real:
judgments that nearly all come from Rechtspraak and hold an area of law, papers of the
Tweede Kamer of this year, and edges that nearly all are recent (a database built weeks
ago). A condition that every row meets finds nothing, so the check is the share of a table
the planner expects a statement to read (its scans of the table together: the kinds of the
feed each read a part), not whether an index is used. What reads a table whole on purpose
is named below, with why.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from psycopg import sql

from lawgraph.db import GraphStore
from lawgraph.db.store import _query, _text
from tests.pg.test_query_plans import _seed

LARGE = ("judgments", "articles", "documents", "edges")
JUDGMENTS = 20_000
DOCUMENTS = 20_000
EDGES = 100_000
# A scan the planner expects to read this share of a large table reads it whole.
WHOLE = 0.5

# Statements that read a large table whole on purpose: name, pattern, why.
WHOLE_BY_DESIGN = [
    (
        "search statistics, rare fields",
        # never the summaries: those are what made the whole count take minutes
        re.compile(r"^SELECT count\(\*\)::float AS n, (?!.*summary).*FROM \w+ doc$"),
        "a field too rare for the sample (the names of a judgment) is measured over the"
        " table without its large values, once every 6 hours in the background",
    ),
    (
        "heat of the whole graph",
        re.compile(r"WITH counted AS MATERIALIZED"),
        "every window in one pass over the edges, once a day in the background",
    ),
    (
        "counts of /api/stats and the coverage",
        re.compile(
            r'^SELECT (count\(\*\)::int FROM "\w+"'
            r'|"\w+" AS value, count\(\*\)::int AS n FROM "\w+" GROUP BY'
            r"|\(SELECT count\(\*\) FROM judgments\)"
            r"|source, tier, court_code, max\(court\))"
        ),
        "a count of a whole table read from an index alone (no row of the table), once"
        " per data version in the background",
    ),
    (
        "facets and total of the list of judgments and of an area of law",
        re.compile(
            r"FROM judgments j .*WHERE j\.stub IS NOT TRUE AND j\.same_as IS NULL"
            r"( AND j\.source = %\(source\)s)?"
            r"( AND lg_subject_areas\(j\.subjects\) @> ARRAY\[%\(subject_area\)s\]::text\[\])?"
            r"( GROUP BY| \) subjects|$)"
        ),
        "the counts of the list the front end shows first (the judgments of Rechtspraak)"
        " and of its largest areas of law cover every judgment of them; kept an hour,"
        " computed in the background",
    ),
]


def _shaped_like_the_real(store: GraphStore) -> None:
    store.execute(
        "INSERT INTO judgments (id, type, props)"
        " SELECT 'judgments/real_' || n, 'judgment', json_build_object("
        " 'source', 'rechtspraak', 'subjects', json_build_array('Bestuursrecht'),"
        " 'stub', false, 'tier', 'rechtbank', 'court_kind', 'rechtbank',"
        " 'date_eff', '2020-01-01', 'summary', 'Beroep ongegrond.')"
        f" FROM generate_series(1, {JUDGMENTS}) n"
    )
    store.execute(
        "INSERT INTO documents (id, type, labels, props)"
        " SELECT 'documents/real_' || n, 'document', ARRAY['TK'], json_build_object("
        " 'kind', CASE n % 3 WHEN 0 THEN 'Motie' WHEN 1 THEN 'Amendement'"
        " ELSE 'Brief regering' END,"
        " 'date', '2026-0' || (n % 9 + 1) || '-15', 'title', 'Motie ' || n,"
        " 'dossier_numbers', json_build_array('36600'))"
        f" FROM generate_series(1, {DOCUMENTS}) n"
    )
    store.execute(
        "INSERT INTO edges (key, from_id, to_id, doc)"
        " SELECT 'real_' || n, 'judgments/real_' || (n % 20000 + 1),"
        " 'articles/filler_' || (n % 9967 + 1),"
        " json_build_object('relation', 'REFERS_TO', 'created_at', now()::text)"
        f" FROM generate_series(1, {EDGES}) n"
    )


# Nodes that read all of their input before they give a row: below them a limit above
# stops nothing early.
_READS_ALL = ("Sort", "Incremental Sort", "Hash", "Materialize", "Aggregate", "Unique")


def _scans(
    plan: dict[str, Any],
    rows: dict[str, float],
    limited: bool = False,
    processes: int = 1,
) -> list[tuple[str, float]]:
    """Per scan of a large table in *plan* the table and the rows the planner expects it
    to read, unless a limit above stops it early (a page read in the order of an index).
    Below a ``Gather`` the rows of a scan are those of each of its processes."""
    kind = plan["Node Type"]
    if kind in ("Gather", "Gather Merge"):
        processes = plan.get("Workers Planned", 0) + 1
    if kind in _READS_ALL:
        limited = False
    if kind == "Limit":
        limited = True
    found = []
    table = plan.get("Relation Name")
    if (
        table in rows
        and not limited
        and kind != "Sample Scan"
        and "Scan" in kind
        and "Bitmap Index" not in kind
    ):
        found.append((table, plan.get("Plan Rows", 0) * processes))
    for child in plan.get("Plans", []):
        found += _scans(child, rows, limited, processes)
    return found


def _whole_reads(plan: dict[str, Any], rows: dict[str, float]) -> list[str]:
    """The large tables the scans of *plan* together read at least ``WHOLE`` of."""
    read: dict[str, float] = {}
    for table, expected in _scans(plan, rows):
        read[table] = read.get(table, 0.0) + expected
    return [
        f"{table}: {expected:.0f} of {rows[table]:.0f} rows"
        for table, expected in sorted(read.items())
        if expected >= WHOLE * rows[table]
    ]


def test_the_background_reads_no_large_table_whole(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from lawgraph.api import warm
    from lawgraph.api.routes.nodes import heat_counts
    from lawgraph.db.queries import _bm25

    # the large tables sampled for the statistics of the search, as the real ones are
    monkeypatch.setattr(_bm25, "SAMPLE_ROWS", 2_000)
    # terms searched often enough for the warm-up: one it searches, and one most judgments
    # hold, which it leaves, as its search would rank them all
    import datetime as dt
    from collections import Counter

    from lawgraph.core import search_stats

    search_stats.merge_day(
        tmp_path,
        dt.date.today().isoformat(),
        Counter({"beroep": 9, "verblijfsvergunning": 7}),
    )
    monkeypatch.setattr(warm, "SEARCH_STATS_DIR", tmp_path)

    _seed(store)
    _shaped_like_the_real(store)
    store.vacuum_analyze()
    captured: list[tuple[Any, Any, dict[str, Any]]] = []
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        captured.append((statement, params, options))
        return query(statement, params, **options)

    store.query = recording  # type: ignore[method-assign]
    try:
        warm.warm_up(store)
        heat_counts(store)
    finally:
        store.query = query  # type: ignore[method-assign]
    assert len(captured) > 20  # the warm-up ran its parts
    assert any("AS rank FROM" in " ".join(_text(c[0]).split()) for c in captured)

    faults, named = [], set()
    with store.pool.connection() as conn:
        rows = dict(
            conn.execute(
                "SELECT relname::text, reltuples::float FROM pg_class"
                " WHERE relname = ANY(%(large)s)",
                {"large": list(LARGE)},
            ).fetchall()
        )
        for statement, params, options in captured:
            text = " ".join(_text(statement).split())
            # as the store runs it: a search reads with its indexes only
            seqscan = "off" if options.get("indexes_only") else "on"
            conn.execute(f"SET enable_seqscan = {seqscan}")
            design = [name for name, p, _ in WHOLE_BY_DESIGN if p.search(text)]
            explain = sql.SQL("EXPLAIN (FORMAT JSON) ") + _query(statement)
            (plan,) = conn.execute(explain, params).fetchone()  # type: ignore[misc]
            found = _whole_reads(plan[0]["Plan"], rows)
            if found and design:
                named.update(design)
            elif found:
                faults.append(f"{'; '.join(found)}\n    {text[:300]}")
    assert not faults, "\n".join(sorted(set(faults)))
    # each exception still names a statement that reads a table whole
    assert named == {name for name, _, _ in WHOLE_BY_DESIGN}, named
