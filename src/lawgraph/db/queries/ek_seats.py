"""The seats of the Eerste Kamer per term and stretch (``lg_ek_terms``, ``lg_ek_seats``):
written whole by ``normalize eerstekamer-mutations``, read by the seats of a cabinet and of
the parliament on a day."""

from __future__ import annotations

import json
from typing import Any

from lawgraph.db import GraphStore


def write(
    store: Any, terms: list[dict[str, Any]], stretches: list[dict[str, Any]]
) -> None:
    """Replace every term and stretch, in one transaction."""
    with store.pool.connection() as conn, conn.transaction():
        conn.execute("DELETE FROM lg_ek_seats")
        conn.execute("DELETE FROM lg_ek_terms")
        for term in terms:
            conn.execute(
                "INSERT INTO lg_ek_terms (start, election, source, checked, mismatches)"
                " VALUES (%s, %s, %s, %s, %s)",
                (
                    term["start"],
                    term["election"],
                    json.dumps(term["source"]),
                    term["checked"],
                    json.dumps(term["mismatches"], ensure_ascii=False),
                ),
            )
        for stretch in stretches:
            conn.execute(
                "INSERT INTO lg_ek_seats (from_date, to_date, term, seats, events)"
                " VALUES (%s, %s, %s, %s, %s)",
                (
                    stretch["from_date"],
                    stretch["to_date"],
                    stretch["term"],
                    json.dumps(stretch["seats"], ensure_ascii=False),
                    json.dumps(stretch["events"], ensure_ascii=False),
                ),
            )


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
