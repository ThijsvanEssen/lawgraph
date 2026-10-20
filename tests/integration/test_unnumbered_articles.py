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

import pytest

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
)
from lawgraph.db import GraphStore
from lawgraph.db.schema import NODE_COLLECTIONS
from tests.asserts import show_items
from tests.databases import Api, module_store
from tests.integration.seed import write_toestanden

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


def _seed(store: GraphStore) -> None:
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
            for kind, external_id, xml, start, end in records
        ],
    )


# The tests read one database built for them all (``store``), on the worker that built it.
pytestmark = pytest.mark.xdist_group("unnumbered_articles")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests here, on a database of its own: they only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _seed(store)
        for _ in range(2):
            cli("normalize", "bwb")
            cli("normalize", "bwb-history")
        yield store


def test_an_article_with_only_a_heading_is_an_article_in_force(
    api: Api,
) -> None:
    listed = api.get_json(f"/api/instruments/{LAW}/articles")["items"]
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

    detail = api.get_json(f"/api/articles/{LAW}/{ADDRESS}")["article"]
    assert detail["key"] == "bwbr0001840_stam_16464063"
    assert detail["text"].startswith("De Grondwet waarborgt de grondrechten")
    assert detail["repealed"] is False
    assert detail["address"] == ADDRESS

    versions = api.get_json(f"/api/articles/{LAW}/{ADDRESS}/history")["versions"]
    assert [(v["label"], v["valid_from"]) for v in versions] == [
        ("Algemene bepaling", "2022-08-30")
    ]

    answer = api.get_json("/api/resolve", q="algemene bepaling Grondwet")
    assert answer["match"]["key"] == "bwbr0001840_stam_16464063"


def test_a_repealed_identity_is_listed_only_when_asked_for(api: Api) -> None:
    in_force = api.get_json(f"/api/instruments/{LAW}/articles")["items"]
    failing = [a for a in in_force if a["repealed"]]
    assert not failing, show_items(failing)
    assert {"Artikel 7", "Artikel 101"}.isdisjoint(a["label"] for a in in_force)

    everything = api.get_json(f"/api/instruments/{LAW}/articles?include_repealed=true")[
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
    assert api.get_json(f"/api/articles/{LAW}/7_stam_2990103")["article"]["repealed"]


def test_no_node_is_named_after_a_missing_number(store: GraphStore) -> None:
    for collection in NODE_COLLECTIONS:
        rows = list(
            store.query(
                f"SELECT key FROM {collection} "
                "WHERE strpos(props ->> 'display_name', 'None') > 0 "
                "OR props ->> 'last_article_number' = 'None' OR props ->> 'label' = 'None'"
            )
        )
        assert rows == [], collection
