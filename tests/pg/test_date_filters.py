"""A period on the lists, on a real PostgreSQL: the instruments by the day they came into
force or were published, the commitments by the day they were made, and the members,
factions and committees active in it. Every day inclusive; one side alone leaves the other
open."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries import cabinets, committees, instruments


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _keys(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(row["_key"] for row in rows)


def test_instruments_by_the_day_they_came_into_force_or_were_published(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("i1", "instrument", kind="wet", citation_title="Wet A",
                  date_in_force="2010-01-01", date_published="2009-12-01"),
            _node("i2", "instrument", kind="wet", citation_title="Wet B",
                  date_in_force="2020-05-01", date_published="2020-04-01"),
            _node("i3", "instrument", kind="wet", citation_title="Wet C"),
        ],
    )  # fmt: skip

    def listed(**period: str) -> list[str]:
        return _keys(instruments.get_instruments_list(store, **period)["items"])

    assert listed() == ["i1", "i2", "i3"]
    assert listed(in_force_from="2015-01-01") == ["i2"]
    assert listed(in_force_to="2020-05-01") == ["i1", "i2"]  # inclusive
    assert listed(in_force_from="2010-01-02", in_force_to="2020-04-30") == []
    assert listed(published_to="2010-01-01") == ["i1"]
    assert listed(published_from="2020-04-01", in_force_from="2020-01-01") == ["i2"]
    total = instruments.get_instruments_list(store, in_force_from="2015-01-01")["total"]
    assert total == 1


def test_commitments_by_the_day_they_were_made(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "commitments",
        [
            _node("c1", "commitment", made_on="2024-01-10", text="Brief over A"),
            _node("c2", "commitment", made_on="2025-03-01", text="Brief over B"),
            _node("c3", "commitment", made_on="2025-12-31", text="Brief over C"),
        ],
    )

    def made(**period: str) -> list[str]:
        page = cabinets.get_commitments(store, **period)
        return sorted(row["commitment"]["_key"] for row in page["items"])

    assert made(made_from="2025-01-01") == ["c2", "c3"]
    assert made(made_to="2025-03-01") == ["c1", "c2"]
    assert made(made_from="2025-03-01", made_to="2025-03-01") == ["c2"]
    assert cabinets.get_commitments(store, made_from="2025-01-01")["total"] == 2


def _people(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node("m1", "member", name="Anna",
                  faction_memberships=[{"from_date": "2010-03-01", "to_date": "2015-01-01",
                                        "faction_key": "a"}]),
            _node("m2", "member", name="Bert",
                  faction_memberships=[{"from_date": "2018-01-01", "to_date": None,
                                        "faction_key": "b"}]),
            _node("m3", "member", name="Carla",
                  government_functions=[{"from_date": "2016-01-01", "to_date": "2017-06-30",
                                         "cabinet_key": "rutte2"}]),
            _node("m4", "member", name="Dirk",
                  ek={"name": "Dirk", "observed_from": "2023-06-13",
                      "observed_until": None}),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node("f1", "faction", name="Oud", active_from="2000-01-01",
                  active_until="2012-01-01"),
            _node("f2", "faction", name="Nieuw", active_from="2010-01-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "committees",
        [
            _node("k1", "committee", name="Commissie Oud", started_on="2000-01-01",
                  ended_on="2010-01-01", observed_until="2010-01-01"),
            _node("k2", "committee", name="Commissie Nieuw", started_on="2015-01-01"),
        ],
    )  # fmt: skip


def test_members_factions_and_committees_active_in_a_period(store: GraphStore) -> None:
    """A seat or a post in a cabinet, the period of a faction or a committee, that overlaps
    the one asked; a committee that ended is listed when it existed in it."""
    _people(store)

    def members(**period: Any) -> list[str]:
        return _keys(committees.get_members(store, **period))

    assert members() == ["m1", "m2"]
    assert members(active_from="2014-12-31") == ["m1", "m2"]
    assert members(active_from="2015-01-02", active_to="2017-12-31") == []
    assert members(active_to="2015-01-01") == ["m1"]  # its last day counts
    # a post in a cabinet counts as being active
    assert _keys(
        committees.get_members(
            store, government=True, active_from="2017-01-01", active_to="2017-12-31"
        )
    ) == ["m3"]
    assert _keys(committees.get_ek_members(store, active_to="2023-06-12")) == []
    assert _keys(committees.get_ek_members(store, active_from="2024-01-01")) == ["m4"]

    def factions(**period: str) -> list[str]:
        return _keys(committees.get_factions(store, **period))

    assert factions(active_to="2005-12-31") == ["f1"]
    assert factions(active_from="2012-01-02") == ["f2"]
    assert factions(active_from="2011-01-01", active_to="2011-12-31") == ["f1", "f2"]

    assert _keys(committees.get_committees(store)) == ["k2"]
    assert _keys(committees.get_committees(store, active_to="2005-01-01")) == ["k1"]
    assert _keys(committees.get_committees(store, active_from="2009-01-01")) == [
        "k1",
        "k2",
    ]
