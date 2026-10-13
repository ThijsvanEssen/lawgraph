"""The place of an article version on a day, gathered over toestanden that come in no order."""

from __future__ import annotations

import random
import time

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


def test_a_toestand_costs_the_same_however_many_versions_the_law_has() -> None:
    """3,000 articles over 200 toestanden, a fifth of them amended in each: 120,000
    versions. Inserting into one list took a minute here; the links take a fraction of a
    second."""
    rng = random.Random(1)
    current = [f"s{i}/v0" for i in range(3000)]
    toestanden = []
    for t in range(200):
        for i in rng.sample(range(3000), 600 if t else 0):
            current[i] = f"s{i}/v{t}"
        toestanden.append([(key, ONE) for key in current])
    places = Places()
    started = time.perf_counter()
    for t, versions in enumerate(toestanden):
        places.add("L", f"{2000 + t}-01-01", versions)
    assert time.perf_counter() - started < 3.0
    positions = places.positions("L")
    assert len(positions) == 3000 + 199 * 600
    last = set(current)
    assert [
        k for k in sorted(positions, key=positions.__getitem__) if k in last
    ] == current


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
