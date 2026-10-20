"""The reads of the laws of the Staatsblad the BWB does not hold (yet) (``retrieve
staatsblad``, ``normalize staatsblad-laws``, ``semantic staatsblad-law-references``,
``semantic bwb-definitions`` and the links of ``semantic tk``): which dossiers wait for their
law, which publications the BWB holds, the stored publications, and the laws and articles
written of them; and what the steps after ``normalize staatsblad-laws`` keep on them
(``unlinked_references``, ``definitions_found``)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RAW_BATCH_SIZE,
    RAW_KIND_STAATSBLAD_LAW,
    RELATION_LEGISLATED_IN,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.dossier_stages import STATUTE_KINDS
from lawgraph.core.raw_records import payload_text
from lawgraph.core.votes import ADOPTED
from lawgraph.db.counting import Store
from lawgraph.db.queries._chunks import update_props
from lawgraph.db.queries.instrument_scope import is_staatsblad_law
from lawgraph.db.queries.raw import iter_raw_records

_LAW = is_staatsblad_law("i")


def dossiers_awaiting_their_law(store: Store) -> Iterator[Any]:
    """The labels of the dossiers the graph holds as adopted (``outcome`` ``aangenomen``),
    whose bill becomes a law of its own (``STATUTE_KINDS``), and to which no instrument is
    ``LEGISLATED_IN`` yet: those whose law ``retrieve staatsblad`` looks for."""
    return store.query(
        f"""
        SELECT d.label FROM {COLLECTION_DOSSIERS} d
        WHERE lg_str(d.props -> 'outcome') = %(adopted)s AND d.kind = ANY(%(kinds)s)
          AND d.label IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.to_id = d.id AND e.relation = %(legislated_in)s
              AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
          )
        ORDER BY d.label ASC NULLS LAST
        """,
        {
            "adopted": ADOPTED,
            "kinds": list(STATUTE_KINDS),
            "legislated_in": RELATION_LEGISLATED_IN,
        },
    )


def enacted_in_the_bwb(store: Store, officials: list[str]) -> dict[str, str]:
    """Of the publications *officials* (``stb-2026-56``), those the BWB holds a regulation
    of (``props.enacted_publication``), with its BWB id."""
    if not officials:
        return {}
    rows = store.query(
        f"""
        SELECT lg_str(i.props -> 'enacted_publication') AS official, min(i.bwb_id) AS bwb_id
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE lg_str(i.props -> 'enacted_publication') = ANY(%(officials)s::text[])
          AND i.kind IS DISTINCT FROM '{KIND_PUBLICATION}' AND i.bwb_id IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        {"officials": officials},
    )
    return {row["official"]: row["bwb_id"] for row in rows}


def law_article_keys(store: Store) -> Iterator[dict[str, Any]]:
    """``{official_id, key}`` of every article of a law of the Staatsblad."""
    return store.query(
        f"""
        SELECT a.official_id, a.key FROM {COLLECTION_ARTICLES} a
        WHERE a.official_id IS NOT NULL
        ORDER BY a.official_id, a.key
        """
    )


def law_keys(store: Store) -> Iterator[Any]:
    """The keys of the laws of the Staatsblad."""
    return store.query(
        f"SELECT i.key FROM {COLLECTION_INSTRUMENTS} i WHERE {_LAW} ORDER BY i.key"
    )


def law_records(store: Store) -> Iterator[tuple[object, str | None]]:
    """``(external_id, xml)`` of every stored law of the Staatsblad (``retrieve
    staatsblad``): a few records, read whole."""
    rows = iter_raw_records(
        store,
        source=SOURCE_STAATSBLAD,
        kinds=[RAW_KIND_STAATSBLAD_LAW],
        since_iso=None,
        batch_size=RAW_BATCH_SIZE[RAW_KIND_STAATSBLAD_LAW],
    )
    for record in store.with_payloads(rows):
        yield record.get("external_id"), payload_text(record)


def laws(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, key, official_id, date_signed, named, unlinked_references,
    definitions_found}`` of every law of the Staatsblad; *named* the BWB ids of the laws of
    its citation title (the Wetboek van Strafvordering of the BWB for the new one): its own
    text means itself by that name."""
    return store.query(
        f"""
        SELECT i.id, i.key, lg_str(i.props -> 'official_id') AS official_id,
               lg_str(i.props -> 'date_signed') AS date_signed,
               ARRAY(
                   SELECT b.bwb_id FROM {COLLECTION_INSTRUMENTS} b
                   WHERE b.citation_title = i.citation_title AND b.bwb_id IS NOT NULL
                   ORDER BY b.bwb_id
               ) AS named,
               (i.props ->> 'unlinked_references')::int AS unlinked_references,
               (i.props ->> 'definitions_found')::int AS definitions_found
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE {_LAW}
        ORDER BY i.key
        """
    )


def keep_counts(
    store: Store,
    collection: str,
    prop: str,
    counts: dict[str, int],
    kept: dict[str, Any],
) -> int:
    """Write *counts* (node id -> count) as *prop* of the nodes of *collection*, those that
    differ from what they keep (*kept*: node id -> its value now): a run that finds what
    the last one found writes nothing. How many were written."""
    changed = [
        {"id": node, prop: count}
        for node, count in sorted(counts.items())
        if kept.get(node) != count
    ]
    return update_props(store, collection, changed, [prop]) if changed else 0


def law_articles(store: Store) -> Iterator[dict[str, Any]]:
    """``{id, key, official_id, article_number, text, unlinked_references}`` of every
    article of a law of the Staatsblad, in the order of each law."""
    return store.query(
        f"""
        SELECT a.id, a.key, a.official_id, a.article_number,
               lg_str(a.props -> 'text') AS text,
               (a.props ->> 'unlinked_references')::int AS unlinked_references
        FROM {COLLECTION_ARTICLES} a
        WHERE a.official_id IS NOT NULL AND a.stub IS NOT TRUE
        ORDER BY a.official_id, a.position ASC NULLS LAST, a.key
        """
    )


def laws_of_dossiers(store: Store) -> Iterator[dict[str, Any]]:
    """``{official_id, citation_title, dossier_numbers, named, numbers}`` of every law of
    the Staatsblad, with the BWB ids of the laws of the same citation title (``named``): a
    paper of one of its dossiers that cites one of those by name means this one; and the
    numbers of its articles."""
    return store.query(
        f"""
        SELECT lg_str(i.props -> 'official_id') AS official_id, i.citation_title,
               lg_text_array(i.props -> 'dossier_numbers') AS dossier_numbers,
               ARRAY(
                   SELECT b.bwb_id FROM {COLLECTION_INSTRUMENTS} b
                   WHERE b.citation_title = i.citation_title AND b.bwb_id IS NOT NULL
                   ORDER BY b.bwb_id
               ) AS named,
               ARRAY(
                   SELECT a.article_number FROM {COLLECTION_ARTICLES} a
                   WHERE a.official_id = lg_str(i.props -> 'official_id')
                     AND a.article_number IS NOT NULL
                   ORDER BY a.article_number ASC NULLS LAST
               ) AS numbers
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE {_LAW} AND i.citation_title IS NOT NULL
        ORDER BY i.key
        """
    )
