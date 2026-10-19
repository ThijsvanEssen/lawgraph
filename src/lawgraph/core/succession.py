"""Old law to new law: where an official source places each article of the old law in the new
law of a recodification, checked against the text of both.

A reader of a source (``core.transposition_tables`` for a transposition table) gives rows: a
part of an old article and its place as the source writes it. ``place`` keeps a row whose
place is an article the new law holds, with every lid it names, from an article the old law
holds: those become one ``TRANSPOSED_TO`` per pair of articles, with the parts in its
``meta.parts``. Nothing is filled in or corrected: a row that does not hold, and an article of
the old law the source gives no article of the new law for, is a ``Gap``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

GapKind = Literal[
    # a row
    "unreadable",  # its place reads as no article and as no place that is none
    "no_old_article",  # the old law has no article of its number
    "no_new_article",  # the new law has no article of the number it names
    "no_lid",  # that article has no lid it names
    # an article of the old law, not repealed, that no row places in the new law
    "no_row",  # the source has no row for it
    "no_article",  # the source places it in no article ("vervallen", "Besluit B2")
    "not_placed",  # each of its places in an article is a gap above
]
ROW_GAPS: tuple[GapKind, ...] = (
    "unreadable",
    "no_old_article",
    "no_new_article",
    "no_lid",
)


@dataclass(frozen=True)
class Place:
    """A place in the new law a source gives: an article with the leden it names, or none."""

    text: str  # as the source writes it: "2.8.6, 1"
    article: str | None  # "2.8.6"; None for a place that is no article
    leden: tuple[str, ...]
    general: bool = False  # "algemene regeling 2.1.10": the general rule that covers it
    readable: bool = True


@dataclass(frozen=True)
class SourceRow:
    """A place the source gives a part of an article of the old law."""

    old_article: str  # "126ffa"
    part: str  # "2 a"; empty for the whole article
    place: Place
    where: str  # where in the source: "p. 94"


@dataclass(frozen=True)
class LawArticle:
    """An article of a law as the graph holds it."""

    id: str
    number: str
    leden: frozenset[str] = frozenset()
    repealed: bool = False


@dataclass(frozen=True)
class Gap:
    """A row that does not hold, or an article of the old law without a place."""

    kind: GapKind
    old_article: str
    part: str = ""
    text: str = ""  # the place as the source writes it; the places of an article
    where: str = ""


@dataclass
class Placed:
    """The pairs of articles with their parts (``{from, to}``), and the gaps."""

    pairs: dict[tuple[str, str], list[dict[str, str]]] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)


def place(
    rows: Iterable[SourceRow],
    old: dict[str, LawArticle],
    new: dict[str, LawArticle],
) -> Placed:
    """Check *rows* against the articles of the *old* and the *new* law (by number)."""
    placed = Placed()
    rows = list(rows)
    for row in rows:
        gap = _row_gap(row, old, new)
        if gap is not None:
            placed.gaps.append(
                Gap(gap, row.old_article, row.part, row.place.text, row.where)
            )
        elif row.place.article is not None:
            pair = (old[row.old_article].id, new[row.place.article].id)
            parts = placed.pairs.setdefault(pair, [])
            part = {"from": row.part, "to": row.place.text}
            if part not in parts:
                parts.append(part)
    placed.gaps += _articles_without_place(rows, old, {o for o, _ in placed.pairs})
    return placed


def _row_gap(
    row: SourceRow, old: dict[str, LawArticle], new: dict[str, LawArticle]
) -> GapKind | None:
    if not row.place.readable:
        return "unreadable"
    if row.old_article not in old:
        return "no_old_article"
    if row.place.article is None:
        return None
    article = new.get(row.place.article)
    if article is None:
        return "no_new_article"
    if not set(row.place.leden) <= article.leden:
        return "no_lid"
    return None


def _articles_without_place(
    rows: list[SourceRow], old: dict[str, LawArticle], placed: set[str]
) -> list[Gap]:
    """The articles of the old law in force that no row places in an article of the new
    law, in the order of their numbers in the source and then of the law."""
    by_article: dict[str, list[SourceRow]] = {}
    for row in rows:
        by_article.setdefault(row.old_article, []).append(row)
    gaps: list[Gap] = []
    for number, article in old.items():
        if article.repealed or article.id in placed:
            continue
        own = by_article.get(number, [])
        if not own:
            gaps.append(Gap("no_row", number))
        elif all(r.place.article is None and r.place.readable for r in own):
            texts = "; ".join(dict.fromkeys(r.place.text for r in own))
            gaps.append(Gap("no_article", number, text=texts, where=own[0].where))
        else:
            gaps.append(Gap("not_placed", number, where=own[0].where))
    return gaps
