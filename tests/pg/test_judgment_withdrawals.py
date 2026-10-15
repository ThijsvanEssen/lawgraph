"""A judgment the Rechtspraak withdrew leaves the graph, on a real PostgreSQL: ``normalize
rechtspraak`` makes of its withdrawal (an ``rs-content`` record with ``meta.withdrawn``) a
stub without its text, parties or edges of its own; what refers to it keeps a stub. A
judgment published again is whole again."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_RECHTSPRAAK_CONTENT,
    RELATION_REFERS_TO,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import GraphStore, edge_key, raw_source_doc
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from tests.paths import fixture_text

ECLI = "ECLI:NL:GHAMS:2026:2678"
ID = "judgments/ecli_nl_ghams_2026_2678"
CITING = "judgments/ecli_nl_hr_2026_1"
ARTICLE = "articles/bwbr0005289_6_162"


def _content(store: GraphStore, ecli: str, xml: str, **meta: Any) -> None:
    store.insert_raw_sources(
        [
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RECHTSPRAAK_CONTENT,
                external_id=ecli,
                payload_text=xml,
                meta={"ecli": ecli, "updated": None, **meta},
            )
        ]
    )


def _normalize(store: GraphStore) -> None:
    result = RechtspraakNormalizePipeline(store=store).run()
    assert result.errors == []


def _edges(store: GraphStore) -> set[tuple[str, str]]:
    rows = store.query("SELECT from_id, to_id FROM edges ORDER BY key")
    return {(row["from_id"], row["to_id"]) for row in rows}


def _loaded(store: GraphStore) -> None:
    """The judgment loaded whole, citing an article and cited by another judgment."""
    _content(store, ECLI, fixture_text("rechtspraak_ghams_2026_2678.xml"))
    _normalize(store)
    store.bulk_insert_or_update_edges(
        [
            {
                "key": edge_key(from_id, RELATION_REFERS_TO, to_id),
                "from_id": from_id,
                "to_id": to_id,
                "relation": RELATION_REFERS_TO,
                "source": "rechtspraak",
            }
            for from_id, to_id in ((ID, ARTICLE), (CITING, ID))
        ]
    )


def _props(store: GraphStore) -> dict[str, Any]:
    doc = store.get_document("judgments", ID.split("/")[1])
    assert doc is not None
    return dict(doc["props"])


def test_a_withdrawn_judgment_is_a_stub_without_its_text_or_edges(
    store: GraphStore,
) -> None:
    _loaded(store)
    assert _props(store).get("text")
    assert store.query(
        "SELECT 1 FROM lg_judgment_persons WHERE id = %(id)s", {"id": ID}
    )

    _content(store, ECLI, "", withdrawn="doc")
    _normalize(store)

    assert _props(store) == {"ecli": ECLI, "stub": True, "withdrawn": "doc"}
    # what it said goes; what refers to it keeps a stub
    assert _edges(store) == {(CITING, ID)}
    persons = "SELECT 1 FROM lg_judgment_persons WHERE id = %(id)s"
    assert list(store.query(persons, {"id": ID})) == []
    light = list(
        store.query("SELECT props FROM lg_judgment_light WHERE id = %(id)s", {"id": ID})
    )
    assert all(not row.get("summary") for row in light)


def test_a_withdrawal_of_a_judgment_not_in_the_graph_keeps_it_out_of_the_gaps(
    store: GraphStore,
) -> None:
    """A citation found later makes no stub of its own, which ``retrieve rechtspraak
    --mode gaps`` would fetch again: the withdrawal made one already."""
    _content(store, "ECLI:NL:RBZWB:2026:5617", "", withdrawn="doc")
    _normalize(store)
    store.ensure_stub_node(
        "judgments", "ecli_nl_hr_2026_9", props={"ecli": "ECLI:NL:HR:2026:9"}
    )
    assert list(gap_queries.stub_dutch_eclis(store)) == ["ECLI:NL:HR:2026:9"]


def test_a_judgment_published_again_is_whole_again(store: GraphStore) -> None:
    _loaded(store)
    _content(store, ECLI, "", withdrawn="doc")
    _normalize(store)

    _content(store, ECLI, fixture_text("rechtspraak_ghams_2026_2678.xml"))
    _normalize(store)

    props = _props(store)
    assert props.get("text") and props["stub"] is False
    assert props.get("withdrawn") is None
