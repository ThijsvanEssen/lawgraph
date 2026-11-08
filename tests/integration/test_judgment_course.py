"""``GET /api/judgments/{ecli}/course`` (Verloop) on real ``normalize rechtspraak`` and the
semantic steps that tie a case: a chain from the rechtbank to the Hoge Raad with its
conclusion, a decision after referral, a gap (an earlier instance not loaded, a decision the
text names), and the first and only instance at the Raad van State.

The cases are made up around the shape of real ones (ECLI:NL:GHSHE:2026:2210 for the outcome
the Rechtspraak records, ECLI:NL:GHDHA:2021:1023 for a referral)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from tests.asserts import assert_status
from tests.integration.seed import (
    rechtspraak_relation,
    rechtspraak_xml,
    write_judgments,
)

RO, AWB = "BWBR0001830", "BWBR0005537"
CIVIEL = "Civiel recht; Verbintenissenrecht"


def _earlier(ecli: str, outcome: str | None = None) -> str:
    return rechtspraak_relation(ecli, "uitspraak", "eerdereAanleg", outcome=outcome)


def _conclusion(ecli: str, instance: str = "eerdereAanleg") -> str:
    return rechtspraak_relation(ecli, "conclusie", instance)


RB, HOF, PHR, HR = (
    "ECLI:NL:RBDHA:2023:100",
    "ECLI:NL:GHDHA:2024:200",
    "ECLI:NL:PHR:2025:300",
    "ECLI:NL:HR:2025:400",
)
# a ruling of the Hoge Raad that sent a case to another hof, and that hof's decision
HOF_AMS, HR_REF, HOF_REF = (
    "ECLI:NL:GHAMS:2019:10",
    "ECLI:NL:HR:2020:20",
    "ECLI:NL:GHDHA:2021:30",
)
RVS_APPEAL, RB_STUB = "ECLI:NL:RVS:2026:40", "ECLI:NL:RBGEL:2025:41"
CRVB_TEXT = "ECLI:NL:CRVB:2026:50"
RVS_FIRST = "ECLI:NL:RVS:2026:60"

CASES = {
    RB: rechtspraak_xml(
        RB,
        "Rechtbank Den Haag",
        "2023-03-01",
        "C/09/1",
        procedure="Eerste aanleg - meervoudig",
        subject=CIVIEL,
    ),
    HOF: rechtspraak_xml(
        HOF,
        "Gerechtshof Den Haag",
        "2024-04-01",
        "200.1/01",
        procedure="Hoger beroep",
        relations=_earlier(RB, "bekrachtiging/bevestiging"),
        subject=CIVIEL,
    ),
    PHR: rechtspraak_xml(
        PHR,
        "Parket bij de Hoge Raad",
        "2025-02-01",
        "24/00001",
        document_type="Conclusie",
        relations=_conclusion(HR, "latereAanleg"),
        subject=CIVIEL,
    ),
    HR: rechtspraak_xml(
        HR,
        "Hoge Raad",
        "2025-05-01",
        "24/00001",
        procedure="Cassatie",
        relations=_earlier(HOF) + _conclusion(PHR),
        subject=CIVIEL,
    ),
    HOF_AMS: rechtspraak_xml(
        HOF_AMS,
        "Gerechtshof Amsterdam",
        "2019-01-01",
        "200.2/01",
        procedure="Hoger beroep",
        subject=CIVIEL,
    ),
    HR_REF: rechtspraak_xml(
        HR_REF,
        "Hoge Raad",
        "2020-01-01",
        "19/00002",
        procedure="Cassatie",
        relations=_earlier(HOF_AMS),
        subject=CIVIEL,
    ),
    HOF_REF: rechtspraak_xml(
        HOF_REF,
        "Gerechtshof Den Haag",
        "2021-01-01",
        "200.3/01",
        procedure="Verwijzing na Hoge Raad",
        relations=_earlier(HR_REF),
        subject=CIVIEL,
    ),
    # its rechtbank is named, not loaded
    RVS_APPEAL: rechtspraak_xml(
        RVS_APPEAL,
        "Raad van State",
        "2026-03-01",
        "202500001/1/A1",
        procedure="Hoger beroep",
        relations=_earlier(RB_STUB),
        subject="Bestuursrecht; Omgevingsrecht",
    ),
    # names the decision it appeals in its text only
    CRVB_TEXT: rechtspraak_xml(
        CRVB_TEXT,
        "Centrale Raad van Beroep",
        "2026-04-01",
        "25/1234 WIA",
        procedure="Hoger beroep",
        text="Appellant heeft hoger beroep ingesteld tegen de uitspraak van de rechtbank "
        "Gelderland van 9 juli 2025 in zaak nr. 24/6811.",
        subject="Bestuursrecht; Socialezekerheidsrecht",
    ),
    RVS_FIRST: rechtspraak_xml(
        RVS_FIRST,
        "Raad van State",
        "2026-05-01",
        "202500002/1/R1",
        procedure="Eerste aanleg - enkelvoudig",
        subject="Bestuursrecht; Omgevingsrecht",
    ),
}


@pytest.fixture
def client(database: str, cli: Any) -> Any:
    store = GraphStore()
    write_judgments(store, CASES)
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-appeal")
    cli("semantic", "rechtspraak-conclusions")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _course(client: TestClient, ecli: str) -> dict[str, Any]:
    response = client.get(f"/api/judgments/{ecli}/course")
    assert_status(response, 200)
    return response.json()


def _basis(step: dict[str, Any]) -> tuple[str, str] | None:
    basis = step["basis"]
    return (basis["bwb_id"], basis["article_number"]) if basis else None


def test_a_chain_from_the_rechtbank_to_the_hoge_raad(client: TestClient) -> None:
    """Asked of the rechtbank, the whole case: the hof with the outcome the Rechtspraak
    records, the conclusion just before the ruling, each court with its article."""
    course = _course(client, RB)
    steps = course["steps"]
    assert [s["ecli"] for s in steps] == [RB, HOF, PHR, HR]
    assert [s["current"] for s in steps] == [True, False, False, False]
    assert [_basis(s) for s in steps] == [(RO, "42"), (RO, "60"), None, (RO, "78")]
    assert [s["area"] for s in steps] == ["civiel"] * 4
    assert steps[1]["links"] == [
        {
            "relation": "APPEAL_OF",
            "to": RB,
            "source_outcome": "Bekrachtiging/bevestiging",
        }
    ]
    assert steps[2]["links"] == [
        {"relation": "ADVISES_ON", "to": HR, "source_outcome": None}
    ]
    assert steps[3]["links"] == [
        {"relation": "APPEAL_OF", "to": HOF, "source_outcome": None}
    ]
    assert course["truncated"] is False
    assert course["unresolved"] == []


def test_a_decision_after_referral_follows_the_ruling(client: TestClient) -> None:
    steps = _course(client, HOF_REF)["steps"]
    assert [s["ecli"] for s in steps] == [HOF_AMS, HR_REF, HOF_REF]
    assert steps[2]["links"] == [
        {"relation": "REFERRED_BY", "to": HR_REF, "source_outcome": None}
    ]
    # no article in the list for a decision after referral: a gap
    assert [_basis(s) for s in steps] == [(RO, "60"), (RO, "78"), None]


def test_an_earlier_instance_not_loaded_is_a_stub_without_basis(
    client: TestClient,
) -> None:
    stub, appeal = _course(client, RVS_APPEAL)["steps"]
    assert (stub["ecli"], stub["loaded"], stub["basis"]) == (RB_STUB, False, None)
    assert stub["court_name"] == "Rechtbank Gelderland"
    assert (appeal["loaded"], _basis(appeal)) == (True, (AWB, "8:105"))


def test_a_decision_the_text_names_and_the_graph_lacks_is_unresolved(
    client: TestClient,
) -> None:
    course = _course(client, CRVB_TEXT)
    assert [s["ecli"] for s in course["steps"]] == [CRVB_TEXT]
    assert course["unresolved"] == [
        {
            "court": "rechtbank Gelderland",
            "date": "2025-07-09",
            "case_number": "24/6811",
        }
    ]


def test_the_first_and_only_instance_at_the_raad_van_state_is_a_gap(
    client: TestClient,
) -> None:
    """The Bevoegdheidsregeling bestuursrechtspraak is not in the list: no basis."""
    (step,) = _course(client, RVS_FIRST)["steps"]
    assert (step["tier"], step["procedure"], step["area"]) == (
        "raad_van_state",
        "Eerste aanleg - enkelvoudig",
        "bestuur",
    )
    assert step["basis"] is None
    assert step["links"] == []


def test_a_judgment_not_in_the_graph_is_404(client: TestClient) -> None:
    assert_status(client.get("/api/judgments/ECLI:NL:HR:1999:1/course"), 404)
