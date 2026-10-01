"""Queries behind the decision (vote) endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_FACTIONS,
    RELATION_PART_OF,
    RELATION_VOTED,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc


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


def _common_filters(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    """The conditions on the decision ``d`` but for kind and outcome."""
    clauses: list[str] = []
    if filters.chamber is not None:
        # TK decisions carry the label "TK", EK ones "EK".
        clauses.append("%(chamber)s = ANY(d.labels)")
        bind["chamber"] = filters.chamber.upper()
    if filters.dossier:
        # Served by the array index on ``dossier_numbers``.
        clauses.append("d.dossier_numbers @> ARRAY[%(dossier)s]::text[]")
        bind["dossier"] = filters.dossier
    if filters.date_from:
        clauses.append("d.date >= %(date_from)s")
        bind["date_from"] = filters.date_from
    if filters.date_to:
        clauses.append("d.date <= %(date_to)s")
        bind["date_to"] = filters.date_to
    if filters.q:
        # AQL LOWER of a missing subject is "", of a number its digits.
        clauses.append("strpos(lower(coalesce(d.props ->> 'subject', '')), %(q)s) > 0")
        bind["q"] = filters.q.lower()
    if filters.party:
        # Start from the faction's own edges rather than scanning every vote.
        choice = ""
        if filters.choice:
            choice = "AND lg_str(e.doc -> 'meta' -> 'choice') = %(choice)s"
            bind["choice"] = filters.choice
        clauses.append(
            f"""d.id IN (
                SELECT e.to_id FROM edges e
                WHERE e.from_id = %(faction_id)s AND e.relation = %(voted)s {choice}
            )"""
        )
        bind["faction_id"] = (
            f"{COLLECTION_FACTIONS}/{make_node_key(filters.party.strip())}"
        )
        bind["voted"] = RELATION_VOTED
    return clauses


def _kind_filter(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    if not filters.kinds:
        return []
    bind["kinds"] = list(filters.kinds)
    return ["r.kind = ANY(%(kinds)s)"]


def _passed_filter(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    if filters.passed is None:
        return []
    bind["passed"] = filters.passed
    return ["r.passed = %(passed)s"]


def _where(clauses: list[str]) -> str:
    return f"WHERE {' AND '.join(clauses)}" if clauses else ""


def _object_or_empty(value: str) -> str:
    """SQL: AQL ``value != null ? value : {}``."""
    return (
        f"CASE WHEN coalesce(json_typeof({value}), 'null') <> 'null'"
        f" THEN {value} ELSE '{{}}'::json END"
    )


# A row of the list, in the order of its keys. ``chamber`` is the stored one when it is
# set (AQL ``||``), else the first of the chambers whose label the decision carries.
_ITEM = f"""json_build_object(
    'id', d.id,
    'key', d.key,
    'date', d.props -> 'date',
    'subject', d.props -> 'subject',
    'external_id', d.props -> 'decision_id',
    'dossier_numbers', d.props -> 'dossier_numbers',
    'kind', d.props -> 'kind',
    'decision_kind', d.props -> 'decision_kind',
    'passed', d.props -> 'passed',
    'chamber', CASE
        WHEN lg_truthy(d.props -> 'chamber') THEN d.props -> 'chamber'
        ELSE to_json((
            SELECT c FROM unnest(%(chambers)s::text[]) WITH ORDINALITY AS u(c, n)
            WHERE c = ANY(d.labels) ORDER BY n LIMIT 1
        ))
    END,
    'result', d.props -> 'result',
    'method', d.props -> 'method',
    'bill_decision', d.props -> 'bill_decision',
    'vote_kind', d.props -> 'vote_kind',
    'tally', {_object_or_empty("d.props -> 'tally'")},
    'voters', {_object_or_empty("d.props -> 'voters'")}
)"""

# The order of the list: newest first, the key settling a day.
_ORDER = "r.date DESC NULLS LAST, r.key ASC"


def _facet(value: str, rows: str, where: list[str]) -> str:
    """SQL: the JSON array ``[{value, count}]`` of *rows* per *value*, most first, then
    by value."""
    return f"""(
        SELECT coalesce(json_agg(
            json_build_object('value', value, 'count', count)
            ORDER BY count DESC, value ASC NULLS FIRST
        ), '[]'::json)
        FROM (
            SELECT {value} AS value, count(*)::int AS count
            FROM {rows} r {_where(where)}
            GROUP BY 1
        ) facet
    )"""


def get_decisions(
    store: GraphStore,
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
    bind: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "chambers": [CHAMBER_TK, CHAMBER_EK],
    }
    common = _common_filters(filters, bind)
    kind = _kind_filter(filters, bind)
    passed = _passed_filter(filters, bind)
    statement = f"""
    WITH filtered AS MATERIALIZED (
        SELECT d.id, d.key, lg_str(d.props -> 'kind') AS kind, d.passed, d.date
        FROM decisions d {_where(common)}
    ),
    matching AS MATERIALIZED (
        SELECT * FROM filtered r {_where(kind + passed)}
    )
    SELECT json_build_object(
        'total', (SELECT count(*)::int FROM matching),
        'items', (
            SELECT coalesce(json_agg({_ITEM} ORDER BY page.n), '[]'::json)
            FROM (
                SELECT r.id, row_number() OVER (ORDER BY {_ORDER}) AS n
                FROM matching r
                ORDER BY {_ORDER}
                LIMIT %(limit)s OFFSET %(offset)s
            ) page
            JOIN decisions d ON d.id = page.id
        ),
        'facets', json_build_object(
            'kind', {_facet("r.kind", "filtered", passed)},
            'passed', {_facet("r.passed", "filtered", kind)},
            'days', (
                SELECT coalesce(json_agg(
                    json_build_object('date', date, 'count', count, 'passed', passed)
                    ORDER BY date ASC NULLS FIRST
                ), '[]'::json)
                FROM (
                    SELECT r.date, count(*)::int AS count,
                           (count(*) FILTER (WHERE r.passed IS TRUE))::int AS passed
                    FROM matching r
                    GROUP BY r.date
                ) day
            )
        )
    )
    """
    rows = list(store.query(statement, bind))
    return rows[0] if rows else {"total": 0, "items": [], "facets": EMPTY_FACETS}


def get_decision_detail(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One decision with every vote cast on it.

    Each vote is a VOTED edge — from a member on a roll-call, from a faction
    otherwise — so the voter's node carries the name to show. The most seats first, then
    by the voter's name and key.
    """
    rows = store.query(
        """
        SELECT d.id, d.key, d.type, d.labels, d.props, (
            SELECT coalesce(json_agg(
                json_build_object(
                    'voter_id', v.id,
                    'voter_key', v.key,
                    'name', CASE
                        WHEN coalesce(json_typeof(v.props -> 'abbreviation'), 'null')
                             <> 'null'
                        THEN v.props -> 'abbreviation' ELSE v.props -> 'name' END,
                    'choice', e.doc -> 'meta' -> 'choice',
                    'seats', e.doc -> 'meta' -> 'seats'
                )
                ORDER BY lg_num(e.doc -> 'meta' -> 'seats') DESC NULLS LAST,
                         v.name ASC NULLS FIRST, v.key ASC
            ), '[]'::json)
            FROM edges e
            JOIN LATERAL (
                SELECT id, key, props, name FROM members WHERE id = e.from_id
                UNION ALL
                SELECT id, key, props, name FROM factions WHERE id = e.from_id
            ) v ON true
            WHERE e.to_id = d.id AND e.relation = %(voted)s
        ) AS votes
        FROM decisions d
        WHERE d.key = %(key)s
        """,
        {"key": key, "voted": RELATION_VOTED},
    )
    row = next(rows, None)
    if row is None:
        return None
    # MERGE(decision, {votes}): the keys of the document in byte order, then ``votes``.
    doc = node_doc(row)
    return {
        "_id": doc["_id"],
        "_key": doc["_key"],
        "labels": doc["labels"],
        "props": doc["props"],
        "type": doc["type"],
        "votes": row["votes"],
    }


def get_decision_document(
    store: GraphStore, decision: dict[str, Any]
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

    # The candidates in their order; within a case the oldest document, as
    # ``_documents_by_case`` picks it (the key settles a tie).
    rows = store.query(
        f"""
        SELECT d.id, d.key, d.type, d.labels, d.props
        FROM edges e
        JOIN documents d ON d.id = e.from_id
        WHERE e.to_id = ANY(%(case_ids)s) AND e.relation = %(part_of)s
          AND e.from_collection = '{COLLECTION_DOCUMENTS}'
        ORDER BY array_position(%(case_ids)s::text[], e.to_id),
                 d.date ASC NULLS FIRST, d.key ASC
        LIMIT 1
        """,
        {
            "case_ids": [
                f"{COLLECTION_CASES}/{make_node_key(str(c))}" for c in candidates
            ],
            "part_of": RELATION_PART_OF,
        },
    )
    row = next(rows, None)
    return node_doc(row) if row else None
