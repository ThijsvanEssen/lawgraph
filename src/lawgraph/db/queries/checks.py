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
    SOURCE_BWB,
    SOURCE_TK,
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
    """BWB regulations (not stubs, not publications) without ``basis`` or ``celex_refs``."""
    aql = f"""
    FOR regulation IN {COLLECTION_INSTRUMENTS}
        FILTER regulation.props.source == @source AND regulation.props.stub != true
        FILTER "Publication" NOT IN regulation.labels
        FILTER regulation.props.basis == null OR regulation.props.celex_refs == null
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    return next(iter(store.query(aql, {"source": SOURCE_BWB})), 0)


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
