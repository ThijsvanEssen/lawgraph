"""The links of an instrument to EU acts and to international law on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import EDGE_SOURCE_BWB_IMPLEMENTS, SOURCE_ECHR
from lawgraph.db import GraphStore
from lawgraph.db.queries.instrument_links import get_eu_links, get_international_links
from lawgraph.db.queries.instrument_scope import InstrumentScope

REGULATION = "instruments/bwbr0009001"
OTHER_REGULATION = "instruments/bwbr0009002"
DIRECTIVE = "instruments/32016l0680"
EU_REGULATION = "instruments/32019r0001"
EU_OTHER = "instruments/32020l0002"
TREATY = "instruments/bwbv0009001"
ECHR = "instruments/bwbv0001000"
VERDRAG = "instruments/verdrag_1"
OWN_1 = "articles/bwbr0009001_1"
OWN_2 = "articles/bwbr0009001_2"
TREATY_3 = "articles/bwbv0009001_3"
ECHR_8 = "articles/bwbv0001000_8"


def _node(key: str, node_type: str, labels: list[str], **props: Any) -> Any:
    return {"_key": key, "type": node_type, "labels": labels, "props": props}


def _edge(
    key: str,
    source: str,
    target: str,
    relation: str,
    confidence: float | None,
    *,
    origin: str = "test",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": origin,
        "status": "canoniek",
        "confidence": confidence,
        "meta": meta or {"note": key},
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0009001", "instrument", ["BWB"], bwb_id="BWBR0009001"),
            _node("bwbr0009002", "instrument", ["BWB"], bwb_id="BWBR0009002"),
            _node("32016l0680", "instrument", ["EU"], celex="32016L0680"),
            _node("32019r0001", "instrument", ["EU"], celex="32019R0001"),
            _node("32020l0002", "instrument", ["EU"], celex="32020L0002"),
            _node(
                "bwbv0009001",
                "instrument",
                ["BWB"],
                bwb_id="BWBV0009001",
                kind="verdrag",
            ),
            _node(
                "bwbv0001000",
                "instrument",
                ["BWB"],
                bwb_id="BWBV0001000",
                kind="verdrag",
            ),
            _node("verdrag_1", "instrument", ["Verdragenbank"], jurisdiction="int"),
        ],
    )

    def article(key: str, number: str, **props: Any) -> Any:
        return _node(
            key,
            "article",
            ["Article"],
            article_number=number,
            display_name=f"Artikel {number}",
            **props,
        )

    store.bulk_insert_or_update_nodes(
        "articles",
        [
            article("bwbr0009001_1", "1", bwb_id="BWBR0009001"),
            article("bwbr0009001_2", "2", bwb_id="BWBR0009001"),
            article("bwbr0009002_1", "1", bwb_id="BWBR0009002"),
            article("bwbv0009001_3", "3", bwb_id="BWBV0009001"),
            article("bwbv0001000_8", "8", bwb_id="BWBV0001000"),
            # an article of a treaty the graph does not hold
            article("bwbv0099999_1", "1", bwb_id="BWBV0099999"),
            article("32016l0680_1", "1", celex="32016L0680"),
        ],
    )

    def judgment(key: str, source: str, date: str | None = None) -> Any:
        props: dict[str, Any] = {
            "ecli": f"ECLI:{key}",
            "display_name": key.upper(),
            "source": source,
            "text": "not read",
        }
        if date:
            props["date"] = date
        return _node(key, "judgment", ["Judgment"], **props)

    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            judgment("echr_1", SOURCE_ECHR, "2020-01-01"),
            judgment("echr_2", SOURCE_ECHR, "2021-01-01"),
            judgment("echr_3", SOURCE_ECHR),
            judgment("echr_4", SOURCE_ECHR, "2022-01-01"),
            judgment("echr_5", SOURCE_ECHR, "2022-01-01"),
            judgment("echr_6", SOURCE_ECHR, "2022-01-01"),
            judgment("nl_1", "rechtspraak", "2022-01-01"),
        ],
    )

    mention = EDGE_SOURCE_BWB_IMPLEMENTS
    store.bulk_insert_or_update_edges(
        [
            # eu-links
            _edge("i1", REGULATION, DIRECTIVE, "IMPLEMENTS", 0.9),
            _edge("i2", REGULATION, EU_REGULATION, "IMPLEMENTS", 0.9),
            _edge("i3", REGULATION, EU_OTHER, "IMPLEMENTS", None),
            _edge("i4", REGULATION, "instruments/missing", "IMPLEMENTS", 1.0),
            _edge("i5", REGULATION, OWN_1, "IMPLEMENTS", 1.0),
            _edge("i6", OTHER_REGULATION, DIRECTIVE, "IMPLEMENTS", 1.0),
            _edge("m1", REGULATION, EU_OTHER, "REFERS_TO", 0.5, origin=mention),
            _edge("m2", REGULATION, EU_REGULATION, "REFERS_TO", 0.6),
            # treaties
            _edge("t1", OWN_1, TREATY_3, "REFERS_TO", 0.8),
            _edge("t2", OWN_2, TREATY, "REFERS_TO", 0.8),
            _edge("t3", OWN_1, VERDRAG, "REFERS_TO", None),
            _edge("t4", OWN_1, OTHER_REGULATION, "REFERS_TO", 1.0),
            _edge("t5", OWN_1, "articles/bwbr0009002_1", "REFERS_TO", 1.0),
            _edge("t6", OWN_1, "articles/bwbv0099999_1", "REFERS_TO", 1.0),
            _edge("t7", OWN_2, ECHR_8, "REFERS_TO", 0.8),
            _edge("t8", OWN_1, TREATY, "REFERS_TO", 0.8),
            _edge("t9", OWN_1, ECHR, "IMPLEMENTS", 1.0),
            _edge("t10", "articles/32016l0680_1", ECHR, "REFERS_TO", 0.7),
            # ECHR judgments
            _edge("j1", "judgments/echr_1", REGULATION, "REFERS_TO", 0.9),
            _edge("j2", "judgments/echr_2", OWN_1, "REFERS_TO", 0.9),
            _edge("j3", "judgments/echr_3", OWN_2, "REFERS_TO", 0.9),
            _edge("j4", "judgments/echr_4", OWN_2, "REFERS_TO", None),
            _edge("j5", "judgments/echr_5", "articles/bwbr0009002_1", "REFERS_TO", 1.0),
            _edge("j6", "judgments/echr_6", VERDRAG, "REFERS_TO", 1.0),
            _edge("j7", "judgments/nl_1", REGULATION, "REFERS_TO", 1.0),
            _edge("j8", "judgments/echr_missing", REGULATION, "REFERS_TO", 1.0),
        ]
    )


def _instrument_keys(rows: list[dict[str, Any]]) -> list[str]:
    return [r["instrument"]["_key"] for r in rows]


def test_eu_links_in_both_directions_most_confident_first(store: GraphStore) -> None:
    _seed(store)

    links = get_eu_links(store, REGULATION)

    assert _instrument_keys(links.implements) == [
        "32016l0680",
        "32019r0001",
        "32020l0002",  # no confidence: last
    ]
    assert links.implements_total == 3
    assert links.implements[0] == {
        "instrument": {
            "_key": "32016l0680",
            "_id": DIRECTIVE,
            "type": "instrument",
            "labels": ["EU"],
            "props": {"celex": "32016L0680"},
        },
        "edge": {
            "relation": "IMPLEMENTS",
            "confidence": 0.9,
            "source": "test",
            "meta": {"note": "i1"},
        },
    }
    assert list(links.implements[0]) == ["instrument", "edge"]
    assert list(links.implements[0]["instrument"]) == [
        "_key",
        "_id",
        "type",
        "labels",
        "props",
    ]
    assert list(links.implements[0]["edge"]) == [
        "relation",
        "confidence",
        "source",
        "meta",
    ]
    assert links.implements[2]["edge"]["confidence"] is None
    # only the REFERS_TO edges of semantic bwb-implements
    assert _instrument_keys(links.mentions) == ["32020l0002"]
    assert links.mentions_total == 1
    assert (links.implemented_by, links.implemented_by_total) == ([], 0)
    assert (links.mentioned_by, links.mentioned_by_total) == ([], 0)

    directive = get_eu_links(store, DIRECTIVE)
    assert _instrument_keys(directive.implemented_by) == ["bwbr0009002", "bwbr0009001"]
    assert directive.implemented_by_total == 2
    assert _instrument_keys(get_eu_links(store, EU_OTHER).mentioned_by) == [
        "bwbr0009001"
    ]


def test_eu_links_are_cut_and_their_totals_are_not(store: GraphStore) -> None:
    _seed(store)

    links = get_eu_links(store, REGULATION, limit=2)

    assert _instrument_keys(links.implements) == ["32016l0680", "32019r0001"]
    assert links.implements_total == 3
    empty = get_eu_links(store, "instruments/none")
    assert empty.implements == [] and empty.implements_total == 0


def _ref(article_id: str, number: str) -> dict[str, Any]:
    return {
        "id": article_id,
        "key": article_id.split("/")[1],
        "article_number": number,
        "display_name": f"Artikel {number}",
    }


def test_the_treaties_the_articles_of_an_instrument_refer_to(
    store: GraphStore,
) -> None:
    _seed(store)

    links = get_international_links(
        store, REGULATION, InstrumentScope("bwb_id", "BWBR0009001")
    )

    assert [
        (
            r["instrument"]["_key"],
            r["own_article"]["key"],
            r["counterpart_article"] and r["counterpart_article"]["key"],
        )
        for r in links.treaties
    ] == [
        ("bwbv0001000", "bwbr0009001_2", "bwbv0001000_8"),  # the lower treaty key
        ("bwbv0009001", "bwbr0009001_1", None),  # the treaty before its article
        ("bwbv0009001", "bwbr0009001_1", "bwbv0009001_3"),
        ("bwbv0009001", "bwbr0009001_2", None),
        ("verdrag_1", "bwbr0009001_1", None),  # no confidence: last
    ]
    assert links.treaties_total == 5
    first = links.treaties[0]
    assert list(first) == ["instrument", "own_article", "counterpart_article", "edge"]
    assert first == {
        "instrument": {
            "_key": "bwbv0001000",
            "_id": ECHR,
            "type": "instrument",
            "labels": ["BWB"],
            "props": {"bwb_id": "BWBV0001000", "kind": "verdrag"},
        },
        "own_article": _ref(OWN_2, "2"),
        "counterpart_article": _ref(ECHR_8, "8"),
        "edge": {"confidence": 0.8, "source": "test", "meta": {"note": "t7"}},
    }
    assert list(first["own_article"]) == [
        "id",
        "key",
        "article_number",
        "display_name",
    ]


def test_the_echr_judgments_that_refer_to_an_instrument(store: GraphStore) -> None:
    _seed(store)

    links = get_international_links(
        store, REGULATION, InstrumentScope("bwb_id", "BWBR0009001")
    )

    assert [r["judgment"]["_key"] for r in links.judgments] == [
        "echr_2",  # newest of the most confident
        "echr_1",
        "echr_3",  # no date
        "echr_4",  # no confidence
    ]
    assert links.judgments_total == 4
    assert links.judgments[0] == {
        "judgment": {
            "_id": "judgments/echr_2",
            "_key": "echr_2",
            "props": {"ecli": "ECLI:echr_2", "display_name": "ECHR_2"},
        },
        "own_article": _ref(OWN_1, "1"),
        "edge": {"confidence": 0.9, "source": "test", "meta": {"note": "j2"}},
    }
    assert list(links.judgments[0]) == ["judgment", "own_article", "edge"]
    # an edge to the instrument names no article of it
    assert links.judgments[1]["own_article"] is None


def test_international_links_are_cut_and_scoped(store: GraphStore) -> None:
    _seed(store)
    scope = InstrumentScope("bwb_id", "BWBR0009001")

    cut = get_international_links(store, REGULATION, scope, limit=1)
    assert len(cut.treaties) == 1 and cut.treaties_total == 5
    assert len(cut.judgments) == 1 and cut.judgments_total == 4

    # without a scope the instrument has no articles: judgments of the instrument only
    verdrag = get_international_links(store, VERDRAG, None)
    assert (verdrag.treaties, verdrag.treaties_total) == ([], 0)
    assert [r["judgment"]["_key"] for r in verdrag.judgments] == ["echr_6"]
    assert verdrag.judgments[0]["own_article"] is None

    # an EU act's articles carry its CELEX number
    eu = get_international_links(
        store, DIRECTIVE, InstrumentScope("celex", "32016L0680")
    )
    assert [
        (r["instrument"]["_key"], r["counterpart_article"]) for r in eu.treaties
    ] == [("bwbv0001000", None)]
    assert eu.judgments_total == 0
