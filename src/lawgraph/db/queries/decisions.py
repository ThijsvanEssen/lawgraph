"""Queries behind the decision (vote) endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    RELATION_PART_OF,
    RELATION_VOTED,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore


@dataclass(frozen=True)
class DecisionFilters:
    """What ``GET /api/decisions`` narrows the decisions to; None is no filter.

    *party* with *choice* keeps the decisions that party voted that way on (``Voor``,
    ``Tegen``: ``meta.choice`` of its VOTED edge); *party* alone the ones it voted on.
    *dossier* is a dossier number, matched against the numbers on the decision; *q* a
    substring of the subject, in any case.
    """

    kinds: tuple[str, ...] | None = None
    passed: bool | None = None
    party: str | None = None
    choice: str | None = None
    chamber: str | None = None
    dossier: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    q: str | None = None


EMPTY_FACETS: dict[str, list[Any]] = {"kind": [], "passed": [], "days": []}


def _common_filters(
    filters: DecisionFilters, bind: dict[str, Any]
) -> tuple[str, list[str]]:
    """The AQL before the loop, and the filters on ``decision`` but for kind and outcome."""
    clauses: list[str] = []
    if filters.chamber is not None:
        # TK decisions carry the label "TK", EK ones "EK".
        clauses.append("FILTER @chamber IN decision.labels")
        bind["chamber"] = filters.chamber.upper()
    if filters.dossier:
        # Served by the array index on ``props.dossier_numbers``.
        clauses.append("FILTER @dossier IN decision.props.dossier_numbers")
        bind["dossier"] = filters.dossier
    if filters.date_from:
        clauses.append("FILTER decision.props.date >= @date_from")
        bind["date_from"] = filters.date_from
    if filters.date_to:
        clauses.append(
            "FILTER decision.props.date != null AND decision.props.date <= @date_to"
        )
        bind["date_to"] = filters.date_to
    if filters.q:
        clauses.append("FILTER CONTAINS(LOWER(decision.props.subject), @q)")
        bind["q"] = filters.q.lower()
    if not filters.party:
        return "", clauses
    clauses.append("FILTER decision._id IN voted_on")
    bind["faction_id"] = f"{COLLECTION_FACTIONS}/{make_node_key(filters.party.strip())}"
    bind["voted"] = RELATION_VOTED
    choice = ""
    if filters.choice:
        choice = "FILTER e.meta.choice == @choice"
        bind["choice"] = filters.choice
    # Start from the faction's own edges rather than scanning every vote.
    pre = f"""
    LET voted_on = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @faction_id AND e.relation == @voted
            {choice}
            RETURN e._to
    )
    """
    return pre, clauses


def _kind_filter(filters: DecisionFilters, var: str, bind: dict[str, Any]) -> str:
    if not filters.kinds:
        return ""
    bind["kinds"] = list(filters.kinds)
    return f"FILTER {var}.kind IN @kinds"


def _passed_filter(filters: DecisionFilters, var: str, bind: dict[str, Any]) -> str:
    if filters.passed is None:
        return ""
    bind["passed"] = filters.passed
    return f"FILTER {var}.passed == @passed"


def get_decisions(
    store: ArangoStore,
    filters: DecisionFilters | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of decisions, newest first, with the seat tally per row, and the facets.

    The tally and the kind are stored on the decision, so a list page costs no
    traversal; filtering by party reads the VOTED edges of that party.

    ``facets`` counts the decisions under the filters: ``kind`` without the kind filter,
    ``passed`` without the outcome filter, ``days`` (per date, how many and how many
    passed) under all of them. There is one decision per Besluit, so the filtered ones are
    read once, three fields each, and every count is made from that.
    """
    filters = filters or DecisionFilters()
    bind: dict[str, Any] = {"limit": limit, "offset": offset}
    pre, common = _common_filters(filters, bind)
    where = "\n            ".join(common)
    kind_on_row = _kind_filter(filters, "row", bind)
    passed_on_row = _passed_filter(filters, "row", bind)
    kind_on_decision = _kind_filter(filters, "decision.props", bind)
    passed_on_decision = _passed_filter(filters, "decision.props", bind)
    aql = f"""
    {pre}
    LET rows = (
        FOR decision IN {COLLECTION_DECISIONS}
            {where}
            RETURN {{
                kind: decision.props.kind,
                passed: decision.props.passed,
                date: decision.props.date
            }}
    )
    LET by_kind = (
        FOR row IN rows
            {passed_on_row}
            COLLECT value = row.kind WITH COUNT INTO count
            SORT count DESC, value
            RETURN {{ value, count }}
    )
    LET by_outcome = (
        FOR row IN rows
            {kind_on_row}
            COLLECT value = row.passed WITH COUNT INTO count
            SORT count DESC, value
            RETURN {{ value, count }}
    )
    LET matching = (
        FOR row IN rows
            {kind_on_row}
            {passed_on_row}
            RETURN row
    )
    LET days = (
        FOR row IN matching
            COLLECT date = row.date
            AGGREGATE count = LENGTH(1), passed = SUM(row.passed == true ? 1 : 0)
            SORT date
            RETURN {{ date, count, passed }}
    )
    LET items = (
        FOR decision IN {COLLECTION_DECISIONS}
            {where}
            {kind_on_decision}
            {passed_on_decision}
            SORT decision.props.date DESC, decision._key
            LIMIT @offset, @limit
            LET tally = decision.props.tally != null ? decision.props.tally : {{}}
            LET voters = decision.props.voters != null ? decision.props.voters : {{}}
            RETURN {{
                id: decision._id,
                key: decision._key,
                date: decision.props.date,
                subject: decision.props.subject,
                external_id: decision.props.decision_id,
                dossier_numbers: decision.props.dossier_numbers,
                kind: decision.props.kind,
                passed: decision.props.passed,
                chamber: decision.props.chamber,
                vote_kind: decision.props.vote_kind,
                tally: tally,
                voters: voters
            }}
    )
    RETURN {{
        total: LENGTH(matching),
        items: items,
        facets: {{ kind: by_kind, passed: by_outcome, days: days }}
    }}
    """
    rows = list(store.query(aql, bind))
    return rows[0] if rows else {"total": 0, "items": [], "facets": EMPTY_FACETS}


def get_decision_detail(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """One decision with every vote cast on it.

    Each vote is a VOTED edge — from a member on a roll-call, from a faction
    otherwise — so the voter's node carries the name to show.
    """
    aql = f"""
    LET decision = DOCUMENT(CONCAT('{COLLECTION_DECISIONS}/', @key))
    FILTER decision != null
    LET votes = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == decision._id AND e.relation == @voted
            LET voter = DOCUMENT(e._from)
            FILTER voter != null
            SORT e.meta.seats DESC, voter.props.name ASC
            RETURN {{
                voter_id: voter._id,
                voter_key: voter._key,
                name: voter.props.abbreviation != null
                    ? voter.props.abbreviation : voter.props.name,
                choice: e.meta.choice,
                seats: e.meta.seats
            }}
    )
    RETURN MERGE(decision, {{ votes: votes }})
    """
    for row in store.query(aql, {"key": key, "voted": RELATION_VOTED}):
        return row
    return None


def get_decision_document(
    store: ArangoStore, decision: dict[str, Any]
) -> dict[str, Any] | None:
    """The document (motion, amendment, bill) the decision was about.

    A decision is ABOUT a case; a document is PART_OF that case. The case the
    decision singled out — ``primary_case_id`` — is tried before the others
    on the same agenda item, and the first document found wins.
    """
    props = decision.get("props") or {}
    primary = props.get("primary_case_id")
    candidates = [primary] if primary else []
    candidates += [c for c in props.get("case_ids") or [] if c != primary]
    if not candidates:
        return None

    aql = f"""
    FOR case_id IN @case_ids
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == case_id AND e.relation == @part_of
            FILTER STARTS_WITH(e._from, '{COLLECTION_DOCUMENTS}/')
            LET document = DOCUMENT(e._from)
            FILTER document != null
            LIMIT 1
            RETURN document
    """
    bind = {
        "case_ids": [f"{COLLECTION_CASES}/{make_node_key(str(c))}" for c in candidates],
        "part_of": RELATION_PART_OF,
    }
    for row in store.query(aql, bind):
        return row
    return None
