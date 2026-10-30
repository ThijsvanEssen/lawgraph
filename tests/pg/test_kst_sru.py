"""The Kamerstukken of the Tweede Kamer of 1994-1995 to 2007-2008 from the KOOP SRU, on a real
PostgreSQL: documents of the Tweede Kamer numbered in their dossier (``normalize kst-sru``),
the dossiers no other source has written from them, the papers PART_OF them (``semantic
kst-sru``), a copy of a paper of the Tweede Kamer's API removed, and the papers in the work
list of ``retrieve tk-content``."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_KST_SRU, SOURCE_KST
from lawgraph.core.models import Node
from lawgraph.db import GraphStore, NodeWriter, raw_source_doc
from lawgraph.pipelines.normalize.kst_sru import KstSruNormalizePipeline
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.semantic.kst_sru import KstSruSemanticPipeline

DOSSIER = "Regels met betrekking tot de inlichtingen- en veiligheidsdiensten"


def _paper(identifier: str, title: str, dossier: str, date: str) -> dict[str, Any]:
    return raw_source_doc(
        source=SOURCE_KST,
        kind=RAW_KIND_KST_SRU,
        external_id=identifier,
        payload_json={
            "identifier": identifier,
            "title": f"Wet; {title}",
            "numbers": [identifier.rsplit("-", 1)[1]],
            "dossier_number": dossier,
            "dossier_numbers": [dossier],
            "dossier_title": DOSSIER,
            "session_year": "1997-1998",
            "date": date,
        },
    )


def _keys(store: GraphStore, statement: str) -> list[Any]:
    return [tuple(row.values()) for row in store.query(statement)]


def _get(store: GraphStore, path: str) -> dict[str, Any]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        return TestClient(app).get(path).json()
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_papers_of_the_sru_join_the_graph(store: GraphStore) -> None:
    # a paper of 2007-2008 the Tweede Kamer's API has too
    with NodeWriter(store) as writer:
        writer.add(
            Node(
                collection="documents",
                key="0b1c-tk-guid",
                labels=["TK"],
                props={
                    "source": "tk",
                    "external_id": "0b1c-tk-guid",
                    "dossier_number": "31200",
                    "sequence": 5,
                    "kind": "Brief regering",
                },
            )
        )
    store.insert_raw_sources(
        [
            _paper("kst-25877-1", "Voorstel van wet", "25877", "1998-02-07"),
            _paper("kst-25877-3", "Memorie van toelichting", "25877", "1998-02-18"),
            _paper("kst-31200-5", "Brief minister over iets", "31200", "2007-10-01"),
        ]
    )
    KstSruNormalizePipeline(store=store).run()
    KstSruSemanticPipeline(store).run()

    assert _keys(store, "SELECT key, source FROM documents ORDER BY key") == [
        ("0b1c-tk-guid", "tk"),
        ("kst_25877_1", "kst"),
        ("kst_25877_3", "kst"),
    ]
    (dossier,) = store.query("SELECT labels, props FROM dossiers WHERE key = '25877'")
    assert dossier["labels"] == ["TK"]
    assert (dossier["props"]["source"], dossier["props"]["title"]) == ("kst", DOSSIER)
    assert _keys(
        store,
        "SELECT from_id, to_id FROM edges WHERE relation = 'PART_OF' ORDER BY from_id",
    ) == [
        ("documents/kst_25877_1", "dossiers/25877"),
        ("documents/kst_25877_3", "dossiers/25877"),
    ]
    # retrieve tk-content fetches their XML
    work = {gap["identifier"]: gap["key"] for gap in _gaps.kamerstuk_gaps(store, [])}
    assert work["kst-25877-3"] == "kst_25877_3"

    page = _get(store, "/api/documents/kst_25877_3")
    assert page["source"] == "kst" and page["kind"] == "Memorie van toelichting"
    dossier_page = _get(store, "/api/dossiers/25877")
    assert dossier_page.get("source") == "kst", dossier_page
