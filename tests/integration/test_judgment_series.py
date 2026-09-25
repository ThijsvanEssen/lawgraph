"""Series of parallel judgments: the real ``normalize rechtspraak`` and ``semantic
rechtspraak-series``, on judgments modelled on three cases of the corpus.

- ECLI:NL:GHAMS:2026:2679 and 2680: two appeals the Gerechtshof Amsterdam decided on one day
  in nearly the same words, each under its own case number: a series.
- ECLI:NL:RBMNE:2024:5485 and 5863: one judgment and its rectification, the same case
  numbers and text: no series.
- Two short art. 81 RO judgments of the Hoge Raad of one day: one template, and a summary
  (``HR: 81.1 RO.``) the court writes every week: no series.
"""

from __future__ import annotations

import random
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

NS = (
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:psi="http://psi.rechtspraak.nl/"'
)


def _words(seed: int, length: int) -> list[str]:
    rng = random.Random(seed)
    return [f"woord{rng.randrange(5000)}" for _ in range(length)]


def _vary(tokens: list[str], every: int, seed: int) -> str:
    return " ".join(
        f"partij{seed}x{i}" if i % every == 0 else word for i, word in enumerate(tokens)
    )


def _xml(
    ecli: str, court: str, date: str, case_number: str, summary: str, text: str
) -> str:
    return (
        f"<open-rechtspraak {NS}><rdf:RDF><rdf:Description>"
        f"<dcterms:identifier>{ecli}</dcterms:identifier>"
        f"<dcterms:creator>{court}</dcterms:creator><dcterms:date>{date}</dcterms:date>"
        f"<psi:zaaknummer>{case_number}</psi:zaaknummer>"
        "<dcterms:type>Uitspraak</dcterms:type><psi:procedure>Hoger beroep</psi:procedure>"
        "</rdf:Description></rdf:RDF>"
        f"<inhoudsindicatie><para>{summary}</para></inhoudsindicatie>"
        f"<uitspraak><para>{text}</para></uitspraak></open-rechtspraak>"
    )


APPEAL = _words(1, 2000)
WABO = " ".join(_words(2, 1200))
TEMPLATE = _words(3, 400)
GHAMS = ("Gerechtshof Amsterdam", "2026-09-22")
RBMNE = ("Rechtbank Midden-Nederland", "2024-09-13")
HR = "Hoge Raad"
ARTICLE_81 = "HR: 81.1 RO."

JUDGMENTS = {
    "ECLI:NL:GHAMS:2026:2679": _xml(
        "ECLI:NL:GHAMS:2026:2679",
        *GHAMS,
        "200.343.752",
        "kopje volgt",
        _vary(APPEAL, 150, 1),
    ),
    "ECLI:NL:GHAMS:2026:2680": _xml(
        "ECLI:NL:GHAMS:2026:2680",
        *GHAMS,
        "200.344.457",
        "kopje volgt",
        _vary(APPEAL, 150, 2),
    ),
    # another appeal of that day, in other words
    "ECLI:NL:GHAMS:2026:2690": _xml(
        "ECLI:NL:GHAMS:2026:2690",
        *GHAMS,
        "200.350.001",
        "Huurrecht.",
        " ".join(_words(4, 2000)),
    ),
    "ECLI:NL:RBMNE:2024:5485": _xml(
        "ECLI:NL:RBMNE:2024:5485",
        *RBMNE,
        "UTR 23/3439 en UTR 23/3440",
        "Wabo. Beroepen ongegrond.",
        WABO,
    ),
    "ECLI:NL:RBMNE:2024:5863": _xml(
        "ECLI:NL:RBMNE:2024:5863",
        *RBMNE,
        "UTR 23/3439 en UTR 23/3440 RECTIFICATIE",
        "Wabo. Beroepen ongegrond. Rectificatie van ECLI:NL:RBMNE:2024:5485.",
        WABO,
    ),
    "ECLI:NL:HR:2025:1500": _xml(
        "ECLI:NL:HR:2025:1500",
        HR,
        "2025-10-03",
        "24/01001",
        ARTICLE_81,
        _vary(TEMPLATE, 40, 1),
    ),
    "ECLI:NL:HR:2025:1501": _xml(
        "ECLI:NL:HR:2025:1501",
        HR,
        "2025-10-03",
        "24/01002",
        ARTICLE_81,
        _vary(TEMPLATE, 40, 2),
    ),
    # the same summary on two other days: a template
    "ECLI:NL:HR:2025:1400": _xml(
        "ECLI:NL:HR:2025:1400",
        HR,
        "2025-09-19",
        "24/00901",
        ARTICLE_81,
        " ".join(_words(5, 400)),
    ),
    "ECLI:NL:HR:2025:1600": _xml(
        "ECLI:NL:HR:2025:1600",
        HR,
        "2025-10-17",
        "24/01101",
        ARTICLE_81,
        " ".join(_words(6, 400)),
    ),
}


def _store_raw(store: ArangoStore, judgments: dict[str, str]) -> None:
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


def _series(store: ArangoStore) -> dict[str, tuple[Any, Any]]:
    aql = """
    FOR j IN judgments FILTER j.props.source == "rechtspraak"
        RETURN [j.props.ecli, j.props.series_id, j.props.series_size]
    """
    return {ecli: (series, size) for ecli, series, size in store.query(aql)}


def test_parallel_cases_are_a_series_and_rectifications_and_templates_are_not(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _store_raw(store, JUDGMENTS)
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-series")

    in_series = {ecli: v for ecli, v in _series(store).items() if v != (None, None)}
    assert in_series == {
        "ECLI:NL:GHAMS:2026:2679": ("ECLI:NL:GHAMS:2026:2679", 2),
        "ECLI:NL:GHAMS:2026:2680": ("ECLI:NL:GHAMS:2026:2679", 2),
    }

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        detail = client.get("/api/judgments/ECLI:NL:GHAMS:2026:2680").json()
        alone = client.get("/api/judgments/ECLI:NL:GHAMS:2026:2690").json()
        listed = client.get("/api/judgments", params={"court": "GHAMS"}).json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert detail["judgment"]["series_id"] == "ECLI:NL:GHAMS:2026:2679"
    assert detail["judgment"]["series_size"] == 2
    assert [j["ecli"] for j in detail["series"]] == ["ECLI:NL:GHAMS:2026:2679"]
    assert alone["judgment"]["series_id"] is None and alone["series"] == []
    assert {i["ecli"]: i["series_size"] for i in listed["items"]} == {
        "ECLI:NL:GHAMS:2026:2679": 2,
        "ECLI:NL:GHAMS:2026:2680": 2,
        "ECLI:NL:GHAMS:2026:2690": None,
    }

    # 2680 turns out to be another judgment: on the next run both lose their series.
    _store_raw(
        store,
        {
            "ECLI:NL:GHAMS:2026:2680": _xml(
                "ECLI:NL:GHAMS:2026:2680",
                *GHAMS,
                "200.344.457",
                "kopje volgt",
                " ".join(_words(7, 2000)),
            )
        },
    )
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-series")
    assert all(value == (None, None) for value in _series(store).values())
