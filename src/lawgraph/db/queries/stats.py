"""Database stats query helpers."""

from __future__ import annotations

import datetime as dt
from typing import Any

from psycopg import sql

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    SOURCE_BWB,
    SOURCE_EERSTEKAMER,
    SOURCE_RECHTSPRAAK,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
    SOURCE_TK,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.cache import TTLCache
from lawgraph.db import GraphStore

_NODE_COLLECTIONS = (
    COLLECTION_INSTRUMENTS,
    COLLECTION_ARTICLES,
    COLLECTION_JUDGMENTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_CASES,
    COLLECTION_DOSSIERS,
    COLLECTION_ACTIVITIES,
    COLLECTION_DECISIONS,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_MEMBERS,
    COLLECTION_CABINETS,
)


def _count_by(store: GraphStore, table: str, column: str) -> dict[str, int]:
    """Number of rows of *table* per value of *column* (``unknown`` when null or empty),
    in the order of the values."""
    statement = sql.SQL(
        "SELECT {column} AS value, count(*)::int AS n FROM {table}"
        " GROUP BY {column} ORDER BY {column} NULLS FIRST"
    ).format(column=sql.Identifier(column), table=sql.Identifier(table))
    return {row["value"] or "unknown": row["n"] for row in store.query(statement)}


# The collections a citation can make a stub in: a node known only because something
# refers to it (``props.stub``), without a text of its own.
_STUB_COLLECTIONS = (COLLECTION_INSTRUMENTS, COLLECTION_ARTICLES, COLLECTION_JUDGMENTS)


def _stub_count(store: GraphStore, collection: str) -> int:
    statement = sql.SQL("SELECT count(*)::int FROM {} WHERE stub IS TRUE").format(
        sql.Identifier(collection)
    )
    return int(next(store.query(statement), 0))


def _replaced_count(store: GraphStore) -> int:
    """The publications of a decision that another loaded publication replaces (``SAME_AS``
    the one kept, ``semantic rechtspraak-duplicates``): the lists show the decision once, by
    the one kept. A stub is never one."""
    return int(
        next(
            store.query(
                "SELECT count(*)::int FROM judgments WHERE same_as IS NOT NULL"
            ),
            0,
        )
    )


def _publication_count(store: GraphStore) -> int:
    return int(
        next(
            store.query(
                "SELECT count(*)::int FROM instruments WHERE kind = %(kind)s",
                {"kind": KIND_PUBLICATION},
            ),
            0,
        )
    )


def get_db_stats(store: GraphStore) -> dict[str, Any]:
    """Document counts per collection (without stubs, and a decision published twice
    once), stub counts, the replaced publications, edge counts per relation, and source
    breakdowns."""
    stubs = {name: _stub_count(store, name) for name in _STUB_COLLECTIONS}
    publications = _publication_count(store)
    replaced = {COLLECTION_JUDGMENTS: _replaced_count(store)}
    nodes = {
        name: store.count(name) - stubs.get(name, 0) - replaced.get(name, 0)
        for name in _NODE_COLLECTIONS
    }
    # an instrument node of a publication (Stb. 2019, 33) is no regulation: counted apart
    nodes[COLLECTION_INSTRUMENTS] -= publications
    nodes["publications"] = publications
    return {
        "nodes": nodes,
        "stubs": stubs,
        "replaced": replaced,
        "edges": {
            "total": store.count(COLLECTION_EDGES),
            "by_relation": _count_by(store, COLLECTION_EDGES, "relation"),
        },
        "by_source": {
            "judgments": _count_by(store, COLLECTION_JUDGMENTS, "source"),
            "documents": _count_by(store, COLLECTION_DOCUMENTS, "source"),
        },
        "instruments": {
            "by_kind": _count_by(store, COLLECTION_INSTRUMENTS, "kind"),
            "by_jurisdiction": _count_by(store, COLLECTION_INSTRUMENTS, "jurisdiction"),
        },
    }


def get_judgment_coverage(store: GraphStore) -> dict[str, Any]:
    """The judgments the graph holds (not the stubs of judgments it only knows as cited),
    per source, court tier and court, with the first and last date of each; how many
    stubs there are; and per court the publications another loaded one replaces
    (``replaced``), which the lists leave out. Every field the per-court count reads is in
    one index of ``db/schema.py``, so it counts without reading a judgment; the replaced
    publications, a few, are read by their own index."""
    group = "source, tier, court_code"
    order = "source NULLS FIRST, tier NULLS FIRST, court_code NULLS FIRST"
    courts = f"""
        SELECT source, tier, court_code, max(court) AS court, count(*)::int AS count,
               min(date_eff) AS first_date, max(date_eff) AS last_date
        FROM judgments WHERE stub = false
        GROUP BY {group} ORDER BY {order}
        """
    replaced = f"""
        SELECT source, tier, court_code, count(*)::int AS count
        FROM judgments WHERE same_as IS NOT NULL
        GROUP BY {group} ORDER BY {order}
        """
    return {
        "courts": list(store.query(courts)),
        "stubs": _stub_count(store, COLLECTION_JUDGMENTS),
        "replaced": list(store.query(replaced)),
    }


# The newest dated record of a source, on or before today: what the graph holds of it, read
# from one index each. A source without an entry has only its last retrieve.
_NEWEST: dict[str, str] = {
    SOURCE_TK: f"""
        SELECT date FROM documents WHERE '{CHAMBER_TK}' = ANY(labels) AND date <= %(today)s
        ORDER BY date DESC LIMIT 1""",
    SOURCE_EERSTEKAMER: f"""
        SELECT date FROM documents WHERE '{CHAMBER_EK}' = ANY(labels) AND date <= %(today)s
        ORDER BY date DESC LIMIT 1""",
    SOURCE_RECHTSPRAAK: """
        SELECT date_eff FROM judgments WHERE date_eff <= %(today)s
        ORDER BY date_eff DESC LIMIT 1""",
    SOURCE_STAATSBLAD: f"""
        SELECT date_published FROM instruments
        WHERE kind = '{KIND_PUBLICATION}' AND lg_str(props -> 'publication_kind') = 'Stb'
          AND date_published <= %(today)s
        ORDER BY date_published DESC LIMIT 1""",
    SOURCE_STAATSCOURANT: f"""
        SELECT date_published FROM instruments
        WHERE kind = '{KIND_PUBLICATION}' AND lg_str(props -> 'publication_kind') = 'Stcrt'
          AND date_published <= %(today)s
        ORDER BY date_published DESC LIMIT 1""",
    SOURCE_BWB: """
        SELECT valid_from FROM instrument_versions WHERE valid_from <= %(today)s
        ORDER BY valid_from DESC LIMIT 1""",
}


_data_as_of_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=4, ttl=60.0)


def cached_data_as_of(store: GraphStore) -> dict[str, Any]:
    """``get_data_as_of``, read at most once a minute per database (``/api/stats`` and every
    page of the feed carry it)."""
    key = store.name
    hit = _data_as_of_cache.get(key)
    if isinstance(hit, dict):
        return hit
    value = get_data_as_of(store)
    _data_as_of_cache.set(key, value)
    return value


# The newest fetch per source, a source without one first. The sources are walked one by
# one through the index, each from the one before (a skip scan): the records themselves
# are not read, however many millions there are.
_RETRIEVED_AT = """
    WITH RECURSIVE sources AS (
        (SELECT source FROM raw_sources WHERE source IS NOT NULL ORDER BY source LIMIT 1)
        UNION ALL
        SELECT (
            SELECT r.source FROM raw_sources r
            WHERE r.source > s.source ORDER BY r.source LIMIT 1
        )
        FROM sources s WHERE s.source IS NOT NULL
    )
    SELECT source, retrieved_at FROM (
        SELECT NULL::text AS source, max(fetched_at) AS retrieved_at
        FROM raw_sources WHERE source IS NULL HAVING count(*) > 0
        UNION ALL
        SELECT s.source,
               (SELECT max(r.fetched_at) FROM raw_sources r WHERE r.source = s.source)
        FROM sources s WHERE s.source IS NOT NULL
    ) found
    ORDER BY source NULLS FIRST
"""


def get_data_as_of(store: GraphStore, *, today: str | None = None) -> dict[str, Any]:
    """Per source the graph holds records of: ``retrieved_at``, the moment its newest raw
    record was fetched (the last retrieve that brought something), and ``newest``, the date
    of its newest dated record on or before *today* (null for a source without one)."""
    today = today or dt.date.today().isoformat()
    rows = store.query(_RETRIEVED_AT)
    result: dict[str, Any] = {}
    for row in rows:
        newest = None
        if row["source"] in _NEWEST:
            newest = next(store.query(_NEWEST[row["source"]], {"today": today}), None)
        result[row["source"]] = {"retrieved_at": row["retrieved_at"], "newest": newest}
    return result
