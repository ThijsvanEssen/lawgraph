"""What an earlier judgment of a case is to a later one, on real ``normalize rechtspraak`` and
the semantic steps that tie them: an appeal, a continuation of the same court, a decision after
referral by the Hoge Raad, the conclusion that advised; the decision the text of an appeal
names when the metadata names none; and no citation between two judgments that have one of
those edges.

The headers follow real cases (ECLI:NL:GHARL:2026:5720, ECLI:NL:GHDHA:2021:1023,
ECLI:NL:RVS:2026:5642, ECLI:NL:RVS:2014:188 with ECLI:NL:CBB:2014:291, the conclusion
ECLI:NL:RVS:2016:1421 of a staatsraad advocaat-generaal, ECLI:NL:HR:2026:1488); the rest is
made up around them.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_RS_CONTENT,
    RELATION_ADVISES_ON,
    RELATION_APPEAL_OF,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import ArangoStore, EdgeWriter, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.semantic.rechtspraak_appeal import (
    SEMANTIC_SOURCE as APPEAL_SOURCE,
)
from lawgraph.pipelines.semantic.rechtspraak_conclusions import (
    SEMANTIC_SOURCE as CONCLUSION_SOURCE,
)
from tests.integration.test_judgment_relations import _relation, _xml

HOF_AL = "Gerechtshof Arnhem-Leeuwarden"
HOF_DH = "Gerechtshof Den Haag"
HOF_DB = "Gerechtshof 's-Hertogenbosch"
RVS = "Raad van State"
CBB = "College van Beroep voor het bedrijfsleven"


def _earlier(ecli: str) -> str:
    return _relation(ecli, "uitspraak", "eerdereAanleg")


def _conclusion(ecli: str, instance: str = "eerdereAanleg") -> str:
    return _relation(ecli, "conclusie", instance)


APPEALS = {
    # an interim judgment of the hof and its final one, one case number
    "ECLI:NL:GHARL:2026:5720": _xml(
        "ECLI:NL:GHARL:2026:5720",
        HOF_AL,
        "2026-09-01",
        "200.335.407/01",
        procedure="Hoger beroep",
        relations=_earlier("ECLI:NL:GHARL:2024:7481"),
    ),
    "ECLI:NL:GHARL:2024:7481": _xml(
        "ECLI:NL:GHARL:2024:7481",
        HOF_AL,
        "2024-12-03",
        "200.335.407/01",
        procedure="Hoger beroep",
    ),
    # the hof the Hoge Raad referred the case to, and the Hoge Raad that ruled on another hof
    "ECLI:NL:GHDHA:2021:1023": _xml(
        "ECLI:NL:GHDHA:2021:1023",
        HOF_DH,
        "2021-06-08",
        "200.278.757/01",
        procedure="Hoger beroep",
        relations=_earlier("ECLI:NL:HR:2019:1858"),
    ),
    "ECLI:NL:HR:2019:1858": _xml(
        "ECLI:NL:HR:2019:1858",
        "Hoge Raad",
        "2019-11-29",
        "18/03295",
        procedure="Cassatie",
        relations=_earlier("ECLI:NL:GHAMS:2018:1473"),
    ),
    # after referral, as its procedure says: the Hoge Raad and the rechtbank appealed
    "ECLI:NL:GHSHE:2021:1620": _xml(
        "ECLI:NL:GHSHE:2021:1620",
        HOF_DB,
        "2021-05-04",
        "200.280.190_01",
        procedure="Verwijzing na Hoge Raad",
        relations=_earlier("ECLI:NL:HR:2020:809") + _earlier("ECLI:NL:RBOBR:2017:1"),
    ),
    # the hof that asked the Hoge Raad questions, after the answer: its interim judgment
    # is continued, the answer is no earlier instance
    "ECLI:NL:GHSHE:2025:74": _xml(
        "ECLI:NL:GHSHE:2025:74",
        HOF_DB,
        "2025-01-14",
        "22/148",
        procedure="Hoger beroep",
        relations=_earlier("ECLI:NL:HR:2024:1299") + _earlier("ECLI:NL:GHSHE:2024:699"),
    ),
    "ECLI:NL:GHSHE:2024:699": _xml(
        "ECLI:NL:GHSHE:2024:699",
        HOF_DB,
        "2024-03-06",
        "22/148",
        procedure="Hoger beroep",
    ),
    "ECLI:NL:HR:2024:1299": _xml(
        "ECLI:NL:HR:2024:1299",
        "Hoge Raad",
        "2024-09-27",
        "24/00806",
        procedure="Prejudiciële beslissing",
    ),
    # an appeal whose metadata names no earlier instance: its text names one not loaded ...
    "ECLI:NL:RVS:2026:5642": _xml(
        "ECLI:NL:RVS:2026:5642",
        RVS,
        "2026-09-23",
        "202504659/1/V6",
        procedure="Hoger beroep",
        text="Uitspraak op de hoger beroepen van: 1. de minister van Sociale Zaken en "
        "Werkgelegenheid 2. [appellant], appellanten, tegen de uitspraak van de rechtbank "
        "Gelderland van 9 juli 2025 in zaak nr. 24/6811 in het geding tussen: [appellant] "
        "en de minister.",
    ),
    # ... and one that is loaded, its case number written otherwise
    "ECLI:NL:RVS:2026:9": _xml(
        "ECLI:NL:RVS:2026:9",
        RVS,
        "2026-01-07",
        "202502001/1/A2",
        procedure="Hoger beroep",
        text="Uitspraak op het hoger beroep van: [appellant], tegen de uitspraak van de "
        "rechtbank Den Haag van 3 maart 2025 in zaak nr. 24/1234 in het geding tussen: "
        "[appellant] en het college.",
    ),
    "ECLI:NL:RBDHA:2025:77": _xml(
        "ECLI:NL:RBDHA:2025:77", "Rechtbank Den Haag", "2025-03-03", "SGR 24/1234"
    ),
    # another case of that day
    "ECLI:NL:RBDHA:2025:78": _xml(
        "ECLI:NL:RBDHA:2025:78", "Rechtbank Den Haag", "2025-03-03", "SGR 24/1235"
    ),
}


def _load(store: ArangoStore, judgments: dict[str, str]) -> None:
    with RawSourceWriter(store) as writer:
        for ecli, xml in judgments.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=xml,
                    meta={"ecli": ecli},
                )
            )


def _edges(store: ArangoStore, source: str) -> set[tuple[str, str, str, str | None]]:
    sql = """
    SELECT e.relation, f.ecli AS from_ecli, t.ecli AS to_ecli,
           e.doc -> 'meta' ->> 'basis' AS basis
    FROM edges e
    LEFT JOIN judgments f ON f.id = e.from_id
    LEFT JOIN judgments t ON t.id = e.to_id
    WHERE e.source = %(source)s
    """
    return {tuple(row.values()) for row in store.query(sql, {"source": source})}


def _key(ecli: str) -> str:
    return "judgments/" + ecli.lower().replace(":", "_")


def test_an_earlier_judgment_is_appealed_continued_or_the_referral(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _load(store, APPEALS)
    cli("normalize", "rechtspraak")
    # what an earlier run made of the continuation
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            _key("ECLI:NL:GHARL:2026:5720"),
            _key("ECLI:NL:GHARL:2024:7481"),
            RELATION_APPEAL_OF,
            source=APPEAL_SOURCE,
        )

    cli("semantic", "rechtspraak-appeal")

    assert _edges(store, APPEAL_SOURCE) == {
        (
            "CONTINUES",
            "ECLI:NL:GHARL:2026:5720",
            "ECLI:NL:GHARL:2024:7481",
            "formal_relation",
        ),
        (
            "REFERRED_BY",
            "ECLI:NL:GHDHA:2021:1023",
            "ECLI:NL:HR:2019:1858",
            "formal_relation",
        ),
        (
            "APPEAL_OF",
            "ECLI:NL:HR:2019:1858",
            "ECLI:NL:GHAMS:2018:1473",
            "formal_relation",
        ),
        (
            "REFERRED_BY",
            "ECLI:NL:GHSHE:2021:1620",
            "ECLI:NL:HR:2020:809",
            "formal_relation",
        ),
        (
            "APPEAL_OF",
            "ECLI:NL:GHSHE:2021:1620",
            "ECLI:NL:RBOBR:2017:1",
            "formal_relation",
        ),
        (
            "CONTINUES",
            "ECLI:NL:GHSHE:2025:74",
            "ECLI:NL:GHSHE:2024:699",
            "formal_relation",
        ),
        ("APPEAL_OF", "ECLI:NL:RVS:2026:9", "ECLI:NL:RBDHA:2025:77", "appeal_text"),
    }
    targets = {
        row["ecli"]: row["targets"]
        for row in store.query(
            "SELECT ecli, props -> 'unresolved_appeal_targets' AS targets "
            "FROM judgments "
            "WHERE json_typeof(props -> 'unresolved_appeal_targets') <> 'null'"
        )
    }
    assert targets == {
        "ECLI:NL:RVS:2026:5642": [
            {
                "court": "rechtbank Gelderland",
                "date": "2025-07-09",
                "case_number": "24/6811",
            }
        ]
    }

    app.dependency_overrides[get_store] = lambda: store
    try:
        detail = TestClient(app).get("/api/judgments/ECLI:NL:RVS:2026:5642").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert (
        detail["judgment"]["unresolved_appeal_targets"]
        == targets["ECLI:NL:RVS:2026:5642"]
    )


CONCLUSIONS = {
    # two judgments whose metadata call each other the conclusion; the real conclusion
    # of the second
    "ECLI:NL:RVS:2014:188": _xml(
        "ECLI:NL:RVS:2014:188",
        RVS,
        "2014-01-29",
        "201302106/1/A2",
        procedure="Hoger beroep",
        relations=_conclusion("ECLI:NL:CBB:2014:291"),
    ),
    "ECLI:NL:CBB:2014:291": _xml(
        "ECLI:NL:CBB:2014:291",
        CBB,
        "2014-07-22",
        "AWB 11/981",
        procedure="Hoger beroep",
        relations=_conclusion("ECLI:NL:CBB:2014:3")
        + _conclusion("ECLI:NL:RVS:2014:188"),
    ),
    "ECLI:NL:CBB:2014:3": _xml(
        "ECLI:NL:CBB:2014:3",
        CBB,
        "2014-01-09",
        "AWB 11/981",
        document_type="Conclusie",
    ),
    # the conclusion of a staatsraad advocaat-generaal, asked in a case of its own number
    "ECLI:NL:RVS:2016:1421": _xml(
        "ECLI:NL:RVS:2016:1421",
        RVS,
        "2016-05-25",
        "201406676/2/A3",
        document_type="Conclusie",
    ),
    "ECLI:NL:RVS:2016:2927": _xml(
        "ECLI:NL:RVS:2016:2927",
        RVS,
        "2016-11-02",
        "201406676/1/A3",
        procedure="Hoger beroep",
    ),
    # another case
    "ECLI:NL:RVS:2016:2928": _xml(
        "ECLI:NL:RVS:2016:2928",
        RVS,
        "2016-11-02",
        "201406677/1/A3",
        procedure="Hoger beroep",
    ),
}


def test_a_conclusion_advises_one_way(database: str, cli: Any) -> None:
    store = ArangoStore()
    _load(store, CONCLUSIONS)
    cli("normalize", "rechtspraak")
    # what an earlier run made of the two judgments
    with EdgeWriter(store, what=None) as edges:
        for one, other in (
            ("ECLI:NL:RVS:2014:188", "ECLI:NL:CBB:2014:291"),
            ("ECLI:NL:CBB:2014:291", "ECLI:NL:RVS:2014:188"),
        ):
            edges.add(
                _key(one), _key(other), RELATION_ADVISES_ON, source=CONCLUSION_SOURCE
            )

    cli("semantic", "rechtspraak-conclusions")

    assert _edges(store, CONCLUSION_SOURCE) == {
        (
            "ADVISES_ON",
            "ECLI:NL:CBB:2014:3",
            "ECLI:NL:CBB:2014:291",
            "formal_relation",
        ),
        (
            "ADVISES_ON",
            "ECLI:NL:RVS:2016:1421",
            "ECLI:NL:RVS:2016:2927",
            "case_number",
        ),
    }


RULING = "ECLI:NL:HR:2026:1488"
APPEALED = "ECLI:NL:GHDHA:2025:861"
CONCLUSION = "ECLI:NL:PHR:2026:202"
CITED = "ECLI:NL:HR:2015:1"
FOOTNOTES = {
    # the ruling names the arrest under cassation and the conclusion in its text
    RULING: _xml(
        RULING,
        "Hoge Raad",
        "2026-09-18",
        "25/01234",
        procedure="Cassatie",
        relations=_earlier(APPEALED) + _conclusion(CONCLUSION),
        text=f"Het hof heeft geoordeeld ({APPEALED}), zoals de advocaat-generaal "
        f"({CONCLUSION}) uiteenzet; de Hoge Raad oordeelde eerder ({CITED}).",
    ),
    APPEALED: _xml(APPEALED, HOF_DH, "2025-04-01", "200.300.001/01"),
    CONCLUSION: _xml(
        CONCLUSION,
        "Parket bij de Hoge Raad",
        "2026-06-05",
        "25/01234",
        document_type="Conclusie",
        relations=_conclusion(RULING, "latereAanleg"),
    ),
    CITED: _xml(CITED, "Hoge Raad", "2015-05-01", "14/00001"),
}


def test_a_procedural_link_is_not_also_a_citation(database: str, cli: Any) -> None:
    store = ArangoStore()
    _load(store, FOOTNOTES)
    cli("normalize", "rechtspraak")
    # as `semantic all` did before: the citations first
    cli("semantic", "rechtspraak-citations")
    cli("semantic", "rechtspraak-appeal")
    cli("semantic", "rechtspraak-conclusions")
    cli("semantic", "rechtspraak-citations")
    cli("semantic", "graph-list-stats", "--judgments-only")

    cited = {
        (row[1], row[2])
        for row in _edges(store, "judgment-citation-linker")
        if row[0] == "REFERS_TO"
    }
    assert cited == {(RULING, CITED)}
    counts = {
        row["ecli"]: row["count"]
        for row in store.query(
            "SELECT ecli, props -> 'inbound_citation_count' AS count FROM judgments"
        )
    }
    assert counts[APPEALED] == 0 and counts[CONCLUSION] == 0 and counts[CITED] == 1

    app.dependency_overrides[get_store] = lambda: store
    try:
        node = (
            TestClient(app)
            .get("/api/nodes/judgments/ecli_nl_hr_2026_1488?limit=200")
            .json()
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    buckets = {
        (b["relation"], b["direction"]): [i["key"] for i in b["items"]]
        for b in node["neighbors"]["buckets"]
    }
    assert buckets == {
        ("APPEAL_OF", "outbound"): ["ecli_nl_ghdha_2025_861"],
        ("ADVISES_ON", "inbound"): ["ecli_nl_phr_2026_202"],
        ("REFERS_TO", "outbound"): ["ecli_nl_hr_2015_1"],
    }
