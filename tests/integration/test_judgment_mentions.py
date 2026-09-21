"""Where judgments cite an article: the real ``semantic rechtspraak`` and the API on its answer.

``normalize rechtspraak`` and ``semantic rechtspraak`` run as processes of their own on the
test server, on three judgments that cite article 1 of the Grondwet in numbered paragraphs.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import seed

GRONDWET = "BWBR0001840"
LAW = "artikel 1 van de Grondwet"
LAW_LID_3 = "artikel 1, derde lid, van de Grondwet"
LAW_LID_2 = "artikel 1, tweede lid, van de Grondwet"


def _judgment_xml(ecli: str, date: str, paragraphs: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<paragroup><nr>{number}</nr><para>{text}</para></paragroup>"
        for number, text in paragraphs
    )
    return (
        '<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dcterms="http://purl.org/dc/terms/"><rdf:RDF><rdf:Description>'
        f"<dcterms:identifier>{ecli}</dcterms:identifier>"
        f"<dcterms:creator>Een rechter</dcterms:creator><dcterms:date>{date}</dcterms:date>"
        "</rdf:Description></rdf:RDF><uitspraak><section>"
        f"<title><nr>1</nr>Overwegingen</title>{body}</section></uitspraak></open>"
    )


JUDGMENTS = {
    # two citations in one paragraph, one in the next
    "ECLI:NL:HR:2020:1": _judgment_xml(
        "ECLI:NL:HR:2020:1",
        "2020-03-01",
        [
            ("1.1", f"Volgens {LAW} geldt dit; anders dan {LAW_LID_3} betoogt."),
            ("1.2", f"Zie ook {LAW_LID_2}."),
        ],
    ),
    "ECLI:NL:GHAMS:2021:2": _judgment_xml(
        "ECLI:NL:GHAMS:2021:2", "2021-05-05", [("4.2", f"Op grond van {LAW_LID_3}.")]
    ),
    "ECLI:NL:RBAMS:2019:3": _judgment_xml(
        "ECLI:NL:RBAMS:2019:3", "2019-01-01", [("2", f"Het {LAW} is van belang.")]
    ),
}


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
    seed(store, documents=0, judgments=0, regulations=1)
    with RawSourceWriter(store) as writer:
        for ecli, xml in JUDGMENTS.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=xml,
                    meta={"ecli": ecli},
                )
            )
    cli("normalize", "bwb")
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _edge_to_grondwet_1(store: ArangoStore, ecli_key: str) -> dict[str, Any]:
    aql = (
        "FOR e IN edges FILTER e._from == @from AND e._to == @to "
        "AND e.relation == 'REFERS_TO' RETURN e"
    )
    bind = {"from": f"judgments/{ecli_key}", "to": "articles/bwbr0001840_1"}
    (edge,) = store.query(aql, bind)
    return edge


def test_the_edge_of_a_judgment_keeps_every_mention_with_its_paragraph_and_span(
    client: TestClient,
) -> None:
    store = ArangoStore()
    edge = _edge_to_grondwet_1(store, "ecli_nl_hr_2020_1")
    judgment = store.judgments.get("ecli_nl_hr_2020_1")
    paragraphs = {p["id"]: p for p in judgment["props"]["paragraphs"]}

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
    client: TestClient,
) -> None:
    body = client.get("/api/judgments/ECLI:NL:HR:2020:1").json()

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


def _cited_by(client: TestClient, **params: Any) -> dict[str, Any]:
    answer = client.get(f"/api/articles/{GRONDWET}/1/cited-by", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_an_article_lists_the_passages_that_cite_it_newest_judgment_first(
    client: TestClient,
) -> None:
    body = _cited_by(client)

    assert body["total"] == 5 and body["article_id"] == "articles/bwbr0001840_1"
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
    client: TestClient,
) -> None:
    by_court = _cited_by(client, court="hr")
    assert by_court["total"] == 3
    assert {i["judgment"]["ecli"] for i in by_court["items"]} == {"ECLI:NL:HR:2020:1"}

    by_tier = _cited_by(client, tier="rechtbank")
    assert by_tier["total"] == 1
    assert by_tier["items"][0]["judgment"]["ecli"] == "ECLI:NL:RBAMS:2019:3"

    by_lid = _cited_by(client, lid="3")
    assert by_lid["total"] == 2
    assert {i["judgment"]["court"] for i in by_lid["items"]} == {"HR", "GHAMS"}
    assert all(i["leden"] == ["3"] for i in by_lid["items"])

    assert _cited_by(client, court="HR", lid="2")["total"] == 1
    assert _cited_by(client, court="GHAMS", lid="2")["items"] == []

    page = _cited_by(client, limit=2, offset=2)
    assert page["total"] == 5 and len(page["items"]) == 2
    assert [i["paragraph_id"] for i in page["items"]] == ["rov-1.1", "rov-1.2"]
    assert _cited_by(client, limit=2, offset=4)["items"][0]["judgment"]["court"] == (
        "RBAMS"
    )
    assert _cited_by(client, offset=99) == {
        "article_id": "articles/bwbr0001840_1",
        "items": [],
        "total": 5,
    }


def test_an_unknown_article_is_a_404_and_a_bad_filter_a_422(
    client: TestClient,
) -> None:
    assert client.get(f"/api/articles/{GRONDWET}/999/cited-by").status_code == 404
    assert client.get(f"/api/articles/{GRONDWET}/1/cited-by?lid=x!").status_code == 422
    assert (
        client.get(f"/api/articles/{GRONDWET}/1/cited-by?tier=zzz").status_code == 422
    )
    assert client.get(f"/api/articles/{GRONDWET}/1/cited-by?limit=0").status_code == 422
