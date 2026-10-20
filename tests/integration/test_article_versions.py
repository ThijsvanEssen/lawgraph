"""What an article said on a date: the real ``normalize bwb-history``, run twice, and the API.

Two toestanden of one law: in the second, article 7 has a new version. The pipeline runs a
second time as every ``normalize all`` does; each article must still have exactly one
current version, and a date must pick the version valid on it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
)
from lawgraph.db import GraphStore
from tests.databases import Api, module_store
from tests.integration.seed import write_toestanden

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0001840"
OLD = (FIXTURES / "bwb_grondwet_toestand.xml").read_text()
NEW = OLD.replace(
    'versie-id="25689252" id="C36647081" label-id="2940564" inwerking="2018-12-21"',
    'versie-id="99999999" id="C36647081" label-id="2940564" inwerking="2025-01-01"',
).replace("Niemand heeft voorafgaand verlof nodig", "Niemand heeft ooit verlof nodig")


def _seed(store: GraphStore) -> None:
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
    write_toestanden(
        store,
        [
            (
                kind,
                external_id,
                xml,
                {
                    "bwb_id": LAW,
                    "state_url": f"https://repo/{LAW}/{start}.xml",
                    "start_date": start,
                    "end_date": end,
                },
            )
            for kind, external_id, xml, start, end in toestanden
        ],
    )


# The tests read one database built for them all (``store``), on the worker that built it.
pytestmark = pytest.mark.xdist_group("article_versions")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _seed(store)
        cli("normalize", "bwb")
        cli("normalize", "bwb-history")
        cli(
            "normalize", "bwb-history"
        )  # a second run must not make old versions current
        yield store


def test_an_article_has_one_current_version_and_a_date_picks_its_text(
    api: Api,
) -> None:
    versions = api.get_json(f"/api/articles/{LAW}/7/history")["versions"]
    assert [(v["valid_from"], v["valid_until"], v["current"]) for v in versions] == [
        ("2018-12-21", "2025-01-01", False),
        ("2025-01-01", None, True),
    ]

    def text_on(date: str) -> str:
        body = api.get_json(f"/api/instruments/{LAW}/articles/at/{date}?limit=500")
        (article,) = [a for a in body["items"] if a["article_number"] == "7"]
        return article["text"]

    assert "voorafgaand verlof" in text_on("2020-01-01")
    assert "ooit verlof" in text_on("2026-01-01")

    toestanden = api.get_json(f"/api/instruments/{LAW}/versions")
    assert toestanden["total"] == 2
    assert [v["current"] for v in toestanden["items"]] == [True, False]


def test_every_article_version_is_current_only_when_nothing_follows_it(
    store: GraphStore,
) -> None:
    rows = list(
        store.query(
            "SELECT props -> 'current' AS current, "
            "coalesce(json_typeof(props -> 'valid_until'), 'null') = 'null' AS open "
            "FROM article_versions"
        )
    )
    assert rows and all(row["current"] == row["open"] for row in rows)
