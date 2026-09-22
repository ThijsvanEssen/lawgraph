"""The front-end gap series through the real chain, from raw records to the API.

One small world, run as ``normalize all`` and ``semantic all`` (processes of their own, on the
test server): the Tijdelijke wet Klimaatfonds, of which the Stb. 2025, 100 changed article 2 in
dossier 36750; the memorandum of that dossier (the recorded Kamerstuk XML, which names article 2
of the law); and two judgments that cite article 2 in numbered paragraphs, one of them its third
lid. Every pipeline of the series meets the others on it: the sections of the memorandum, the
edge they upgrade, the mentions of the judgments, the parts of the article, and the answers the
API builds from all of them.
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
    RAW_KIND_RS_CONTENT,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_KAMERSTUK_XML,
    RAW_KIND_TK_ZAAK,
    SOURCE_BWB,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.semantic.tk_mvt import SEMANTIC_SOURCE_SECTIONS
from tests.integration.seed import FIXTURES, uid

LAW = "BWBR0044234"
LAW_TITLE = "Tijdelijke wet Klimaatfonds"
DOSSIER = "36750"
MVT_ID = uid(1, 1)  # the Id of the memorandum as the Tweede Kamer sends it
MVT_KEY = make_node_key(MVT_ID)
WET_KEY = make_node_key(uid(2, 1))
COMMITTEE = uid(1, 10)

CITES_LID_3 = f"artikel 2, derde lid, van de {LAW_TITLE}"
CITES_LID_4 = f"artikel 2, vierde lid, van de {LAW_TITLE}"

TOESTAND = f"""<?xml version='1.0' encoding='utf-8'?>
<toestand bwb-id="{LAW}" inwerkingtreding="2025-07-01">
  <wetgeving soort="wet" inwerkingtredingsdatum="2025-07-01">
    <intitule>{LAW_TITLE}</intitule>
    <citeertitel status="officieel">{LAW_TITLE}</citeertitel>
    <wet-besluit><wettekst>
      <artikel bwb-ng-variabel-deel="/Artikel1" stam-id="4401" versie-id="1" inwerking="2021-01-01"
          label="Artikel 1" effect="nieuw">
        <kop><label>Artikel</label><nr>1</nr></kop>
        <lid><lidnr>1</lidnr><al>Er is een Klimaatfonds.</al></lid>
      </artikel>
      <artikel bwb-ng-variabel-deel="/Artikel2" stam-id="4402" versie-id="7" inwerking="2025-07-01"
          label="Artikel 2" effect="wijziging" bron="Stb.2025-100">
        <kop><label>Artikel</label><nr>2</nr></kop>
        <meta-data><brondata><oorspronkelijk>
          <publicatie effect="wijziging" soort="Stb" urlidentifier="stb-2025-100">
            <publicatiejaar>2025</publicatiejaar><publicatienr>100</publicatienr>
            <dossierref dossier="{DOSSIER}">{DOSSIER}</dossierref>
          </publicatie>
        </oorspronkelijk></brondata></meta-data>
        <lid><lidnr>1</lidnr><al>De middelen worden besteed aan klimaatmaatregelen.</al></lid>
        <lid><lidnr>2</lidnr><al>Een maatregel is een investering.</al></lid>
        <lid><lidnr>3</lidnr><al>Niet voor de landbouwsector.</al></lid>
        <lid><lidnr>4</lidnr><al>Wel voor de glastuinbouw.</al></lid>
      </artikel>
      <artikel bwb-ng-variabel-deel="/Artikel3" stam-id="4403" versie-id="1" inwerking="2021-01-01"
          label="Artikel 3" effect="nieuw">
        <kop><label>Artikel</label><nr>3</nr></kop>
        <lid><lidnr>1</lidnr><al>Zie
            <intref doc="jci1.3:c:{LAW}&amp;artikel=2" bwb-id="{LAW}">artikel 2, derde lid</intref>.
        </al></lid>
      </artikel>
    </wettekst></wet-besluit>
  </wetgeving>
</toestand>"""


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
    "ECLI:NL:HR:2026:11": _judgment_xml(
        "ECLI:NL:HR:2026:11",
        "2026-02-03",
        [("2.1", f"Volgens {CITES_LID_3} mag het niet."), ("2.2", "Dat is anders.")],
    ),
    "ECLI:NL:RBAMS:2026:12": _judgment_xml(
        "ECLI:NL:RBAMS:2026:12", "2026-03-04", [("5", f"Op grond van {CITES_LID_4}.")]
    ),
}


def _tk_payloads() -> Iterator[tuple[str, str, dict[str, Any]]]:
    dossier = {
        "Id": uid(1, 3),
        "Nummer": DOSSIER,
        "Toevoeging": None,
        "Titel": "Wijziging van de Tijdelijke wet Klimaatfonds",
        "Afgesloten": False,
    }
    yield RAW_KIND_TK_DOSSIER, dossier["Id"], dossier
    zaak = {
        "Id": uid(1, 2),
        "Nummer": "2025Z36750",
        "Soort": "Wetgeving",
        "Titel": dossier["Titel"],
        "Onderwerp": "Landbouw en het Klimaatfonds",
        "Kamerstukdossier": [{"Id": dossier["Id"], "Nummer": DOSSIER}],
    }
    yield RAW_KIND_TK_ZAAK, zaak["Id"], zaak
    for identifier, kind, sequence in (
        (MVT_ID, "Memorie van toelichting", 3),
        (uid(2, 1), "Voorstel van wet", 2),
    ):
        document = {
            "Id": identifier,
            "Soort": kind,
            "DocumentNummer": f"2025D0000{sequence}",
            "Titel": zaak["Titel"],
            "Onderwerp": zaak["Onderwerp"],
            "Datum": "2025-05-21T00:00:00+02:00",
            "Volgnummer": sequence,
            "Zaak": [zaak],
            "DocumentActor": [],
        }
        yield RAW_KIND_TK_DOCUMENT, identifier, document
    commission = {
        "Id": COMMITTEE,
        "NaamNL": "Commissie voor Klimaat",
        "Afkorting": "KGG",
    }
    yield RAW_KIND_TK_COMMISSIE, COMMITTEE, commission
    activity = {
        "Id": uid(1, 11),
        "Nummer": "2025A00001",
        "Soort": "Commissiedebat",
        "Datum": "2025-06-01T00:00:00+02:00",
        "Voortouwcommissie_Id": COMMITTEE,
        "Agendapunt": [{"Zaak": [zaak]}],
    }
    yield RAW_KIND_TK_ACTIVITEIT, activity["Id"], activity


def _seed(store: ArangoStore) -> None:
    with RawSourceWriter(store) as writer:
        for kind, external_id, payload in _tk_payloads():
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=external_id,
                    payload_json=payload,
                )
            )
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_KAMERSTUK_XML,
                external_id=f"kst-{DOSSIER}-3",
                payload_text=(FIXTURES / "kst_36750_3.xml").read_text(encoding="utf-8"),
                meta={"document": MVT_KEY},
            )
        )
        for kind, external_id in (
            (RAW_KIND_BWB_TOESTAND, LAW),
            (RAW_KIND_BWB_TOESTAND_ALL, f"{LAW}@2025-07-01"),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=TOESTAND,
                    meta={
                        "bwb_id": LAW,
                        "state_url": f"https://repo/{LAW}/x.xml",
                        "start_date": "2025-07-01",
                    },
                )
            )
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


def _explains(store: ArangoStore) -> dict[str, Any]:
    aql = """
    FOR e IN edges FILTER e.relation == 'EXPLAINS'
        RETURN {key: e._key, from: e._from, to: e._to, source: e.source,
                confidence: e.confidence, meta: e.meta}
    """
    return {row["key"]: row for row in store.query(aql)}


@pytest.fixture()
def world(database: str, cli: Any) -> Iterator[tuple[TestClient, ArangoStore, Any]]:
    store = ArangoStore()
    _seed(store)
    cli("normalize", "all")
    cli("semantic", "all")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app), store, cli
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def test_the_dossier_and_its_papers_as_the_parliament_side_of_the_api_sees_them(
    world: tuple[TestClient, ArangoStore, Any],
) -> None:
    client, _, _ = world

    hub = _get(client, f"/api/dossiers/{DOSSIER}")
    assert (hub["document_count"], hub["activity_count"]) == (2, 1)
    assert hub["documents_by_kind"] == {
        "Memorie van toelichting": 1,
        "Voorstel van wet": 1,
    }
    # the publication that changed the law (canoniek) and the paper that proposes to (voorgesteld)
    assert {(i["bwb_id"], i["relation"], i["status"]) for i in hub["instruments"]} == {
        (LAW, "amends", "canoniek"),
        (LAW, "amends", "voorgesteld"),
    }
    assert [(c["slug"], c["role"]) for c in hub["committees"]] == [("kgg", "lead")]
    assert hub["senate"] == {"document_count": 0, "first_date": None}

    committee = _get(client, "/api/committees/kgg")
    assert [d["number"] for d in committee["dossiers"]] == [DOSSIER]
    assert (committee["dossier_total"], committee["active_dossier_count"]) == (1, 1)

    # every document carries its chamber, source and whether it explains, wherever it is listed
    listed = {
        "/api/documents": _get(client, "/api/documents", dossier=DOSSIER)["items"],
        f"/api/dossiers/{DOSSIER}/documents": _get(
            client, f"/api/dossiers/{DOSSIER}/documents"
        )["items"],
    }
    for path, items in listed.items():
        by_key = {d["key"]: d for d in items}
        assert set(by_key) == {MVT_KEY, WET_KEY}, path
        assert (by_key[MVT_KEY]["chamber"], by_key[MVT_KEY]["source"]) == ("TK", "tk")
        assert by_key[MVT_KEY]["is_explanatory"] is True, path
        assert by_key[WET_KEY]["is_explanatory"] is False, path

    entries = _get(client, f"/api/dossiers/{DOSSIER}/timeline")["entries"]
    assert sorted(e["node_type"] for e in entries) == [
        "activity",
        "document",
        "document",
    ]
    activity = next(e for e in entries if e["node_type"] == "activity")
    assert activity["committee"]["slug"] == "kgg"
    documents = {
        e["body"]["kind"]: e["body"] for e in entries if e["node_type"] == "document"
    }
    assert documents["Memorie van toelichting"]["is_explanatory"] is True
    assert all(
        "text" not in body for body in documents.values()
    )  # slim: never the text


def test_the_memorandum_explains_the_article_through_the_section_that_names_it(
    world: tuple[TestClient, ArangoStore, Any],
) -> None:
    client, store, cli = world

    # One EXPLAINS edge: the dossier-level edge of `tk-mvt`, upgraded by `tk-mvt-articles`.
    (edge,) = _explains(store).values()
    assert edge["from"] == f"documents/{MVT_KEY}"
    assert edge["to"] == "article_versions/bwbr0044234_av_4402_7"
    assert (edge["source"], edge["confidence"]) == (SEMANTIC_SOURCE_SECTIONS, 0.85)
    anchor = edge["meta"]["section_anchor"]
    assert edge["meta"]["heading"] == "Artikel I"

    explained = _get(client, f"/api/articles/{LAW}/2/explained-by")
    assert explained["total"] == 1
    (item,) = explained["items"]
    assert item["document"]["key"] == MVT_KEY
    assert (item["document"]["chamber"], item["document"]["is_explanatory"]) == (
        "TK",
        True,
    )
    assert item["target"] == "article_version"
    assert item["scope"] == "article" and item["section_anchor"] == anchor
    assert item["confidence"] == 0.85

    # the section the edge names is a section of the document, and its text the passage
    document = _get(client, f"/api/documents/{MVT_KEY}")
    assert document["dossier_numbers"] == [DOSSIER]
    assert [(t["bwb_id"], t["article_number"]) for t in document["explains"]] == [
        (LAW, "2")
    ]
    sections = {s["id"]: s for s in document["sections"]}
    assert sections[anchor]["heading"] == "Artikel I"
    assert document["text"].startswith("MEMORIE VAN TOELICHTING\n")

    passages = _get(
        client, f"/api/documents/{MVT_KEY}/passages", bwb_id=LAW, article="2"
    )
    assert passages["total"] == 1
    (passage,) = passages["items"]
    assert passage["section_id"] == anchor
    section = sections[anchor]
    assert (
        passage["text"] == document["text"][section["char_start"] : section["char_end"]]
    )
    assert passage["text"].startswith("Artikel I\nDit wetsvoorstel beoogt artikel 2")
    assert (passage["match_type"], passage["confidence"]) == ("body_named_law", 0.85)
    for other in ("1", "3"):  # articles the law has and no section names
        assert _get(
            client, f"/api/documents/{MVT_KEY}/passages", bwb_id=LAW, article=other
        ) == {"total": 0, "items": []}

    # the whole semantic phase again writes the same edge, not a second one
    cli("semantic", "all")
    assert _explains(store) == {edge["key"]: edge}


def test_the_law_its_article_and_the_judgments_that_cite_it(
    world: tuple[TestClient, ArangoStore, Any],
) -> None:
    client, _, _ = world

    article = _get(client, f"/api/articles/{LAW}/2")["article"]
    assert [p["id"] for p in article["parts"]] == ["lid-1", "lid-2", "lid-3", "lid-4"]
    third = article["parts"][2]
    assert article["text"][third["start"] : third["end"]] == third["text"]
    assert third["text"] == "Niet voor de landbouwsector."

    # article 3 refers to the third lid of article 2: the reference, and the citation it became
    body = _get(client, f"/api/articles/{LAW}/3")
    (reference,) = body["references"]
    assert (reference["kind"], reference["article"], reference["leden"]) == (
        "intref",
        "2",
        ["3"],
    )
    text = body["article"]["text"]
    assert text[reference["start"] : reference["end"]] == reference["text"]
    (citation,) = body["citations"]
    assert citation["target"]["article_number"] == "2" and citation["leden"] == ["3"]

    # the version that the amendment made has the same parts, and says which dossier changed it
    (version,) = _get(client, f"/api/articles/{LAW}/2/history")["versions"]
    assert version["parts"] == article["parts"]
    assert version["change"] == "amends"
    assert [d["number"] for d in version["amended_by"]["dossiers"]] == [DOSSIER]

    # both judgments cite article 2; the lid filter keeps the one that cites the third
    cited = _get(client, f"/api/articles/{LAW}/2/cited-by")
    assert [(m["judgment"]["ecli"], m["leden"]) for m in cited["items"]] == [
        ("ECLI:NL:RBAMS:2026:12", ["4"]),
        ("ECLI:NL:HR:2026:11", ["3"]),
    ]
    only = _get(client, f"/api/articles/{LAW}/2/cited-by", lid="3")
    assert only["total"] == 1
    (mention,) = only["items"]
    assert mention["judgment"]["ecli"] == "ECLI:NL:HR:2026:11"
    assert (mention["paragraph_id"], mention["paragraph_number"]) == ("rov-2.1", "2.1")
    assert mention["text"] == CITES_LID_3 and mention["qualifier"] == "derde lid"

    judgment = _get(client, "/api/judgments/ECLI:NL:HR:2026:11")
    (cited_article,) = judgment["cited_articles"]
    assert cited_article["article"]["bwb_id"] == LAW
    assert cited_article["article"]["article_number"] == "2"
    assert cited_article["leden"] == ["3"]
    assert (cited_article["paragraph_ids"], cited_article["mention_count"]) == (
        ["rov-2.1"],
        1,
    )
    by_id = {p["paragraph_id"]: p for p in judgment["judgment"]["paragraphs"]}
    (span,) = by_id["rov-2.1"]["citations"]
    assert by_id["rov-2.1"]["text"][span["start"] : span["end"]] == CITES_LID_3
    assert by_id["rov-2.2"]["citations"] == []


def test_what_a_reader_types_resolves_and_every_node_has_its_facets(
    world: tuple[TestClient, ArangoStore, Any],
) -> None:
    client, _, _ = world

    resolved = _get(
        client, "/api/resolve", q="artikel 2 lid 3 Tijdelijke wet Klimaatfonds"
    )
    assert (resolved["kind"], resolved["match"]["key"]) == ("article", "bwbr0044234_2")
    assert resolved["qualifier"] == "lid 3"
    assert (
        _get(client, "/api/resolve", q=DOSSIER)["match"]["id"] == f"dossiers/{DOSSIER}"
    )
    judgment = _get(client, "/api/resolve", q="ECLI:NL:HR:2026:11")
    assert judgment["match"]["id"] == "judgments/ecli_nl_hr_2026_11"

    # the search ranks the article that was asked for first
    found = _get(client, "/api/search", q="art 2 klimaatfonds", types="articles")
    assert found["results"]["articles"][0]["key"] == "bwbr0044234_2"

    # the facets of the memorandum count what the series wrote around it
    facets = _get(client, f"/api/nodes/documents/{MVT_KEY}/facets")["items"]
    counted = {
        (f["relation"], f["direction"], f["collection"]): f["count"] for f in facets
    }
    assert counted[("EXPLAINS", "outbound", "article_versions")] == 1
    assert counted[("PART_OF", "outbound", "dossiers")] == 1
    assert counted[("REFERS_TO", "outbound", "articles")] == 1
