"""``GET /api/judgments/{ecli}/course`` (Verloop) on real ``normalize rechtspraak`` and the
semantic steps that tie a case: a chain from the rechtbank to the Hoge Raad with its
conclusion, a decision after referral, a gap (an earlier instance not loaded, a decision the
text names), and the first and only instance at the Raad van State (art. 8:6 Awb).

The cases are made up around the shape of real ones (ECLI:NL:GHSHE:2026:2210 for the outcome
the Rechtspraak records, ECLI:NL:GHDHA:2021:1023 for a referral)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from tests.asserts import assert_status, show_items
from tests.integration.seed import (
    rechtspraak_relation,
    rechtspraak_xml,
    write_judgments,
)

RO, AWB, AWR = "BWBR0001830", "BWBR0005537", "BWBR0002320"
RV, SV = "BWBR0001827", "BWBR0001903"
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
HR_TAX = "ECLI:NL:HR:2026:70"

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
        # as the source often names it (ECLI:NL:GHDHA:2026:2845): the referral is the edge
        procedure="Hoger beroep",
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
    # cassation in a tax case (as ECLI:NL:HR:2026:1016)
    HR_TAX: rechtspraak_xml(
        HR_TAX,
        "Hoge Raad",
        "2026-06-01",
        "25/00070",
        procedure="Cassatie",
        subject="Bestuursrecht; Belastingrecht",
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
    assert steps[0]["basis"]["key"] == "bwbr0001830_42"
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
    # the article of the referral, though its procedure reads Hoger beroep
    assert [_basis(s) for s in steps] == [(RO, "60"), (RO, "78"), (RV, "424")]


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


def test_the_first_and_only_instance_at_the_raad_van_state_has_art_8_6(
    client: TestClient,
) -> None:
    """Art. 8:6 Awb names the court of the Bevoegdheidsregeling or of another statute: the
    article of the regeling is the route's (``/routes``), not the step's."""
    (step,) = _course(client, RVS_FIRST)["steps"]
    assert (step["tier"], step["procedure"], step["area"]) == (
        "raad_van_state",
        "Eerste aanleg - enkelvoudig",
        "bestuur",
    )
    assert _basis(step) == (AWB, "8:6")
    assert step["links"] == []


def test_cassation_in_a_tax_case_has_art_28_awr(client: TestClient) -> None:
    (step,) = _course(client, HR_TAX)["steps"]
    assert (step["tier"], step["area"], _basis(step)) == (
        "hoge_raad",
        "belasting",
        (AWR, "28"),
    )


def test_the_routes_name_each_court_with_its_article(client: TestClient) -> None:
    response = client.get("/api/judgments/routes")
    assert_status(response, 200)
    areas = {a["area"]: a for a in response.json()["areas"]}
    assert list(areas) == ["civiel", "straf", "bestuur", "belasting"]
    civiel = [
        (s["tier"], s["basis"]["article_number"]) for s in areas["civiel"]["steps"]
    ]
    assert civiel == [
        ("rechtbank", "42"),
        ("gerechtshof", "60"),
        ("hoge_raad", "78"),
        ("hoge_raad", "78"),
        ("gerechtshof", "424"),
    ]
    rvs = next(s for s in areas["bestuur"]["steps"] if s["tier"] == "raad_van_state")
    assert (rvs["basis"]["article_number"], rvs["designations"]) == (
        "8:6",
        [
            {
                "bwb_id": AWB,
                "article_number": "bijlage 2 artikel 2",
                "key": "bwbr0005537_bijlage_2_artikel_2",
            }
        ],
    )
    assert rvs["basis"]["key"] == "bwbr0005537_8_6"
    with_gaps = [a for a in areas.values() if a["gaps"]]
    assert not with_gaps, show_items(with_gaps)
    belasting = {
        s["tier"]: (
            _basis(s),
            [(d["bwb_id"], d["article_number"]) for d in s["designations"]],
        )
        for s in areas["belasting"]["steps"]
        if s["after_tier"] is None
    }
    assert belasting == {
        "rechtbank": ((RO, "44"), [(AWB, "8:6")]),
        "gerechtshof": ((RO, "60"), [(AWB, "8:105"), (AWB, "bijlage 2 artikel 12")]),
        "hoge_raad": ((AWR, "28"), [(RO, "78")]),
    }
    bestuur = areas["bestuur"]["steps"]
    hofs = [s for s in bestuur if s["tier"] == "gerechtshof"]
    assert [(s["procedures"][0], _basis(s), s["designations"]) for s in hofs] == [
        (
            "Eerste aanleg",
            (AWB, "8:6"),
            [
                {
                    "bwb_id": AWB,
                    "article_number": "bijlage 2 artikel 5",
                    "key": "bwbr0005537_bijlage_2_artikel_5",
                }
            ],
        ),
        (
            "Hoger beroep",
            (AWB, "8:105"),
            [
                {
                    "bwb_id": AWB,
                    "article_number": "bijlage 2 artikel 12",
                    "key": "bwbr0005537_bijlage_2_artikel_12",
                }
            ],
        ),
    ]
    (hr,) = [s for s in bestuur if s["tier"] == "hoge_raad"]
    assert (hr["after_tier"], _basis(hr)) == ("centrale_raad_van_beroep", (RO, "78"))
    assert {
        "bwb_id": "BWBR0002221",
        "article_number": "53",
        "key": "bwbr0002221_53",
    } in hr["designations"]
    # the HR in first and only instance for ambtsmisdrijven (art. 76 RO), no step before it
    (ambts,) = [
        s
        for s in areas["straf"]["steps"]
        if s["procedures"] == ["Eerste en enige aanleg"]
    ]
    assert (ambts["tier"], ambts["after_tier"], _basis(ambts)) == (
        "hoge_raad",
        None,
        (RO, "76"),
    )
    # the Awb is not loaded here
    assert response.json()["regeling"] == []


@pytest.mark.parametrize(
    ("area", "basis", "designations"),
    [
        ("civiel", (RO, "78"), [(RV, "398")]),
        ("belasting", (AWR, "28"), [(RO, "78")]),
    ],
)
def test_leapfrog_cassation_is_a_step_after_the_rechtbank(
    client: TestClient,
    area: str,
    basis: tuple[str, str],
    designations: list[tuple[str, str]],
) -> None:
    response = client.get("/api/judgments/routes")
    assert_status(response, 200)
    (steps,) = [a["steps"] for a in response.json()["areas"] if a["area"] == area]
    leap = [s for s in steps if s["after_tier"] == "rechtbank"]
    assert len(leap) == 1, show_items(leap)
    assert (leap[0]["tier"], _basis(leap[0])) == ("hoge_raad", basis)
    assert [(d["bwb_id"], d["article_number"]) for d in leap[0]["designations"]] == (
        designations
    )
    # art. 398 Rv belongs to the leapfrog only, not to cassation after the hof
    plain = [s for s in steps if s["tier"] == "hoge_raad" and s["after_tier"] is None]
    with_rv = [s for s in plain if any(d["bwb_id"] == RV for d in s["designations"])]
    assert not with_rv, show_items(with_rv)


@pytest.mark.parametrize(
    ("area", "basis"),
    [("civiel", (RV, "424")), ("straf", (SV, "440")), ("belasting", (AWR, "29e"))],
)
def test_the_hof_after_a_referral_is_a_step_after_the_hoge_raad(
    client: TestClient, area: str, basis: tuple[str, str]
) -> None:
    response = client.get("/api/judgments/routes")
    assert_status(response, 200)
    (steps,) = [a["steps"] for a in response.json()["areas"] if a["area"] == area]
    referred = [s for s in steps if s["after_tier"] == "hoge_raad"]
    assert len(referred) == 1, show_items(referred)
    assert (
        referred[0]["tier"],
        referred[0]["procedures"],
        _basis(referred[0]),
    ) == ("gerechtshof", ["Verwijzing na Hoge Raad"], basis)


def test_a_judgment_not_in_the_graph_is_404(client: TestClient) -> None:
    assert_status(client.get("/api/judgments/ECLI:NL:HR:1999:1/course"), 404)
