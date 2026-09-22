"""Queries behind the decision (vote) endpoints."""

from __future__ import annotations

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


def get_decisions(
    store: ArangoStore,
    *,
    passed: bool | None = None,
    party: str | None = None,
    chamber: str | None = None,
    dossier: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of decisions, newest first, with the seat tally per row.

    The tally is stored on the decision, so a list page costs no traversal.
    Filtering by *party* does need one, over the VOTED edges of that party;
    *dossier* is a dossier number, matched against the numbers on the decision.
    """
    bind: dict[str, Any] = {"limit": limit, "offset": offset}
    filters: list[str] = []

    if passed is not None:
        filters.append("FILTER decision.props.passed == @passed")
        bind["passed"] = passed
    if chamber is not None:
        # TK decisions carry the label "TK", EK ones "EK".
        filters.append("FILTER @chamber IN decision.labels")
        bind["chamber"] = chamber.upper()
    if dossier:
        # Served by the array index on ``props.dossier_numbers``.
        filters.append("FILTER @dossier IN decision.props.dossier_numbers")
        bind["dossier"] = dossier
    party_pre = ""
    if party:
        filters.append("FILTER decision._id IN voted_on")
        bind["faction_id"] = f"{COLLECTION_FACTIONS}/{make_node_key(party.strip())}"
        bind["voted"] = RELATION_VOTED
        # Start from the faction's own edges rather than scanning every vote.
        party_pre = f"""
    LET voted_on = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @faction_id AND e.relation == @voted
            RETURN e._to
    )
        """

    where = "\n            ".join(filters)
    aql = f"""
    {party_pre}
    LET total = LENGTH(
        FOR decision IN {COLLECTION_DECISIONS}
            {where}
            RETURN 1
    )
    LET items = (
        FOR decision IN {COLLECTION_DECISIONS}
            {where}
            SORT decision.props.date DESC
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
                passed: decision.props.passed,
                chamber: decision.props.chamber,
                vote_kind: decision.props.vote_kind,
                tally: tally,
                voters: voters
            }}
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(store.query(aql, bind))
    return rows[0] if rows else {"total": 0, "items": []}


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
