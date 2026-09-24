"""An article with only a heading, and the repealed identities of a law: the real
``normalize bwb`` and ``normalize bwb-history`` (twice, as every rebuild runs them) on the
Grondwet, and the API on their answer.

The Grondwet has the Algemene bepaling (``stam-id`` 16464063): a ``<kop>`` with a ``<titel>``
and no ``<nr>``. It is in force, has a text and parts, stands where the document has it (the
fixture is an excerpt: after articles 82 and 142), and is addressed by its ``stam-id``.
Article 7 is gone from the newest toestand and article 101 is ``vervallen`` in it: both are
listed only when asked for.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    DOCUMENT_COLLECTIONS,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    SOURCE_BWB,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0001840"
OLD = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
NEW = re.sub(
    r'<artikel bwb-ng-variabel-deel="/Hoofdstuk1/Artikel7".*?</artikel>',
    "",
    OLD,
    count=1,
    flags=re.DOTALL,
)
ADDRESS = "stam_16464063"


def _seed(store: ArangoStore) -> None:
    records = [
        (RAW_KIND_BWB_TOESTAND, LAW, NEW, "2025-01-01", None),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2023-02-22",
            OLD,
            "2023-02-22",
            "2024-12-31",
        ),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2025-01-01",
            NEW,
            "2025-01-01",
            "9999-12-31",
        ),
    ]
    with RawSourceWriter(store) as writer:
        for kind, external_id, xml, start, end in records:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=xml,
                    meta={
                        "bwb_id": LAW,
                        "state_url": f"https://repo/{LAW}/{start}.xml",
                        "start_date": start,
                        "end_date": end,
                    },
                )
            )


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
    _seed(store)
    for _ in range(2):
        cli("normalize", "bwb")
        cli("normalize", "bwb-history")
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def test_an_article_with_only_a_heading_is_an_article_in_force(
    client: TestClient,
) -> None:
    listed = _get(client, f"/api/instruments/{LAW}/articles")["items"]
    # the order of the document
    assert [a["label"] for a in listed] == [
        "Artikel 82",
        "Artikel 142",
        "Algemene bepaling",
        "Artikel 92",
        "Artikel 138",
    ]
    heading = listed[2]
    assert (heading["address"], heading["article_number"]) == (ADDRESS, None)
    assert heading["display_name"] == "Algemene bepaling Grondwet"
    assert heading["text_preview"].startswith("De Grondwet waarborgt")
    assert heading["repealed"] is False

    detail = _get(client, f"/api/articles/{LAW}/{ADDRESS}")["article"]
    assert detail["key"] == "bwbr0001840_stam_16464063"
    assert detail["text"].startswith("De Grondwet waarborgt de grondrechten")
    assert detail["repealed"] is False
    assert detail["address"] == ADDRESS

    versions = _get(client, f"/api/articles/{LAW}/{ADDRESS}/history")["versions"]
    assert [(v["label"], v["valid_from"]) for v in versions] == [
        ("Algemene bepaling", "2022-08-30")
    ]

    answer = client.get(
        "/api/resolve", params={"q": "algemene bepaling Grondwet"}
    ).json()
    assert answer["match"]["key"] == "bwbr0001840_stam_16464063"


def test_a_repealed_identity_is_listed_only_when_asked_for(client: TestClient) -> None:
    in_force = _get(client, f"/api/instruments/{LAW}/articles")["items"]
    assert all(not a["repealed"] for a in in_force)
    assert {"Artikel 7", "Artikel 101"}.isdisjoint(a["label"] for a in in_force)

    everything = _get(client, f"/api/instruments/{LAW}/articles?include_repealed=true")[
        "items"
    ]
    repealed = {a["label"]: a for a in everything if a["repealed"]}
    assert set(repealed) == {"Artikel 7", "Artikel 101"}
    identity = repealed["Artikel 7"]  # gone from the toestand: a historical identity
    assert (identity["key"], identity["last_article_number"]) == (
        "bwbr0001840_7_stam_2990103",
        "7",
    )
    assert identity["address"] == "7_stam_2990103"
    assert everything[-1] == identity  # after the articles of the toestand
    assert repealed["Artikel 101"]["article_number"] == "101"  # vervallen in it
    assert _get(client, f"/api/articles/{LAW}/7_stam_2990103")["article"]["repealed"]


def test_no_node_is_named_after_a_missing_number(client: TestClient) -> None:
    store = ArangoStore()
    for collection in DOCUMENT_COLLECTIONS:
        if collection == "raw_sources":
            continue
        rows = list(
            store.query(
                f"FOR d IN {collection} FILTER CONTAINS(d.props.display_name, 'None') "
                "OR d.props.last_article_number == 'None' OR d.props.label == 'None' "
                "RETURN d._key"
            )
        )
        assert rows == [], collection
