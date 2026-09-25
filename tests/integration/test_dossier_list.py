"""Every dossier, open and closed: ``GET /api/dossiers`` with its filters, orders and facets,
and ``/open`` as the same list with ``status=open``."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.dossier_numbers import dossier_order
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, NodeWriter

TITLE = (
    "Wijziging van de Uitvoeringswet Algemene verordening gegevensbescherming "
    "(Verzamelwet gegevensbescherming)"
)


def _dossier(number: str, suffix: str, **props: Any) -> Node:
    label = f"{number}-{suffix}" if suffix else number
    return Node(
        collection=COLLECTION_DOSSIERS,
        type=NodeType.DOSSIER,
        key=label.lower().replace("-", "_"),
        labels=["TK"],
        props={
            "number": number,
            "suffix": suffix,
            "label": label,
            "order": dossier_order(number, suffix),
            **props,
        },
    )


DOSSIERS = [
    _dossier(
        "36264",
        "",
        title=TITLE,
        track_kind="wetsvoorstel",
        opened_on="2023-01-10",
        closed=True,
        closed_on="2026-06-26",
        outcome="aangenomen",
    ),
    _dossier(
        "37020", "", title="Miljoenennota", track_kind="nota", opened_on="2026-09-15"
    ),
    _dossier(
        "37020",
        "XV",
        title="Begroting SZW",
        track_kind="begroting",
        opened_on="2026-09-15",
    ),
    _dossier(
        "37020",
        "IIA",
        title="Begroting Staten-Generaal",
        track_kind="begroting",
        opened_on="2026-09-15",
    ),
    _dossier(
        "35000",
        "",
        title="Ingetrokken wet",
        track_kind="wetsvoorstel",
        opened_on="2018-01-01",
        closed=True,
        closed_on="2019-01-01",
        outcome="ingetrokken",
    ),
]


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_dossier_can_be_listed_found_and_ordered(database: str) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(DOSSIERS)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        everything = _get(client, "/api/dossiers")
        found = _get(client, "/api/dossiers", subject="verzamelwet gegevensbescherming")
        closed = _get(client, "/api/dossiers", status="closed", sort="closed_on")
        enacted = _get(client, "/api/dossiers", outcome="aangenomen")
        budget = _get(client, "/api/dossiers", number="37020")
        by_title = _get(client, "/api/dossiers", sort="title", limit=2)
        still_open = _get(client, "/api/dossiers/open")
        both_filters = _get(client, "/api/dossiers/open", status="closed")
        bad = client.get("/api/dossiers", params={"has_stage": "nope"}).status_code
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert everything["total"] == 5
    assert {f["value"]: f["count"] for f in everything["facets"]["status"]} == {
        "open": 3,
        "closed": 2,
    }
    assert [d["number"] for d in found["items"]] == ["36264"]
    assert found["items"][0]["short_title"] == "Verzamelwet gegevensbescherming"
    assert found["items"][0]["outcome"] == "aangenomen"
    assert [d["number"] for d in closed["items"]] == ["36264", "35000"]
    # the facet of a chosen dimension keeps its other values
    assert {f["value"]: f["count"] for f in closed["facets"]["status"]} == {
        "open": 3,
        "closed": 2,
    }
    assert [d["number"] for d in enacted["items"]] == ["36264"]
    # a number: that number and its chapters, in the order of the Kamer
    assert [d["number"] for d in budget["items"]] == ["37020", "37020-IIA", "37020-XV"]
    assert [d["title"] for d in by_title["items"]] == [
        "Begroting Staten-Generaal",
        "Begroting SZW",
    ]
    assert by_title["total"] == 5
    assert still_open["total"] == 3
    assert both_filters["total"] == 3  # /open is always open
    assert bad == 422
