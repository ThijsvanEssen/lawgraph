"""What ``semantic tk-paper-outcomes`` reads: the decisions on motions and amendments, the
documents they were taken on, the documents a newer one replaces, and the outcomes kept before
(``core/votes.py``). Each of them for every document, or for those of *documents* alone
(``None``: every one); and the documents a poll touched (``touched_documents``)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    RELATION_ABOUT,
    RELATION_PART_OF,
    RELATION_REVISES,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_relations import RULE_REPLACEMENT
from lawgraph.core.models import make_node_key, node_id
from lawgraph.core.tk_records.kinds import DECIDED_KINDS, KIND_AMENDMENT, KIND_MOTION
from lawgraph.core.votes import DOCUMENT_OUTCOME_PROPS
from lawgraph.db.counting import Store
from lawgraph.db.queries._json_sql import is_present
from lawgraph.db.queries.decisions import motion_documents
from lawgraph.db.queries.semantic.tk import WRITTEN_SQL, written_params

# Decisions whose documents are looked up in one query.
_CHUNK = 5_000

# Every decision on a motion or an amendment: the case it singled out is one (the Tweede
# Kamer), or it is of that kind without one (a vote of the Eerste Kamer on a motion). Of
# *documents* only those that may be taken on one of them: that single out a case one of them is
# PART_OF, or that are ABOUT one of them.
_DECISIONS = f"""
SELECT d.id, d.key, d.date, d.passed,
       lg_str(d.props -> 'decision_kind') AS decision_kind,
       lg_str(d.props -> 'result') AS result,
       d.props -> 'tally' AS tally,
       lg_str(d.props -> 'kind') AS kind,
       lg_str(d.props -> 'primary_case_kind') AS primary_case_kind,
       lg_str(d.props -> 'primary_case_id') AS primary_case_id
FROM {COLLECTION_DECISIONS} d
WHERE (lg_str(d.props -> 'primary_case_kind') = ANY(%(kinds)s::text[])
       OR lg_str(d.props -> 'kind') = ANY(%(kinds)s::text[]))
  AND (%(documents)s::text[] IS NULL
       OR lg_str(d.props -> 'primary_case_id') IN (
           SELECT lg_str(c.props -> 'external_id')
           FROM {COLLECTION_EDGES} e JOIN {COLLECTION_CASES} c ON c.id = e.to_id
           WHERE e.from_id = ANY(%(documents)s::text[]) AND e.relation = '{RELATION_PART_OF}')
       OR d.id IN (
           SELECT e.from_id FROM {COLLECTION_EDGES} e
           WHERE e.to_id = ANY(%(documents)s::text[]) AND e.relation = '{RELATION_ABOUT}'))
ORDER BY d.id
"""

# The motions and amendments a newer document replaces ("ter vervanging van nr. 19").
_REPLACED = f"""
SELECT DISTINCT e.to_id AS id
FROM edges e
JOIN documents d ON d.id = e.to_id
WHERE e.relation = %(revises)s AND e.from_collection = 'documents'
  AND e.to_collection = 'documents' AND e.doc -> 'meta' ->> 'rule' = '{RULE_REPLACEMENT}'
  AND (starts_with(d.kind, '{KIND_MOTION}') OR starts_with(d.kind, '{KIND_AMENDMENT}'))
  AND (%(documents)s::text[] IS NULL OR e.to_id = ANY(%(documents)s::text[]))
"""

# The status the page of a motion of the Eerste Kamer states (``normalize
# eerstekamer-motions``), of those that have one.
_STATED = f"""
SELECT d.id, lg_str(d.props -> 'status') AS status
FROM documents d
WHERE d.source = '{SOURCE_EERSTEKAMER}' AND starts_with(d.kind, '{KIND_MOTION}')
  AND lg_str(d.props -> 'status') IS NOT NULL
  AND (%(documents)s::text[] IS NULL OR d.id = ANY(%(documents)s::text[]))
"""

# The outcomes kept before, from the light rows of the documents (``lg_document_light``).
_KEPT = f"""
SELECT l.id, {", ".join(f"l.props -> '{name}' AS {name}" for name in DOCUMENT_OUTCOME_PROPS)}
FROM lg_document_light l
WHERE {is_present("l.props -> 'outcome'")}
  AND (%(documents)s::text[] IS NULL OR l.id = ANY(%(documents)s::text[]))
"""


def document_decisions(
    store: Store, documents: list[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Document id -> the decisions taken on it (``{key, date, passed, decision_kind, result,
    tally}``), each document as ``motion_documents`` finds it."""
    decisions = list(
        store.query(_DECISIONS, {"kinds": list(DECIDED_KINDS), "documents": documents})
    )
    wanted = None if documents is None else set(documents)
    by_document: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunked(decisions, _CHUNK):
        for decision, (document, _) in zip(
            chunk, motion_documents(store, chunk), strict=True
        ):
            if document is None:
                continue
            found = f"{document['collection']}/{document['key']}"
            if wanted is None or found in wanted:
                by_document.setdefault(found, []).append(decision)
    return by_document


def replaced_documents(store: Store, documents: list[str] | None = None) -> set[str]:
    """The ids of the motions and amendments a newer document replaces."""
    # one column: the store gives its values
    return set(
        store.query(_REPLACED, {"revises": RELATION_REVISES, "documents": documents})
    )


def stated_statuses(store: Store, documents: list[str] | None = None) -> dict[str, str]:
    """Document id -> the status the page of a motion of the Eerste Kamer states."""
    rows = store.query(_STATED, {"documents": documents})
    return {row["id"]: row["status"] for row in rows}


def kept_outcomes(
    store: Store, documents: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Document id -> ``{outcome, decided_on, tally, decision}`` as kept, of every document that
    has an outcome."""
    return {
        row["id"]: {name: row[name] for name in DOCUMENT_OUTCOME_PROPS}
        for row in store.query(_KEPT, {"documents": documents})
    }


def primary_cases(store: Store, decisions: list[str]) -> list[str]:
    """The ``id`` of the case each decision of *decisions* singles out (``primary_case_id``,
    keyed as the case is), of those that single one out."""
    rows = store.query(
        f"""
        SELECT lg_str(d.props -> 'primary_case_id') FROM {COLLECTION_DECISIONS} d
        WHERE d.id = ANY(%(ids)s::text[])
          AND coalesce(lg_str(d.props -> 'primary_case_id'), '') <> ''
        """,
        {"ids": decisions},
    )
    return sorted(
        {node_id(COLLECTION_CASES, make_node_key(str(case))) for case in rows}
    )


# The documents whose outcome what a poll touched can change: those among the nodes *ids* or
# at an end of an edge written since *since* (``WRITTEN_SQL``), every document of a case among
# them or of a case such a document is PART_OF (which of them is the oldest can change), and
# the document a decision among them is ABOUT (a vote of the Eerste Kamer). *ids* hold the
# cases the touched decisions single out (``primary_cases``).
_TOUCHED = f"""
WITH seeds AS (
    SELECT unnest(%(ids)s::text[]) AS id
    UNION
    SELECT e.from_id FROM {COLLECTION_EDGES} e WHERE {WRITTEN_SQL}
    UNION
    SELECT e.to_id FROM {COLLECTION_EDGES} e WHERE {WRITTEN_SQL}
),
cases AS (
    SELECT id FROM seeds WHERE starts_with(id, '{COLLECTION_CASES}/')
    UNION
    SELECT e.to_id FROM {COLLECTION_EDGES} e JOIN seeds s ON e.from_id = s.id
    WHERE e.relation = '{RELATION_PART_OF}' AND e.to_collection = '{COLLECTION_CASES}'
      AND e.from_collection = '{COLLECTION_DOCUMENTS}'
)
SELECT id FROM seeds WHERE starts_with(id, '{COLLECTION_DOCUMENTS}/')
UNION
SELECT e.from_id FROM {COLLECTION_EDGES} e JOIN cases c ON e.to_id = c.id
WHERE e.relation = '{RELATION_PART_OF}' AND e.from_collection = '{COLLECTION_DOCUMENTS}'
UNION
SELECT e.to_id FROM {COLLECTION_EDGES} e JOIN seeds s ON e.from_id = s.id
WHERE e.relation = '{RELATION_ABOUT}' AND e.from_collection = '{COLLECTION_DECISIONS}'
  AND e.to_collection = '{COLLECTION_DOCUMENTS}'
ORDER BY 1
"""


def touched_documents(
    store: Store, ids: list[str], since_iso: str, written: dict[str, tuple[str, ...]]
) -> list[str]:
    """The ``id`` of the documents whose outcome the nodes *ids* or an edge written at or
    after *since_iso* (of *written*) can change (``_TOUCHED``)."""
    params = {"ids": ids, "since": since_iso, **written_params(written)}
    return list(store.query(_TOUCHED, params))
