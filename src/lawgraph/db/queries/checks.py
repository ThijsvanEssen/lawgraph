"""The reads of ``lawgraph check``: node counts per source, dangling edges, search views
against their collections, and the props a normalize step keeps for a semantic step. Each
is one read-only query."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_ECHR_JUDGMENT,
    SOURCE_BWB,
    SOURCE_ECHR,
    SOURCE_TK,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.db.counting import Store


def count_nodes_of_source(store: Store, collection: str, source: str) -> int:
    """How many nodes of *collection* have ``props.source`` *source*."""
    aql = f"""
        FOR d IN {collection}
            FILTER d.props.source == @source
            COLLECT WITH COUNT INTO n
            RETURN n
        """
    return next(iter(store.query(aql, {"source": source})), 0)


def count_echr_judgments_in_raw(store: Store) -> int:
    """How many judgments the HUDOC records hold: one per ECLI, whatever its languages, and
    one per item without an ECLI, as ``normalize echr`` keys them."""
    aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            LET ecli = UPPER(TRIM(TO_STRING(r.payload_json.ecli || "")))
            COLLECT judgment = ecli != "" ? ecli : r.external_id
            COLLECT WITH COUNT INTO n
            RETURN n
        """
    bind_vars = {"source": SOURCE_ECHR, "kind": RAW_KIND_ECHR_JUDGMENT}
    return next(iter(store.query(aql, bind_vars)), 0)


def echr_article_fields(store: Store) -> Iterator[Any]:
    """The ``articles`` field of every ECHR judgment that has one, as HUDOC gave it."""
    aql = f"""
        FOR j IN {COLLECTION_JUDGMENTS}
            FILTER j.props.source == @source AND j.props.articles != null
            RETURN j.props.articles
        """
    return store.query(aql, {"source": SOURCE_ECHR})


def dangling_edges(store: Store) -> Iterator[dict[str, Any]]:
    """``{relation, n}``: the edges per relation to or from a node that does not exist."""
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER DOCUMENT(e._from) == null OR DOCUMENT(e._to) == null
        COLLECT relation = e.relation WITH COUNT INTO n
        RETURN {{relation, n}}
    """
    return store.query(aql)


def view_and_collection_size(
    store: Store, view: str, collection: str
) -> dict[str, Any]:
    """``{indexed, stored}``: the documents search *view* holds and *collection* holds."""
    aql = f"""
        LET indexed = FIRST(FOR d IN {view} COLLECT WITH COUNT INTO n RETURN n)
        LET stored = LENGTH({collection})
        RETURN {{indexed, stored}}
        """
    row: dict[str, Any] = next(iter(store.query(aql)))
    return row


def count_regulations_without_derived_props(store: Store) -> int:
    """BWB regulations (not stubs, not publications) without ``basis``, ``celex_refs`` or
    ``implements_celex``."""
    aql = f"""
    FOR regulation IN {COLLECTION_INSTRUMENTS}
        FILTER regulation.props.source == @source AND regulation.props.stub != true
        FILTER "Publication" NOT IN regulation.labels
        FILTER regulation.props.basis == null OR regulation.props.celex_refs == null
            OR regulation.props.implements_celex == null
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    return next(iter(store.query(aql, {"source": SOURCE_BWB})), 0)


def bwb_treaties_by_match(store: Store) -> dict[str, int]:
    """BWB treaties (not stubs) by what their treaty number finds: ``matched`` (a
    Verdragenbank treaty has it), ``unmatched`` (none has it) and ``unnumbered`` (the
    treaty carries none)."""
    aql = f"""
    FOR treaty IN {COLLECTION_INSTRUMENTS}
        FILTER treaty.props.source == @bwb AND treaty.props.kind == "verdrag"
        FILTER treaty.props.stub != true
        LET number = treaty.props.treaty_number
        LET found = number == null ? [] : (
            FOR record IN {COLLECTION_INSTRUMENTS}
                FILTER record.props.treaty_number == number
                FILTER record.props.source == @verdragenbank
                LIMIT 1
                RETURN 1
        )
        COLLECT match = number == null ? "unnumbered"
            : (LENGTH(found) > 0 ? "matched" : "unmatched") WITH COUNT INTO n
        RETURN [match, n]
    """
    bind = {"bwb": SOURCE_BWB, "verdragenbank": SOURCE_VERDRAGENBANK}
    return dict(store.query(aql, bind))


def count_documents_read_from(store: Store, text_source: str) -> int:
    """Tweede Kamer documents whose text and sections were read from *text_source*."""
    aql = f"""
    FOR d IN {COLLECTION_DOCUMENTS}
        FILTER d.props.source == @source AND d.props.text_source == @text_source
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    bind = {"source": SOURCE_TK, "text_source": text_source}
    return next(iter(store.query(aql, bind)), 0)


def cases_by_named_dossier(store: Store) -> dict[bool, int]:
    """How many cases name a dossier (True) and how many do not (False)."""
    aql = f"""
    FOR case IN {COLLECTION_CASES}
        COLLECT named = LENGTH(case.props.dossier_numbers || []) > 0 WITH COUNT INTO n
        RETURN [named, n]
    """
    return dict(store.query(aql))
