"""How a judgment ended and what a conclusion proposes: the real ``normalize rechtspraak`` and
``semantic rechtspraak``, and the API on their answer (the detail, the passages that cite an
article, the judgments that cite a law, the canvas); and what the ECHR found per article,
as ``normalize echr`` writes it, on the same lists."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.core.echr_findings import echr_outcome_props
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, make_edge_doc
from tests.integration.seed import seed, write_judgments

GRONDWET = "BWBR0001840"
LAW = "artikel 1 van de Grondwet"
RULING = "ECLI:NL:HR:2020:1"
CONCLUSION = "ECLI:NL:PHR:2020:2"
ECHR = "ECLI:CE:ECHR:2026:0908JUD000748123"
NO_VIOLATION = (
    "No violation of Article 8 - Right to respect for private and family life (Article "
    "8-1 - Respect for family life)"
)


def _xml(ecli: str, court: str, document: str, body: str) -> str:
    return (
        '<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dcterms="http://purl.org/dc/terms/"><rdf:RDF><rdf:Description>'
        f"<dcterms:identifier>{ecli}</dcterms:identifier>"
        f"<dcterms:creator>{court}</dcterms:creator><dcterms:date>2020-03-01"
        f"</dcterms:date><dcterms:type>{document}</dcterms:type>"
        "</rdf:Description></rdf:RDF>"
        f"{body}</open>"
    )


JUDGMENTS = {
    RULING: _xml(
        RULING,
        "Hoge Raad",
        "Uitspraak",
        "<uitspraak><section><title><nr>1</nr>Beoordeling van het middel</title>"
        f"<paragroup><nr>1.1</nr><para>Volgens {LAW} faalt het middel.</para></paragroup>"
        "</section><section><title><nr>2</nr>Beslissing</title>"
        "<para>De Hoge Raad:</para><para>- verwerpt het beroep;</para>"
        "<para>Dit arrest is gewezen door de vicepresident.</para></section></uitspraak>",
    ),
    CONCLUSION: _xml(
        CONCLUSION,
        "Parket bij de Hoge Raad",
        "Conclusie",
        "<conclusie><section><title><nr>1</nr>Beoordeling</title>"
        f"<paragroup><nr>1.1</nr><para>Het {LAW} is van belang.</para></paragroup>"
        "</section><section><title><nr>2</nr>Conclusie</title>"
        "<para>De conclusie strekt tot verwerping van het beroep.</para></section>"
        "</conclusie>",
    ),
}


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = GraphStore()
    seed(store, documents=0, judgments=0, regulations=1)
    write_judgments(store, JUDGMENTS)
    cli("normalize", "bwb")
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")
    # an ECHR judgment as ``normalize echr`` writes it, citing the same article
    key = make_node_key(ECHR)
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            {
                "key": key,
                "type": "judgment",
                "labels": ["ECHR"],
                "props": {
                    "source": "echr",
                    "ecli": ECHR,
                    "date": "2026-09-08",
                    "court_code": "ECHR",
                    "conclusion": NO_VIOLATION,
                    **echr_outcome_props(NO_VIOLATION),
                },
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"judgments/{key}",
                f"articles/{make_node_key(GRONDWET, '1')}",
                "REFERS_TO",
                source="echr-citation-linker",
                confidence=0.95,
            )
        ]
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_detail_says_how_the_judgment_ended(client: TestClient) -> None:
    ruling = client.get(f"/api/judgments/{RULING}").json()["judgment"]
    assert (ruling["outcome"], ruling["outcome_text"]) == (
        "verworpen",
        "verwerpt het beroep",
    )
    paragraphs = {p["paragraph_id"]: p["text"] for p in ruling["paragraphs"]}
    assert "verwerpt het beroep" in paragraphs[ruling["outcome_paragraph_id"]]
    conclusion = client.get(f"/api/judgments/{CONCLUSION}").json()["judgment"]
    assert conclusion["outcome"] is None
    assert conclusion["conclusion_outcome"] == "verwerping"
    assert conclusion["conclusion_outcome_text"] == (
        "De conclusie strekt tot verwerping van het beroep."
    )
    echr = client.get(f"/api/judgments/{ECHR}").json()["judgment"]
    assert echr["outcome"] == "geen schending"
    assert [(f["article"], f["finding"]) for f in echr["echr_findings"]] == [
        ("8", "geen schending")
    ]


def _outcomes(rows: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    return {
        row["ecli"]: (row["outcome"], row["conclusion_outcome"],
                      [f["finding"] for f in row["echr_findings"]])
        for row in rows
    }  # fmt: skip


EXPECTED = {
    RULING: ("verworpen", None, []),
    CONCLUSION: (None, "verwerping", []),
}


def test_the_lists_of_citing_judgments_say_it_light(client: TestClient) -> None:
    passages = client.get(f"/api/articles/{GRONDWET}/1/cited-by").json()["items"]
    assert _outcomes([p["judgment"] for p in passages]) == EXPECTED
    judgments = client.get(f"/api/instruments/{GRONDWET}/judgments").json()["items"]
    assert _outcomes(judgments) == {**EXPECTED, ECHR: ("geen schending", None, [
        "geen schending"])}  # fmt: skip


def test_the_canvas_carries_the_outcome_alone(client: TestClient) -> None:
    answer = client.get(
        f"/api/nodes/articles/{make_node_key(GRONDWET, '1')}",
        params={"props": "canvas", "limit": 50},
    ).json()
    props = {
        item["props"].get("ecli"): item["props"]
        for bucket in answer["neighbors"]["buckets"]
        for item in bucket["items"]
        if item["collection"] == "judgments"
    }
    assert props[RULING]["outcome"] == "verworpen"
    assert props[ECHR]["outcome"] == "geen schending"
    assert "outcome_text" not in props[RULING]
