"""The place of an article version on a day, gathered over toestanden that come in no order."""

from __future__ import annotations

import random

from lawgraph.core.bwb_xml import Crumb
from lawgraph.pipelines.normalize._bwb_places import Order, Places

ONE = (Crumb("hoofdstuk", "Hoofdstuk 1", "Oud"),)
RENAMED = (Crumb("hoofdstuk", "Hoofdstuk 1", "Nieuw"),)
TWO = (Crumb("hoofdstuk", "Hoofdstuk 2", None),)


def _merged(*sequences: list[str]) -> list[str]:
    order = Order()
    for sequence in sequences:
        order.merge(sequence)
    return list(order)


def test_every_toestand_keeps_its_order_in_the_merged_one() -> None:
    old, new = ["a", "b", "c", "d", "e", "f"], ["a", "x", "y", "b", "c", "e"]
    for order in (_merged(old, new), _merged(new, old)):
        assert [k for k in order if k in old] == old
        assert [k for k in order if k in new] == new


def test_a_version_first_in_a_toestand_goes_first() -> None:
    assert _merged(["b", "c"], ["a", "b"]) == ["a", "b", "c"]


class _Key(str):
    """A version key that counts how often the order touches a key."""

    touches = 0

    def __hash__(self) -> int:
        _Key.touches += 1
        return str.__hash__(self)

    def __eq__(self, other: object) -> bool:
        _Key.touches += 1
        return str.__eq__(self, other)


def _law(articles: int, toestanden: int) -> list[list[str]]:
    """The toestanden of a law of *articles* articles, a fifth of them amended in each."""
    rng = random.Random(1)
    current = [f"s{i}/v0" for i in range(articles)]
    law = [list(current)]
    for t in range(1, toestanden):
        for i in rng.sample(range(articles), articles // 5):
            current[i] = f"s{i}/v{t}"
        law.append(list(current))
    return law


def _touches_to_add(places: Places, versions: list[str]) -> int:
    _Key.touches = 0
    places.add("L", "2100-01-01", [(_Key(key), ONE) for key in versions])
    return _Key.touches


def test_a_toestand_costs_the_same_however_many_versions_the_law_has() -> None:
    """Adding a toestand touches each of its versions a fixed number of times, whether the
    law holds one earlier toestand or fifty (inserting into one list touched them all)."""
    law = _law(500, 50)
    short, long = Places(), Places()
    short.add("L", "2099-01-01", [(key, ONE) for key in law[-1]])
    for t, versions in enumerate(law):
        long.add("L", f"{2000 + t}-01-01", [(key, ONE) for key in versions])
    amended = [f"{key}/next" if i % 5 == 0 else key for i, key in enumerate(law[-1])]
    assert _touches_to_add(long, amended) == _touches_to_add(short, amended)
    positions, last = long.positions("L"), set(amended)
    assert [
        k for k in sorted(positions, key=positions.__getitem__) if k in last
    ] == amended


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
