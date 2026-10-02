"""The instrument queries (``/api/instruments/...``) on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from lawgraph.db.queries import instruments

BWB = "BWBR0001854"
CELEX = "32016R0679"


def _doc(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _edge(source: str, target: str, relation: str, **meta: Any) -> dict[str, Any]:
    return {
        "_key": f"{source}>{relation}>{target}".replace("/", ":"),
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "x",
        "status": "canoniek",
        "meta": meta,
    }


def _keys(docs: list[dict[str, Any]]) -> list[str]:
    return [d["_key"] for d in docs]


# ── articles ─────────────────────────────────────────────────────────────────


def _seed_articles(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _doc("a3", "article", bwb_id=BWB, article_number="3", position=2),
            _doc("a1", "article", bwb_id=BWB, article_number="1", position=0),
            _doc("a2b", "article", bwb_id=BWB, article_number="2b", position=1),
            _doc("a2a", "article", bwb_id=BWB, article_number="2a", position=1),
            # no position: last, by key
            _doc("hist_z", "article", bwb_id=BWB, article_number="9"),
            _doc("hist_y", "article", bwb_id=BWB, article_number="8"),
            _doc("stub", "article", bwb_id=BWB, article_number="99", stub=True),
            _doc("gone", "article", bwb_id=BWB, article_number="7", repealed=True),
            # a non-boolean flag is not true
            _doc("odd", "article", bwb_id=BWB, article_number="6", stub="true"),
            _doc("other", "article", bwb_id="BWBR0000001", position=0),
            _doc("eu1", "article", celex=CELEX, article_number="1", position=0),
        ],
    )


def test_articles_in_document_order_without_stubs_and_repealed(
    store: GraphStore,
) -> None:
    _seed_articles(store)
    items, total = instruments.get_articles(store, BWB.lower())
    assert total == 7
    assert _keys(items) == ["a1", "a2a", "a2b", "a3", "hist_y", "hist_z", "odd"]
    first = items[0]
    assert list(first) == ["_key", "_id", "type", "labels", "props"]
    assert first == {
        "_key": "a1",
        "_id": "articles/a1",
        "type": "article",
        "labels": [],
        "props": {"article_number": "1", "bwb_id": BWB, "position": 0},
    }


def test_articles_with_stubs_and_repealed_and_paging(store: GraphStore) -> None:
    _seed_articles(store)
    items, total = instruments.get_articles(
        store, BWB, include_stubs=True, include_repealed=True
    )
    assert total == 9
    assert _keys(items) == [
        "a1",
        "a2a",
        "a2b",
        "a3",
        "gone",
        "hist_y",
        "hist_z",
        "odd",
        "stub",
    ]
    items, total = instruments.get_articles(store, BWB, limit=2, offset=3)
    assert (total, _keys(items)) == (7, ["a3", "hist_y"])
    # a page past the end still knows the total
    assert instruments.get_articles(store, BWB, offset=50) == ([], 7)
    assert instruments.get_articles(store, BWB, limit=0) == ([], 7)


def test_articles_of_an_eu_act_and_of_nothing(store: GraphStore) -> None:
    _seed_articles(store)
    items, total = instruments.get_articles(store, CELEX.lower())
    assert (total, _keys(items)) == (1, ["eu1"])
    assert instruments.get_articles(store, "BWBR9999999") == ([], 0)


# ── judgments ────────────────────────────────────────────────────────────────


def test_judgments_grouped_by_judgment(store: GraphStore) -> None:
    _seed_articles(store)
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _doc("j_old", "judgment", ecli="ECLI:O", date_eff="2001-01-01", text="t"),
            _doc("j_new", "judgment", ecli="ECLI:N", date_eff="2020-01-01"),
            _doc("j_b", "judgment", ecli="ECLI:B", display_name="B"),
            _doc("j_a", "judgment", ecli="ECLI:A"),
            _doc(
                "j_many",
                "judgment",
                ecli="ECLI:M",
                date_eff="1990-01-01",
                court_code="HR",
                tier="hoge_raad",
                court_kind="hoge_raad",
            ),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("judgments/j_many", "articles/a3", "REFERS_TO"),
            _edge("judgments/j_many", "articles/hist_z", "REFERS_TO"),
            _edge("judgments/j_many", "articles/a1", "REFERS_TO"),
            _edge("judgments/j_old", "articles/a1", "REFERS_TO"),
            _edge("judgments/j_new", "articles/a2a", "REFERS_TO"),
            _edge("judgments/j_b", "articles/a1", "REFERS_TO"),
            _edge("judgments/j_a", "articles/a1", "REFERS_TO"),
            # a stub article is an article of the law too
            _edge("judgments/j_a", "articles/stub", "REFERS_TO"),
            # a judgment that is missing is counted, not listed
            _edge("judgments/j_missing", "articles/a1", "REFERS_TO"),
            # not a judgment, not a reference, not this law
            _edge("documents/d", "articles/a1", "REFERS_TO"),
            _edge("judgments/j_b", "articles/a3", "EXPLAINS"),
            _edge("judgments/j_b", "articles/other", "REFERS_TO"),
        ]
    )
    items, total = instruments.get_instrument_judgments(store, BWB, sort="cited")
    assert total == 6
    # most cited articles first, then the newest (no date last), then the id
    assert [i["judgment"]["_key"] for i in items] == [
        "j_many",
        "j_a",
        "j_new",
        "j_old",
        "j_b",
    ]
    # by default the newest first (no date last), then the id
    by_date, _ = instruments.get_instrument_judgments(store, BWB)
    assert [i["judgment"]["_key"] for i in by_date] == [
        "j_new",
        "j_old",
        "j_many",
        "j_a",
        "j_b",
    ]
    paged, _ = instruments.get_instrument_judgments(store, BWB, limit=2, offset=1)
    assert [i["judgment"]["_key"] for i in paged] == ["j_old", "j_many"]
    # every citing judgment per year, not the page; a missing one is not counted
    assert instruments.get_instrument_judgment_years(store, BWB) == [
        {"value": None, "count": 2},
        {"value": "1990", "count": 1},
        {"value": "2001", "count": 1},
        {"value": "2020", "count": 1},
    ]
    found = instruments.get_citing_judgments(store, BWB, limit=1)
    assert (found.total, len(found.items), len(found.years)) == (6, 1, 4)
    many = items[0]
    assert list(many) == ["judgment", "cited_articles"]
    assert list(many["judgment"]) == ["_id", "_key", "props"]
    assert many["judgment"] == {
        "_id": "judgments/j_many",
        "_key": "j_many",
        "props": {
            "ecli": "ECLI:M",
            "display_name": None,
            "court_code": "HR",
            "tier": "hoge_raad",
            "court_kind": "hoge_raad",
            "date_eff": "1990-01-01",
            "advocate_general": None,
            "advocate_general_role": None,
        },
    }
    assert many["cited_articles"] == [
        {"id": "articles/a1", "key": "a1", "article_number": "1", "display_name": None},
        {"id": "articles/a3", "key": "a3", "article_number": "3", "display_name": None},
        {
            "id": "articles/hist_z",
            "key": "hist_z",
            "article_number": "9",
            "display_name": None,
        },
    ]
    assert list(many["cited_articles"][0]) == [
        "id",
        "key",
        "article_number",
        "display_name",
    ]
    assert [a["key"] for a in items[1]["cited_articles"]] == ["a1", "stub"]
    assert items[4]["judgment"]["props"] == {
        "ecli": "ECLI:B",
        "display_name": "B",
        "court_code": None,
        "tier": None,
        "court_kind": None,
        "date_eff": None,
        "advocate_general": None,
        "advocate_general_role": None,
    }

    items, total = instruments.get_instrument_judgments(
        store, BWB, sort="cited", limit=1
    )
    assert (total, [i["judgment"]["_key"] for i in items]) == (6, ["j_many"])
    assert instruments.get_instrument_judgments(store, "BWBR9999999") == ([], 0)


def test_a_citing_conclusion_names_its_advocate_general(store: GraphStore) -> None:
    _seed_articles(store)
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _doc(
                "c1",
                "judgment",
                ecli="ECLI:C",
                decision_kind="conclusie",
                advocate_general="T. Hartlief",
                advocate_general_role="advocaat-generaal",
            ),
            # only a conclusion is read for it
            _doc("u1", "judgment", ecli="ECLI:U", advocate_general="X"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("judgments/c1", "articles/a1", "REFERS_TO"),
            _edge("judgments/u1", "articles/a1", "REFERS_TO"),
        ]
    )
    items, _ = instruments.get_instrument_judgments(store, BWB)
    props = {i["judgment"]["_key"]: i["judgment"]["props"] for i in items}
    assert (
        props["c1"]["advocate_general"],
        props["c1"]["advocate_general_role"],
    ) == ("T. Hartlief", "advocaat-generaal")
    assert props["u1"]["advocate_general"] is None

    app.dependency_overrides[get_store] = lambda: store
    try:
        body = (
            TestClient(app).get(f"/api/instruments/{BWB}/judgments?sort=cited").json()
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert (body["sort"], body["total"]) == ("cited", 2)
    assert body["facets"] == {"year": [{"value": None, "count": 2}]}
    item = next(i for i in body["items"] if i["key"] == "c1")
    assert (item["advocate_general"], item["advocate_general_role"]) == (
        "T. Hartlief",
        "advocaat-generaal",
    )


# ── dossiers ─────────────────────────────────────────────────────────────────


def _dossier(key: str, **props: Any) -> dict[str, Any]:
    return _doc(key, "dossier", **props)


def test_dossiers_direct_and_through_amending_publications(store: GraphStore) -> None:
    _seed_articles(store)
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _dossier("d_direct", number="100", opened_on="2010-01-01"),
            _dossier("d_both", number="200", opened_on="2015-01-01"),
            _dossier("d_pub", number="300", opened_on="2015-01-01"),
            _dossier("d_pub2", number="250", opened_on="2015-01-01"),
            _dossier("d_none", number="400"),
            _dossier("d_tie_b", number="500", opened_on="2000-01-01"),
            _dossier("d_tie_a", number="500", opened_on="2000-01-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _doc(BWB.lower(), "instrument", bwb_id=BWB),
            _doc(
                "stb1",
                "instrument",
                identifier="Stb. 2019, 1",
                date_published="2019-01-01",
            ),
            _doc(
                "stb2",
                "instrument",
                identifier="Stb. 2020, 2",
                date_published="2020-01-01",
            ),
            _doc("stb3", "instrument", date_published="2021-01-01"),
        ],
    )
    instrument = f"instruments/{BWB.lower()}"
    store.bulk_insert_or_update_edges(
        [
            _edge("instruments/stb1", "articles/a1", "AMENDS"),
            _edge("instruments/stb2", "articles/a2a", "INTRODUCES"),
            _edge("instruments/stb3", "articles/gone", "REPEALS"),
            _edge("instruments/stb_missing", "articles/a3", "AMENDS"),
            _edge(instrument, "dossiers/d_direct", "LEGISLATED_IN"),
            _edge(instrument, "dossiers/d_both", "LEGISLATED_IN"),
            _edge("instruments/stb1", "dossiers/d_both", "LEGISLATED_IN"),
            _edge("instruments/stb1", "dossiers/d_pub", "LEGISLATED_IN"),
            _edge("instruments/stb2", "dossiers/d_pub", "LEGISLATED_IN"),
            _edge("instruments/stb3", "dossiers/d_pub2", "LEGISLATED_IN"),
            _edge("instruments/stb_missing", "dossiers/d_none", "LEGISLATED_IN"),
            _edge(instrument, "dossiers/d_tie_b", "LEGISLATED_IN"),
            _edge(instrument, "dossiers/d_tie_a", "LEGISLATED_IN"),
            # a missing dossier is neither counted nor listed
            _edge(instrument, "dossiers/d_missing", "LEGISLATED_IN"),
            # not a dossier, not legislated in
            _edge(instrument, "documents/x", "LEGISLATED_IN"),
            _edge("instruments/stb1", "dossiers/d_direct", "EXPLAINS"),
        ]
    )
    items, total = instruments.get_instrument_dossiers(store, BWB)
    assert total == 7
    assert [(i["dossier"]["_key"], i["via"], i["publication"]) for i in items] == [
        # opened newest first, then the number, then the key; never opened last
        ("d_both", "instrument", None),
        ("d_pub2", "amending_publication", "stb3"),
        ("d_pub", "amending_publication", "Stb. 2020, 2"),
        ("d_direct", "instrument", None),
        ("d_tie_a", "instrument", None),
        ("d_tie_b", "instrument", None),
        ("d_none", "amending_publication", None),
    ]
    assert list(items[0]) == ["dossier", "via", "publication"]
    assert items[0]["dossier"] == {
        "_key": "d_both",
        "_id": "dossiers/d_both",
        "type": "dossier",
        "labels": [],
        "props": {"number": "200", "opened_on": "2015-01-01"},
    }
    items, total = instruments.get_instrument_dossiers(store, BWB, limit=2)
    assert (total, [i["dossier"]["_key"] for i in items]) == (7, ["d_both", "d_pub2"])
    assert instruments.get_instrument_dossiers(store, "BWBR9999999") == ([], 0)


# ── amended by ───────────────────────────────────────────────────────────────


def test_amended_by_grouped_per_instrument_newest_first(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_articles(store)
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _doc(
                "p1",
                "instrument",
                date_published="2020-01-01",
                dossier_numbers=["36000"],
            ),
            _doc("p2", "instrument", date_published="2021-01-01"),
            _doc(
                "p3a",
                "instrument",
                date_published="2019-01-01",
                date_signed="2018-12-01",
            ),
            _doc(
                "p3b",
                "instrument",
                date_published="2019-01-01",
                date_signed="2018-12-01",
            ),
            _doc("p3c", "instrument", date_published="2019-01-01"),
            _doc("p4", "instrument", dossier_numbers=["35000", " 36000 "]),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents", [_doc("doc1", "document", date_published="2022-01-01")]
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(
                "instruments/p1", "articles/a1", "AMENDS", effective_date="2020-07-01"
            ),
            _edge(
                "instruments/p1", "articles/a2a", "AMENDS", effective_date="2020-03-01"
            ),
            _edge("instruments/p1", "articles/a2a", "INTRODUCES"),
            _edge(
                "instruments/p1",
                "articles/gone",
                "REPEALS",
                effective_date="2021-01-01",
            ),
            _edge("instruments/p2", "articles/a3", "INTRODUCES"),
            _edge("instruments/p3a", "articles/a3", "AMENDS"),
            _edge("instruments/p3b", "articles/a3", "AMENDS"),
            _edge("instruments/p3c", "articles/a3", "AMENDS"),
            _edge("instruments/p4", "articles/a3", "AMENDS"),
            # any node may amend; a missing one is dropped
            _edge("documents/doc1", "articles/a1", "AMENDS"),
            _edge("instruments/p_missing", "articles/a1", "AMENDS"),
            # not a mutation, not this law
            _edge("instruments/p2", "articles/a1", "REFERS_TO"),
            _edge("instruments/p2", "articles/other", "AMENDS"),
        ]
    )
    asked: list[list[str]] = []

    def titles(_store: Any, numbers: Any) -> dict[str, str | None]:
        asked.append(list(numbers))
        return {"36000": "Wet X"} if numbers else {}

    monkeypatch.setattr(instruments, "get_dossier_titles", titles)
    data = instruments.get_instrument_amended_by(store, BWB)
    assert data.total == 7
    assert [i["instrument"]["_key"] for i in data.items] == [
        "doc1",
        "p2",
        "p1",
        "p3b",
        "p3a",
        "p3c",
        "p4",
    ]
    p1 = data.items[2]
    assert list(p1) == [
        "instrument",
        "amends",
        "introduces",
        "repeals",
        "articles_affected",
        "first_effective_date",
    ]
    assert {k: v for k, v in p1.items() if k != "instrument"} == {
        "amends": 2,
        "introduces": 1,
        "repeals": 1,
        "articles_affected": 3,
        "first_effective_date": "2020-03-01",
    }
    assert p1["instrument"]["_id"] == "instruments/p1"
    assert data.items[1]["first_effective_date"] is None
    assert asked == [["35000", "36000"]]
    assert data.dossier_titles == {"36000": "Wet X"}

    page = instruments.get_instrument_amended_by(store, BWB, limit=2, offset=5)
    assert page.total == 7
    assert [i["instrument"]["_key"] for i in page.items] == ["p3c", "p4"]
    beyond = instruments.get_instrument_amended_by(store, BWB, offset=10)
    assert (beyond.items, beyond.total, beyond.dossier_titles) == ([], 7, {})


def test_amended_by_of_nothing_asks_no_titles(store: GraphStore) -> None:
    data = instruments.get_instrument_amended_by(store, "BWBR9999999")
    assert (data.items, data.total, data.dossier_titles) == ([], 0, {})


# ── related instruments ──────────────────────────────────────────────────────


def test_related_instruments_of_a_bwb_regulation(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _doc("f1", "article", bwb_id=BWB),
            _doc("f2", "article", bwb_id=BWB),
            _doc("x1", "article", bwb_id="BWBR0000002"),
            _doc("x2", "article", bwb_id="BWBR0000002"),
            _doc("y1", "article", bwb_id="BWBR0000003"),
            _doc("z1", "article", bwb_id="BWBR0000004"),
            _doc("n1", "article", bwb_id="BWBR0000005"),
            _doc("eu", "article", celex=CELEX),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _doc("bwbr0000002", "instrument", bwb_id="BWBR0000002"),
            _doc("a_first", "instrument", bwb_id="BWBR0000003"),
            _doc("bwbr0000004", "instrument", bwb_id="BWBR0000004"),
            # BWBR0000005 has no instrument: dropped, not counted
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("articles/f1", "articles/x1", "REFERS_TO"),
            _edge("articles/f2", "articles/x2", "REFERS_TO"),
            _edge("articles/y1", "articles/f1", "REFERS_TO"),
            _edge("articles/f1", "articles/y1", "REFERS_TO"),
            _edge("articles/z1", "articles/f2", "REFERS_TO"),
            _edge("articles/f1", "articles/z1", "REFERS_TO"),
            _edge("articles/f1", "articles/n1", "REFERS_TO"),
            # inside the law, to a node that is no article, to an EU act (no bwb_id)
            _edge("articles/f1", "articles/f2", "REFERS_TO"),
            _edge("articles/f1", "judgments/j", "REFERS_TO"),
            _edge("articles/f1", "articles/eu", "REFERS_TO"),
            _edge("articles/f1", "articles/x1", "AMENDS"),
        ]
    )
    items, total = instruments.get_instrument_related_instruments(store, BWB)
    assert total == 3
    assert [
        (i["instrument"]["_key"], i["outbound_count"], i["inbound_count"])
        for i in items
    ] == [
        ("a_first", 1, 1),
        ("bwbr0000002", 2, 0),
        ("bwbr0000004", 1, 1),
    ]
    assert list(items[0]) == ["instrument", "outbound_count", "inbound_count"]
    assert list(items[0]["instrument"]) == ["_key", "_id", "type", "labels", "props"]
    items, total = instruments.get_instrument_related_instruments(store, BWB, limit=1)
    assert (total, len(items)) == (3, 1)


def test_related_instruments_of_an_eu_act(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _doc("eu1", "article", celex=CELEX),
            _doc("eu2", "article", celex="32000L0001"),
            _doc("nl1", "article", bwb_id=BWB),
            # an article with both: its bwb_id identifies it
            _doc("both", "article", bwb_id="BWBR0000009", celex="32000L0001"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _doc("32000l0001", "instrument", celex="32000L0001"),
            _doc(BWB.lower(), "instrument", bwb_id=BWB),
            _doc("bwbr0000009", "instrument", bwb_id="BWBR0000009"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("articles/eu1", "articles/eu2", "REFERS_TO"),
            _edge("articles/nl1", "articles/eu1", "REFERS_TO"),
            _edge("articles/nl1", "articles/eu1", "REFERS_TO") | {"_key": "dup"},
            _edge("articles/eu1", "articles/both", "REFERS_TO"),
        ]
    )
    items, total = instruments.get_instrument_related_instruments(store, CELEX)
    assert total == 3
    assert [
        (i["instrument"]["_key"], i["outbound_count"], i["inbound_count"])
        for i in items
    ] == [
        (BWB.lower(), 0, 2),
        ("32000l0001", 1, 0),
        ("bwbr0000009", 1, 0),
    ]


# ── the list ─────────────────────────────────────────────────────────────────


def _seed_list(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _doc(
                "bwbr0000002",
                "instrument",
                bwb_id="BWBR0000002",
                citation_title="Burgerlijk Wetboek",
                title="BW",
                kind="wet",
                jurisdiction="nl",
                article_count=500,
                inbound_citation_count=7,
                uri="https://wetten.overheid.nl/BWBR0000002",
            ),
            _doc(
                "bwbr0000001",
                "instrument",
                bwb_id="BWBR0000001",
                citation_title="Algemene wet",
                kind="wet",
                jurisdiction="nl",
                article_count=10,
                display_name="Awb",
            ),
            _doc(
                "t_only",
                "instrument",
                title="alleen titel",
                kind="amvb",
                jurisdiction="nl",
            ),
            _doc("dn_only", "instrument", display_name="Naam", article_count=10),
            _doc("bare", "instrument"),
            _doc(
                "32016r0679",
                "instrument",
                celex=CELEX,
                citation_title="AVG",
                kind="verordening",
                jurisdiction="eu",
                article_count=99,
            ),
            _doc(
                "stb1",
                "instrument",
                kind="publicatie",
                citation_title="Stb. 2019, 1",
                publication_kind="Stb",
                publication_year=2019,
                publication_number=1,
            ),
        ],
    )


def test_the_list_by_title(store: GraphStore) -> None:
    _seed_list(store)
    got = instruments.get_instruments_list(store)
    assert list(got) == ["total", "items"]
    assert got["total"] == 6
    # no citation_title first, by key; then the titles in the collation
    assert [i["_key"] for i in got["items"]] == [
        "bare",
        "dn_only",
        "t_only",
        "bwbr0000001",
        "32016r0679",
        "bwbr0000002",
    ]
    by_key = {i["_key"]: i for i in got["items"]}
    assert list(by_key["bwbr0000002"]) == [
        "_id",
        "_key",
        "bwb_id",
        "celex",
        "title",
        "short_title",
        "kind",
        "citation_title",
        "display_name",
        "jurisdiction",
        "article_count",
        "inbound_citation_count",
        "uri",
        "publication_kind",
        "publication_year",
        "publication_number",
        "next_version_from",
    ]
    assert by_key["bwbr0000002"] == {
        "_id": "instruments/bwbr0000002",
        "_key": "bwbr0000002",
        "bwb_id": "BWBR0000002",
        "celex": None,
        "title": "BW",
        "short_title": None,
        "kind": "wet",
        "citation_title": "Burgerlijk Wetboek",
        "display_name": "Burgerlijk Wetboek",
        "jurisdiction": "nl",
        "article_count": 500,
        "inbound_citation_count": 7,
        "uri": "https://wetten.overheid.nl/BWBR0000002",
        "publication_kind": None,
        "publication_year": None,
        "publication_number": None,
        "next_version_from": None,
    }
    assert (
        by_key["bwbr0000001"]["citation_title"],
        by_key["bwbr0000001"]["display_name"],
    ) == (
        "Algemene wet",
        "Awb",
    )
    assert (by_key["t_only"]["citation_title"], by_key["t_only"]["display_name"]) == (
        "alleen titel",
        "alleen titel",
    )
    assert by_key["dn_only"]["citation_title"] == "Naam"
    assert (by_key["bare"]["citation_title"], by_key["bare"]["display_name"]) == (
        "bare",
        "bare",
    )


def test_the_list_by_article_count_with_filters_and_paging(store: GraphStore) -> None:
    _seed_list(store)
    got = instruments.get_instruments_list(store, sort="article_count")
    # the most articles first, ties by key descending, none last
    assert [i["_key"] for i in got["items"]] == [
        "bwbr0000002",
        "32016r0679",
        "dn_only",
        "bwbr0000001",
        "t_only",
        "bare",
    ]
    got = instruments.get_instruments_list(store, jurisdiction="NL")
    assert (got["total"], [i["_key"] for i in got["items"]]) == (
        3,
        ["t_only", "bwbr0000001", "bwbr0000002"],
    )
    got = instruments.get_instruments_list(store, kind="Publicatie")
    assert (got["total"], [i["_key"] for i in got["items"]]) == (1, ["stb1"])
    assert got["items"][0]["publication_year"] == 2019
    got = instruments.get_instruments_list(store, article_count_min=11)
    assert (got["total"], [i["_key"] for i in got["items"]]) == (
        2,
        ["32016r0679", "bwbr0000002"],
    )
    got = instruments.get_instruments_list(
        store, kind="wet", article_count_min=10, sort="article_count", limit=1, offset=1
    )
    assert (got["total"], [i["_key"] for i in got["items"]]) == (2, ["bwbr0000001"])
    assert instruments.get_instruments_list(store, offset=100) == {
        "total": 6,
        "items": [],
    }
    # a query that tokenises to nothing is no filter
    got = instruments.get_instruments_list(store, q="!", limit=2)
    assert (got["total"], [i["_key"] for i in got["items"]]) == (6, ["bare", "dn_only"])


def test_the_list_names_the_first_coming_change(store: GraphStore) -> None:
    _seed_list(store)
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [
            _doc(
                "a_past",
                "instrument_version",
                bwb_id="BWBR0000001",
                valid_from="2000-01-01",
            ),
            _doc(
                "a_later",
                "instrument_version",
                bwb_id="BWBR0000001",
                valid_from="2999-07-01",
            ),
            _doc(
                "a_next",
                "instrument_version",
                bwb_id="BWBR0000001",
                valid_from="2999-01-01",
            ),
            _doc(
                "b_past",
                "instrument_version",
                bwb_id="BWBR0000002",
                valid_from="2001-01-01",
            ),
        ],
    )
    got = instruments.get_instruments_list(store)
    coming = {i["_key"]: i["next_version_from"] for i in got["items"]}
    # the first toestand after today; none for a law without one, an EU act or no law
    assert coming == {
        "bare": None,
        "dn_only": None,
        "t_only": None,
        "bwbr0000001": "2999-01-01",
        "32016r0679": None,
        "bwbr0000002": None,
    }


# ── versions and the law on a date ───────────────────────────────────────────


def _seed_versions(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [
            _doc("v2010", "instrument_version", bwb_id=BWB, valid_from="2010-01-01"),
            _doc("v2020b", "instrument_version", bwb_id=BWB, valid_from="2020-01-01"),
            _doc("v2020a", "instrument_version", bwb_id=BWB, valid_from="2020-01-01"),
            _doc(
                "v_other",
                "instrument_version",
                bwb_id="BWBR0000001",
                valid_from="2000-01-01",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _doc(
                "av1_old",
                "article_version",
                bwb_id=BWB,
                article_number="1",
                valid_from="2010-01-01",
                valid_until="2015-01-01",
                position=0,
            ),
            _doc(
                "av1_new",
                "article_version",
                bwb_id=BWB,
                article_number="1",
                valid_from="2015-01-01",
                position=0,
            ),
            _doc(
                "av2",
                "article_version",
                bwb_id=BWB,
                article_number="2",
                valid_from="2010-01-01",
                valid_until="2030-01-01",
                position=1,
            ),
            _doc(
                "av_nostart",
                "article_version",
                bwb_id=BWB,
                article_number="3",
                position=2,
            ),
            _doc(
                "av_nopos",
                "article_version",
                bwb_id=BWB,
                article_number="4",
                valid_from="2010-01-01",
            ),
            _doc(
                "av_bijlage",
                "article_version",
                bwb_id=BWB,
                article_number="bijlage I",
                valid_from="2010-01-01",
                position=3,
            ),
            # the match is case-sensitive, as LIKE in AQL
            _doc(
                "av_Bijlage",
                "article_version",
                bwb_id=BWB,
                article_number="Bijlage II",
                valid_from="2010-01-01",
                position=4,
            ),
            _doc(
                "av_late",
                "article_version",
                bwb_id=BWB,
                article_number="5",
                valid_from="2016-01-01",
                position=5,
            ),
        ],
    )


def test_versions_newest_first(store: GraphStore) -> None:
    _seed_versions(store)
    docs = instruments.get_instrument_versions(store, BWB.lower())
    assert _keys(docs) == ["v2020b", "v2020a", "v2010"]
    assert list(docs[0]) == ["_key", "_id", "type", "labels", "props"]
    assert instruments.get_instrument_versions(store, "BWBR9999999") == []


def test_articles_at_a_date(store: GraphStore) -> None:
    _seed_versions(store)
    law = instruments.get_articles_at(store, BWB.lower(), "2015-01-01")
    assert law.first_version_from == "2010-01-01"
    assert law.total == 5
    # the end is exclusive: on 2015-01-01 the new version of 1 holds
    assert _keys(law.items) == [
        "av1_new",
        "av2",
        "av_nostart",
        "av_Bijlage",
        "av_nopos",
    ]
    assert list(law.items[0]) == ["_key", "_id", "type", "labels", "props"]
    law = instruments.get_articles_at(store, BWB, "2014-12-31", limit=2, offset=1)
    assert (law.total, _keys(law.items)) == (5, ["av2", "av_nostart"])
    law = instruments.get_articles_at(store, BWB, "2014-12-31", offset=9)
    assert (law.total, law.items, law.first_version_from) == (5, [], "2010-01-01")
    # the first day of the first toestand holds the law; the day before nothing
    assert instruments.get_articles_at(store, BWB, "2010-01-01").total == 5
    before = instruments.get_articles_at(store, BWB, "2009-12-31")
    assert (before.items, before.total, before.first_version_from) == (
        [],
        0,
        "2010-01-01",
    )


def test_articles_at_a_date_without_a_start_of_the_law(store: GraphStore) -> None:
    _seed_versions(store)
    assert instruments.get_articles_at(store, "BWBR9999999", "2020-01-01") == (
        instruments.LawOnADate(items=[], total=0, first_version_from=None)
    )
    # a toestand without a start sorts first: no law on any date
    store.bulk_insert_or_update_nodes(
        "instrument_versions", [_doc("v_nostart", "instrument_version", bwb_id=BWB)]
    )
    law = instruments.get_articles_at(store, BWB, "2020-01-01")
    assert (law.items, law.total, law.first_version_from) == ([], 0, None)
