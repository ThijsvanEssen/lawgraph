"""What an article said on a date: the real ``normalize bwb-history``, run twice, and the API.

Two toestanden of one law: in the second, article 7 has a new version. The pipeline runs a
second time as every ``normalize all`` does; each article must still have exactly one
current version, and a date must pick the version valid on it.
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
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    SOURCE_BWB,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0001840"
OLD = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
NEW = OLD.replace(
    'versie-id="25689252" id="C36647081" label-id="2940564" inwerking="2018-12-21"',
    'versie-id="99999999" id="C36647081" label-id="2940564" inwerking="2025-01-01"',
).replace("Niemand heeft voorafgaand verlof nodig", "Niemand heeft ooit verlof nodig")


def _seed(store: ArangoStore) -> None:
    toestanden = [
        (RAW_KIND_BWB_TOESTAND, LAW, NEW, "2025-01-01", None),
        (
            RAW_KIND_BWB_TOESTAND_ALL,
            f"{LAW}@2018-12-21",
            OLD,
            "2018-12-21",
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
        for kind, external_id, xml, start, end in toestanden:
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
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("normalize", "bwb-history")  # a second run must not make old versions current
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:500])
    return response.json()


def test_an_article_has_one_current_version_and_a_date_picks_its_text(
    client: TestClient,
) -> None:
    versions = _get(client, f"/api/articles/{LAW}/7/history")["versions"]
    assert [(v["valid_from"], v["valid_until"], v["current"]) for v in versions] == [
        ("2018-12-21", "2025-01-01", False),
        ("2025-01-01", None, True),
    ]

    def text_on(date: str) -> str:
        body = _get(client, f"/api/instruments/{LAW}/articles/at/{date}?limit=500")
        (article,) = [a for a in body["items"] if a["article_number"] == "7"]
        return article["text"]

    assert "voorafgaand verlof" in text_on("2020-01-01")
    assert "ooit verlof" in text_on("2026-01-01")

    toestanden = _get(client, f"/api/instruments/{LAW}/versions")
    assert toestanden["total"] == 2
    assert [v["current"] for v in toestanden["items"]] == [True, False]


def test_every_article_version_is_current_only_when_nothing_follows_it(
    client: TestClient,
) -> None:
    store = ArangoStore()
    rows = list(
        store.query(
            "FOR v IN article_versions RETURN "
            "{current: v.props.current, open: v.props.valid_until == null}"
        )
    )
    assert rows and all(row["current"] == row["open"] for row in rows)
