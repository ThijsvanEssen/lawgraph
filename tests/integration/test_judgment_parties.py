"""The kop and the parties of a judgment: the real ``normalize rechtspraak`` and the API.

``normalize rechtspraak`` runs as a process of its own on the test server, on judgments of
the Rechtspraak whose kop the segmentation lost lines of, and whose parties the front end
read from the text itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from tests.integration.seed import write_judgments

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
JUDGMENTS = {
    "ECLI:NL:GHARL:2026:6060": "rechtspraak_gharl_2026_6060.xml",
    "ECLI:NL:HR:2019:1278": "rechtspraak_hr_2019_1278.xml",
    "ECLI:NL:RVS:2026:5668": "rechtspraak_rvs_2026_5668.xml",
    "ECLI:NL:RVS:2007:BB0782": "rechtspraak_rvs_2007_bb0782.xml",
}
# normalized before parties were read
OLD = "ECLI:NL:HR:2001:1"


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = GraphStore()
    write_judgments(
        store, {ecli: (FIXTURES / name).read_text() for ecli, name in JUDGMENTS.items()}
    )
    cli("normalize", "rechtspraak")
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [
            {
                "_key": make_node_key(OLD),
                "type": "Judgment",
                "props": {"ecli": OLD, "source": SOURCE_RECHTSPRAAK},
            }
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _judgment(client: TestClient, ecli: str) -> dict[str, Any]:
    response = client.get(f"/api/judgments/{ecli}")
    assert response.status_code == 200, response.text
    judgment: dict[str, Any] = response.json()["judgment"]
    return judgment


def test_the_kop_keeps_every_line_and_the_parties_are_served(
    client: TestClient,
) -> None:
    judgment = _judgment(client, "ECLI:NL:GHARL:2026:6060")

    kop = judgment["paragraphs"][0]
    assert kop["kind"] == "subheading"
    assert "in de strafzaak tegen\n\n[verdachte] ," in kop["text"]
    assert judgment["parties"] == [
        {
            "name": "[verdachte]",
            "role": "Verdachte",
            "roles": ["Verdachte"],
            "role_stated": True,
            "side": "second",
            "alias": None,
            # "wat de verdachte en haar raadsvrouw, mr. M.E. Broekert, ... naar voren
            # hebben gebracht"
            "representatives": [
                {
                    "name": "mr. M.E. Broekert",
                    "role": "raadsman",
                    "place": None,
                    "capacity": None,
                }
            ],
        }
    ]


def test_a_role_that_is_derived_says_so(client: TestClient) -> None:
    parties = _judgment(client, "ECLI:NL:RVS:2026:5668")["parties"]

    assert [(p["name"], p["role"], p["role_stated"]) for p in parties] == [
        ("[appellant]", "Appellant", True),
        ("de burgemeester van Rijswijk", "Verweerder", False),
    ]


def test_the_parties_of_the_hoge_raad_with_aliases_and_lawyers(
    client: TestClient,
) -> None:
    parties = _judgment(client, "ECLI:NL:HR:2019:1278")["parties"]

    assert [(p["role"], p["name"], p["alias"]) for p in parties] == [
        ("Eiser", "[eiseres 1]", "[eisers]"),
        ("Eiser", "[eiser 2]", "[eisers]"),
        ("Verweerder", "MAATSCHAP GRONINGEN", "de Maatschap"),
        ("Verweerder", "NEDERLANDSE AARDOLIE MAATSCHAPPIJ B.V.", "NAM"),
        ("Verweerder", "EBN B.V.", "EBN"),
        ("Verweerder", "DE STAAT DER NEDERLANDEN", "de Staat"),
    ]
    assert parties[4]["representatives"] == [
        {
            "name": "mr. J.F. de Groot",
            "role": "advocaat",
            "place": None,
            "capacity": None,
        },
        {
            "name": "mr. P.A. Fruytier",
            "role": "advocaat",
            "place": None,
            "capacity": None,
        },
    ]


def test_who_the_hearing_names_acts_for_each_party_and_finds_the_judgment(
    client: TestClient,
) -> None:
    """Thijs, 13 Oct: cmd+k "R. van Gelder" did not find ECLI:NL:RVS:2007:BB0782, whose
    hearing names him as the advocaat of the appellants."""
    parties = _judgment(client, "ECLI:NL:RVS:2007:BB0782")["parties"]

    assert [
        (
            p["name"],
            [
                (r["name"], r["role"], r["place"], r["capacity"])
                for r in p["representatives"]
            ],
        )
        for p in parties
    ] == [
        (
            "[appellanten]",
            [("mr. drs. R. van Gelder", "advocaat", "Voorschoten", None)],
        ),
        (
            "het college van gedeputeerde staten van Zuid-Holland",
            [
                (
                    "mr. I.T.F. Vermeulen",
                    "gemachtigde",
                    None,
                    "ambtenaar in dienst van de provincie",
                )
            ],
        ),
        (
            "de gemeenteraad van Nieuwerkerk aan den IJssel",
            [("mr. R. van der Meulen MPM", "gemachtigde", None, None)],
        ),
    ]
    for mode in ("full", "live"):
        response = client.get(
            "/api/search",
            params={"q": "R. van Gelder", "types": "judgments", "mode": mode},
        )
        assert response.status_code == 200, response.text
        (hit,) = response.json()["results"]["judgments"]
        assert hit["extra"]["ecli"] == "ECLI:NL:RVS:2007:BB0782"
        assert hit["extra"]["person"] == {
            "name": "mr. drs. R. van Gelder",
            "role": "advocaat",
            "party": "[appellanten]",
        }


def test_a_judgment_normalized_before_parties_has_none_yet(client: TestClient) -> None:
    assert _judgment(client, OLD)["parties"] is None


def test_the_openapi_schema_names_the_parties(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert "parties" in schemas["JudgmentDTO"]["properties"]
    assert schemas["JudgmentParty"]["properties"]["side"]["enum"] == [
        "first",
        "second",
        "other",
    ]
