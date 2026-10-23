"""How many hits a search of a type has, and how they divide over the values of its facets
(``SearchType.facets``): over the rows that hold the words, not ranked, so that it costs
what finding them costs. Past ``COUNT_CAP`` rows it stops: the count is then a lower bound
(``Counted.capped``) and the facets are those of the rows found first."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from lawgraph.db.queries.search.clause import build_search_clause
from lawgraph.db.queries.search.spec import Asked, SearchType

# The most rows counted per type. A common word holds tens of thousands of judgments; the
# first this many found tell the divisions well enough, and reading them stays within
# milliseconds.
COUNT_CAP = 5000


@dataclass(frozen=True)
class Counted:
    """The rows a search matches: their number (at least that many when *capped*) and,
    per facet, its values with their counts, in the order of the facet."""

    total: int
    capped: bool
    facets: dict[str, list[tuple[str | None, int]]]


def count_type(kind: SearchType, asked: Asked) -> Counted:
    """The rows of *kind* that hold the words of *asked* (``SearchType.match``), at most
    ``COUNT_CAP`` of them, counted in one pass per facet set (``GROUPING SETS``)."""
    assert kind.match is not None
    match = kind.match(kind, asked)
    clause, params = build_search_clause(
        kind.table,
        match.tokens,
        kind.fields,
        termed=match.termed,
        laws=match.laws,
        any_word=asked.any_word,
    )
    # OFFSET 0 plans the matches on their own, from the indexes of the words (as
    # ``text.text_query`` does); the cap stops the heap reads of a bitmap scan early
    found = f"SELECT * FROM {kind.table} r WHERE {clause} {match.where} OFFSET 0"
    statement_params: dict[str, Any] = {
        **params,
        **match.params,
        "_cap": COUNT_CAP,
    }
    facets = kind.facets
    values = ", ".join(f"{facet.sql} AS f{n}" for n, facet in enumerate(facets))
    sets = "".join(f"(f{n}), " for n in range(len(facets)))
    grouped = ", ".join(f"grouping(f{n}) AS g{n}, f{n}" for n in range(len(facets)))
    statement = (
        f"SELECT {grouped + ', ' if grouped else ''}count(*) AS n"
        f" FROM (SELECT {values or '1 AS one'} FROM ({found}) r LIMIT %(_cap)s) c"
        + (f" GROUP BY GROUPING SETS ({sets}())" if facets else "")
    )
    rows = list(asked.store.query(statement, statement_params, indexes_only=True))
    if not facets:
        total = int(rows[0])  # the one column of the one row
        return Counted(total, total >= COUNT_CAP, {})
    total = next(
        int(r["n"]) for r in rows if all(r[f"g{n}"] for n in range(len(facets)))
    )
    counted: dict[str, list[tuple[str | None, int]]] = {}
    for n, facet in enumerate(facets):
        merged: Counter[str | None] = Counter()
        for row in rows:
            if not row[f"g{n}"]:
                merged[facet.value_of(row[f"f{n}"])] += int(row["n"])
        counted[facet.name] = _ordered(merged, facet.by_value)
    return Counted(total, total >= COUNT_CAP, counted)


def _ordered(
    counts: Counter[str | None], by_value: bool
) -> list[tuple[str | None, int]]:
    """The values with their counts, largest count first (the greatest value first with
    *by_value*); the rows without a value last."""
    held = [(v, n) for v, n in counts.items() if v is not None]
    if by_value:
        held.sort(key=lambda item: item[0] or "", reverse=True)
    else:
        held.sort(key=lambda item: (-item[1], item[0] or ""))
    return held + ([(None, counts[None])] if None in counts else [])
