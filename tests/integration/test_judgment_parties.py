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
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
JUDGMENTS = {
    "ECLI:NL:GHARL:2026:6060": "rechtspraak_gharl_2026_6060.xml",
    "ECLI:NL:HR:2019:1278": "rechtspraak_hr_2019_1278.xml",
    "ECLI:NL:RVS:2026:5668": "rechtspraak_rvs_2026_5668.xml",
}
# normalized before parties were read
OLD = "ECLI:NL:HR:2001:1"


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for ecli, name in JUDGMENTS.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=(FIXTURES / name).read_text(),
                    meta={"ecli": ecli},
                )
            )
    cli("normalize", "rechtspraak")
    store.db.collection(COLLECTION_JUDGMENTS).insert(
        {
            "_key": make_node_key(OLD),
            "type": "Judgment",
            "props": {"ecli": OLD, "source": SOURCE_RECHTSPRAAK},
        }
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
            "role_stated": True,
            "side": "second",
            "alias": None,
            "representatives": [],
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
        {"name": "mr. J.F. de Groot", "role": "advocaat"},
        {"name": "mr. P.A. Fruytier", "role": "advocaat"},
    ]


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
