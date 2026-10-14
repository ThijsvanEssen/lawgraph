"""The seats of the Eerste Kamer per term and stretch (``lg_ek_terms``, ``lg_ek_seats``):
written whole by ``normalize eerstekamer-mutations``, read by the seats of a cabinet and of
the parliament on a day."""

from __future__ import annotations

import json
from functools import partial
from typing import Any

from psycopg.types.json import Json

from lawgraph.db import GraphStore


def write(
    store: Any, terms: list[dict[str, Any]], stretches: list[dict[str, Any]]
) -> None:
    """Replace every term and stretch, in one transaction."""
    store.execute_together(
        [
            ("DELETE FROM lg_ek_seats", None),
            ("DELETE FROM lg_ek_terms", None),
            (
                "INSERT INTO lg_ek_terms (start, election, source, checked, mismatches)"
                " SELECT * FROM json_to_recordset(%(rows)s::json) AS r(start text,"
                " election text, source json, checked boolean, mismatches json)",
                {"rows": _json(terms)},
            ),
            (
                "INSERT INTO lg_ek_seats (from_date, to_date, term, seats, events)"
                " SELECT * FROM json_to_recordset(%(rows)s::json) AS r(from_date text,"
                " to_date text, term text, seats json, events json)",
                {"rows": _json(stretches)},
            ),
        ]
    )


def _json(rows: list[dict[str, Any]]) -> Json:
    return Json(rows, dumps=partial(json.dumps, ensure_ascii=False))


def stretches_between(store: GraphStore, start: str, end: str) -> list[dict[str, Any]]:
    """The stretches that overlap *start* to *end*, oldest first, each with whether its term
    is ``checked``: ``{from_date, to_date, seats, events, checked}``."""
    return list(
        store.query(
            """
            SELECT s.from_date, s.to_date, s.seats, s.events, t.checked
            FROM lg_ek_seats s
            JOIN lg_ek_terms t ON t.start = s.term
            WHERE s.from_date <= %(end)s AND (s.to_date IS NULL OR s.to_date >= %(start)s)
            ORDER BY s.from_date ASC NULLS LAST
            """,
            {"start": start, "end": end},
        )
    )


def stretch_on(store: GraphStore, day: str) -> dict[str, Any] | None:
    """The stretch of the Eerste Kamer that holds *day*, with whether its term is
    ``checked``; None for a day before the first term known."""
    return next(
        iter(
            store.query(
                """
                SELECT s.from_date, s.to_date, s.seats, s.events, t.checked, t.source
                FROM lg_ek_seats s
                JOIN lg_ek_terms t ON t.start = s.term
                WHERE s.from_date <= %(day)s AND (s.to_date IS NULL OR s.to_date >= %(day)s)
                ORDER BY s.from_date DESC NULLS LAST
                LIMIT 1
                """,
                {"day": day},
            )
        ),
        None,
    )


def events(store: Any) -> list[dict[str, Any]]:
    """Every change of the stretches (``kind``, ``date``, ``member``) and the first day of
    every term: what the periods of a member's page are checked against."""
    rows = store.query(
        """
        SELECT e ->> 'kind' AS kind, e ->> 'date' AS date, e ->> 'member' AS member
        FROM lg_ek_seats s, json_array_elements(s.events) AS e
        UNION ALL
        SELECT 'term', t.start, NULL FROM lg_ek_terms t
        """
    )
    return list(rows)
