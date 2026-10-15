"""Each linker derives its edges in full: after a run, an edge of its source that it no longer
derives is gone, and an edge of another source stays. Under ``--since`` only the nodes it read
lose theirs."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_EU_CELEX,
    RELATION_ACCOMPANIES,
    RELATION_ANSWERS,
    RELATION_BASED_ON,
    RELATION_CONTINUES,
    RELATION_EXPLAINS,
    RELATION_MADE_IN,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_RELATED_TO,
    RELATION_REVISES,
    RELATION_SCOPED_BY,
    RELATION_SECOND_READING_OF,
    SOURCE_EURLEX,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db import GraphStore, edge_key, raw_source_doc
from lawgraph.pipelines.semantic import (
    bwb,
    bwb_annexes,
    bwb_grondslagen,
    eerstekamer,
    eurlex,
    rechtspraak_referrals,
    staatsblad,
    staatscourant,
    tk_dossier_relations,
    tk_mvt,
)

OTHER_SOURCE = "another-step"
SINCE = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
RECENT = SINCE.date().isoformat()
LONG_AGO = "2001-01-01"


def _plant(store: GraphStore, source: str, *edges: tuple[str, str, str]) -> None:
    """Edges of *source* (``(from, relation, to)``) that no run derives."""
    store.bulk_insert_or_update_edges(
        [
            {
                "key": edge_key(from_id, relation, to_id),
                "from_id": from_id,
                "to_id": to_id,
                "relation": relation,
                "source": source,
            }
            for from_id, relation, to_id in edges
        ]
    )


def _edges(store: GraphStore) -> set[tuple[str, str, str, str]]:
    return {
        (row["from_id"], row["relation"], row["to_id"], row["source"])
        for row in store.query("SELECT from_id, relation, to_id, source FROM edges")
    }


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": "t", "labels": [], "props": props}


# ── the steps that always read everything ────────────────────────────────────

FULL = [
    (
        eerstekamer.EerstekamerSemanticPipeline,
        eerstekamer.SEMANTIC_SOURCE,
        [RELATION_PART_OF],
    ),
    (
        bwb_grondslagen.BWBGrondslagenSemanticPipeline,
        bwb_grondslagen.SEMANTIC_SOURCE,
        [RELATION_BASED_ON],
    ),
    (
        bwb_annexes.BWBAnnexesSemanticPipeline,
        bwb_annexes.SEMANTIC_SOURCE,
        [RELATION_SCOPED_BY],
    ),
    (
        rechtspraak_referrals.RechtspraakReferralsSemanticPipeline,
        rechtspraak_referrals.SEMANTIC_SOURCE,
        [RELATION_ANSWERS],
    ),
    (
        staatsblad.StaatsbladSemanticPipeline,
        staatsblad.SEMANTIC_SOURCE,
        [RELATION_EXPLAINS],
    ),
    (tk_mvt.TKMvtSemanticPipeline, tk_mvt.SEMANTIC_SOURCE, [RELATION_EXPLAINS]),
    (
        tk_dossier_relations.TKDossierRelationsSemanticPipeline,
        tk_dossier_relations.SEMANTIC_SOURCE,
        [
            RELATION_RELATED_TO,
            RELATION_REVISES,
            RELATION_ACCOMPANIES,
            RELATION_SECOND_READING_OF,
            RELATION_CONTINUES,
            RELATION_MADE_IN,
        ],
    ),
]


@pytest.mark.parametrize(
    ("pipeline", "source", "relations"),
    FULL,
    ids=[source for _, source, _ in FULL],
)
def test_a_run_removes_the_edges_of_its_step_it_no_longer_derives(
    store: GraphStore, pipeline: Any, source: str, relations: list[str]
) -> None:
    stale = [("documents/a", relation, "documents/b") for relation in relations]
    _plant(store, source, *stale)
    others = [("documents/a", relation, "documents/c") for relation in relations]
    _plant(store, OTHER_SOURCE, *others)

    pipeline(store=store).run()

    assert _edges(store) == {(*edge, OTHER_SOURCE) for edge in others}


def test_tk_mvt_leaves_the_edges_tk_mvt_articles_took_over(store: GraphStore) -> None:
    taken_over = ("documents/mvt", RELATION_EXPLAINS, "articles/a")
    _plant(store, tk_mvt.SEMANTIC_SOURCE_SECTIONS, taken_over)

    tk_mvt.TKMvtSemanticPipeline(store=store).run()

    assert _edges(store) == {(*taken_over, tk_mvt.SEMANTIC_SOURCE_SECTIONS)}


# ── the steps that read a window under --since ──────────────────────────────


def test_bwb_removes_the_edges_of_an_article_whose_references_are_gone(
    store: GraphStore,
) -> None:
    """A full run does not read an article without references, yet its edges go; a run under
    --since that read no regulation removes nothing."""
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                "bwbr1_1", bwb_id="BWBR1", article_number="1", text="Zonder verwijzing."
            )
        ],
    )
    stale = ("articles/bwbr1_1", RELATION_REFERS_TO, "articles/bwbr1_2")
    _plant(store, bwb.SEMANTIC_SOURCE, stale)

    bwb.BWBSemanticPipeline(store=store).run(since=SINCE)
    assert _edges(store) == {(*stale, bwb.SEMANTIC_SOURCE)}

    bwb.BWBSemanticPipeline(store=store).run()
    assert _edges(store) == set()


def test_eurlex_under_since_removes_only_from_the_articles_it_read(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("recent_1", celex="32020R0001", article_number="1", text="Geen."),
            _node("old_1", celex="31990R0001", article_number="1", text="Geen."),
        ],
    )
    store.insert_raw_sources(
        [
            raw_source_doc(
                source=SOURCE_EURLEX,
                kind=RAW_KIND_EU_CELEX,
                external_id="32020R0001",
                meta={"celex": "32020R0001"},
            )
        ]
    )
    recent = ("articles/recent_1", RELATION_REFERS_TO, "articles/x")
    old = ("articles/old_1", RELATION_REFERS_TO, "articles/x")
    _plant(store, eurlex.SEMANTIC_SOURCE, recent, old)

    eurlex.EurlexSemanticPipeline(store=store).run(since=SINCE)
    assert _edges(store) == {(*old, eurlex.SEMANTIC_SOURCE)}

    eurlex.EurlexSemanticPipeline(store=store).run()
    assert _edges(store) == set()


def test_staatscourant_under_since_removes_only_from_the_publications_it_read(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments", [_node("bwbr1", bwb_id="BWBR1", citation_title="Wet een")]
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node(
                "stcrt_new", source=SOURCE_STAATSCOURANT, date=RECENT, bwb_id="BWBR1"
            ),
            _node("stcrt_old", source=SOURCE_STAATSCOURANT, date=LONG_AGO),
        ],
    )
    derived = ("documents/stcrt_new", RELATION_EXPLAINS, "instruments/bwbr1")
    recent = ("documents/stcrt_new", RELATION_EXPLAINS, "instruments/bwbr2")
    old = ("documents/stcrt_old", RELATION_EXPLAINS, "instruments/bwbr1")
    _plant(store, staatscourant.SEMANTIC_SOURCE, recent, old)

    staatscourant.StaatscourantSemanticPipeline(store=store).run(since=SINCE)
    assert _edges(store) == {
        (*derived, staatscourant.SEMANTIC_SOURCE),
        (*old, staatscourant.SEMANTIC_SOURCE),
    }

    staatscourant.StaatscourantSemanticPipeline(store=store).run()
    assert _edges(store) == {(*derived, staatscourant.SEMANTIC_SOURCE)}
