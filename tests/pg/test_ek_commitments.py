"""The commitments of the Eerste Kamer on a real PostgreSQL: the pages normalized beside those
of the Tweede Kamer (``normalize eerstekamer-commitments``), who made them
(``semantic eerstekamer-government``), and ``/api/commitments`` with its ``chamber``."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_EERSTEKAMER_COMMITMENT,
    SOURCE_EERSTEKAMER,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.normalize.eerstekamer_commitments import (
    EerstekamerCommitmentsNormalizePipeline,
)
from lawgraph.pipelines.semantic.eerstekamer_government import (
    EerstekamerGovernmentSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_government import TKGovernmentSemanticPipeline
from tests.optional import present
from tests.paths import fixture_text

SZW = "/toezegging/uitzondering_pgb_sector_voor_2030"
BZK = "/toezegging/betekenis_civil_society"


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": [], "props": props}


def _store(store: GraphStore) -> None:
    """Two pages; dossier 36746 stored (28831 not); Vijlbrief minister of SZW since the
    cabinet Jetten; a commitment of the Tweede Kamer beside them."""
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("36746", "dossier", label="36746", number="36746")]
    )
    store.bulk_insert_or_update_nodes(
        "cabinets", [_node("jetten", "cabinet", from_date="2026-02-23")]
    )
    post = {
        "function": "minister van Sociale Zaken en Werkgelegenheid",
        "ministry": "szw",
        "seat": "minister van Sociale Zaken en Werkgelegenheid",
        "cabinet_key": "jetten",
        "from_date": "2026-02-23",
    }
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node(
                "vijlbrief",
                "member",
                name="Steven Vijlbrief",
                government_name="S.P.R.A. Vijlbrief",
                government_functions=[post],
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "commitments",
        [
            {
                "key": "tk_1",
                "type": "commitment",
                "labels": ["TK"],
                "props": {
                    "text": "Een brief.",
                    "status": "Openstaand",
                    "number": "TZ202601-1",
                },
            }
        ],
    )
    with RawSourceWriter(store) as writer:
        for path, fixture in (
            (SZW, "ek_commitment_t04275.html"),
            (BZK, "ek_commitment_t00012.html"),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_EERSTEKAMER,
                    kind=RAW_KIND_EERSTEKAMER_COMMITMENT,
                    external_id=path,
                    payload_text=fixture_text(fixture, sub="eerstekamer"),
                    meta={
                        "url": "https://www.eerstekamer.nl" + path,
                        "read_on": "2026-11-07",
                    },
                )
            )


def test_the_commitments_of_the_eerste_kamer_beside_those_of_the_tweede(
    store: GraphStore,
) -> None:
    _store(store)
    EerstekamerCommitmentsNormalizePipeline(store=store).run()
    EerstekamerGovernmentSemanticPipeline(store=store).run()
    # the step of the Tweede Kamer leaves those of the Eerste Kamer alone
    TKGovernmentSemanticPipeline(store=store).run()

    szw = present(store.get_document("commitments", "ek_t04275"))
    assert {"EK", "EersteKamer"} <= set(szw["labels"])
    props = szw["props"]
    assert (props["number"], props["status"], props["made_on"]) == (
        "T04275",
        "Openstaand",
        "2026-07-07",
    )
    assert (props["member_key"], props["ministry"], props["cabinet"]) == (
        "vijlbrief",
        "szw",
        "jetten",
    )
    assert props["member_missing"] is None

    bzk = present(store.get_document("commitments", "ek_t00012"))["props"]
    # De Graaf held no post this graph knows: a gap, with why
    assert bzk["member_key"] is None
    assert bzk["member_missing"] == "unmatched"

    about = set(
        store.query(
            "SELECT from_id || ' ' || to_id || ' ' || (doc -> 'meta' ->> 'basis')"
            " FROM edges WHERE relation = 'ABOUT' AND from_collection = 'commitments'"
        )
    )
    # 28831 is not in the graph: no edge
    assert about == {"commitments/ek_t04275 dossiers/36746 kamerstukken"}
    authored = set(
        store.query(
            "SELECT from_id || ' ' || to_id FROM edges"
            " WHERE relation = 'AUTHORED' AND to_collection = 'commitments'"
        )
    )
    assert authored == {"members/vijlbrief commitments/ek_t04275"}

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = client.get("/api/commitments", params={"chamber": "EK"}).json()
        assert listed["total"] == 2
        assert {f["value"]: f["count"] for f in listed["facets"]["chamber"]} == {
            "EK": 2,
            "TK": 1,
        }
        one = client.get("/api/commitments/ek_t04275").json()
        assert one["chamber"] == "EK"
        assert one["number"] == "T04275"
        assert one["minister_role"] == "Minister van Sociale Zaken en Werkgelegenheid"
        assert one["member"]["key"] == "vijlbrief"
        assert one["source"]["url"] == "https://www.eerstekamer.nl" + SZW
        assert one["source"]["retrieved_on"] == "2026-11-07"
        assert [(d["number"], d["basis"]) for d in one["dossiers"]] == [
            ("36746", "kamerstukken")
        ]
        tk = client.get("/api/commitments/tk_1").json()
        assert (tk["chamber"], tk["source"]) == ("TK", None)
        # an open one of either chamber under one status
        both = client.get("/api/commitments", params={"status": "Openstaand"}).json()
        assert both["total"] == 2
    finally:
        app.dependency_overrides.pop(get_store, None)
