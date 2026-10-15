"""What ``semantic tk-paper-outcomes`` reads: the decisions on motions and amendments, the
papers they were taken on, the papers a newer one replaces, and the outcomes kept before
(``core/votes.py``)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    RELATION_REVISES,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_relations import RULE_REPLACEMENT
from lawgraph.core.tk_records.kinds import DECIDED_KINDS, KIND_AMENDMENT, KIND_MOTION
from lawgraph.core.votes import PAPER_OUTCOME_PROPS
from lawgraph.db.counting import Store
from lawgraph.db.queries._json_sql import is_present
from lawgraph.db.queries.decisions import motion_papers

# Decisions whose papers are looked up in one query.
_CHUNK = 5_000

# Every decision on a motion or an amendment: the case it singled out is one (the Tweede
# Kamer), or it is of that kind without one (a vote of the Eerste Kamer on a motion).
_DECISIONS = f"""
SELECT d.id, d.key, d.date, d.passed,
       lg_str(d.props -> 'decision_kind') AS decision_kind,
       lg_str(d.props -> 'result') AS result,
       d.props -> 'tally' AS tally,
       lg_str(d.props -> 'kind') AS kind,
       lg_str(d.props -> 'primary_case_kind') AS primary_case_kind,
       lg_str(d.props -> 'primary_case_id') AS primary_case_id
FROM {COLLECTION_DECISIONS} d
WHERE lg_str(d.props -> 'primary_case_kind') = ANY(%(kinds)s::text[])
   OR lg_str(d.props -> 'kind') = ANY(%(kinds)s::text[])
ORDER BY d.id
"""

# The motions and amendments a newer paper replaces ("ter vervanging van nr. 19").
_REPLACED = f"""
SELECT DISTINCT e.to_id AS id
FROM edges e
JOIN documents d ON d.id = e.to_id
WHERE e.relation = %(revises)s AND e.from_collection = 'documents'
  AND e.to_collection = 'documents' AND e.doc -> 'meta' ->> 'rule' = '{RULE_REPLACEMENT}'
  AND (starts_with(d.kind, '{KIND_MOTION}') OR starts_with(d.kind, '{KIND_AMENDMENT}'))
"""

# The status the page of a motion of the Eerste Kamer states (``normalize
# eerstekamer-motions``), of those that have one.
_STATED = f"""
SELECT d.id, lg_str(d.props -> 'status') AS status
FROM documents d
WHERE d.source = '{SOURCE_EERSTEKAMER}' AND starts_with(d.kind, '{KIND_MOTION}')
  AND lg_str(d.props -> 'status') IS NOT NULL
"""

# The outcomes kept before, from the light rows of the papers (``lg_document_light``).
_KEPT = f"""
SELECT l.id, {", ".join(f"l.props -> '{name}' AS {name}" for name in PAPER_OUTCOME_PROPS)}
FROM lg_document_light l
WHERE {is_present("l.props -> 'outcome'")}
"""


def paper_decisions(store: Store) -> dict[str, list[dict[str, Any]]]:
    """Paper id -> the decisions taken on it (``{key, date, passed, decision_kind, result,
    tally}``), each paper as ``motion_papers`` finds it."""
    decisions = list(store.query(_DECISIONS, {"kinds": list(DECIDED_KINDS)}))
    by_paper: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunked(decisions, _CHUNK):
        for decision, (paper, _) in zip(
            chunk, motion_papers(store, chunk), strict=True
        ):
            if paper is None:
                continue
            by_paper.setdefault(f"{paper['collection']}/{paper['key']}", []).append(
                decision
            )
    return by_paper


def replaced_papers(store: Store) -> set[str]:
    """The ids of the motions and amendments a newer paper replaces."""
    # one column: the store gives its values
    return set(store.query(_REPLACED, {"revises": RELATION_REVISES}))


def stated_statuses(store: Store) -> dict[str, str]:
    """Paper id -> the status the page of a motion of the Eerste Kamer states."""
    return {row["id"]: row["status"] for row in store.query(_STATED, {})}


def kept_outcomes(store: Store) -> dict[str, dict[str, Any]]:
    """Paper id -> ``{outcome, decided_on, tally, decision}`` as kept, of every paper that
    has an outcome."""
    return {
        row["id"]: {name: row[name] for name in PAPER_OUTCOME_PROPS}
        for row in store.query(_KEPT, {})
    }
