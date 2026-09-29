"""Committees that share an abbreviation (G17): the Vaste commissie BuHaOS of 2017-2024 and
the Algemene commissie BuHaOS sitting now. Each has a slug of its own, its kind and period,
and one count of the open dossiers it leads, the same in list and detail and none for the
one that ended. The real ``normalize tk-dossiers`` and ``semantic graph-list-stats``.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_COMMITTEES,
    COLLECTION_DOSSIERS,
    RAW_KIND_TK_COMMISSIE,
    RELATION_ABOUT,
    RELATION_LED_BY,
    SOURCE_TK,
)
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db import (
    ArangoStore,
    EdgeWriter,
    NodeWriter,
    RawSourceWriter,
    raw_source_doc,
)
from tests.integration.seed import uid

VASTE, ALGEMENE = uid(1, 4), uid(2, 4)
COMMITTEES = [
    {
        "Id": VASTE,
        "Afkorting": "BuHaOS",
        "NaamNL": "Vaste commissie voor Buitenlandse Handel en Ontwikkelingssamenwerking",
        "Inhoudsopgave": "Vaste commissies",
        "DatumActief": "2017-11-09T00:00:00+01:00",
        "DatumInactief": "2024-07-02T00:00:00+02:00",
    },
    {
        "Id": ALGEMENE,
        "Afkorting": "BuHaOS",
        "NaamNL": "Algemene commissie voor Buitenlandse Handel en Ontwikkelingssamenwerking",
        "Inhoudsopgave": "Algemene commissies",
        "DatumActief": "2024-07-02T00:00:00+02:00",
        "DatumInactief": None,
    },
]


def _seed(store: ArangoStore) -> None:
    with RawSourceWriter(store) as writer:
        for payload in COMMITTEES:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_COMMISSIE,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )
    nodes = [
        Node(
            collection=COLLECTION_DOSSIERS,
            type=NodeType.DOSSIER,
            key=number,
            labels=["TK"],
            props={"number": number, "label": number, "closed": closed},
        )
        for number, closed in (("36000", False), ("36001", False), ("35000", True))
    ] + [
        Node(
            collection=COLLECTION_ACTIVITIES,
            type=NodeType.ACTIVITY,
            key=f"a{i}",
            labels=["TK"],
            props={"date": "2025-01-01"},
        )
        for i in range(4)
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)
    # three debates of the sitting committee on two open dossiers and a closed one; one of
    # the old committee on an open dossier
    led = [
        ("a0", ALGEMENE, "36000"),
        ("a1", ALGEMENE, "36000"),
        ("a2", ALGEMENE, "36001"),
        ("a2", ALGEMENE, "35000"),
        ("a3", VASTE, "36000"),
    ]
    with EdgeWriter(store, what=None) as edges:
        for activity, committee, dossier in led:
            activity_id = f"{COLLECTION_ACTIVITIES}/{activity}"
            edges.add(
                activity_id,
                f"{COLLECTION_COMMITTEES}/{make_node_key(committee)}",
                RELATION_LED_BY,
                source="t",
            )
            edges.add(
                activity_id,
                f"{COLLECTION_DOSSIERS}/{dossier}",
                RELATION_ABOUT,
                source="t",
            )


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def test_committees_that_share_an_abbreviation_are_each_reachable(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _seed(store)
    cli("normalize", "tk-dossiers")
    cli("semantic", "graph-list-stats")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = {c["slug"]: c for c in _get(client, "/api/committees")}
        sitting = _get(client, "/api/committees/buhaos")
        ended = _get(client, "/api/committees/buhaos-2017")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert set(listed) == {"buhaos", "buhaos-2017"}
    assert (
        sitting["name"],
        sitting["kind"],
        sitting["started_on"],
        sitting["ended_on"],
    ) == (
        COMMITTEES[1]["NaamNL"],
        "algemeen",
        "2024-07-02",
        None,
    )
    assert (ended["kind"], ended["ended_on"]) == ("vast", "2024-07-02")
    # two open dossiers, not three debates; the one that ended leads none
    assert (
        sitting["active_dossier_count"] == listed["buhaos"]["active_dossier_count"] == 2
    )
    assert (
        ended["active_dossier_count"]
        == listed["buhaos-2017"]["active_dossier_count"]
        == 0
    )
