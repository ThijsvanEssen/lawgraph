"""The total and facets of the lists under the filters visitors choose most, counted by the
warm-up (``warm._warm_common_filters``) after it is ``warm``: a wide filter counts every row
under it, minutes cold on prod, and the visitor who chooses it first would see no counts.
Which values there are comes from the facets of the list itself; each is asked with the
filters the explorer sends, as the answers are kept per filter. ``limit=1``: the page of a
list is read fresh, what is kept are its counts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from functools import partial
from typing import Any

from lawgraph.config.constants import CHAMBER_TK, CHAMBERS, KIND_TREATY
from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import DecisionFilters, decision_counts
from lawgraph.db.queries.documents import list_documents
from lawgraph.db.queries.instruments import get_instruments_list
from lawgraph.db.queries.judgments import JudgmentFilters, get_judgments_list

# One filter of a list: its name in the log and what counts it.
Filter = tuple[str, Callable[[], object]]

# The bars of the year axis of the judgments (the last forty, ``JudgmentYears`` of the explorer).
WARM_YEARS = 40
# The kinds of paper counted, the most papers first: each reads every paper of its chamber
# again after a poll, where the total and facets of the judgments last an hour.
WARM_DOCUMENT_KINDS = 5
# The jurisdictions of the filter of the list of laws (no facet counts them).
_JURISDICTIONS = ("nl", "eu")


def _values(rows: list[dict[str, Any]] | None) -> list[Any]:
    """The values of the rows of a facet, without the rows that have none."""
    return [row["value"] for row in rows or [] if row.get("value")]


def _judgments(store: GraphStore) -> Iterator[Filter]:
    """Each court (``tier``), main area of law and source but the largest (nearly the whole
    list, and no list asks it), and each year of the axis, the newest first."""

    def listed(**filters: Any) -> Callable[[], dict[str, Any]]:
        return partial(get_judgments_list, store, JudgmentFilters(**filters), limit=1)

    facets = listed()()["facets"] or {}
    for tier in _values(facets.get("tier")):
        yield f"judgments of {tier}", listed(tiers=(tier,))
    for area in _values(facets.get("subject_area")):
        yield f"judgments in {area}", listed(subject_area=area)
    for source in _values(facets.get("source"))[1:]:
        yield f"judgments of {source}", listed(source=source)
    years = sorted(_values(facets.get("year")), reverse=True)[:WARM_YEARS]
    for year in years:
        whole = {"from_date": f"{year}-01-01", "to_date": f"{year}-12-31"}
        yield f"judgments of {year}", listed(**whole)


def _instruments(store: GraphStore) -> Iterator[Filter]:
    """As the list of laws opens (with an article): each jurisdiction, the treaties (the
    count beside Verdragen), each main area of law and each theme, by the key of its concept
    in the URL (its slug, else its id)."""

    def listed(**filters: Any) -> Callable[[], dict[str, Any]]:
        return partial(
            get_instruments_list, store, article_count_min=1, limit=1, **filters
        )

    facets = listed()()["facets"] or {}
    for jurisdiction in _JURISDICTIONS:
        yield f"instruments of {jurisdiction}", listed(jurisdiction=jurisdiction)
    yield "treaties", listed(kind=KIND_TREATY)
    for name in ("legal_area", "policy_domain"):
        for concept in facets.get(name) or []:
            key = concept.get("slug") or concept.get("id")
            if key:
                yield f"instruments of {name} {key}", listed(**{name: key})


def _documents(store: GraphStore) -> Iterator[Filter]:
    """Each chamber and both, and the largest kinds of the Tweede Kamer, the list it opens."""

    def listed(
        chambers: tuple[str, ...], **filters: Any
    ) -> Callable[[], dict[str, Any]]:
        return partial(list_documents, store, chambers=chambers, limit=1, **filters)

    for chamber in CHAMBERS:
        yield f"documents of {chamber}", listed((chamber,))
    yield "documents of both chambers", listed(CHAMBERS)
    facets = listed((CHAMBER_TK,))()["facets"] or {}
    for kind in _values(facets.get("kind"))[:WARM_DOCUMENT_KINDS]:
        yield f"documents of {CHAMBER_TK}: {kind}", listed((CHAMBER_TK,), kinds=(kind,))


def _decisions(store: GraphStore) -> Iterator[Filter]:
    """Of each chamber: its list, each kind and each outcome."""
    for chamber in CHAMBERS:
        base = DecisionFilters(chamber=chamber)
        facets = decision_counts(store, base)["facets"] or {}
        for kind in _values(facets.get("kind")):
            filters = replace(base, kinds=(kind,))
            yield (
                f"decisions of {chamber}: {kind}",
                partial(decision_counts, store, filters),
            )
        for passed in (True, False):
            filters = replace(base, passed=passed)
            yield (
                f"decisions of {chamber}: passed {passed}",
                partial(decision_counts, store, filters),
            )


def common_filters(store: GraphStore) -> Iterator[Filter]:
    """Every filter, the lists that count quickly first: a warm-up that newer data stops
    finds these kept the next time, and goes on where it stopped."""
    yield from _decisions(store)
    yield from _documents(store)
    yield from _instruments(store)
    yield from _judgments(store)
