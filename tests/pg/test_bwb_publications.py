"""``semantic bwb-publications`` on a real PostgreSQL: a paper of the Staatsblad or the
Staatscourant ``SAME_AS`` the publication of the BWB of the same official id, by the keys
alone; none for a paper whose publication the BWB does not name, nor to an instrument that is
no publication; derived in full, so one no longer derived goes."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.pipelines.semantic.bwb_publications import (
    SEMANTIC_SOURCE,
    BWBPublicationsSemanticPipeline,
)


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": [], "props": props}


def _same_as(store: GraphStore) -> list[tuple[str, str]]:
    return [
        (r["from_id"], r["to_id"])
        for r in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'SAME_AS' AND source = %(s)s"
            " ORDER BY from_id",
            {"s": SEMANTIC_SOURCE},
        )
    ]


def test_a_paper_is_the_publication_of_its_official_id(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("stb_stb_2019_33", source="staatsblad", identifier="stb-2019-33"),
            _node("stcrt_stcrt_2020_12345", source="staatscourant",
                  identifier="stcrt-2020-12345"),
            # no publication of the BWB of its id
            _node("stcrt_stcrt_2020_9", source="staatscourant", identifier="stcrt-2020-9"),
            # an instrument of its id that is no publication
            _node("stb_stb_2018_1", source="staatsblad", identifier="stb-2018-1"),
            # a paper of another source with a key of that shape
            _node("stb_stb_2017_5", source="tk", identifier="stb-2017-5"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("stb_2019_33", kind="publicatie", official_id="stb-2019-33"),
            _node(
                "stcrt_2020_12345", kind="publicatie", official_id="stcrt-2020-12345"
            ),
            _node("stb_2018_1", kind="wet"),
            _node("stb_2017_5", kind="publicatie"),
        ],
    )
    BWBPublicationsSemanticPipeline(store).run()
    assert _same_as(store) == [
        ("documents/stb_stb_2019_33", "instruments/stb_2019_33"),
        ("documents/stcrt_stcrt_2020_12345", "instruments/stcrt_2020_12345"),
    ]
    (edge,) = store.query(
        "SELECT confidence, doc -> 'meta' ->> 'basis' AS basis FROM edges"
        " WHERE relation = 'SAME_AS' AND from_id = 'documents/stb_stb_2019_33'"
    )
    assert (edge["confidence"], edge["basis"]) == (1.0, "official_id")

    # derived in full: an edge whose publication went is removed, the others stay
    store.execute("DELETE FROM instruments WHERE id = 'instruments/stb_2019_33'")
    BWBPublicationsSemanticPipeline(store).run()
    assert _same_as(store) == [
        ("documents/stcrt_stcrt_2020_12345", "instruments/stcrt_2020_12345")
    ]
