"""The judgments that cite a law, kept in columns (``db/queries/law_citations.py``)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lawgraph.db.queries import law_citations
from lawgraph.db.queries.law_citations import LawCitations


@pytest.fixture(autouse=True)
def _forget() -> Iterator[None]:
    law_citations.forget()
    yield
    law_citations.forget()


def row(
    judgment_id: str,
    date: str | None,
    tier: str | None,
    cited: float | None = 0,
    count: int = 1,
    areas: list[str] | None = None,
) -> dict[str, object]:
    return {
        "judgment_id": judgment_id,
        "date_eff": date,
        "tier": tier,
        "cited": cited,
        "cited_count": count,
        "areas": areas,
    }


# in the order of the ids, as the database hands them over
ROWS = [
    row("a", "2020-05-01", "hoge_raad", 5, 2, ["Strafrecht"]),
    row("b", "2021-01-01", "rechtbank", 1, 1, ["Civiel recht", "Strafrecht"]),
    row("c", None, "rechtbank", None, 3, None),
    row("d", "2021-01-01", None, 9, 1, ["Civiel recht"]),
    row("e", "2020-12-31", "hoge_raad", 5, 2, ["Strafrecht"]),
]


def ids_of(sort: str = "date", **kw: object) -> list[str]:
    found = LawCitations(ROWS).read(
        sort,
        kw.pop("limit", 10),  # type: ignore[arg-type]
        kw.pop("offset", 0),  # type: ignore[arg-type]
        kw.pop("year", None),  # type: ignore[arg-type]
        kw.pop("tiers", ()),  # type: ignore[arg-type]
        kw.pop("area", None),  # type: ignore[arg-type]
    )
    assert found is not None
    return found.ids


def test_the_newest_come_first_then_the_id_and_a_missing_date_last() -> None:
    assert ids_of("date") == ["b", "d", "e", "a", "c"]


def test_the_judgments_citing_most_articles_come_first_then_the_newest() -> None:
    assert ids_of("cited") == ["c", "e", "a", "b", "d"]


def test_the_most_cited_judgment_comes_first_a_missing_count_last() -> None:
    assert ids_of("citation_count") == ["d", "e", "a", "b", "c"]


def test_a_page_is_cut_from_the_order() -> None:
    assert ids_of("date", limit=2, offset=1) == ["d", "e"]
    assert ids_of("date", limit=2, offset=4) == ["c"]
    assert ids_of("date", offset=9) == []


def test_a_page_counts_only_the_judgments_under_the_filters() -> None:
    assert ids_of(year="2021") == ["b", "d"]
    assert ids_of(tiers=("hoge_raad", "rechtbank")) == ["b", "e", "a", "c"]
    assert ids_of(area="Strafrecht") == ["b", "e", "a"]
    assert ids_of(year="2021", tiers=("rechtbank",), area="Strafrecht") == ["b"]
    assert ids_of(year="1800") == []


def test_the_counts_leave_out_their_own_filter() -> None:
    found = LawCitations(ROWS).read("date", 10, 0, "2021", ("rechtbank",), None)
    assert found is not None
    counts = found.counts
    assert counts.total == 1
    # years: under the tiers and area, whatever the year; no date first
    assert counts.years == [
        {"value": None, "count": 1},
        {"value": "2021", "count": 1},
    ]
    # tiers: under the year and area, whatever the tiers; the most first, none last
    assert counts.tiers == [
        {"value": "rechtbank", "count": 1},
        {"value": None, "count": 1},
    ]
    # areas: under the year and tiers; a judgment counts for each of its areas
    assert counts.areas == [
        {"value": "Civiel recht", "count": 1},
        {"value": "Strafrecht", "count": 1},
    ]


def test_without_filters_every_judgment_is_counted() -> None:
    found = LawCitations(ROWS).read("date", 10, 0, None, (), None)
    assert found is not None
    assert found.counts.total == 5
    assert found.counts.tiers[0] == {"value": "hoge_raad", "count": 2}
    assert found.counts.areas == [
        {"value": "Strafrecht", "count": 3},
        {"value": "Civiel recht", "count": 2},
    ]


def test_a_law_nobody_cites_is_empty() -> None:
    found = LawCitations([]).read("date", 10, 0, None, (), None)
    assert found is not None and found.ids == [] and found.counts.total == 0


def test_the_laws_are_kept_up_to_the_budget_the_one_used_longest_ago_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(law_citations, "LAW_CITATIONS_ROWS", 7)
    first, second, third = (LawCitations(ROWS) for _ in range(3))  # 5 rows each
    law_citations.keep("first", first)
    law_citations.keep("second", second)
    assert first.released and not second.released
    assert law_citations.generation("first") == 1
    law_citations.keep("third", third)
    assert second.released and not third.released
    assert first.read("date", 1, 0, None, (), None) is None


def test_a_law_read_lately_is_dropped_last(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(law_citations, "LAW_CITATIONS_ROWS", 11)
    first, second, third = (LawCitations(ROWS) for _ in range(3))
    law_citations.keep("first", first)
    law_citations.keep("second", second)
    law_citations.used("first")
    law_citations.keep("third", third)
    assert second.released and not first.released and not third.released


def test_the_only_law_is_never_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(law_citations, "LAW_CITATIONS_ROWS", 1)
    only = law_citations.keep("only", LawCitations(ROWS))
    assert not only.released
