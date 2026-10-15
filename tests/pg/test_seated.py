"""Who sits in a faction or committee now is one rule (``lg_seated``) for the SEO pages,
the API and the children a path starts from: a seat of the Tweede Kamer without a last day
or with one still ahead holds; a seat of the Eerste Kamer a snapshot no longer shows has
ended."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries import seo
from lawgraph.db.queries.committees import get_committee_detail
from lawgraph.db.queries.members import get_member_committees
from lawgraph.db.queries.path_groups import children_of

COMMITTEE = "committees/justitie"
FACTION = "factions/vvd"
OPEN = "members/open"  # Tweede Kamer, no last day
LEAVING = "members/leaving"  # Tweede Kamer, last day still ahead
LEFT = "members/left"  # Tweede Kamer, last day past
UNSEEN = "members/unseen"  # Eerste Kamer, no longer on its page
SEATED = {OPEN, LEAVING}


def _node(key: str, kind: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": kind, "labels": [], "props": props}


def _seat(key: str, member: str, group: str, **meta: Any) -> dict[str, Any]:
    return {
        "key": key,
        "from_id": member,
        "to_id": group,
        "relation": "MEMBER_OF",
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": meta,
    }


@pytest.fixture()
def seats(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node(m.split("/")[1], "member", name=m.split("/")[1])
            for m in (OPEN, LEAVING, LEFT, UNSEEN)
        ],
    )
    store.bulk_insert_or_update_nodes(
        "committees", [_node("justitie", "committee", name="Justitie", slug="justitie")]
    )
    store.bulk_insert_or_update_nodes("factions", [_node("vvd", "faction", name="VVD")])
    store.bulk_insert_or_update_edges(
        [
            seat
            for group in (COMMITTEE, FACTION)
            for seat in (
                _seat(f"{group}-open", OPEN, group, from_date="2023-12-06"),
                _seat(
                    f"{group}-leaving",
                    LEAVING,
                    group,
                    from_date="2021-03-31",
                    to_date="2999-12-31",
                ),
                _seat(
                    f"{group}-left",
                    LEFT,
                    group,
                    from_date="2010-06-17",
                    to_date="2017-03-22",
                ),
                _seat(
                    f"{group}-unseen",
                    UNSEEN,
                    group,
                    chamber="EK",
                    observed_from="2023-06-13",
                    observed_until="2024-01-02",
                ),
            )
        ]
    )
    return store


def test_the_seo_pages_and_the_api_seat_the_same_members(seats: GraphStore) -> None:
    detail = get_committee_detail(seats, "justitie")
    assert detail is not None
    assert {m["id"] for m in detail["members"]} == SEATED
    committee = seo.committee(seats, COMMITTEE)
    faction = seo.faction(seats, FACTION)
    assert committee is not None and faction is not None
    assert {m["id"] for m in committee["members"]} == SEATED
    assert {m["id"] for m in faction["members"]} == SEATED


def test_a_path_starts_from_the_seated_members_first(seats: GraphStore) -> None:
    for group in (COMMITTEE, FACTION):
        kept = [child.id for child in children_of(seats, group, 10).kept]
        assert set(kept[:2]) == SEATED, group
        assert set(kept[2:]) == {LEFT, UNSEEN}, group


def test_a_member_s_committees_lead_with_a_seat_still_held(seats: GraphStore) -> None:
    seats.bulk_insert_or_update_nodes(
        "committees", [_node("financien", "committee", name="Financiën")]
    )
    seats.bulk_insert_or_update_edges(
        [
            _seat(
                "leaving-financien",
                LEAVING,
                "committees/financien",
                from_date="2005-01-01",
                to_date="2009-01-01",
            )
        ]
    )
    held = get_member_committees(seats, LEAVING)
    assert [row["key"] for row in held] == ["justitie", "financien"]
