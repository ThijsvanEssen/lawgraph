"""The dictum of a motion: kept by ``semantic tk-dictum``, light, and shown with its vote."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from lawgraph.pipelines.semantic import tk_dictum

MOTION_TEXT = """MOTIE VAN HET LID TEUNISSEN
De Kamer,
gehoord de beraadslaging,
overwegende dat de klimaatschade op de toekomstige generaties wordt afgewenteld;
verzoekt de regering de kosten van deze klimaatschade inzichtelijk te maken,
en gaat over tot de orde van de dag.
Teunissen"""


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _graph(store: GraphStore) -> None:
    """A motion with text and the vote on it; a letter with text; a motion without."""
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node(
                "motie", "document", kind="Motie", date="2026-09-01", text=MOTION_TEXT
            ),
            _node(
                "brief",
                "document",
                kind="Brief regering",
                date="2026-09-01",
                text="Geachte voorzitter,\nverzoekt u …\nHoogachtend,",
            ),
            _node("kaal", "document", kind="Motie", date="2026-09-02"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "cases", [_node("z_m", "case", external_id="Z-M", kind="Motie")]
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(
                "s_motie",
                "decision",
                date="2026-09-08",
                dossier_numbers=["36800"],
                subject="Motie Teunissen",
                primary_case_id="Z-M",
                primary_case_kind="Motie",
                passed=False,
            ),
            _node(
                "s_wet",
                "decision",
                date="2026-09-08",
                dossier_numbers=["36800"],
                subject="Wet",
                primary_case_kind="Wetgeving",
                passed=True,
            ),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            {
                "_key": "p",
                "_from": "documents/motie",
                "_to": "cases/z_m",
                "relation": "PART_OF",
                "source": "test",
            },
            {
                "_key": "a",
                "_from": "decisions/s_motie",
                "_to": "cases/z_m",
                "relation": "ABOUT",
                "source": "test",
            },
        ]
    )


def test_a_motion_keeps_its_dictum_and_its_vote_shows_it(store: GraphStore) -> None:
    _graph(store)
    dictum = (
        "verzoekt de regering de kosten van deze klimaatschade inzichtelijk te maken"
    )

    assert tk_dictum.run(store) == 1  # the one motion with text
    props = {
        key: store.get_document("documents", key)["props"].get("dictum")
        for key in ("motie", "brief", "kaal")
    }
    assert props == {"motie": dictum, "brief": None, "kaal": None}
    # light, through the trigger on documents: the list of votes reads it there
    light = next(
        store.query(
            "SELECT props -> 'dictum' FROM lg_document_light WHERE id = 'documents/motie'"
        )
    )
    assert light == dictum

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        items = {i["key"]: i for i in client.get("/api/decisions").json()["items"]}
        assert items["s_motie"]["dictum"] == dictum
        assert items["s_wet"]["dictum"] is None
        assert client.get("/api/decisions/s_motie").json()["dictum"] == dictum
        assert client.get("/api/documents/motie").json()["dictum"] == dictum
    finally:
        app.dependency_overrides.pop(get_store, None)
