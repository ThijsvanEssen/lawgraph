"""Whether a law or an article holds, as the API says it (``validity``), and expired ones
lower in the search: the Bouwbesluit 2012, repealed on 1 January 2024 and replaced by the
Besluit bouwwerken leefomgeving, said "geldend" on its page and was the first hit for
"dakkapel"; art. 28a of the Wte, which lapsed in 2007 in a law still in force, said
"Geldend recht"."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_PART_OF, RELATION_TRANSPOSED_TO
from lawgraph.core.completeness import SOURCE_RUN_STATE
from lawgraph.db import GraphStore, make_edge_doc, version_cache
from lawgraph.db.queries import state as state_queries
from lawgraph.db.queries.search import dispatch
from tests.databases import Api

BOUWBESLUIT, BBL, WTE = "BWBR0030461", "BWBR0041297", "BWBR0007657"
FUTURE = "BWBR0099999"


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "labels": [], "props": props}


def _put(store: GraphStore, collection: str, nodes: list[dict[str, Any]]) -> None:
    store.bulk_insert_or_update_nodes(
        collection, [{**node, "type": collection[:-1]} for node in nodes]
    )


def _seed(store: GraphStore) -> None:
    _put(
        store,
        "instruments",
        [
            _node(
                "bwbr0030461",
                bwb_id=BOUWBESLUIT,
                title="Bouwbesluit 2012",
                citation_title="Bouwbesluit 2012",
                source="bwb",
                date_in_force="2012-04-01",
                date_expired="2024-01-01",
            ),
            _node(
                "bwbr0041297",
                bwb_id=BBL,
                title="Besluit bouwwerken leefomgeving",
                citation_title="Besluit bouwwerken leefomgeving",
                source="bwb",
                date_in_force="2024-01-01",
            ),
            _node(
                "bwbr0007657",
                bwb_id=WTE,
                title="Wet toezicht effectenverkeer 1995",
                source="bwb",
                date_in_force="1995-06-01",
            ),
            _node(
                "bwbr0099999",
                bwb_id=FUTURE,
                title="Wet later",
                source="bwb",
                date_in_force="2099-01-01",
            ),
            _node(
                "wet_stb_2026_56",
                title="Wetboek van Strafvordering",
                source="staatsblad",
                kind="wet",
                official_id="stb-2026-56",
                status="vastgesteld",
                in_force=False,
            ),
            _node(
                "32016l0680",
                celex="32016L0680",
                title="Richtlijn 2016/680",
                source="eurlex",
            ),
        ],  # fmt: skip
    )
    _put(
        store,
        "articles",
        [
            _node(
                "bwbr0030461_1_1",
                bwb_id=BOUWBESLUIT,
                article_number="1.1",
                stam_id="1",
                text="Een dakkapel dakkapel is een bouwwerk.",
            ),
            _node(
                "bwbr0041297_2_29",
                bwb_id=BBL,
                article_number="2.29",
                stam_id="2",
                text="Vergunningvrij is een dakkapel in het achterdakvlak, als wordt "
                "voldaan aan de eisen van plat dak en hoogte en de afstand tot de "
                "dakvoet en de daknok en de zijkanten van het dakvlak.",
            ),
            _node(
                "bwbr0007657_28a",
                bwb_id=WTE,
                article_number="28a",
                stam_id="3",
                text="Vervallen",
            ),
            _node(
                "bwbr0007657_29",
                bwb_id=WTE,
                article_number="29",
                stam_id="4",
                text="Een effect.",
            ),
        ],  # fmt: skip
    )
    _put(
        store,
        "article_versions",
        [
            _node(
                "bwbr0007657_28a_1998",
                bwb_id=WTE,
                article_number="28a",
                stam_id="3",
                valid_from="1998-09-25",
                valid_until="2007-01-01",
            ),
            _node(
                "bwbr0007657_28a_2007",
                bwb_id=WTE,
                article_number="28a",
                stam_id="3",
                valid_from="2007-01-01",
                valid_until="2007-01-01",
            ),
            _node(
                "bwbr0007657_29_1998",
                bwb_id=WTE,
                article_number="29",
                stam_id="4",
                valid_from="1998-09-25",
                current=True,
            ),
        ],  # fmt: skip
    )
    store.bulk_insert_or_update_edges(
        [
            *(
                make_edge_doc(
                    f"articles/{article}", f"instruments/{law}", RELATION_PART_OF
                )
                for article, law in [
                    ("bwbr0030461_1_1", "bwbr0030461"),
                    ("bwbr0041297_2_29", "bwbr0041297"),
                    ("bwbr0007657_28a", "bwbr0007657"),
                    ("bwbr0007657_29", "bwbr0007657"),
                ]
            ),
            make_edge_doc(
                "articles/bwbr0030461_1_1",
                "articles/bwbr0041297_2_29",
                RELATION_TRANSPOSED_TO,
                meta={"basis": "transposition_table", "source": "stb-2018-291"},
            ),
        ]
    )
    state_queries.set_state(
        store,
        SOURCE_RUN_STATE + "bwb",
        {
            "state": "done",
            "at": "2026-10-20T23:10:34Z",
            "as_of": "2026-10-20T23:10:34Z",
        },
    )


@pytest.fixture()
def seeded(store: GraphStore) -> Iterator[GraphStore]:
    version_cache.clear()
    _seed(store)
    yield store
    version_cache.clear()


def _law(api: Api, identifier: str) -> Any:
    return api.get_json(f"/api/instruments/{identifier}")["validity"]


def _article(api: Api, law: str, number: str) -> Any:
    return api.get_json(f"/api/articles/{law}/{number}")["article"]["validity"]


def test_a_law_says_whether_it_holds_and_what_replaced_it(
    seeded: GraphStore, api: Api
) -> None:
    repealed = _law(api, BOUWBESLUIT)
    assert (repealed["state"], repealed["date"], repealed["as_of"]) == (
        "expired",
        "2024-01-01",
        "2026-10-21",
    )
    assert [
        (s["bwb_id"], s["articles"], s["path"]) for s in repealed["successors"]
    ] == [(BBL, 1, f"/wetten/{BBL}")]
    assert (_law(api, BBL)["state"], _law(api, BBL)["successors"]) == ("in_force", [])
    assert (_law(api, FUTURE)["state"], _law(api, FUTURE)["date"]) == (
        "not_in_force_yet",
        "2099-01-01",
    )
    assert _law(api, "STB-2026-56")["state"] == "not_in_force_yet"
    assert _law(api, "32016L0680") is None


def test_an_article_holds_as_long_as_its_law_and_its_own_versions(
    seeded: GraphStore, api: Api
) -> None:
    old = _article(api, BOUWBESLUIT, "1.1")
    assert (old["state"], old["date"]) == ("expired", "2024-01-01")
    assert [s["bwb_id"] for s in old["successors"]] == [BBL]
    lapsed = _article(api, WTE, "28a")
    assert (lapsed["state"], lapsed["date"], lapsed["successors"]) == (
        "expired",
        "2007-01-01",
        [],
    )
    assert _article(api, WTE, "29")["state"] == "in_force"
    assert _article(api, BBL, "2.29")["state"] == "in_force"


def test_an_expired_law_or_article_comes_after_those_that_hold(
    seeded: GraphStore,
) -> None:
    """Both articles hold "dakkapel" in their text (0.1); the old one twice, in a short
    text, which BM25 ranks higher. While typing too."""
    full = dispatch.search_all(seeded, q="dakkapel", types=["articles"], limit=10)
    live, _ = dispatch.search_live(seeded, q="dakkapel", types=["articles"], limit=10)
    for found in (full["articles"], live["articles"]):
        assert [hit["key"] for hit in found] == ["bwbr0041297_2_29", "bwbr0030461_1_1"]
        assert [hit["extra"]["expired_on"] for hit in found] == [None, "2024-01-01"]
