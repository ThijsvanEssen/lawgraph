"""The course of a case (``core/judgment_course.py``): the area of law, the article that gives
a court its say, how far a course reaches and the order of its steps."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from lawgraph.core.judgment_course import (
    Edge,
    area_of,
    basis_of,
    order_steps,
    reach,
    route_designations,
    route_gaps,
)

RO, AWB = "BWBR0001830", "BWBR0005537"


@pytest.mark.parametrize(
    ("subjects", "area"),
    [
        (["Civiel recht; Verbintenissenrecht"], "civiel"),
        (["Strafrecht"], "straf"),
        (["Bestuursrecht; Omgevingsrecht"], "bestuur"),
        (["Bestuursrecht; Belastingrecht"], "belasting"),
        (["Internationaal publiekrecht"], None),
        (None, None),
    ],
)
def test_the_area_of_law_is_read_from_the_subjects(
    subjects: list[str] | None, area: str | None
) -> None:
    assert area_of(subjects) == area


@pytest.mark.parametrize(
    ("tier", "procedure", "area", "basis"),
    [
        ("rechtbank", "Eerste aanleg - meervoudig", "civiel", (RO, "42")),
        ("rechtbank", "Eerste aanleg - enkelvoudig", "belasting", (RO, "44")),
        ("rechtbank", "Eerste aanleg - enkelvoudig", "straf", (RO, "45")),
        ("rechtbank", "Eerste aanleg - meervoudig", "bestuur", (AWB, "8:6")),
        ("gerechtshof", "Hoger beroep", "straf", (RO, "60")),
        ("gerechtshof", "hoger beroep kort geding", "civiel", (RO, "60")),
        ("hoge_raad", "Cassatie", "civiel", (RO, "78")),
        ("hoge_raad", "Artikel 81 RO-zaken", "straf", (RO, "78")),
        ("raad_van_state", "Hoger beroep", "bestuur", (AWB, "8:105")),
        ("centrale_raad_van_beroep", "Hoger beroep", "bestuur", (AWB, "8:105")),
        ("raad_van_state", "Eerste aanleg - enkelvoudig", "bestuur", (AWB, "8:6")),
        ("college_van_beroep_bedrijfsleven", "Eerste aanleg", "bestuur", (AWB, "8:6")),
        # gaps: not in the list, never guessed
        ("hoge_raad", "Cassatie", "belasting", None),
        ("gerechtshof", "Verwijzing na Hoge Raad", "civiel", None),
        ("rechtbank", "Eerste en enige aanleg", "civiel", None),
        ("rechtbank", "Eerste aanleg - meervoudig", None, None),
        (None, "Hoger beroep", "civiel", None),
    ],
)
def test_the_basis_of_a_step_is_read_from_the_list(
    tier: str | None,
    procedure: str | None,
    area: str | None,
    basis: tuple[str, str] | None,
) -> None:
    expected = {"bwb_id": basis[0], "article_number": basis[1]} if basis else None
    assert basis_of(tier, procedure, area) == expected


def _graph(edges: list[Edge]) -> Callable[[list[str]], list[Edge]]:
    def edges_of(ids: list[str]) -> list[Edge]:
        return [e for e in edges if e.from_id in ids or e.to_id in ids]

    return edges_of


CASE = [
    Edge("hof", "rb", "APPEAL_OF"),
    Edge("hr", "hof", "APPEAL_OF"),
    Edge("phr", "hr", "ADVISES_ON"),
    Edge("hof2", "hr", "REFERRED_BY"),
]


def test_a_course_reaches_both_ways() -> None:
    edges, truncated = reach("rb", _graph(CASE), depth=8, limit=24)
    assert set(edges) == set(CASE)
    assert truncated is False


def test_a_course_stops_at_its_depth_and_says_so() -> None:
    edges, truncated = reach("rb", _graph(CASE), depth=1, limit=24)
    assert edges == [Edge("hof", "rb", "APPEAL_OF")]
    assert truncated is True


def test_a_course_stops_at_its_limit_and_says_so() -> None:
    edges, truncated = reach("hr", _graph(CASE), depth=8, limit=3)
    assert len({e.from_id for e in edges} | {e.to_id for e in edges}) == 3
    assert truncated is True


def test_the_steps_are_in_the_order_of_the_case() -> None:
    """The earlier instance first, the conclusion just before its judgment, the decision
    after referral last; an interim judgment of the same place by date."""
    edges = [*CASE, Edge("hof", "hof-tussen", "CONTINUES")]
    dates = {"rb": "2020-01-01", "hof-tussen": "2021-01-01", "hof": "2021-06-01"}
    assert order_steps("hof", edges, dates) == [
        "rb",
        "hof-tussen",
        "hof",
        "phr",
        "hr",
        "hof2",
    ]


def test_a_decision_after_referral_comes_after_all_it_names() -> None:
    """It names the rechtbank, the hof and the ruling of the Hoge Raad; the hof names none
    (ECLI:NL:GHDHA:2026:2845): the rechtbank and the hof by date, then the conclusion and
    the ruling, then the decision."""
    edges = [
        Edge("hof2", "rb", "APPEAL_OF"),
        Edge("hof2", "hof", "APPEAL_OF"),
        Edge("hof2", "hr", "REFERRED_BY"),
        Edge("hr", "hof", "APPEAL_OF"),
        Edge("phr", "hr", "ADVISES_ON"),
    ]
    dates = {"rb": "2022-01-01", "hof": "2023-01-01"}
    assert order_steps("hof2", edges, dates) == ["rb", "hof", "phr", "hr", "hof2"]


def test_a_cycle_in_the_edges_still_gives_every_judgment_once() -> None:
    edges = [Edge("a", "b", "APPEAL_OF"), Edge("b", "a", "APPEAL_OF")]
    assert sorted(order_steps("a", edges, {})) == ["a", "b"]


def test_a_court_the_regeling_names_has_its_basis_in_the_list() -> None:
    """Each article of the Bevoegdheidsregeling names a court the list gives an article."""
    for d in route_designations():
        assert basis_of(d["tier"], d["procedure"], "bestuur"), d


def test_a_gap_is_a_step_the_list_has_no_article_for() -> None:
    for gap in route_gaps():
        for tier in gap["tiers"]:
            for area in gap["areas"]:
                assert basis_of(tier, gap["procedures"][0], area) is None, (tier, area)
