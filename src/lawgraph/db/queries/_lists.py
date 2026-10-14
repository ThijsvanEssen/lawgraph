"""The parts of the SQL of a list with facets: its ``WHERE``, its filters per facet, a facet
(the rows per value, most first) and a page with its total."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


def where(clauses: Iterable[str]) -> str:
    """SQL: ``WHERE`` each of *clauses*; empty without one."""
    joined = " AND ".join(f"({clause})" for clause in clauses)
    return f"WHERE {joined}" if joined else ""


@dataclass(frozen=True)
class FacetFilters:
    """The filters of a list with facets: *shared* hold for the list and every facet, each
    of *own* (by the dimension of its facet) for the list and every facet but its own."""

    shared: list[str] = field(default_factory=list)
    own: dict[str, str] = field(default_factory=dict)

    def clauses(self, *leave_out: str) -> list[str]:
        """The filters, without the own filters of the dimensions *leave_out*."""
        kept = (clause for name, clause in self.own.items() if name not in leave_out)
        return [*self.shared, *kept]

    def where(self, *leave_out: str) -> str:
        """SQL: ``WHERE`` the filters, without the own filters of *leave_out*."""
        return where(self.clauses(*leave_out))


# SQL: the rows of a facet (``value``, ``count``) as a JSON array ``[{value, count}]``, most
# first, then by value.
FACET_AGG = (
    "coalesce(json_agg(json_build_object('value', value, 'count', count)"
    " ORDER BY count DESC, value ASC NULLS FIRST), '[]'::json)"
)


def counted(value: str, rows: str, condition: str = "") -> str:
    """SQL: the rows *rows* (a ``FROM`` item) under *condition* (a ``WHERE``) per *value*:
    ``value`` and ``count``."""
    return (
        f"SELECT {value} AS value, count(*)::int AS count"
        f" FROM {rows} {condition} GROUP BY 1"
    )


def facet_of(rows: str) -> str:
    """SQL: the facet of *rows* (a ``SELECT`` of ``value`` and ``count``): ``FACET_AGG``."""
    return f"(SELECT {FACET_AGG} FROM ({rows}) counted)"


def facet(value: str, rows: str, condition: str = "") -> str:
    """SQL: the facet of the rows *rows* under *condition* per *value* (``counted``), as
    a JSON array (``FACET_AGG``)."""
    return facet_of(counted(value, rows, condition))


def facet_rows(
    value: str, rows: str, condition: str = "", *, by_count: bool = True
) -> str:
    """SQL: the facet of ``facet`` as rows (``value``, ``count``): most first, then by
    value; without *by_count* by value alone."""
    order = "count DESC, value ASC NULLS FIRST" if by_count else "value ASC NULLS FIRST"
    return f"{counted(value, rows, condition)} ORDER BY {order}"


def paged(rows: str, page: str) -> str:
    """SQL: a page and the total in one statement: every row carries ``total`` (the rows
    of *rows*, a ``FROM`` item), the rows of *page* their place ``n``; a page past the end
    is one row with the total alone (``n`` null). *page* selects ``row_number() OVER (...)
    AS n``, orders by it and pages."""
    return f"""
        SELECT t.total, p.*
        FROM (SELECT count(*)::int AS total FROM {rows}) t
        LEFT JOIN ({page}) p ON true
        ORDER BY p.n
    """


def page_of(rows: str, order: str) -> str:
    """SQL: the page (``%(limit)s``, ``%(offset)s``) of the rows *rows* in *order*, each
    with its place ``n``: the *page* of ``paged``."""
    return (
        f"SELECT *, row_number() OVER (ORDER BY {order}) AS n FROM {rows}"
        f" ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s"
    )


def split_page(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The rows of a ``paged`` statement as (the rows of the page, the total)."""
    found = list(rows)
    total = int(found[0]["total"]) if found else 0
    return [row for row in found if row["n"] is not None], total


def without_page(bind: dict[str, Any]) -> dict[str, Any]:
    """*bind* without the page (``limit``, ``offset``): what a count, the same on every
    page, is kept under (``version_cache``)."""
    return {k: v for k, v in bind.items() if k not in ("limit", "offset")}
