"""A period on the lists and the search, on a real PostgreSQL: the instruments by the day
they came into force or were published, the commitments by the day they were made, the
members, factions and committees active in it, and the hits of a search by their own date
or period. Every day inclusive; one side alone leaves the other open."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import cabinets, committees, instruments
from lawgraph.db.queries import search as search_queries


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


@pytest.fixture()
def dated(store: GraphStore) -> GraphStore:
    """Of every type of the search a hit on ``stikstof`` of before 2015 and one after."""
    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("d1", "document", title="Stikstof in de Veluwe", date="2010-01-01"),
            _node("d2", "document", title="Stikstof en de bouw", date="2024-01-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node("j1", "judgment", display_name="Rechtbank stikstof Veluwe",
                  names=["Stikstof"], date_eff="2010-02-01"),
            _node("j2", "judgment", display_name="Raad van State stikstof bouw",
                  names=["Stikstof"], date_eff="2023-02-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("s1", "dossier", label="30000", title="Stikstofwet oud",
                  opened_on="2008-01-01"),
            _node("s2", "dossier", label="36000", title="Stikstofwet nieuw",
                  opened_on="2022-01-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr1", "instrument", bwb_id="BWBR1", kind="wet",
                  citation_title="Stikstofwet 2005", date_in_force="2005-01-01"),
            _node("bwbr2", "instrument", bwb_id="BWBR2", kind="wet",
                  citation_title="Stikstofwet 2021", date_in_force="2021-07-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbr1_1", "article", bwb_id="BWBR1", article_number="1",
                  display_name="Artikel 1 Stikstofwet 2005", text="De stikstof."),
            _node("bwbr2_1", "article", bwb_id="BWBR2", article_number="1",
                  display_name="Artikel 1 Stikstofwet 2021", text="De stikstof."),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node("v1", "decision", subject="Motie over stikstof", date="2011-01-01"),
            _node("v2", "decision", subject="Motie over stikstof", date="2024-01-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "commitments",
        [
            _node("t1", "commitment", text="Brief over stikstof", made_on="2012-01-01"),
            _node("t2", "commitment", text="Brief over stikstof", made_on="2024-05-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            _node("kab1", "cabinet", name="Kabinet Stikstof I", from_date="2002-01-01",
                  to_date="2006-01-01"),
            _node("kab2", "cabinet", name="Kabinet Stikstof II", from_date="2022-01-10"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node("fa1", "faction", name="Stikstofpartij Oud", active_from="2000-01-01",
                  active_until="2010-01-01"),
            _node("fa2", "faction", name="Stikstofpartij Nieuw", active_from="2019-01-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "committees",
        [
            _node("ko1", "committee", name="Commissie Stikstof Oud",
                  started_on="2000-01-01", ended_on="2010-01-01"),
            _node("ko2", "committee", name="Commissie Stikstof Nieuw",
                  started_on="2020-01-01"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node("me1", "member", name="Stikstof Oud",
                  faction_memberships=[{"from_date": "2000-01-01",
                                        "to_date": "2009-01-01"}]),
            _node("me2", "member", name="Stikstof Nieuw",
                  government_functions=[{"from_date": "2022-01-10", "to_date": None}]),
        ],
    )  # fmt: skip
    return store


# Of each type the hit of after 2015 and the one of before.
NEW = {
    "documents": "documents/d2",
    "judgments": "judgments/j2",
    "dossiers": "dossiers/s2",
    "instruments": "instruments/bwbr2",
    "articles": "articles/bwbr2_1",
    "decisions": "decisions/v2",
    "commitments": "commitments/t2",
    "cabinets": "cabinets/kab2",
    "factions": "factions/fa2",
    "committees": "committees/ko2",
    "members": "members/me2",
}
OLD = {
    "documents": "documents/d1",
    "judgments": "judgments/j1",
    "dossiers": "dossiers/s1",
    "instruments": "instruments/bwbr1",
    "articles": "articles/bwbr1_1",
    "decisions": "decisions/v1",
    "commitments": "commitments/t1",
    "cabinets": "cabinets/kab1",
    "factions": "factions/fa1",
    "committees": "committees/ko1",
    "members": "members/me1",
}


@pytest.mark.parametrize("live", [False, True])
def test_a_search_keeps_the_hits_of_its_period(dated: GraphStore, live: bool) -> None:
    """Every type: without a period both hits, from 2015 the new one alone, until 2014
    the old one alone; a hit by its own date, or a period of its own that overlaps; an
    article by the day its law came into force."""
    search = search_queries.search_live if live else search_queries.search_full
    types = list(NEW)

    def found(**period: str) -> dict[str, set[str]]:
        hits, partial = search(dated, q="stikstof", types=types, limit=10, **period)
        assert not partial
        return {t: {h["id"] for h in hits[t]} for t in types}

    every = found()
    for table in types:
        assert {NEW[table], OLD[table]} <= every[table], (table, every[table])
    recent = found(since="2015-01-01")
    for table in types:
        assert NEW[table] in recent[table] and OLD[table] not in recent[table], (
            table,
            recent[table],
        )
    early = found(until="2014-12-31")
    for table in types:
        assert OLD[table] in early[table] and NEW[table] not in early[table], (
            table,
            early[table],
        )


def test_a_period_comes_before_the_limit_of_a_live_search(
    dated: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live search reads the first ``LIVE_CANDIDATES`` it finds: the period is kept in
    that lookup, so the one hit of the period is found even with one candidate."""
    monkeypatch.setattr(search_queries, "LIVE_CANDIDATES", 1)
    for since, expected in (("2015-01-01", "documents/d2"), (None, None)):
        hits, _ = search_queries.search_live(
            dated, q="stikstof", types=["documents"], limit=10, since=since
        )
        if expected:
            assert [h["id"] for h in hits["documents"]] == [expected]
        else:
            assert len(hits["documents"]) == 1
