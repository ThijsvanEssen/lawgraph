"""Parts and references of a BWB article, from the XML through normalize and semantic to the API.

The real ``normalize bwb``, ``normalize bwb-history`` and ``semantic bwb`` run on a small
toestand as a process of their own, on the test server; the answers are the API's.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    SOURCE_BWB,
)
from lawgraph.core.qualifiers import parse_qualifier
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

BWB = "BWBR9100001"
OTHER = "BWBR9100002"

TOESTAND = f"""<?xml version='1.0' encoding='utf-8'?>
<toestand bwb-id="{BWB}" inwerkingtreding="2020-01-01">
  <wetgeving soort="wet" inwerkingtredingsdatum="2020-01-01">
    <intitule>Wet parts</intitule>
    <citeertitel status="officieel">Wet parts</citeertitel>
    <wet-besluit><wettekst>
      <artikel bwb-ng-variabel-deel="/Artikel1" stam-id="9001" versie-id="1" inwerking="2020-01-01"
          label="Artikel 1" effect="nieuw">
        <kop><label>Artikel</label><nr>1</nr></kop>
        <lid><lidnr>1</lidnr><al>In deze wet wordt verstaan onder:</al>
          <lijst>
            <li><li.nr>a.</li.nr><al>wet: zie
                <extref doc="jci1.3:c:{OTHER}&amp;hoofdstuk=1&amp;artikel=5"
                    bwb-id="{OTHER}">artikel 5, tweede lid, onder b,
                    van de Andere wet</extref>;</al></li>
            <li><li.nr>b.</li.nr><al>bijlage:</al>
              <lijst><li><li.nr>1°.</li.nr><al>een;</al></li><li><li.nr>2°.</li.nr><al>twee.</al></li></lijst>
            </li>
          </lijst></lid>
        <lid><lidnr>2</lidnr><al>Zie
            <intref doc="jci1.3:c:{BWB}&amp;artikel=2" bwb-id="{BWB}">artikel 2,
            eerste en tweede lid, aanhef</intref>, en
            <intref doc="jci1.3:c:{BWB}&amp;artikel=2" bwb-id="{BWB}">artikel 2, derde lid</intref>.
        </al></lid>
      </artikel>
      <artikel bwb-ng-variabel-deel="/Artikel2" stam-id="9002" versie-id="1" inwerking="2020-01-01"
          label="Artikel 2" effect="nieuw">
        <kop><label>Artikel</label><nr>2</nr></kop>
        <lid><lidnr>1</lidnr><al>Een.</al></lid><lid><lidnr>2</lidnr><al>Twee.</al></lid>
        <lid><lidnr>3</lidnr><al>Drie.</al></lid>
      </artikel>
    </wettekst></wet-besluit>
  </wetgeving>
</toestand>"""


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for kind, external_id in (
            (RAW_KIND_BWB_TOESTAND, BWB),
            (RAW_KIND_BWB_TOESTAND_ALL, f"{BWB}@2020-01-01"),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=TOESTAND,
                    meta={
                        "bwb_id": BWB,
                        "state_url": f"https://repo/{BWB}/x.xml",
                        "start_date": "2020-01-01",
                    },
                )
            )
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("semantic", "bwb")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_parts_and_references_come_out_of_the_api_as_the_xml_had_them(
    client: TestClient,
) -> None:
    body = client.get(f"/api/articles/{BWB}/1").json()

    article = body["article"]
    parts = {p["id"]: p for p in article["parts"]}
    assert list(parts) == [
        "lid-1",
        "lid-1-aanhef",
        "lid-1-onder-a",
        "lid-1-onder-b",
        "lid-1-onder-b-onder-1",
        "lid-1-onder-b-onder-2",
        "lid-2",
    ]
    text = article["text"]
    for part in parts.values():
        assert text[part["start"] : part["end"]] == part["text"]
    assert parts["lid-1-aanhef"]["text"] == "In deze wet wordt verstaan onder:"
    assert parts["lid-1-onder-b-onder-2"]["number"] == "2°"
    assert parts["lid-1-onder-b-onder-2"]["text"] == "twee."

    # Every reference, in text order, with the lid it names; offsets valid in `text`.
    refs = body["references"]
    assert [(r["kind"], r["bwb_id"], r["article"]) for r in refs] == [
        ("extref", OTHER, "5"),
        ("intref", BWB, "2"),
        ("intref", BWB, "2"),
    ]
    assert [(r["leden"], r["onderdelen"], r["aanhef"]) for r in refs] == [
        (["2"], ["b"], False),
        (["1", "2"], [], True),
        (["3"], [], False),
    ]
    for ref in refs:
        assert text[ref["start"] : ref["end"]] == ref["text"]


def test_the_edge_and_the_citation_carry_the_qualifier_of_the_reference(
    client: TestClient,
) -> None:
    body = client.get(f"/api/articles/{BWB}/1").json()

    # One edge per target article (its key is from, relation, to): the reference to article
    # 2 is one citation, the target of the other reference is not in the graph.
    (citation,) = body["citations"]
    assert citation["target"]["article_number"] == "2"
    assert citation["reference_kind"] == "intref"
    # Either span of the two may be the one the edge keeps; it carries its own qualifier.
    named = parse_qualifier(citation["text"])
    assert citation["leden"] == list(named.leden) != []
    assert citation["aanhef"] is named.aanhef

    (downstream,) = client.get(f"/api/articles/{BWB}/2/relationships").json()[
        "downstream_implications"
    ]
    assert downstream["reference_kind"] == "intref"
    assert downstream["text"] == citation["text"]
    assert (downstream["start"], downstream["end"]) == (
        citation["start"],
        citation["end"],
    )
    assert downstream["leden"] == citation["leden"]


def test_a_version_of_the_article_has_the_same_parts(client: TestClient) -> None:
    article = client.get(f"/api/articles/{BWB}/1").json()["article"]

    (version,) = client.get(f"/api/articles/{BWB}/1/history").json()["versions"]

    assert version["text"] == article["text"]
    assert version["parts"] == article["parts"]
