"""What a dossier's law changes and implements, on the dossier detail (dossier 36931, 2026):
the laws its bill proposes to amend, what its Staatsblad enacted (an article rolled up to its
law), and the EU acts its publication and its act implement; never its own new act; in the
order its title names them."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_IMPLEMENTS,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
)
from lawgraph.db import GraphStore, make_edge_doc

TITLE = (
    "Wijziging van de Wet op het financieel toezicht, de Wet toezicht "
    "accountantsorganisaties en enkele andere wetten in verband met de implementatie van "
    "Richtlijn (EU) 2023/2864 en Verordening (EU) 2023/2869 betreffende het Europees "
    "centraal toegangspunt (Wet implementatie Europees centraal toegangspunt)"
)


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _act(key: str, name: str, **ids: Any) -> dict[str, Any]:
    return _node(key, "instrument", title=name, citation_title=name, **ids)


def test_the_dossier_says_what_its_law_changes_and_implements(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node("36931", "dossier", number="36931", label="36931", title=TITLE)],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("bill", "document", kind="Voorstel van wet", dossier_numbers=["36931"])],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _act(
                "bwbr0019079",
                "Wet toezicht accountantsorganisaties",
                bwb_id="BWBR0019079",
                short_title="Wta",
            ),
            _act(
                "bwbr0020368",
                "Wet op het financieel toezicht",
                bwb_id="BWBR0020368",
                short_title="Wft",
            ),
            _act(
                "bwbr0052854",
                "Wet implementatie Europees centraal toegangspunt",
                bwb_id="BWBR0052854",
            ),
            _act("32023r2869", "Verordening (EU) 2023/2869", celex="32023R2869"),
            _act("32023l2864", "Richtlijn (EU) 2023/2864", celex="32023L2864"),
            _node(
                "stb_2026_217",
                "instrument",
                title="Stb. 2026, 217",
                publication_kind="Stb",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                "bwbr0020368_1_1", "article", bwb_id="BWBR0020368", article_number="1:1"
            )
        ],
    )
    dossier = "dossiers/36931"
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc("documents/bill", dossier, RELATION_PART_OF, source="t"),
            # the bill proposes (its title names the EU act and its own act too)
            *(
                make_edge_doc(
                    "documents/bill",
                    f"instruments/{key}",
                    RELATION_AMENDS,
                    source="t",
                    status=EDGE_STATUS_VOORGESTELD,
                )
                for key in ("bwbr0020368", "bwbr0019079", "bwbr0052854")
            ),
            # the publication enacts and implements; the act implements
            make_edge_doc(
                "instruments/stb_2026_217", dossier, RELATION_LEGISLATED_IN, source="t"
            ),
            make_edge_doc(
                "instruments/bwbr0052854", dossier, RELATION_LEGISLATED_IN, source="t"
            ),
            make_edge_doc(
                "instruments/stb_2026_217",
                "articles/bwbr0020368_1_1",
                RELATION_AMENDS,
                source="t",
            ),
            make_edge_doc(
                "articles/bwbr0020368_1_1",
                "instruments/bwbr0020368",
                RELATION_PART_OF,
                source="t",
            ),
            make_edge_doc(
                "instruments/stb_2026_217",
                "instruments/32023l2864",
                RELATION_IMPLEMENTS,
                source="t",
            ),
            make_edge_doc(
                "instruments/bwbr0052854",
                "instruments/32023r2869",
                RELATION_IMPLEMENTS,
                source="t",
            ),
        ]
    )

    app.dependency_overrides[get_store] = lambda: store
    try:
        effect = TestClient(app).get("/api/dossiers/36931").json()["legal_effect"]
    finally:
        app.dependency_overrides.pop(get_store, None)

    # the order the title names them; the bill's own act is no law it amends
    assert [(a["short"], sorted(a["basis"])) for a in effect["amends"]] == [
        ("Wft", ["staatsblad", "voorstel"]),
        ("Wta", ["voorstel"]),
    ]
    assert effect["amends"][0]["name"] == "Wet op het financieel toezicht"
    assert [(i["celex"], i["basis"]) for i in effect["implements"]] == [
        ("32023L2864", ["staatsblad"]),
        ("32023R2869", ["wet"]),
    ]
    assert effect["implements"][0]["short"] is None
