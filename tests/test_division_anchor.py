"""The anchor of a division names it as the reader of the whole law does (``deelIds``)."""

from __future__ import annotations

from lawgraph.core.division_anchor import (
    as_anchor,
    breadcrumb_on,
    division_anchors,
    division_path,
)

AWB = [
    {"type": "hoofdstuk", "label": "Hoofdstuk 10", "title": "Bepalingen"},
    {"type": "titeldeel", "label": "Titel 10.2", "title": "Toezicht"},
    {"type": "afdeling", "label": "Afdeling 10.2.2", "title": "Vernietiging"},
]


def test_each_division_by_the_path_of_its_labels() -> None:
    assert division_anchors(
        [
            {"label": "Boek 6"},
            {"label": "Titel 3"},
            {"label": "Afdeling 1", "title": "X"},
        ]
    ) == ["deel-boek-6", "deel-boek-6-titel-3", "deel-boek-6-titel-3-afdeling-1"]
    assert division_anchors(AWB)[-1] == "deel-hoofdstuk-10-titel-10.2-afdeling-10.2.2"


def test_folded_without_accents_and_by_its_title_without_a_label() -> None:
    assert division_anchors([{"label": "Hoofdstuk Ä 2"}]) == ["deel-hoofdstuk-a-2"]
    assert division_anchors([{"title": "Slotbepalingen"}, {"label": "§ 1"}]) == [
        "deel-slotbepalingen",
        "deel-slotbepalingen-1",
    ]
    assert division_anchors([{"type": "hoofdstuk"}, {"label": "§ 1"}]) == [
        "deel-",
        "deel-1",
    ]
    assert division_anchors(None) == []


def test_an_anchor_as_asked() -> None:
    for asked in (
        "#deel-hoofdstuk-6",
        "deel-hoofdstuk-6",
        "Hoofdstuk-6",
        " hoofdstuk-6",
    ):
        assert as_anchor(asked) == "deel-hoofdstuk-6"


def test_the_path_down_to_the_division() -> None:
    assert division_path(AWB, "deel-hoofdstuk-10-titel-10.2") == AWB[:2]
    assert division_path(AWB, "deel-hoofdstuk-10-titel-10.2-afdeling-10.2.2") == AWB
    assert division_path(AWB, "deel-hoofdstuk-1") is None
    assert division_path([], "deel-hoofdstuk-1") is None


def test_the_breadcrumb_of_a_day() -> None:
    props = {
        "breadcrumb": AWB[:1],
        "breadcrumb_changes": [{"from": "2025-01-01", "breadcrumb": AWB}],
    }
    assert breadcrumb_on(props, "2024-12-31") == AWB[:1]
    assert breadcrumb_on(props, "2025-01-01") == AWB
