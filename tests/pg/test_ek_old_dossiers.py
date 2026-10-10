"""The dossiers of the papers of the Eerste Kamer that the Tweede Kamer's data has no dossier
of (its OData begins about 2005), on a real PostgreSQL: written from the papers' own SRU
metadata (``normalize eerstekamer``), with ``source`` ``eerstekamer``, the papers then PART_OF
them (``semantic eerstekamer``); a dossier the Tweede Kamer has is not written; one it
delivers later takes the node over."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RAW_KIND_EK_KAMERSTUK, SOURCE_EERSTEKAMER
from lawgraph.core import tk_records
from lawgraph.core.models import Node, NodeType
from lawgraph.db import GraphStore, NodeWriter
from lawgraph.db.store import raw_source_doc
from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline
from lawgraph.pipelines.semantic.eerstekamer import EerstekamerSemanticPipeline


def _paper(identifier: str, number: str, title: str, date: str) -> dict[str, Any]:
    return raw_source_doc(
        source=SOURCE_EERSTEKAMER,
        kind=RAW_KIND_EK_KAMERSTUK,
        external_id=identifier,
        payload_json={
            "identifier": identifier,
            "kind": "Memorie van antwoord",
            "number": identifier[-1].upper(),
            "title": f"Stuk {identifier}",
            "dossier_number": number,
            "dossier_title": title,
            "date": date,
        },
    )


def _tk_dossier(number: str, title: str) -> Node:
    key, _, props = tk_records.dossier(
        {"Id": f"tk-{number}", "Nummer": int(number), "Titel": title}
    )  # type: ignore[misc]
    return Node(
        collection="dossiers",
        type=NodeType.DOSSIER,
        key=key,
        labels=["TK"],
        props=props,
    )


def _dossier(store: GraphStore, key: str) -> dict[str, Any]:
    (row,) = store.query(
        "SELECT labels, props FROM dossiers WHERE key = %(k)s", {"k": key}
    )
    return row


def _part_of(store: GraphStore) -> list[tuple[str, str]]:
    return [
        (r["from_id"], r["to_id"])
        for r in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'PART_OF'"
            " ORDER BY from_id, to_id"
        )
    ]


def test_a_dossier_of_the_papers_and_the_tweede_kamer_takes_it_over(
    store: GraphStore,
) -> None:
    with NodeWriter(store) as writer:
        writer.add(_tk_dossier("30300", "Begroting Justitie 2006 (de Kamer)"))
    store.insert_raw_sources(
        [
            _paper("kst-26200-a", "26200", "Begroting 1999", "1998-11-10"),
            _paper("kst-26200-b", "26200", "Begroting 1999", "1998-12-01"),
            # the newest names another title: the one most papers give wins
            _paper("kst-26200-c", "26200", "Begrotingsstaat 1999", "1999-01-12"),
            _paper("kst-30300-a", "30300", "Begroting 2006 (een stuk)", "2006-02-01"),
        ]
    )
    EerstekamerNormalizePipeline(store=store).run()
    EerstekamerSemanticPipeline(store).run()

    made = _dossier(store, "26200")
    assert made["props"]["source"] == "eerstekamer" and made["labels"] == ["EK"]
    assert made["props"]["title"] == "Begroting 1999"
    assert (made["props"]["number"], made["props"]["label"]) == ("26200", "26200")
    assert "kind" not in made["props"] and "phases" not in made["props"]
    # the Tweede Kamer's dossier is not written by the papers
    kept = _dossier(store, "30300")["props"]
    assert (kept["source"], kept["title"]) == (
        "tk",
        "Begroting Justitie 2006 (de Kamer)",
    )
    assert _part_of(store) == [
        ("documents/ek_kst_26200_a", "dossiers/26200"),
        ("documents/ek_kst_26200_b", "dossiers/26200"),
        ("documents/ek_kst_26200_c", "dossiers/26200"),
        ("documents/ek_kst_30300_a", "dossiers/30300"),
    ]

    # the dossier page says where it comes from
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    app.dependency_overrides[get_store] = lambda: store
    try:
        page = TestClient(app).get("/api/dossiers/26200").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert (page["source"], page["title_source"], page["title"]) == (
        "eerstekamer",
        "eerstekamer",
        "Begroting 1999",
    )
    assert page["kind"] is None and not page["phases"]

    # the Tweede Kamer delivers the dossier later: it takes the node over, the papers stay
    with NodeWriter(store) as writer:
        writer.add(_tk_dossier("26200", "Vaststelling begroting 1999"))
    taken = _dossier(store, "26200")["props"]
    assert (taken["source"], taken["title"]) == ("tk", "Vaststelling begroting 1999")
    assert taken["external_id"] == "tk-26200"
    # a run of the papers again does not write it back
    EerstekamerNormalizePipeline(store=store).run()
    assert _dossier(store, "26200")["props"]["source"] == "tk"
    assert len(_part_of(store)) == 4
