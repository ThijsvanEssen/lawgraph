"""``semantic bwb-captions``: every article of a regulation keeps what it is about (its
caption), the deepest title of its breadcrumb only one division of the law has; the title of
the article names it, in the API and the server HTML alike."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND
from lawgraph.db import GraphStore
from tests.integration.seed import write_toestanden
from tests.optional import present

BW6 = "BWBR0005289"
BOEK = {
    "type": "boek",
    "label": "Boek 6",
    "title": "Algemeen gedeelte van het verbintenissenrecht",
}


def _article(number: str, *crumbs: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "key": f"{BW6.lower()}_{number}",
        "type": "article",
        "labels": [],
        "props": {
            "bwb_id": BW6,
            "article_number": number,
            "instrument_abbreviation": "BW6",
            "breadcrumb": [BOEK]
            + [
                {"type": t, "label": label, "title": title}
                for t, label, title in crumbs
            ],
        },
    }


def test_an_article_keeps_what_it_is_about(database: str, cli: Any) -> None:
    store = GraphStore()
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _article("162", ("titeldeel", "Titel 3", "Onrechtmatige daad"),
                     ("afdeling", "Afdeling 1", "Algemene bepalingen")),
            _article("1", ("titeldeel", "Titel 1", "Verbintenissen in het algemeen"),
                     ("afdeling", "Afdeling 1", "Algemene bepalingen")),
        ],
    )  # fmt: skip
    write_toestanden(
        store, [(RAW_KIND_BWB_TOESTAND, BW6, "<toestand/>", {"bwb_id": BW6})]
    )

    first = cli("semantic", "bwb-captions")
    again = cli("semantic", "bwb-captions")

    assert "2 changed" in first.stderr and "0 changed" in again.stderr
    caption = {
        key: (present(store.get_node("articles", key)).props.get("caption"))
        for key in ("bwbr0005289_162", "bwbr0005289_1")
    }
    assert caption == {
        "bwbr0005289_162": "Onrechtmatige daad",
        "bwbr0005289_1": "Verbintenissen in het algemeen",
    }
    app.dependency_overrides[get_store] = lambda: store
    try:
        body = TestClient(app).get("/api/nodes/articles/bwbr0005289_162").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert body["title"] == "Art. 6:162 BW, Onrechtmatige daad"
