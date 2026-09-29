"""The place of an article version on a day, gathered over toestanden that come in no order."""

from __future__ import annotations

from lawgraph.core.bwb_xml import Crumb
from lawgraph.pipelines.normalize._bwb_places import Places, merge_order

ONE = (Crumb("hoofdstuk", "Hoofdstuk 1", "Oud"),)
RENAMED = (Crumb("hoofdstuk", "Hoofdstuk 1", "Nieuw"),)
TWO = (Crumb("hoofdstuk", "Hoofdstuk 2", None),)


def _merged(*sequences: list[str]) -> list[str]:
    order: list[str] = []
    known: set[str] = set()
    for sequence in sequences:
        merge_order(order, known, sequence)
    return order


def test_every_toestand_keeps_its_order_in_the_merged_one() -> None:
    old, new = ["a", "b", "c", "d", "e", "f"], ["a", "x", "y", "b", "c", "e"]
    for order in (_merged(old, new), _merged(new, old)):
        assert [k for k in order if k in old] == old
        assert [k for k in order if k in new] == new


def test_a_version_first_in_a_toestand_goes_first() -> None:
    assert _merged(["b", "c"], ["a", "b"]) == ["a", "b", "c"]


def test_a_breadcrumb_changes_on_the_first_toestand_under_the_new_one() -> None:
    places = Places()
    places.add("L", "2025-01-01", [("a", RENAMED)])
    places.add("L", "2018-01-01", [("a", ONE)])
    places.add("L", "2026-01-01", [("a", RENAMED)])
    assert places.breadcrumbs("a") == {
        "breadcrumb": [{"type": "hoofdstuk", "label": "Hoofdstuk 1", "title": "Oud"}],
        "breadcrumb_changes": [
            {
                "from": "2025-01-01",
                "breadcrumb": [
                    {"type": "hoofdstuk", "label": "Hoofdstuk 1", "title": "Nieuw"}
                ],
            }
        ],
    }
    assert places.breadcrumbs("unread") is None


def test_a_run_since_a_date_adds_to_what_was_stored() -> None:
    places = Places()
    places.seed(
        "L",
        [
            {"key": "a", "breadcrumb": [{"type": "hoofdstuk", "label": "Hoofdstuk 1"}]},
            {"key": "b", "breadcrumb": None},
        ],
    )
    places.add("L", "2026-01-01", [("z", TWO), ("a", TWO)])
    assert places.positions("L") == {"z": 0, "a": 1, "b": 2}
    crumbs = places.breadcrumbs("a")
    assert crumbs is not None
    assert crumbs["breadcrumb"] == [{"type": "hoofdstuk", "label": "Hoofdstuk 1"}]
    assert crumbs["breadcrumb_changes"] == [
        {
            "from": "2026-01-01",
            "breadcrumb": [{"type": "hoofdstuk", "label": "Hoofdstuk 2"}],
        }
    ]
