"""Conclusions and preliminary rulings: the real ``normalize rechtspraak`` and the two semantic
steps that tie judgments of one case, and the node responses on their edges.

The headers are those of ECLI:NL:HR:2019:1278 (a preliminary ruling that names its conclusion
and, in its text, the case number of the referring decision) and ECLI:NL:PHR:2019:496 (its
conclusion); the rest is made up around them.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.core.judgments import Referral
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve import _gaps

NS = (
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:psi="http://psi.rechtspraak.nl/" '
    'xmlns:ecli="https://e-justice.europa.eu/ecli"'
)


def _relation(ecli: str, kind: str, instance: str) -> str:
    return (
        f'<dcterms:relation ecli:resourceIdentifier="{ecli}" '
        f'psi:type="http://psi.rechtspraak.nl/{kind}" '
        f'psi:aanleg="http://psi.rechtspraak.nl/{instance}">{ecli}</dcterms:relation>'
    )


def _xml(
    ecli: str,
    court: str,
    date: str,
    case_number: str,
    *,
    document_type: str = "Uitspraak",
    procedure: str | None = None,
    relations: str = "",
    text: str = "De rechter beslist.",
) -> str:
    procedure_xml = f"<psi:procedure>{procedure}</psi:procedure>" if procedure else ""
    return (
        f"<open-rechtspraak {NS}><rdf:RDF><rdf:Description>"
        f"<dcterms:identifier>{ecli}</dcterms:identifier>"
        f"<dcterms:creator>{court}</dcterms:creator><dcterms:date>{date}</dcterms:date>"
        f"<psi:zaaknummer>{case_number}</psi:zaaknummer>"
        f"<dcterms:type>{document_type}</dcterms:type>{procedure_xml}{relations}"
        "</rdf:Description></rdf:RDF><uitspraak><section>"
        f"<title><nr>1</nr>De procedure</title><paragroup><nr>1.1</nr><para>{text}</para>"
        "</paragroup></section></uitspraak></open-rechtspraak>"
    )


REFERRAL = (
    "Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober 2018 heeft de "
    "rechtbank Assen op de voet van art. 392 Rv prejudiciële vragen aan de Hoge Raad gesteld."
)
JUDGMENTS = {
    "ECLI:NL:HR:2019:1278": _xml(
        "ECLI:NL:HR:2019:1278",
        "Hoge Raad",
        "2019-07-19",
        "18/04298",
        procedure="Prejudiciële beslissing",
        relations=_relation("ECLI:NL:PHR:2019:496", "conclusie", "eerdereAanleg"),
        text=REFERRAL,
    ),
    "ECLI:NL:PHR:2019:496": _xml(
        "ECLI:NL:PHR:2019:496",
        "Parket bij de Hoge Raad",
        "2019-05-10",
        "18/04298",
        document_type="Conclusie",
        relations=_relation("ECLI:NL:HR:2019:1278", "conclusie", "latereAanleg"),
    ),
    # the referring decision, its case number spaced as the metadata spaces it
    "ECLI:NL:RBNNE:2018:4308": _xml(
        "ECLI:NL:RBNNE:2018:4308",
        "Rechtbank Noord-Nederland",
        "2018-10-10",
        "C/19/117301 / HA ZA 16-256",
    ),
    # a conclusion that no relation ties, and the judgment of its case
    "ECLI:NL:PHR:2020:1": _xml(
        "ECLI:NL:PHR:2020:1",
        "Parket bij de Hoge Raad",
        "2020-01-10",
        "19/00001",
        document_type="Conclusie",
    ),
    "ECLI:NL:HR:2020:2": _xml(
        "ECLI:NL:HR:2020:2", "Hoge Raad", "2020-03-06", "19/00001", procedure="Cassatie"
    ),
    # a preliminary ruling (ECLI:NL:HR:2022:824) whose text writes the case number of the
    # referring decision otherwise than its metadata
    "ECLI:NL:HR:2022:824": _xml(
        "ECLI:NL:HR:2022:824",
        "Hoge Raad",
        "2022-06-03",
        "21/02242",
        procedure="Prejudiciële beslissing",
        text="Bij tussenvonnis in de zaak C/09/610280/ KG ZA 21/346 van 11 juni 2021 heeft "
        "voorzieningenrechter in de rechtbank te Den Haag op de voet van art. 392 Rv "
        "prejudiciële vragen aan de Hoge Raad gesteld.",
    ),
    "ECLI:NL:RBDHA:2021:5927": _xml(
        "ECLI:NL:RBDHA:2021:5927",
        "Rechtbank Den Haag",
        "2021-06-11",
        "C-09-610280-KG ZA 21-346",
    ),
    # a preliminary ruling (ECLI:NL:HR:2024:1366) whose referring decision is not loaded
    "ECLI:NL:HR:2024:1366": _xml(
        "ECLI:NL:HR:2024:1366",
        "Hoge Raad",
        "2024-10-04",
        "23/01968",
        procedure="Prejudiciële beslissing",
        text="Bij tussenvonnis in de zaak 8963920 CV EXPL 21-1168 van 12 mei 2023 heeft de "
        "rechtbank Rotterdam op de voet van art. 392 Rv een prejudiciële vraag aan de Hoge "
        "Raad gesteld.",
    ),
    # a preliminary ruling whose metadata names the referring decision
    "ECLI:NL:HR:2026:1265": _xml(
        "ECLI:NL:HR:2026:1265",
        "Hoge Raad",
        "2026-06-01",
        "S 26/01234",
        procedure="Prejudiciële beslissing",
        relations=_relation("ECLI:NL:GHSHE:2026:724", "uitspraak", "eerdereAanleg"),
    ),
}


def _edges(store: ArangoStore, relation: str) -> set[tuple[str, str, str]]:
    aql = """
    FOR e IN edges FILTER e.relation == @relation
        RETURN [DOCUMENT(e._from).props.ecli, DOCUMENT(e._to).props.ecli, e.meta.basis]
    """
    return {tuple(row) for row in store.query(aql, {"relation": relation})}


def test_conclusions_and_referrals_tie_the_judgments_of_a_case(
    database: str, cli: Any
) -> None:
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
    cli("semantic", "rechtspraak-appeal")
    cli("semantic", "rechtspraak-conclusions")
    cli("semantic", "rechtspraak-referrals")

    assert _edges(store, "ADVISES_ON") == {
        ("ECLI:NL:PHR:2019:496", "ECLI:NL:HR:2019:1278", "formal_relation"),
        ("ECLI:NL:PHR:2020:1", "ECLI:NL:HR:2020:2", "case_number"),
    }
    assert _edges(store, "ANSWERS") == {
        ("ECLI:NL:HR:2019:1278", "ECLI:NL:RBNNE:2018:4308", "referral_text"),
        ("ECLI:NL:HR:2022:824", "ECLI:NL:RBDHA:2021:5927", "referral_text"),
        # not loaded: a stub, which `retrieve rechtspraak --mode gaps` fetches
        ("ECLI:NL:HR:2026:1265", "ECLI:NL:GHSHE:2026:724", "formal_relation"),
    }
    # a preliminary ruling appeals nothing
    assert _edges(store, "APPEAL_OF") == set()
    # what `retrieve rechtspraak --mode gaps` looks up in the index of the referral date
    assert _gaps.unanswered_referrals(store) == [
        Referral(case_numbers=("8963920 CV EXPL 21-1168",), date="2023-05-12")
    ]

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        ruling = client.get("/api/nodes/judgments/ecli_nl_hr_2019_1278").json()
        conclusion = client.get("/api/nodes/judgments/ecli_nl_phr_2019_496").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    buckets = {
        (b["relation"], b["direction"]): [i["key"] for i in b["items"]]
        for b in ruling["neighbors"]["buckets"]
    }
    assert buckets[("ADVISES_ON", "inbound")] == ["ecli_nl_phr_2019_496"]
    assert buckets[("ANSWERS", "outbound")] == ["ecli_nl_rbnne_2018_4308"]
    assert [
        (b["relation"], b["direction"]) for b in conclusion["neighbors"]["buckets"]
    ] == [("ADVISES_ON", "outbound")]


def test_the_lookup_by_case_number_walks_the_index(database: str) -> None:
    """A sparse array index is not used for a loop variable: the lookup of a few hundred
    case numbers read every judgment once per number (minutes on 33,000 judgments)."""
    store = ArangoStore()
    asked: list[tuple[str, dict[str, Any]]] = []
    real_query = store.query

    def recording(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        asked.append((aql, bind_vars or {}))
        return real_query(aql, bind_vars, **kw)

    store.query = recording  # type: ignore[method-assign]
    from lawgraph.db.queries.semantic import judgments_by_case_keys

    list(judgments_by_case_keys(store, ["18/04298"]))
    ((aql, bind),) = asked
    kinds = [
        node["type"] for node in store.db.aql.explain(aql, bind_vars=bind)["nodes"]
    ]
    assert "IndexNode" in kinds and "EnumerateCollectionNode" not in kinds, kinds
