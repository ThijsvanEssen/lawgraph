"""The lists the warm-up counts under the filters visitors choose: a small top of the facets
of the list itself, each asked as the explorer asks it."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import pytest

from lawgraph.api import warm
from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import DecisionFilters
from lawgraph.db.queries.judgments import JudgmentFilters

STORE = cast(GraphStore, object())


def _rows(*values: Any) -> list[dict[str, Any]]:
    return [{"value": value, "count": 1} for value in values]


def _run_all(parts: Iterable[warm.Part]) -> list[warm.Part]:
    found = list(parts)
    for part in found:
        part.run(STORE)
    return found


def test_the_judgments_by_a_top_of_their_facets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[JudgmentFilters] = []

    def listed(store: Any, filters: JudgmentFilters, limit: int) -> dict[str, Any]:
        asked.append(filters)
        return {
            "facets": {
                "tier": _rows("rechtbank", None, "hoge_raad"),
                "subject_area": _rows(*[f"area {n}" for n in range(9)]),
                # the source of nearly every judgment is nearly the whole list
                "source": _rows("rechtspraak", "echr"),
                "year": _rows(None, *[str(year) for year in range(2015, 2026)]),
            }
        }

    monkeypatch.setattr(warm, "get_judgments_list", listed)
    _run_all(warm._judgment_filters(STORE))
    assert asked == [
        JudgmentFilters(),
        JudgmentFilters(tiers=("rechtbank",)),
        JudgmentFilters(tiers=("hoge_raad",)),
        *(JudgmentFilters(subject_area=f"area {n}") for n in range(warm.WARM_TOP)),
        JudgmentFilters(source="echr"),
        # a bar of the explorer's axis: a whole year, the newest first
        *(
            JudgmentFilters(from_date=f"{year}-01-01", to_date=f"{year}-12-31")
            for year in range(2025, 2025 - warm.WARM_YEARS, -1)
        ),
    ]


def test_the_decisions_of_each_chamber(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[DecisionFilters] = []
    many = [f"kind {n}" for n in range(9)]

    def counts(store: Any, filters: DecisionFilters) -> dict[str, Any]:
        asked.append(filters)
        return {"facets": {"kind": _rows(*many)}}

    monkeypatch.setattr(warm, "decision_counts", counts)
    _run_all(warm._decision_filters(STORE))
    for chamber in ("TK", "EK"):
        assert DecisionFilters(chamber=chamber) in asked
        assert DecisionFilters(chamber=chamber, passed=True) in asked
        assert DecisionFilters(chamber=chamber, passed=False) in asked
        kinds = [f.kinds for f in asked if f.chamber == chamber and f.kinds]
        assert kinds == [(kind,) for kind in many[: warm.WARM_TOP]]


def test_the_documents_of_the_other_chamber_and_the_largest_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[Any, Any]] = []
    many = [f"kind {n}" for n in range(9)]

    def listed(store: Any, *, chambers: Any, limit: int, kinds: Any = None) -> Any:
        asked.append((chambers, kinds))
        return {"facets": {"kind": _rows(*many)}}

    monkeypatch.setattr(warm, "list_documents", listed)
    _run_all(warm._document_filters(STORE))
    assert (("EK",), None) in asked and (("TK", "EK"), None) in asked
    assert [kinds[0] for _c, kinds in asked if kinds] == many[: warm.WARM_TOP]
    assert {chambers for chambers, kinds in asked if kinds} == {("TK",)}


def test_the_instruments_by_jurisdiction_treaty_and_a_top_of_areas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[dict[str, Any]] = []

    def listed(store: Any, **filters: Any) -> dict[str, Any]:
        asked.append(filters)
        return {
            "facets": {
                # the key of a concept in the explorer's URL: its slug, else its id
                "legal_area": [
                    {"slug": None, "id": None},
                    {"slug": None, "id": "c2"},
                    *({"slug": f"area-{n}", "id": f"a{n}"} for n in range(9)),
                ],
                "policy_domain": [{"slug": "zorg", "id": "c3"}],
            }
        }

    monkeypatch.setattr(warm, "get_instruments_list", listed)
    _run_all(warm._instrument_filters(STORE))
    base = {"article_count_min": 1, "limit": 1}
    assert asked == [
        base,
        {**base, "jurisdiction": "nl"},
        {**base, "jurisdiction": "eu"},
        {**base, "kind": "verdrag"},
        {**base, "legal_area": "c2"},
        *({**base, "legal_area": f"area-{n}"} for n in range(warm.WARM_TOP - 1)),
        {**base, "policy_domain": "zorg"},
    ]


def test_the_lists_in_their_order_each_filter_its_own_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = (
        "_decision_filters",
        "_document_filters",
        "_instrument_filters",
        "_judgment_filters",
    )
    for name in order:
        monkeypatch.setattr(
            warm, name, lambda store, name=name: [warm.Part(name, print)]
        )
    found = [part.name for part in warm._common_filter_parts(STORE)]
    assert tuple(found) == order
