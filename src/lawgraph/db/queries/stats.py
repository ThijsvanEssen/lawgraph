"""Database stats query helpers."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

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
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    COLLECTION_RAW_SOURCES,
    SOURCE_BWB,
    SOURCE_EERSTEKAMER,
    SOURCE_RECHTSPRAAK,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
    SOURCE_TK,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.cache import TTLCache
from lawgraph.db import ArangoStore

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


def _count_by(store: ArangoStore, collection: str, field: str) -> dict[str, int]:
    """Number of documents in *collection* per value of *field* (``unknown`` when null)."""
    aql = f"""
    FOR doc IN {collection}
        COLLECT value = doc.{field} WITH COUNT INTO n
        RETURN [value, n]
    """
    return {value or "unknown": n for value, n in store.query(aql)}


# The collections a citation can make a stub in: a node known only because something
# refers to it (``props.stub``), without a text of its own.
_STUB_COLLECTIONS = (COLLECTION_INSTRUMENTS, COLLECTION_ARTICLES, COLLECTION_JUDGMENTS)


def _stub_count(store: ArangoStore, collection: str) -> int:
    aql = f"""
    FOR doc IN {collection}
        FILTER doc.props.stub == true
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    return cast(int, next(iter(store.query(aql)), 0))


def _replaced_count(store: ArangoStore) -> int:
    """The publications of a decision that another loaded publication replaces (``SAME_AS``
    the one kept, ``semantic rechtspraak-duplicates``): the lists show the decision once, by
    the one kept. A stub is never one: counted from the sparse index alone."""
    aql = f"""
    FOR doc IN {COLLECTION_JUDGMENTS}
        FILTER doc.props.same_as != null
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    return cast(int, next(iter(store.query(aql)), 0))


def _publication_count(store: ArangoStore) -> int:
    aql = f"""
    FOR doc IN {COLLECTION_INSTRUMENTS}
        FILTER doc.props.kind == '{KIND_PUBLICATION}'
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    rows = store.query(aql)
    return cast(int, next(iter(rows), 0))


def get_db_stats(store: ArangoStore) -> dict[str, Any]:
    """Document counts per collection (without stubs, and a decision published twice
    once), stub counts, the replaced publications, edge counts per relation, and source
    breakdowns."""
    stubs = {name: _stub_count(store, name) for name in _STUB_COLLECTIONS}
    publications = _publication_count(store)
    replaced = {COLLECTION_JUDGMENTS: _replaced_count(store)}
    nodes = {
        name: cast(int, store.collection(name).count())
        - stubs.get(name, 0)
        - replaced.get(name, 0)
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
            "total": store.edges.count(),
            "by_relation": _count_by(store, COLLECTION_EDGES, "relation"),
        },
        "by_source": {
            "judgments": _count_by(store, COLLECTION_JUDGMENTS, "props.source"),
            "documents": _count_by(store, COLLECTION_DOCUMENTS, "props.source"),
        },
        "instruments": {
            "by_kind": _count_by(store, COLLECTION_INSTRUMENTS, "props.kind"),
            "by_jurisdiction": _count_by(
                store, COLLECTION_INSTRUMENTS, "props.jurisdiction"
            ),
        },
    }


def get_judgment_coverage(store: ArangoStore) -> dict[str, Any]:
    """The judgments the graph holds (not the stubs of judgments it only knows as cited),
    per source, court tier and court, with the first and last date of each; how many
    stubs there are; and per court the publications another loaded one replaces
    (``replaced``), which the lists leave out. Every field the per-court count reads is in
    one index of ``db/schema.py``, so it counts without reading a judgment; the replaced
    publications, a few, are read by their own index."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
        FILTER j.props.stub == false
        COLLECT source = j.props.source, tier = j.props.tier,
                court_code = j.props.court_code
        AGGREGATE count = COUNT(1), first_date = MIN(j.props.date_eff),
                  last_date = MAX(j.props.date_eff), court = MAX(j.props.court)
        RETURN {{source, tier, court_code, court, count, first_date, last_date}}
    """
    stubs = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
        FILTER j.props.stub == true
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    replaced = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
        FILTER j.props.same_as != null
        COLLECT source = j.props.source, tier = j.props.tier,
                court_code = j.props.court_code WITH COUNT INTO count
        RETURN {{source, tier, court_code, count}}
    """
    return {
        "courts": list(store.query(aql)),
        "stubs": next(iter(store.query(stubs)), 0),
        "replaced": list(store.query(replaced)),
    }


# The newest dated record of a source, on or before today: what the graph holds of it, read
# from one index each. A source without an entry has only its last retrieve.
_NEWEST: dict[str, str] = {
    SOURCE_TK: f"""
        FOR n IN {COLLECTION_DOCUMENTS}
            FILTER POSITION(n.labels, "{CHAMBER_TK}") AND n.props.date <= @today
            SORT n.props.date DESC LIMIT 1 RETURN n.props.date""",
    SOURCE_EERSTEKAMER: f"""
        FOR n IN {COLLECTION_DOCUMENTS}
            FILTER POSITION(n.labels, "{CHAMBER_EK}") AND n.props.date <= @today
            SORT n.props.date DESC LIMIT 1 RETURN n.props.date""",
    SOURCE_RECHTSPRAAK: f"""
        FOR n IN {COLLECTION_JUDGMENTS}
            FILTER n.props.date_eff <= @today
            SORT n.props.date_eff DESC LIMIT 1 RETURN n.props.date_eff""",
    SOURCE_STAATSBLAD: f"""
        FOR n IN {COLLECTION_INSTRUMENTS}
            FILTER n.props.kind == "{KIND_PUBLICATION}" AND n.props.publication_kind == "Stb"
            FILTER n.props.date_published <= @today
            SORT n.props.date_published DESC LIMIT 1 RETURN n.props.date_published""",
    SOURCE_STAATSCOURANT: f"""
        FOR n IN {COLLECTION_INSTRUMENTS}
            FILTER n.props.kind == "{KIND_PUBLICATION}"
                AND n.props.publication_kind == "Stcrt"
            FILTER n.props.date_published <= @today
            SORT n.props.date_published DESC LIMIT 1 RETURN n.props.date_published""",
    SOURCE_BWB: f"""
        FOR n IN {COLLECTION_INSTRUMENT_VERSIONS}
            FILTER n.props.valid_from <= @today
            SORT n.props.valid_from DESC LIMIT 1 RETURN n.props.valid_from""",
}


_data_as_of_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=4, ttl=60.0)


def cached_data_as_of(store: ArangoStore) -> dict[str, Any]:
    """``get_data_as_of``, read at most once a minute per database (``/api/stats`` and every
    page of the feed carry it)."""
    key = str(store.db.name)
    hit = _data_as_of_cache.get(key)
    if isinstance(hit, dict):
        return hit
    value = get_data_as_of(store)
    _data_as_of_cache.set(key, value)
    return value


def get_data_as_of(store: ArangoStore, *, today: str | None = None) -> dict[str, Any]:
    """Per source the graph holds records of: ``retrieved_at``, the moment its newest raw
    record was fetched (the last retrieve that brought something), and ``newest``, the date
    of its newest dated record on or before *today* (null for a source without one)."""
    today = today or dt.date.today().isoformat()
    aql = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
        COLLECT source = r.source AGGREGATE retrieved_at = MAX(r.fetched_at)
        SORT source
        RETURN {{ source, retrieved_at }}
    """
    result: dict[str, Any] = {}
    for row in store.query(aql):
        newest = None
        if row["source"] in _NEWEST:
            newest = next(
                iter(store.query(_NEWEST[row["source"]], {"today": today})), None
            )
        result[row["source"]] = {"retrieved_at": row["retrieved_at"], "newest": newest}
    return result
