"""The reads of ``lawgraph check``: node counts per source, dangling edges, search views
against their collections, and the props a normalize step keeps for a semantic step. Each
is one read-only query."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg import sql

from lawgraph.config.constants import (
    RAW_KIND_ECHR_JUDGMENT,
    SOURCE_BWB,
    SOURCE_ECHR,
    SOURCE_TK,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.db.counting import Store
from lawgraph.db.schema import NODE_COLLECTIONS


def _absent(field: str) -> str:
    """``props.<field> == null``: missing or null."""
    return f"coalesce(json_typeof(props -> '{field}'), 'null') = 'null'"


def count_nodes_of_source(store: Store, collection: str, source: str) -> int:
    """How many nodes of *collection* have ``props.source`` *source*."""
    if collection not in NODE_COLLECTIONS:
        raise ValueError(f"Unknown collection: {collection!r}")
    statement = sql.SQL(
        "SELECT count(*)::int FROM {} WHERE lg_str(props -> 'source') = %(source)s"
    ).format(sql.Identifier(collection))
    return next(store.query(statement, {"source": source}), 0)


def count_echr_judgments_in_raw(store: Store) -> int:
    """How many judgments the HUDOC records hold: one per ECLI, whatever its languages, and
    one per item without an ECLI, as ``normalize echr`` keys them."""
    statement = r"""
        SELECT count(*)::int FROM (
            SELECT DISTINCT CASE WHEN ecli <> '' THEN ecli ELSE external_id END
            FROM (
                SELECT external_id,
                       upper(btrim(coalesce(
                           nullif(doc -> 'payload_json' ->> 'ecli', ''), ''
                       ), E' \t\r\n')) AS ecli
                FROM raw_sources
                WHERE source = %(source)s AND kind = %(kind)s
            ) records
        ) judgments
        """
    bind = {"source": SOURCE_ECHR, "kind": RAW_KIND_ECHR_JUDGMENT}
    return next(store.query(statement, bind), 0)


def echr_article_fields(store: Store) -> Iterator[Any]:
    """The ``articles`` field of every ECHR judgment that has one, as HUDOC gave it."""
    return store.query(
        f"""
        SELECT props -> 'articles' FROM judgments
        WHERE source = %(source)s AND NOT {_absent("articles")}
        ORDER BY key
        """,
        {"source": SOURCE_ECHR},
    )


def dangling_edges(store: Store) -> Iterator[dict[str, Any]]:
    """``{relation, n}``: the edges per relation to or from a node that does not exist."""
    return store.query(
        """
        SELECT e.relation, count(*)::int AS n FROM edges e
        WHERE NOT EXISTS (SELECT 1 FROM nodes WHERE nodes.id = e.from_id)
           OR NOT EXISTS (SELECT 1 FROM nodes WHERE nodes.id = e.to_id)
        GROUP BY e.relation
        ORDER BY e.relation NULLS FIRST
        """
    )


def view_and_collection_size(
    store: Store, view: str, collection: str
) -> dict[str, Any]:
    """``{indexed, stored}``: the documents search *view* holds and *collection* holds.

    The search columns are generated columns of the table itself, so the two are the same
    count; ``lawgraph check`` reports them as it did for the ArangoSearch views (D7)."""
    stored = store.count(collection)
    return {"indexed": stored, "stored": stored}


def count_regulations_without_derived_props(store: Store) -> int:
    """BWB regulations (not stubs, not publications) without ``basis``, ``celex_refs`` or
    ``implements_celex``."""
    statement = f"""
        SELECT count(*)::int FROM instruments
        WHERE lg_str(props -> 'source') = %(source)s AND stub IS NOT TRUE
          AND NOT ('Publication' = ANY(labels))
          AND ({_absent("basis")} OR {_absent("celex_refs")}
               OR {_absent("implements_celex")})
        """
    return next(store.query(statement, {"source": SOURCE_BWB}), 0)


def bwb_treaties_by_match(store: Store) -> dict[str, int]:
    """BWB treaties (not stubs) by what their treaty number finds: ``matched`` (a
    Verdragenbank treaty has it), ``unmatched`` (none has it) and ``unnumbered`` (the
    treaty carries none)."""
    rows = store.query(
        """
        SELECT CASE
                   WHEN t.treaty_number IS NULL THEN 'unnumbered'
                   WHEN EXISTS (
                       SELECT 1 FROM instruments r
                       WHERE r.treaty_number = t.treaty_number
                         AND lg_str(r.props -> 'source') = %(verdragenbank)s
                   ) THEN 'matched'
                   ELSE 'unmatched'
               END AS match,
               count(*)::int AS n
        FROM instruments t
        WHERE lg_str(t.props -> 'source') = %(bwb)s AND t.kind = 'verdrag'
          AND t.stub IS NOT TRUE
        GROUP BY match
        ORDER BY match
        """,
        {"bwb": SOURCE_BWB, "verdragenbank": SOURCE_VERDRAGENBANK},
    )
    return {row["match"]: row["n"] for row in rows}


def count_documents_read_from(store: Store, text_source: str) -> int:
    """Tweede Kamer documents whose text and sections were read from *text_source*."""
    statement = """
        SELECT count(*)::int FROM documents
        WHERE source = %(source)s AND lg_str(props -> 'text_source') = %(text_source)s
        """
    bind = {"source": SOURCE_TK, "text_source": text_source}
    return next(store.query(statement, bind), 0)


def cases_by_named_dossier(store: Store) -> dict[bool, int]:
    """How many cases name a dossier (True) and how many do not (False)."""
    rows = store.query(
        """
        SELECT coalesce(cardinality(lg_text_array(props -> 'dossier_numbers')), 0) > 0
                   AS named,
               count(*)::int AS n
        FROM cases
        GROUP BY named
        ORDER BY named
        """
    )
    return {row["named"]: row["n"] for row in rows}


def shared_member_slugs(store: Store) -> list[dict[str, Any]]:
    """Every slug more than one member has, with how many: ``{slug, count}``."""
    return list(
        store.query(
            """
            SELECT lg_str(props -> 'slug') AS slug, count(*)::int AS count
            FROM members
            WHERE lg_str(props -> 'slug') IS NOT NULL
            GROUP BY 1
            HAVING count(*) > 1
            ORDER BY 1 ASC NULLS FIRST
            """
        )
    )
