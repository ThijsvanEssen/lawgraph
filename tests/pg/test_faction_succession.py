"""A faction whose seats all passed to a new one (``semantic tk-faction-succession``):
``CONTINUES`` from the new faction to the old, and the edge goes when the seats no longer
say so."""

from __future__ import annotations

from lawgraph.config.constants import RELATION_CONTINUES, RELATION_MEMBER_OF
from lawgraph.db import GraphStore, make_edge_doc
from lawgraph.pipelines.semantic.tk_faction_succession import (
    TKFactionSuccessionSemanticPipeline,
)


def _seat(member: str, faction: str, start: str, end: str | None):
    return make_edge_doc(
        f"members/{member}",
        f"factions/{faction}",
        RELATION_MEMBER_OF,
        source="t",
        meta={"from_date": start, "to_date": end, "role": "Lid"},
    )


def _continues(store: GraphStore) -> list[tuple[str, str, dict]]:
    return [
        (row["from_id"], row["to_id"], row["doc"]["meta"])
        for row in store.query(
            "SELECT from_id, to_id, doc FROM edges WHERE relation = %s"
            " AND source = 'tk-faction-succession' ORDER BY from_id, to_id",
            (RELATION_CONTINUES,),
        )
    ]


def test_the_new_faction_continues_the_one_whose_seats_it_took(
    store: GraphStore,
) -> None:
    seats = [
        _seat("a", "gl_pvda", "2023-10-27", "2026-06-09"),
        _seat("b", "gl_pvda", "2023-10-27", "2026-06-09"),
        _seat("a", "pro", "2026-06-10", None),
        _seat("b", "pro", "2026-06-10", None),
        # a faction of the Eerste Kamer has no period: nothing to read
        make_edge_doc(
            "members/e", "factions/ek_pro", RELATION_MEMBER_OF, source="t", meta={}
        ),
    ]
    store.bulk_insert_or_update_edges(seats)

    TKFactionSuccessionSemanticPipeline(store=store).run()

    assert _continues(store) == [
        (
            "factions/pro",
            "factions/gl_pvda",
            {
                "reason": "alle_zetels",
                "effective_date": "2026-06-10",
                "seats": 2,
            },
        )
    ]

    # derived in full: a seat of the old faction that now goes elsewhere ends the edge
    store.bulk_insert_or_update_edges([_seat("b", "other", "2026-06-10", None)])
    TKFactionSuccessionSemanticPipeline(store=store).run()
    assert _continues(store) == []
