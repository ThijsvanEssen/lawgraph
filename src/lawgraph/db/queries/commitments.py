"""Queries behind the commitment endpoints."""

from __future__ import annotations

from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_ABOUT,
    RELATION_ANSWERS,
    RELATION_MADE_IN,
)
from lawgraph.core.time import dutch_today
from lawgraph.core.tk_records.commitments import COMMITMENT_OPEN, NO_DUE_DATE
from lawgraph.db import GraphStore
from lawgraph.db.queries import _words
from lawgraph.db.queries._lists import FacetFilters, facet
from lawgraph.db.queries.cabinets import person_object
from lawgraph.db.schema import search_words

# What a commitment item shows beside its own props: who made it, its dossiers (with the
# basis of each: ``core/provenance.py``), the activity it was made in and the letters that fulfil it (``ANSWERS``, light).
_COMMITMENT_ITEM = f"""json_build_object(
    'commitment', json_build_object(
        'key', c.key, 'id', c.id, 'type', c.type, 'labels', to_json(c.labels),
        'props', c.props
    ),
    'member', (
        SELECT {person_object("m")} FROM members m WHERE m.key = c.member_key
    ),
    'dossiers', (
        SELECT coalesce(json_agg(json_build_object(
            'key', d.key, 'number', d.props -> 'label', 'title', d.props -> 'title',
            'basis', e.doc -> 'meta' -> 'basis'
        ) ORDER BY d.label ASC NULLS FIRST, d.key ASC), '[]'::json)
        FROM edges e JOIN dossiers d ON d.id = e.to_id
        WHERE e.from_id = c.id AND e.relation = %(about)s
          AND e.to_collection = '{COLLECTION_DOSSIERS}'
    ),
    'activity', (
        SELECT json_build_object(
            'key', a.key, 'date', a.props -> 'date', 'number', a.props -> 'number',
            'kind', a.props -> 'kind', 'agenda_title', a.props -> 'agenda_title'
        )
        FROM edges e JOIN activities a ON a.id = e.to_id
        WHERE e.from_id = c.id AND e.relation = %(made_in)s
          AND e.to_collection = '{COLLECTION_ACTIVITIES}'
        ORDER BY e.to_id ASC
        LIMIT 1
    ),
    'fulfilled_by', (
        SELECT coalesce(json_agg(json_build_object(
            'id', l.id, 'key', split_part(l.id, '/', 2), 'kind', l.props -> 'kind',
            'date', l.props -> 'date',
            'title', l.props -> 'title', 'dossier_number', l.props -> 'dossier_number',
            'dossier_suffix', l.props -> 'dossier_suffix',
            'sequence', l.props -> 'sequence'
        ) ORDER BY lg_str(l.props -> 'date') ASC NULLS LAST, l.id), '[]'::json)
        FROM edges e JOIN lg_document_light l ON l.id = e.from_id
        WHERE e.to_id = c.id AND e.relation = %(answers)s
          AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    )
)"""


# The dimensions a commitment list counts as facets, and the column each counts.
_COMMITMENT_FACETS = {
    "status": "c.status",
    "cabinet": "c.cabinet",
    "ministry": "c.ministry",
}

# The words of a commitment: its text and number, folded as the search folds them
# (``lg_fold``: lower case, no accents), so ``ecole`` finds the école. Tested row by row:
# the index on its words (``search_words``) is not folded.
_WORDS = f"lg_fold({search_words(COLLECTION_COMMITMENTS, 'c')})"

# The day a commitment is expected to be resolved (a string), or the placeholder of none;
# one without it is due before every day.
_EXPECTED = "(c.props ->> 'expected_resolution')"
_DATED = f"{_EXPECTED} IS DISTINCT FROM %(no_date)s"


def _expected_before(day: str) -> str:
    return f"coalesce({_EXPECTED} < %({day})s, true)"


# The orders of the list; the key settles ties. Soonest due puts those without a date (or
# with the placeholder of none) last.
_COMMITMENT_SORTS = {
    "date": "c.made_on DESC NULLS LAST, c.key ASC",
    "expected_resolution": (
        f"coalesce({_EXPECTED} = %(no_date)s, true) ASC,"
        f" {_EXPECTED} ASC NULLS FIRST, c.made_on DESC NULLS LAST, c.key ASC"
    ),
}


def _commitment_filters(
    bind: dict[str, Any],
    *,
    member: str | None,
    dossier: str | None,
    due_before: str | None,
    overdue: bool,
    q: tuple[tuple[str, ...], ...],
    made_from: str | None = None,
    made_to: str | None = None,
) -> list[str]:
    """The conditions on the commitment ``c`` of every count, their values in *bind*."""
    shared: list[str] = []
    # the day it was made, inclusive (``commitments_made_on``)
    if made_from:
        shared.append("c.made_on >= %(made_from)s")
        bind["made_from"] = made_from
    if made_to:
        shared.append("c.made_on <= %(made_to)s")
        bind["made_to"] = made_to
    if member:
        shared.append("c.member_key = %(member)s")
        bind["member"] = member
    if due_before:
        shared.append(f"{_DATED} AND {_expected_before('due_before')}")
        bind["due_before"] = due_before
        bind["no_date"] = NO_DUE_DATE
    if overdue:
        shared.append(
            f"c.status = %(open)s AND {_DATED} AND {_expected_before('today')}"
        )
        bind["open"] = COMMITMENT_OPEN
        bind["no_date"] = NO_DUE_DATE
        bind["today"] = dutch_today().isoformat()
    shared += _words.any_query(q, _WORDS, bind, indexed=False)
    if dossier:
        shared.append(
            """EXISTS (
                SELECT 1 FROM edges e JOIN dossiers d ON d.id = e.to_id
                WHERE e.from_id = c.id AND e.relation = %(about)s
                  AND (d.label = %(dossier)s OR d.number = %(dossier)s)
            )"""
        )
        bind["dossier"] = dossier
    return shared


def get_commitments(
    store: GraphStore,
    *,
    status: str | None = None,
    member: str | None = None,
    cabinet: str | None = None,
    ministry: str | None = None,
    dossier: str | None = None,
    due_before: str | None = None,
    overdue: bool = False,
    q: tuple[tuple[str, ...], ...] = (),
    sort: str = "date",
    limit: int = 100,
    offset: int = 0,
    made_from: str | None = None,
    made_to: str | None = None,
    facets: bool = True,
) -> dict[str, Any]:
    """A page of commitments, the total and ``facets``: per ``status``, ``cabinet`` and
    ``ministry`` the number of commitments per value under the other filters, each
    dimension counted without its own filter (``facets=False``: the page and the total
    alone, ``facets`` None). *q* the queries, any of them, each the words of which the
    text or number holds every one, in any order (``_words.any_query``). *dossier* is a number (``36600``) or the
    label of a dossier (``36600-VII``); *overdue* keeps the open ones whose expected date
    has passed; *made_from* and *made_to* the first and last day it was made on; *sort* is ``date`` (newest made first) or ``expected_resolution`` (soonest
    first, those without one last)."""
    own: dict[str, str] = {}
    bind: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "about": RELATION_ABOUT,
        "made_in": RELATION_MADE_IN,
        "answers": RELATION_ANSWERS,
    }
    for name, value in (
        ("status", status),
        ("cabinet", cabinet),
        ("ministry", ministry),
    ):
        if value:
            own[name] = f"{_COMMITMENT_FACETS[name]} = %({name})s"
            bind[name] = value
    shared = _commitment_filters(
        bind,
        member=member,
        dossier=dossier,
        due_before=due_before,
        overdue=overdue,
        q=q,
        made_from=made_from,
        made_to=made_to,
    )
    if sort == "expected_resolution":
        bind["no_date"] = NO_DUE_DATE
    order = _COMMITMENT_SORTS.get(sort, _COMMITMENT_SORTS["date"])

    filters = FacetFilters(shared, own)
    per_facet = ",\n".join(
        f"'{name}', {facet(column, 'commitments c', filters.where(name))}"
        for name, column in _COMMITMENT_FACETS.items()
    )
    statement = f"""
    WITH matching AS MATERIALIZED (
        SELECT c.id FROM commitments c {filters.where()}
    )
    SELECT json_build_object(
        'total', (SELECT count(*)::int FROM matching),
        'items', (
            SELECT coalesce(json_agg({_COMMITMENT_ITEM} ORDER BY page.n), '[]'::json)
            FROM (
                SELECT c.id, row_number() OVER (ORDER BY {order}) AS n
                FROM matching JOIN commitments c ON c.id = matching.id
                ORDER BY {order}
                LIMIT %(limit)s OFFSET %(offset)s
            ) page
            JOIN commitments c ON c.id = page.id
        ),
        'facets', {f"json_build_object({per_facet})" if facets else "NULL::json"}
    )
    """
    rows = list(store.query(statement, bind))
    return (
        cast(dict[str, Any], rows[0])
        if rows
        else {"total": 0, "items": [], "facets": {}}
    )


def get_commitment(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One commitment as a list item; None when unknown."""
    rows = store.query(
        f"SELECT {_COMMITMENT_ITEM} FROM commitments c WHERE c.key = %(key)s",
        {
            "key": key,
            "about": RELATION_ABOUT,
            "made_in": RELATION_MADE_IN,
            "answers": RELATION_ANSWERS,
        },
    )
    return cast(dict[str, Any] | None, next(rows, None))
