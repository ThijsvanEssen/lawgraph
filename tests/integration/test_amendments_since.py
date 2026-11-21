"""``semantic bwb-amendments --since`` (the daily run) reads the article versions of the
regulations fetched since then and comes to what a run over all does: a run over all after it
changes nothing."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
from lawgraph.core.bwb_xml import article_version_key
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.semantic.bwb_amendments import (
    EDGE_SOURCE,
    BWBAmendmentsSemanticPipeline,
)

LAW, OTHER = "BWBR0000001", "BWBR0000002"


def _pub(number: str, *dossiers: str, year: int = 2019) -> dict[str, Any]:
    return {
        "id": f"stb-{year}-{number}",
        "kind": "Stb",
        "year": year,
        "number": number,
        "signed": f"{year}-01-15",
        "published": f"{year}-01-20",
        "dossiers": list(dossiers),
    }


def _version(
    bwb_id: str,
    stam_id: str,
    versie: str,
    origin: dict[str, Any],
    *,
    effect: str = "wijziging",
    valid_from: str = "2019-02-01",
    commencement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": article_version_key(bwb_id, stam_id, versie),
        "type": "article_version",
        "labels": [],
        "props": {
            "bwb_id": bwb_id,
            "stam_id": stam_id,
            "effect": effect,
            "valid_from": valid_from,
            "source_publication": origin["id"],
            "origin_publication": origin,
            "commencement_publication": commencement,
        },
    }


def _fetched(store: GraphStore, *bwb_ids: str, toestand: str = "2019") -> None:
    """The toestand of *bwb_ids* fetched now; changed (``changed_at``) when *toestand* is
    another than the one stored."""
    with RawSourceWriter(store) as writer:
        for bwb_id in bwb_ids:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=f"<toestand>{toestand}</toestand>",
                    meta={"bwb_id": bwb_id},
                )
            )


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            {"key": n, "type": "dossier", "labels": [], "props": {"number": n}}
            for n in ("35000", "36000", "36100")
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {"key": b, "type": "x", "labels": [], "props": {"bwb_id": b}}
            for b in (LAW, OTHER)
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "key": make_node_key(b, "art", s),
                "type": "article",
                "labels": [],
                "props": {"bwb_id": b, "stam_id": s},
            }
            for b in (LAW, OTHER)
            for s in ("1", "2")
        ],
    )
    # Stb. 2019, 10 amends both laws and is commenced by Stb. 2019, 11, in OTHER first
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _version(LAW, "1", "1", _pub("10", "35000"), commencement=_pub("11")),
            _version(LAW, "2", "1", _pub("12", "36000"), effect="nieuw"),
            _version(
                OTHER,
                "1",
                "1",
                _pub("10", "35000"),
                commencement=_pub("11"),
                valid_from="2019-01-01",
            ),
            _version(OTHER, "2", "1", _pub("13"), effect="vervallen"),
        ],
    )
    _fetched(store, LAW, OTHER)


def _derived(store: GraphStore) -> tuple[list[Any], list[Any]]:
    """What the step keeps: its edges (but when they were made) and the publications."""
    edges = store.query(
        """
        SELECT key, (doc::jsonb - 'created_at')::text FROM edges
        WHERE source = %(source)s ORDER BY key
        """,
        {"source": EDGE_SOURCE},
    )
    publications = store.query(
        "SELECT key, props::jsonb::text FROM instruments"
        " WHERE key LIKE 'stb%%' ORDER BY key"
    )
    return [tuple(r.values()) for r in edges], [tuple(r.values()) for r in publications]


def test_the_daily_run_comes_to_what_a_run_over_all_does(database: str) -> None:
    store = GraphStore()
    _seed(store)
    BWBAmendmentsSemanticPipeline(store).run()
    edges, _ = _derived(store)
    assert len(edges) > 5

    time.sleep(1.1)  # fetched_at has a precision of a second
    window = dt.datetime.now(dt.UTC).replace(microsecond=0)
    # a day: LAW fetched again, its article 1 amended by a new publication of a new
    # dossier, its article 2 now from another one, Stb. 2019, 10 named with another
    # dossier (OTHER, not read, names the first)
    store.execute("DELETE FROM article_versions WHERE bwb_id = %(b)s", {"b": LAW})
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _version(LAW, "1", "1", _pub("10", "36000"), commencement=_pub("11")),
            _version(
                LAW,
                "1",
                "2",
                _pub("20", "36100", year=2026),
                valid_from="2026-07-01",
                commencement=_pub("21", year=2026),
            ),
            _version(LAW, "2", "2", _pub("14", "36000", "36100"), effect="nieuw"),
        ],
    )
    _fetched(store, LAW, toestand="2026")

    result = BWBAmendmentsSemanticPipeline(store).run(since=window)
    assert result.created > 0
    daily = _derived(store)

    over_all = BWBAmendmentsSemanticPipeline(store).run()

    assert (over_all.created, over_all.updated) == (0, 0)
    assert _derived(store) == daily


def test_a_day_without_a_regulation_fetched_reads_nothing(database: str) -> None:
    store = GraphStore()
    _seed(store)
    BWBAmendmentsSemanticPipeline(store).run()
    time.sleep(1.1)

    result = BWBAmendmentsSemanticPipeline(store).run(
        since=dt.datetime.now(dt.UTC).replace(microsecond=0)
    )

    assert (result.created, result.updated, result.unchanged) == (0, 0, 0)
