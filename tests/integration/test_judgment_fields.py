"""The text of a conclusion, the judgments a judgment cites and the publications of one
decision: the real ``normalize rechtspraak``, the semantic steps and the API on their answer.

The headers follow the open data of the Rechtspraak: ECLI:NL:PHR:2025:311 (a conclusion,
its text in ``<conclusie>``), and ECLI:NL:HR:1985:AW8335 with BH3435 and BV4163 (one arrest
published three times; the two old publications carry no text and name the one that
replaces them in ``dcterms:isReplacedBy``).
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
from tests.integration.test_judgment_relations import NS

CONCLUSION = "ECLI:NL:PHR:2025:311"
RULING = "ECLI:NL:HR:2021:10"
CITED = "ECLI:NL:HR:2015:1"
KEPT = "ECLI:NL:HR:1985:AW8335"
REPLACED = ("ECLI:NL:HR:1985:BH3435", "ECLI:NL:HR:1985:BV4163")
# replaced by a publication that is not loaded: nothing to count it with
ORPHAN = "ECLI:NL:HR:2003:BV5502"


def _header(ecli: str, court: str, date: str, case_number: str, extra: str = "") -> str:
    return (
        f"<open-rechtspraak {NS}><rdf:RDF><rdf:Description>"
        f"<dcterms:identifier>{ecli}</dcterms:identifier>{extra}"
        f"<dcterms:creator>{court}</dcterms:creator><dcterms:date>{date}</dcterms:date>"
        f"<psi:zaaknummer>{case_number}</psi:zaaknummer>"
    )


def _conclusion() -> str:
    return (
        _header(CONCLUSION, "Parket bij de Hoge Raad", "2025-03-28", "24/01234")
        + "<dcterms:type>Conclusie</dcterms:type></rdf:Description></rdf:RDF>"
        "<inhoudsindicatie><para>Cassatie; bestuursrecht.</para></inhoudsindicatie>"
        "<conclusie><para>PROCUREUR-GENERAAL BIJ DE HOGE RAAD DER NEDERLANDEN</para>"
        "<section><title><nr>1</nr>Inleiding</title><paragroup><nr>1.1</nr>"
        "<para>De advocaat-generaal concludeert tot verwerping van het beroep.</para>"
        "</paragroup></section></conclusie></open-rechtspraak>"
    )


def _judgment(
    ecli: str, date: str, case_number: str, *, text: str | None, extra: str = ""
) -> str:
    body = (
        "<uitspraak><section><title><nr>1</nr>Beoordeling</title><paragroup>"
        f"<nr>1.1</nr><para>{text}</para></paragroup></section></uitspraak>"
        if text
        else ""
    )
    return (
        _header(ecli, "Hoge Raad", date, case_number, extra)
        + "<dcterms:type>Uitspraak</dcterms:type></rdf:Description></rdf:RDF>"
        f"{body}</open-rechtspraak>"
    )


def _replaced_by(ecli: str) -> str:
    return f"<dcterms:isReplacedBy>{ecli}</dcterms:isReplacedBy>"


JUDGMENTS = {
    CONCLUSION: _conclusion(),
    RULING: _judgment(
        RULING,
        "2021-03-05",
        "20/00001",
        text=f"Zoals eerder geoordeeld (HR 1 mei 2015, {CITED}; HR 6 maart 1985, "
        f"{REPLACED[0]}), faalt het middel.",
    ),
    CITED: _judgment(CITED, "2015-05-01", "14/00001", text="Het middel slaagt."),
    KEPT: _judgment(
        KEPT,
        "1985-03-06",
        "22 825",
        text="De Hoge Raad verwerpt het beroep.",
        extra="".join(f"<dcterms:replaces>{e}</dcterms:replaces>" for e in REPLACED),
    ),
    **{
        ecli: _judgment(
            ecli, "1985-03-06", "22 825", text=None, extra=_replaced_by(KEPT)
        )
        for ecli in REPLACED
    },
    ORPHAN: _judgment(
        ORPHAN,
        "2003-02-11",
        "00709/02",
        text=None,
        extra=_replaced_by("ECLI:NL:HR:2003:AF2343"),
    ),
}


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
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
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-duplicates")
    cli("semantic", "rechtspraak-citations")
    cli("semantic", "graph-list-stats")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_a_conclusion_has_its_text_and_paragraphs(client: TestClient) -> None:
    judgment = client.get(f"/api/judgments/{CONCLUSION}").json()["judgment"]

    assert judgment["decision_kind"] == "conclusie"
    assert [(p["number"], p["text"]) for p in judgment["paragraphs"][-2:]] == [
        ("1", "Inleiding"),
        ("1.1", "De advocaat-generaal concludeert tot verwerping van het beroep."),
    ]
    assert "concludeert tot verwerping" in judgment["props"]["text"]


def test_a_judgment_lists_the_judgments_it_cites_and_counts_them(
    client: TestClient,
) -> None:
    detail = client.get(f"/api/judgments/{RULING}").json()
    listed = client.get("/api/judgments", params={"q": RULING}).json()["items"]

    assert sorted(j["ecli"] for j in detail["cited_judgments"]) == [
        "ECLI:NL:HR:1985:BH3435",
        CITED,
    ]
    assert [(j["ecli"], j["outbound_citation_count"]) for j in listed] == [(RULING, 2)]


def test_the_publications_of_one_decision_are_linked_and_counted_once(
    client: TestClient,
) -> None:
    store = ArangoStore()
    same_as = {
        tuple(row)
        for row in store.query(
            "FOR e IN edges FILTER e.relation == 'SAME_AS' "
            "RETURN [DOCUMENT(e._from).props.ecli, DOCUMENT(e._to).props.ecli]"
        )
    }
    assert same_as == {(ecli, KEPT) for ecli in REPLACED}

    kept = client.get(f"/api/judgments/{KEPT}").json()
    replaced = client.get(f"/api/judgments/{REPLACED[0]}").json()
    assert sorted(j["ecli"] for j in kept["same_as"]) == sorted(REPLACED)
    assert replaced["judgment"]["same_as"] == KEPT
    assert [j["ecli"] for j in replaced["same_as"]] == [KEPT]

    # the list shows the decision once, counted with the citations of its other publications
    hr_1985 = client.get(
        "/api/judgments", params={"from": "1985-01-01", "to": "1985-12-31"}
    ).json()
    assert [(j["ecli"], j["inbound_citation_count"]) for j in hr_1985["items"]] == [
        (KEPT, 1)
    ]
    assert hr_1985["total"] == 1
    assert {"value": "1985", "count": 1} in hr_1985["facets"]["year"]
    everything = client.get("/api/judgments").json()
    assert everything["total"] == len(JUDGMENTS) - len(REPLACED)
    # asked for by its ECLI, a replaced publication is found
    asked = client.get("/api/judgments", params={"q": REPLACED[1]}).json()
    assert [j["ecli"] for j in asked["items"]] == [REPLACED[1]]
    # one whose replacing publication is not loaded stands alone
    orphan = client.get(f"/api/judgments/{ORPHAN}").json()
    assert (orphan["judgment"]["same_as"], orphan["same_as"]) == (None, [])
