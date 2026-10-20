"""Where judgments cite an article: the real ``semantic rechtspraak`` and the API on its answer.

``normalize rechtspraak`` and ``semantic rechtspraak`` run as processes of their own on the
test server, on three judgments that cite article 1 of the Grondwet in numbered paragraphs.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    RELATION_REFERS_TO,
)
from lawgraph.db import EdgeWriter, GraphStore
from lawgraph.pipelines.semantic.rechtspraak import (
    EDGE_SOURCE as RECHTSPRAAK_LINKER,
)
from tests.asserts import assert_status, show_items
from tests.databases import Api, module_store
from tests.integration.seed import judgment_xml, seed, write_judgments
from tests.optional import present

GRONDWET = "BWBR0001840"
LAW = "artikel 1 van de Grondwet"
LAW_LID_3 = "artikel 1, derde lid, van de Grondwet"
LAW_LID_2 = "artikel 1, tweede lid, van de Grondwet"


JUDGMENTS = {
    # two citations in one paragraph, one in the next
    "ECLI:NL:HR:2020:1": judgment_xml(
        "ECLI:NL:HR:2020:1",
        "2020-03-01",
        [
            ("1.1", f"Volgens {LAW} geldt dit; anders dan {LAW_LID_3} betoogt."),
            ("1.2", f"Zie ook {LAW_LID_2}."),
        ],
    ),
    "ECLI:NL:GHAMS:2021:2": judgment_xml(
        "ECLI:NL:GHAMS:2021:2", "2021-05-05", [("4.2", f"Op grond van {LAW_LID_3}.")]
    ),
    "ECLI:NL:RBAMS:2019:3": judgment_xml(
        "ECLI:NL:RBAMS:2019:3", "2019-01-01", [("2", f"Het {LAW} is van belang.")]
    ),
}


# The tests read one database built for them all (``store``), on the worker that built it;
# the one that writes has a database of its own (``database``).
pytestmark = pytest.mark.xdist_group("judgment_mentions")


def _build(store: GraphStore, cli: Any) -> None:
    seed(store, documents=0, judgments=0, regulations=1)
    write_judgments(store, JUDGMENTS)
    cli("normalize", "bwb")
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests that only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _build(store, cli)
        yield store


def _edge_to_grondwet_1(store: GraphStore, ecli_key: str) -> dict[str, Any]:
    sql = (
        "SELECT doc FROM edges WHERE from_id = %(from)s AND to_id = %(to)s "
        "AND relation = 'REFERS_TO'"
    )
    params = {"from": f"judgments/{ecli_key}", "to": "articles/bwbr0001840_1"}
    (edge,) = store.query(sql, params)
    return edge


def test_the_edge_of_a_judgment_keeps_every_mention_with_its_paragraph_and_span(
    store: GraphStore,
) -> None:
    edge = _edge_to_grondwet_1(store, "ecli_nl_hr_2020_1")
    judgment = store.get_document("judgments", "ecli_nl_hr_2020_1")
    paragraphs = {p["id"]: p for p in present(judgment)["props"]["paragraphs"]}

    assert edge["meta"]["mention_count"] == 3
    assert edge["confidence"] == 0.95
    first, second, third = edge["meta"]["mentions"]
    assert [m["paragraph_id"] for m in (first, second, third)] == [
        "rov-1.1",
        "rov-1.1",
        "rov-1.2",
    ]
    # every span is a place in the text of its paragraph, in reading order
    for mention in (first, second, third):
        text = paragraphs[mention["paragraph_id"]]["text"]
        assert text[mention["start"] : mention["end"]] == mention["raw_match"]
    assert first["end"] <= second["start"]
    assert first["raw_match"] == LAW and second["raw_match"] == LAW_LID_3
    assert (first["leden"], second["leden"], third["leden"]) == ([], ["3"], ["2"])
    assert second["paragraph_number"] == "1.1" and second["qualifier"] == "derde lid"


def test_the_judgment_serves_the_stored_citations_per_occurrence(
    api: Api,
) -> None:
    body = api.get_json("/api/judgments/ECLI:NL:HR:2020:1")

    paragraphs = {p["paragraph_id"]: p for p in body["judgment"]["paragraphs"]}
    assert paragraphs["rov-1.1"]["number"] == "1.1"
    text = paragraphs["rov-1.1"]["text"]
    first, second = paragraphs["rov-1.1"]["citations"]
    assert text[first["start"] : first["end"]] == LAW
    assert text[second["start"] : second["end"]] == LAW_LID_3
    assert second["leden"] == ["3"] and first["start"] < second["start"]
    assert first["target"]["article_number"] == "1"
    (last,) = paragraphs["rov-1.2"]["citations"]
    assert last["leden"] == ["2"]

    (cited,) = body["cited_articles"]
    assert cited["article"]["bwb_id"] == GRONDWET
    assert cited["paragraph_ids"] == ["rov-1.1", "rov-1.2"]
    assert cited["paragraph_numbers"] == ["1.1", "1.2"]
    assert cited["mention_count"] == 3 and cited["confidence"] == 0.95
    assert len(body["articles"]) == 1
    # the words of the strongest mention, where the linker found them in its snippet
    assert cited["snippet_paragraph_id"] == "rov-1.1" and cited["text"] == LAW
    assert cited["snippet"][cited["start"] : cited["end"]] == LAW


def _cited_by(api: Api, **params: Any) -> dict[str, Any]:
    body: dict[str, Any] = api.get_json(
        f"/api/articles/{GRONDWET}/1/cited-by", **params
    )
    return body


def test_an_article_lists_the_passages_that_cite_it_newest_judgment_first(
    api: Api,
) -> None:
    body = _cited_by(api)

    assert body["total"] == 5 and body["article_id"] == "articles/bwbr0001840_1"
    # five passages in three judgments
    assert body["judgment_total"] == 3
    rows = [(i["judgment"]["ecli"], i["paragraph_id"]) for i in body["items"]]
    assert rows == [
        ("ECLI:NL:GHAMS:2021:2", "rov-4.2"),
        ("ECLI:NL:HR:2020:1", "rov-1.1"),
        ("ECLI:NL:HR:2020:1", "rov-1.1"),
        ("ECLI:NL:HR:2020:1", "rov-1.2"),
        ("ECLI:NL:RBAMS:2019:3", "rov-2"),
    ]
    first = body["items"][0]
    assert first["judgment"]["court"] == "GHAMS"
    assert first["judgment"]["tier"] == "gerechtshof"
    assert first["judgment"]["date"] == "2021-05-05"
    assert first["paragraph_number"] == "4.2"
    assert first["leden"] == ["3"] and first["qualifier"] == "derde lid"
    assert first["text"] == LAW_LID_3
    assert LAW_LID_3 in first["snippet"] and first["confidence"] == 0.95
    # within a judgment the passages follow the text
    hr = [i for i in body["items"] if i["judgment"]["court"] == "HR"]
    assert [i["start"] for i in hr[:2]] == sorted(i["start"] for i in hr[:2])


def test_the_passages_filter_on_court_tier_and_lid_and_page_with_an_exact_total(
    api: Api,
) -> None:
    by_court = _cited_by(api, court="hr")
    assert by_court["total"] == 3
    assert {i["judgment"]["ecli"] for i in by_court["items"]} == {"ECLI:NL:HR:2020:1"}

    by_tier = _cited_by(api, tier="rechtbank")
    assert by_tier["total"] == 1
    assert by_tier["items"][0]["judgment"]["ecli"] == "ECLI:NL:RBAMS:2019:3"

    by_lid = _cited_by(api, lid="3")
    assert (by_lid["total"], by_lid["judgment_total"]) == (2, 2)
    assert {i["judgment"]["court"] for i in by_lid["items"]} == {"HR", "GHAMS"}
    failing = [i for i in by_lid["items"] if i["leden"] != ["3"]]
    assert not failing, show_items(failing)

    assert _cited_by(api, court="HR", lid="2")["total"] == 1
    assert _cited_by(api, court="GHAMS", lid="2")["items"] == []

    page = _cited_by(api, limit=2, offset=2)
    assert page["total"] == 5 and len(page["items"]) == 2
    assert [i["paragraph_id"] for i in page["items"]] == ["rov-1.1", "rov-1.2"]
    assert _cited_by(api, limit=2, offset=4)["items"][0]["judgment"]["court"] == (
        "RBAMS"
    )
    assert _cited_by(api, offset=99) == {
        "article_id": "articles/bwbr0001840_1",
        "items": [],
        "total": 5,
        "judgment_total": 3,
        "echr_judgment_total": 0,
    }


def test_an_unknown_article_is_a_404_and_a_bad_filter_a_422(
    api: Api,
) -> None:
    assert_status(api.get(f"/api/articles/{GRONDWET}/999/cited-by"), 404)
    assert_status(api.get(f"/api/articles/{GRONDWET}/1/cited-by?lid=x!"), 422)
    assert_status(api.get(f"/api/articles/{GRONDWET}/1/cited-by?tier=zzz"), 422)
    assert_status(api.get(f"/api/articles/{GRONDWET}/1/cited-by?limit=0"), 422)


def test_a_citation_the_text_no_longer_makes_goes(database: str, cli: Any) -> None:
    """An edge an earlier run made (to the wrong article, with the paragraph number of
    then) goes when the judgment is linked again."""
    store = GraphStore()
    _build(store, cli)
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            "judgments/ecli_nl_hr_2020_1",
            "articles/bwbr0001840_2",
            RELATION_REFERS_TO,
            source=RECHTSPRAAK_LINKER,
            meta={
                "mentions": [
                    {
                        "paragraph_id": "rov-1.1",
                        "paragraph_number": "1.1.",
                        "start": 0,
                        "end": 9,
                        "raw_match": "artikel 2",
                        "snippet": "zie artikel 2",
                        "confidence": 0.9,
                    }
                ]
            },
        )

    cli("semantic", "rechtspraak")

    cited = store.query(
        "SELECT to_id FROM edges WHERE from_id = 'judgments/ecli_nl_hr_2020_1' "
        "AND relation = 'REFERS_TO'"
    )
    assert list(cited) == ["articles/bwbr0001840_1"]


def test_a_neighbor_neighborhood_and_path_give_the_passages_where_a_judgment_cites(
    api: Api,
) -> None:
    article = "articles/bwbr0001840_1"
    judgment = "judgments/ecli_nl_hr_2020_1"
    asked = {"relations": "REFERS_TO", "edge_meta": "passages"}

    def neighbor(**params: Any) -> dict[str, Any]:
        body = api.get_json(f"/api/nodes/{article}", **params)
        (row,) = [
            item
            for bucket in body["neighbors"]["buckets"]
            for item in bucket["items"]
            if item["id"] == judgment
        ]
        return row["meta"]

    assert "passages" not in neighbor(relations="REFERS_TO")
    first, second = neighbor(**asked)["passages"]  # the first place of each paragraph
    assert (first["paragraph_id"], first["paragraph_number"]) == ("rov-1.1", "1.1")
    assert (first["text"], second["paragraph_id"]) == (LAW, "rov-1.2")
    for passage in (first, second):
        assert passage["snippet"][passage["start"] : passage["end"]] == passage["text"]
        assert passage["footnote"] is None
    assert neighbor(**asked, props="canvas")["passages"] == [first, second]

    body = api.get_json(f"/api/nodes/{article}/neighborhood", **asked)
    (edge,) = [e for e in body["edges"] if e["source"] == judgment]
    assert edge["passages"] == [first, second]
    plain = api.get_json(f"/api/nodes/{article}/neighborhood", depth=1)
    failing = [e for e in plain["edges"] if "passages" in e]
    assert not failing, show_items(failing)

    ids = f"{judgment},{article}"
    body = api.get_json("/api/paths", ids=ids, edge_meta="passages")
    (edge,) = body["edges"]
    assert edge["passages"] == [first, second]
    plain = api.get_json("/api/paths", ids=ids)
    assert "passages" not in plain["edges"][0]
