"""The light tables kept by their triggers alone, on a real PostgreSQL: after writes of every
kind (a node, an edge before its node, a node or edge written again, one deleted)
``semantic graph-light`` finds no row to add, and ``--all`` keeps the same rows. That is why
the daily run leaves it out (``semantic all --since``) and the weekly run keeps it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_VOTED,
)
from lawgraph.db import GraphStore, schema
from lawgraph.pipelines.semantic import graph_light
from lawgraph.pipelines.semantic.graph_light import GraphLightSemanticPipeline
from tests.pg.committee_graph import Graph, write_votes

# The table each fill of ``graph-light`` keeps.
TABLES = {
    "judgment-light": "lg_judgment_light",
    "document-light": "lg_document_light",
    "instrument-names": "lg_instrument_names",
    "faction-votes": "lg_faction_votes",
    "authored": "lg_authored",
    "led": "lg_led",
    "judgment-persons": "lg_judgment_persons",
    "cited-by": schema.CITED_BY_TABLE,
}
ARTICLE = "articles/bwbr0005289_6_162"
# The parties of a judgment, each with the person who stood for it.
PARTIES = [
    {"name": name, "role": role, "roles": [role], "role_stated": True, "side": side,
     "alias": None, "representatives": [{"name": person, "role": as_, "place": None,
                                         "capacity": None}]}
    for name, role, side, person, as_ in (
        ("[appellant]", "Appellant", "first", "mr. P. van Gelder", "advocaat"),
        ("het college", "Verweerder", "second", "mr. I. Vermeulen", "gemachtigde"),
    )
]  # fmt: skip


def _mentions(*leden: str) -> list[dict[str, Any]]:
    return [
        {"leden": [lid], "snippet": "…", "raw_match": "art. 6:162 BW", "start": 0,
         "end": 13, "paragraph_id": "p1", "confidence": 1.0}
        for lid in leden
    ]  # fmt: skip


def _rows(store: GraphStore) -> dict[str, list[str]]:
    return {
        table: list(
            store.query(f"SELECT to_jsonb(t)::text AS row FROM {table} t ORDER BY 1")
        )
        for table in TABLES.values()
    }


def _first_writes(g: Graph) -> None:
    g.node(
        "judgments",
        "j1",
        ecli="ECLI:NL:HR:2020:1",
        date_eff="2020-01-01",
        tier="hoge_raad",
        parties=PARTIES,
        summary="Onrechtmatige daad.",
    )
    g.node(
        "judgments",
        "j2",
        ecli="ECLI:NL:HR:2021:2",
        date_eff="2021-01-01",
        tier="hoge_raad",
    )
    # a citation written before its judgment
    g.edge("judgments/j3", RELATION_REFERS_TO, ARTICLE, mentions=_mentions("1"))
    g.edge("judgments/j1", RELATION_REFERS_TO, ARTICLE, mentions=_mentions("2"))
    g.node(
        "instruments",
        "bwbr0005289",
        bwb_id="BWBR0005289",
        citation_title="Burgerlijk Wetboek Boek 6",
        short_title="BW6",
    )
    g.node(
        "documents",
        "doc1",
        title="Motie",
        kind="Motie",
        date="2025-01-02",
        dossier_numbers=["36000"],
        text="De hele tekst.",
    )
    g.node("documents", "doc2", title="Brief", kind="Brief", date="2025-01-03")
    g.node("members", "m2", name="Bram")
    g.edge(
        "members/m2", RELATION_AUTHORED, "documents/doc1", role="Eerste ondertekenaar"
    )
    g.edge("documents/doc1", RELATION_PART_OF, "dossiers/d1")
    g.node("committees", "c1", name="Financiën", slug="fin")
    g.node("activities", "a1", date="2024-01-01")
    g.node("cases", "k1", started_on="2023-05-05")
    g.edge("activities/a1", RELATION_LED_BY, "committees/c1")
    g.edge("activities/a2", RELATION_LED_BY, "committees/c1")  # before its activity
    g.edge("cases/k1", RELATION_LED_BY, "committees/c1")
    g.edge("activities/a1", RELATION_ABOUT, "dossiers/d1")
    g.write()  # fmt: skip


def _second_writes(g: Graph) -> None:
    g.node(
        "judgments",
        "j1",
        ecli="ECLI:NL:HR:2020:1",
        date_eff="2020-02-02",
        tier="hoge_raad",
        parties=PARTIES[:1],
        summary="Anders.",
    )
    g.node(
        "judgments",
        "j3",
        ecli="ECLI:NL:RBAMS:2022:3",
        date_eff="2022-03-03",
        tier="rechtbank",
    )
    g.edge("judgments/j1", RELATION_REFERS_TO, ARTICLE, mentions=_mentions("2", "3"))
    g.node(
        "documents",
        "doc1",
        title="Motie",
        kind="Motie",
        date="2025-01-05",
        dossier_numbers=["36000", "36001"],
        text="Een andere tekst.",
    )
    g.node(
        "instruments",
        "bwbr0005289",
        bwb_id="BWBR0005289",
        citation_title="Burgerlijk Wetboek Boek 6",
        short_title="BW 6",
    )
    g.node("decisions", "s1", date="2024-01-05")
    g.edge("factions/vvd", RELATION_VOTED, "decisions/s9", choice="Voor")  # no decision
    g.node("activities", "a2", date="2024-02-02")
    g.node("activities", "a1", date="2024-03-03")
    g.edge("cases/k1", RELATION_PART_OF, "dossiers/d2")
    g.edge("documents/doc2", RELATION_PART_OF, "cases/k1")
    g.edge("members/m2", RELATION_AUTHORED, "documents/doc2", role="Mede ondertekenaar")
    g.write()  # fmt: skip


def _written(store: GraphStore) -> None:
    write_votes(store)
    g = Graph(store)
    _first_writes(g)
    _second_writes(g)
    store.execute("DELETE FROM judgments WHERE id = 'judgments/j2'")
    store.execute("DELETE FROM decisions WHERE id = 'decisions/s2'")
    store.execute("DELETE FROM edges WHERE from_id = 'activities/a1'"
                  " AND to_id = 'dossiers/d1'")  # fmt: skip


def test_the_triggers_leave_graph_light_nothing_to_do(store: GraphStore) -> None:
    """What the daily run would find: no row to add, none changed; also after a paper
    with signatures is deleted."""
    _written(store)
    store.execute("DELETE FROM documents WHERE id = 'documents/doc2'")
    kept = _rows(store)
    assert set(TABLES) == {fill.name for fill in graph_light._FILLS}
    assert [table for table, rows in kept.items() if not rows] == []

    assert GraphLightSemanticPipeline(store=store).run().updated == 0
    assert _rows(store) == kept


def test_every_row_again_is_the_row_the_triggers_kept(store: GraphStore) -> None:
    """``--all`` keeps what the triggers kept. Not after a paper is deleted: its signatures
    keep its date until ``--all`` (the date follows a write of the paper, not its delete)."""
    _written(store)
    kept = _rows(store)

    assert GraphLightSemanticPipeline(store=store, every=True).run().updated > 0
    assert _rows(store) == kept
