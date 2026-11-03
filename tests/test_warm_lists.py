"""The lists the warm-up counts under the filters visitors choose: the values come from the
facets of the list itself, each asked as the explorer asks it."""

from __future__ import annotations

from typing import Any, cast

import pytest

from lawgraph.api import warm_lists
from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import DecisionFilters
from lawgraph.db.queries.judgments import JudgmentFilters

STORE = cast(GraphStore, object())


def _rows(*values: Any) -> list[dict[str, Any]]:
    return [{"value": value, "count": 1} for value in values]


def test_the_judgments_by_their_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[JudgmentFilters] = []

    def listed(store: Any, filters: JudgmentFilters, limit: int) -> dict[str, Any]:
        asked.append(filters)
        return {
            "facets": {
                "tier": _rows("rechtbank", None, "hoge_raad"),
                "subject_area": _rows("Strafrecht"),
                # the source of nearly every judgment is nearly the whole list
                "source": _rows("rechtspraak", "echr", "cjeu"),
                "year": _rows(None, "2023", "2024"),
            }
        }

    monkeypatch.setattr(warm_lists, "get_judgments_list", listed)
    for _name, ask in warm_lists._judgments(STORE):
        ask()
    assert asked == [
        JudgmentFilters(),
        JudgmentFilters(tiers=("rechtbank",)),
        JudgmentFilters(tiers=("hoge_raad",)),
        JudgmentFilters(subject_area="Strafrecht"),
        JudgmentFilters(source="echr"),
        JudgmentFilters(source="cjeu"),
        # a bar of the explorer's axis: a whole year, the newest first
        JudgmentFilters(from_date="2024-01-01", to_date="2024-12-31"),
        JudgmentFilters(from_date="2023-01-01", to_date="2023-12-31"),
    ]


def test_the_years_are_those_of_the_axis(monkeypatch: pytest.MonkeyPatch) -> None:
    years = [str(year) for year in range(1950, 2026)]
    monkeypatch.setattr(
        warm_lists,
        "get_judgments_list",
        lambda *a, **k: {"facets": {"year": _rows(*years)}},
    )
    names = [name for name, _ask in warm_lists._judgments(STORE)]
    assert len(names) == warm_lists.WARM_YEARS == 40
    assert names[0].endswith("2025") and names[-1].endswith("1986")


def test_the_decisions_of_each_chamber(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[DecisionFilters] = []

    def counts(store: Any, filters: DecisionFilters) -> dict[str, Any]:
        asked.append(filters)
        return {"facets": {"kind": _rows("Motie")}}

    monkeypatch.setattr(warm_lists, "decision_counts", counts)
    for _name, ask in warm_lists._decisions(STORE):
        ask()
    for chamber in ("TK", "EK"):
        assert DecisionFilters(chamber=chamber) in asked
        assert DecisionFilters(chamber=chamber, kinds=("Motie",)) in asked
        assert DecisionFilters(chamber=chamber, passed=True) in asked
        assert DecisionFilters(chamber=chamber, passed=False) in asked


def test_the_documents_of_each_chamber_and_the_largest_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[Any, Any]] = []
    many = [f"kind {n}" for n in range(9)]

    def listed(store: Any, *, chambers: Any, limit: int, kinds: Any = None) -> Any:
        asked.append((chambers, kinds))
        return {"facets": {"kind": _rows(*many)}}

    monkeypatch.setattr(warm_lists, "list_documents", listed)
    for _name, ask in warm_lists._documents(STORE):
        ask()
    assert (("EK",), None) in asked and (("TK", "EK"), None) in asked
    assert [kinds[0] for _c, kinds in asked if kinds] == many[
        : warm_lists.WARM_DOCUMENT_KINDS
    ]
    assert {chambers for chambers, kinds in asked if kinds} == {("TK",)}


def test_the_instruments_by_area_theme_jurisdiction_and_treaty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[dict[str, Any]] = []

    def listed(store: Any, **filters: Any) -> dict[str, Any]:
        asked.append(filters)
        return {
            "facets": {
                # the key of a concept in the explorer's URL: its slug, else its id
                "legal_area": [
                    {"slug": "staatsrecht", "id": "c1"},
                    {"slug": None, "id": "c2"},
                    {"slug": None, "id": None},
                ],
                "policy_domain": [{"slug": "zorg", "id": "c3"}],
            }
        }

    monkeypatch.setattr(warm_lists, "get_instruments_list", listed)
    for _name, ask in warm_lists._instruments(STORE):
        ask()
    base = {"article_count_min": 1, "limit": 1}
    assert asked == [
        base,
        {**base, "jurisdiction": "nl"},
        {**base, "jurisdiction": "eu"},
        {**base, "kind": "verdrag"},
        {**base, "legal_area": "staatsrecht"},
        {**base, "legal_area": "c2"},
        {**base, "policy_domain": "zorg"},
    ]


def test_the_lists_in_their_order(monkeypatch: pytest.MonkeyPatch) -> None:
    order = ("_decisions", "_documents", "_instruments", "_judgments")
    for name in order:
        monkeypatch.setattr(
            warm_lists, name, lambda store, name=name: [(name, lambda: None)]
        )
    found = [name for name, _ask in warm_lists.common_filters(STORE)]
    assert tuple(found) == order
