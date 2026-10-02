"""The page of a bill of the Eerste Kamer onto its dossier, on a real database: what the
page gives, in the dossier's ``senate``; a bill whose dossier the graph lacks is passed over."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_EK_BILL, SOURCE_EERSTEKAMER
from lawgraph.config.settings import EK_ATTRIBUTION
from lawgraph.core.models import Node, NodeType
from lawgraph.db import GraphStore, NodeWriter, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PATH = "/wetsvoorstel/36791_wet_toekomstbestendige"


def test_a_bill_page_tells_its_dossier_where_the_bill_is(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    with NodeWriter(store) as writer:
        writer.add(
            Node(
                collection="dossiers",
                type=NodeType.DOSSIER,
                key="36791",
                labels=["TK"],
                props={"number": "36791", "label": "36791", "title": "Huurcommissie"},
            )
        )
    with RawSourceWriter(store) as writer:
        for path, name, status in (
            (PATH, "ek_bill_36791.html", "Plenaire behandeling Eerste Kamer afgerond"),
            # its dossier is not in the graph
            (
                "/wetsvoorstel/36879_x",
                "ek_bill_36879.html",
                "In schriftelijke voorbereiding",
            ),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_EERSTEKAMER,
                    kind=RAW_KIND_EK_BILL,
                    external_id=path,
                    payload_text=(FIXTURES / name).read_text(),
                    meta={
                        "url": f"https://www.eerstekamer.nl{path}",
                        "read_on": "2026-10-03",
                        "status": status,
                    },
                )
            )
    cli("normalize", "eerstekamer-bills")

    assert store.get_document("dossiers", "36879") is None
    bill = store.get_document("dossiers", "36791")["props"]["ek_bill"]
    assert (bill["submitted_on"], bill["read_on"]) == ("2025-08-15", "2026-10-03")

    app.dependency_overrides[get_store] = lambda: store
    try:
        senate = TestClient(app).get("/api/dossiers/36791").json()["senate"]
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert senate["submitted_on"] == "2025-08-15"
    assert senate["status"] == "Plenaire behandeling Eerste Kamer afgerond"
    assert [s["state"] for s in senate["progress"]] == ["vol", "vol", "vol", "geblokt"]
    paper = senate["progress"][1]["papers"][1]
    assert (paper["kind"], paper["number"]) == ("verslag", "EK, B")
    assert paper["url"].startswith("https://www.eerstekamer.nl/")
    assert senate["source"] == {
        "url": f"https://www.eerstekamer.nl{PATH}",
        "read_on": "2026-10-03",
        "attribution": EK_ATTRIBUTION,
    }
