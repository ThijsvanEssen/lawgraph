"""Every paged list gives each row once when its pages are walked, also where many rows
share the value it sorts on (140 decisions on one day)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_MEMBERS,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, NodeWriter

ROWS = 60


def _nodes() -> list[Node]:
    return [
        *(
            Node(
                collection=collection,
                type=node_type,
                key=f"{node_type.value}_{i:03d}",
                labels=["TK"],
                props=props,
            )
            for i in range(ROWS)
            for collection, node_type, props in (
                (
                    COLLECTION_DECISIONS,
                    NodeType.DECISION,
                    {"subject": "Motie", "date": "2026-09-22", "dossier_numbers": []},
                ),
                (
                    COLLECTION_DOCUMENTS,
                    NodeType.DOCUMENT,
                    {"title": "Brief", "date": "2026-09-22"},
                ),
                (
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    {"label": str(37000 + ROWS), "opened_on": "2026-09-22"},
                ),
                (COLLECTION_MEMBERS, NodeType.MEMBER, {"name": "Jansen"}),
            )
        )
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/api/decisions",
        "/api/documents",
        "/api/dossiers/open",
        "/api/members?include_all=true",
    ],
)
def test_walking_the_pages_finds_every_row_once(database: str, path: str) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(_nodes())
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        seen: list[Any] = []
        for offset in range(0, ROWS, 7):
            separator = "&" if "?" in path else "?"
            body = client.get(f"{path}{separator}limit=7&offset={offset}").json()
            rows = body["items"] if isinstance(body, dict) else body
            seen += [row.get("key") or row.get("id") for row in rows]
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert len(seen) == ROWS
    assert len(set(seen)) == ROWS
