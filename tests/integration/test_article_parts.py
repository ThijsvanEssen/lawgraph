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
)
from lawgraph.core.qualifiers import parse_qualifier
from lawgraph.db import GraphStore
from tests.integration.seed import write_toestanden

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
      <artikel bwb-ng-variabel-deel="/Artikel3" stam-id="9003" versie-id="1" inwerking="2020-01-01"
          label="Artikel 3" effect="nieuw">
        <kop><label>Artikel</label><nr>3</nr></kop>
        <al>In deze wet wordt verstaan onder:</al>
        <al><nadruk>adviseren:</nadruk></al>
        <lijst><li><li.nr>a.</li.nr><al>raden;</al></li><li><li.nr>b.</li.nr><al>wijzen;</al></li></lijst>
        <al><nadruk>systemen:</nadruk></al>
        <lijst type="ongemarkeerd">
          <li><li.nr>–</li.nr><al><nadruk>netwerk:</nadruk></al>
            <lijst><li><li.nr>a.</li.nr><al>een kabel; of</al></li></lijst></li>
          <li><li.nr>–</li.nr><al><nadruk>richtlijn:</nadruk> een richtlijn;</al></li>
        </lijst>
      </artikel>
      <artikel bwb-ng-variabel-deel="/Artikel4" stam-id="9004" versie-id="1" inwerking="2020-01-01"
          label="Artikel 4" effect="nieuw">
        <kop><label>Artikel</label><nr>4</nr></kop>
        <lid><lidnr>1</lidnr><al>Het forfait bedraagt bij een waarde van:</al>
          <table><tgroup cols="2">
            <colspec colname="col1" colnum="1"/><colspec colname="col2" colnum="2"/>
            <thead><row><entry><al>meer dan</al></entry>
              <entry><al>op jaarbasis</al></entry></row></thead>
            <tbody><row><entry><al>€ 12.500</al></entry><entry><al>nihil</al></entry></row>
              <row><entry namest="col1" nameend="col2">
                <al>in alle andere gevallen 0,35%</al></entry></row>
            </tbody></tgroup></table></lid>
        <lid><lidnr>2</lidnr><al>Twee.</al></lid>
      </artikel>
      <artikel bwb-ng-variabel-deel="/Artikel5" stam-id="9005" versie-id="1" inwerking="2020-01-01"
          label="Artikel 5" effect="nieuw">
        <kop><label>Artikel</label><nr>5</nr></kop>
        <al>Ter uitvoering van <extref doc="32016R0679" label="verordening"
            reeks="Celex">verordening (EU) 2016/679</extref>, zie <intref doc=""
            bwb-id="{BWB}" bwb-ng-variabel-deel="/Bijlage">de bijlage</intref>,
            <extref doc="jci1.3:c:{BWB}&amp;hoofdstuk=1" bwb-id="{BWB}">hoofdstuk 1</extref>
            en <extref doc="jci1.3:c:{OTHER}&amp;artikel=7" bwb-id="{OTHER}">artikel 7 van
            de Andere wet</extref>.</al>
      </artikel>
    </wettekst>
    <bijlage bwb-ng-variabel-deel="/Bijlage" label="Bijlage">
      <kop><label>Bijlage</label><titel>Lijst</titel></kop><al>Een lijst.</al>
    </bijlage></wet-besluit>
  </wetgeving>
</toestand>"""


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = GraphStore()
    write_toestanden(
        store,
        [
            (
                kind,
                external_id,
                TOESTAND,
                {
                    "bwb_id": BWB,
                    "state_url": f"https://repo/{BWB}/x.xml",
                    "start_date": "2020-01-01",
                },
            )
            for kind, external_id in (
                (RAW_KIND_BWB_TOESTAND, BWB),
                (RAW_KIND_BWB_TOESTAND_ALL, f"{BWB}@2020-01-01"),
            )
        ],
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

    (downstream,) = client.get(f"/api/articles/{BWB}/2").json()[
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

    (listed,) = client.get(f"/api/articles/{BWB}/1/history").json()["versions"]
    version = client.get(f"/api/articles/{BWB}/1/history/{listed['key']}").json()

    assert version["text"] == article["text"]
    assert version["parts"] == article["parts"]


def test_the_law_of_a_day_carries_the_parts_with_the_text(client: TestClient) -> None:
    """The whole-law reader nests the text by these, as the article reader does."""
    article = client.get(f"/api/articles/{BWB}/1").json()["article"]

    items = client.get(
        f"/api/instruments/{BWB}/articles/at/2020-06-01",
        params={"text_preview_chars": 0, "include_text": "true"},
    ).json()["items"]
    first = next(item for item in items if item["article_number"] == "1")

    assert first["text"] == article["text"]
    assert first["parts"] == [
        {k: v for k, v in part.items() if k != "text"} for part in article["parts"]
    ]


def test_definitions_hold_their_own_lists_and_are_named_by_their_term(
    client: TestClient,
) -> None:
    """A definition paragraph with its own list (Wft 1:1) and an unmarked definition with
    its own a, b (art. 1 Cbw): the list stays under its term, which the part names."""
    article = client.get(f"/api/articles/{BWB}/3").json()["article"]

    assert [(p["id"], p["number"], p["term"]) for p in article["parts"]] == [
        ("aanhef", None, None),
        ("tekst-1", None, "adviseren"),
        ("tekst-1-onder-a", "a", None),
        ("tekst-1-onder-b", "b", None),
        ("tekst-2", None, "systemen"),
        ("tekst-2-onder-_1", "–", "netwerk"),
        ("tekst-2-onder-_1-onder-a", "a", None),
        ("tekst-2-onder-_2", "–", "richtlijn"),
    ]
    assert article["parts"][0]["text"] == "In deze wet wordt verstaan onder:"

    items = client.get(
        f"/api/instruments/{BWB}/articles/at/2020-06-01",
        params={"text_preview_chars": 0, "include_text": "true"},
    ).json()["items"]
    third = next(item for item in items if item["article_number"] == "3")
    assert [p["term"] for p in third["parts"]] == [p["term"] for p in article["parts"]]


def test_a_table_comes_out_of_the_api_with_its_rows_and_cells(
    client: TestClient,
) -> None:
    article = client.get(f"/api/articles/{BWB}/4").json()["article"]
    (table,) = article["tables"]
    text = article["text"]
    assert text[table["start"] : table["end"]].split("\n") == [
        "meer dan\top jaarbasis",
        "€ 12.500\tnihil",
        "in alle andere gevallen 0,35%",
    ]
    assert (table["head_rows"], table["columns"]) == (1, 2)
    assert table["spans"] == [{"row": 2, "cell": 0, "cols": 2, "rows": 1}]
    lid = next(part for part in article["parts"] if part["id"] == "lid-1")
    assert lid["end"] == table["end"]

    (listed,) = client.get(f"/api/articles/{BWB}/4/history").json()["versions"]
    version = client.get(f"/api/articles/{BWB}/4/history/{listed['key']}").json()
    assert version["tables"] == article["tables"]
    items = client.get(
        f"/api/instruments/{BWB}/articles/at/2020-06-01",
        params={"text_preview_chars": 0, "include_text": "true"},
    ).json()["items"]
    fourth = next(item for item in items if item["article_number"] == "4")
    assert fourth["tables"] == article["tables"]


def test_a_reference_names_its_target_an_eu_act_and_an_annex_among_them(
    client: TestClient,
) -> None:
    """The EU act of a CELEX link (not loaded here), the annex of a link to one, the
    regulation of a link to a chapter, the article of a link to one (of a law not loaded):
    each with whether the data holds it."""
    refs = client.get(f"/api/articles/{BWB}/5").json()["references"]

    assert [
        (r["kind"], r["celex"], r["target"]["id"], r["target"]["exists"]) for r in refs
    ] == [
        ("extref", "32016R0679", "instruments/32016r0679", False),
        ("intref", None, f"annexes/{BWB.lower()}_annex", True),
        ("extref", None, f"instruments/{BWB.lower()}", True),
        ("extref", None, f"articles/{OTHER.lower()}_7", False),
    ]


def test_the_law_of_a_day_carries_the_references_and_citations_when_asked(
    client: TestClient,
) -> None:
    """``include=references``: each article whose version of the day is its current one
    has the references and the citations of the article reader, so the whole-law reader
    asks no article apart; without it, neither."""
    url = f"/api/instruments/{BWB}/articles/at/2020-06-01"
    asked = {"text_preview_chars": 0, "include_text": "true"}
    items = client.get(url, params={**asked, "include": "references"}).json()["items"]
    by_number = {item["article_number"]: item for item in items}

    for number in ("1", "5"):
        reader = client.get(f"/api/articles/{BWB}/{number}").json()
        assert by_number[number]["references"] == reader["references"], number
        assert by_number[number]["citations"] == [
            {**c, "definition_ref": None} for c in reader["citations"]
        ], number
    assert by_number["1"]["citations"] != []
    assert by_number["2"]["references"] == [] and by_number["2"]["citations"] == []

    plain = client.get(url, params=asked).json()["items"]
    assert all(i["references"] is None and i["citations"] is None for i in plain)
