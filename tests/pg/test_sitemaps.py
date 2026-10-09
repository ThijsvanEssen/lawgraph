"""The sitemaps of Concordans on a real PostgreSQL (``lawgraph sitemaps``): per kind of
page the readable addresses, with the day each last changed; what has no page, or is
too old, left out."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph.api.seo import shell
from lawgraph.commands import sitemaps as command
from lawgraph.config import settings
from lawgraph.db import GraphStore
from lawgraph.db.queries import sitemaps as queries


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": ["TK"], "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {"_key": key, "_from": source, "_to": target, "relation": relation,
            "source": "test", "meta": {}}  # fmt: skip


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0005289", "instrument", bwb_id="BWBR0005289", kind="wet"),
            _node("bwbr0001854", "instrument", bwb_id="BWBR0001854", kind="wet"),
            _node("bwbr0099999", "instrument", bwb_id="BWBR0099999", stub=True),
            _node("stb_2026_94", "instrument", official_id="stb-2026-94"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [
            _node("v_old", "version", bwb_id="BWBR0005289", valid_from="2020-01-01",
                  current=False),
            _node("v_now", "version", bwb_id="BWBR0005289", valid_from="2025-07-01",
                  current=True),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbr0005289_163", "article", bwb_id="BWBR0005289",
                  article_number="163", position=163, inbound_citation_count=5),
            _node("bwbr0005289_162", "article", bwb_id="BWBR0005289",
                  article_number="162", position=162, inbound_citation_count=900),
            _node("bwbr0005289_164", "article", bwb_id="BWBR0005289",
                  article_number="164", position=164, repealed=True),
            _node("bwbr0001854_1", "article", bwb_id="BWBR0001854",
                  article_number="1", position=1, inbound_citation_count=10),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("kst_36496_71", "document", kind="Motie", dossier_number="36496",
                  sequence=71),
            _node("kst_36600_viii_12", "document", kind="Amendement",
                  dossier_number="36600", dossier_suffix="VIII", sequence=12),
            _node("kst_30000_5", "document", kind="Motie", dossier_number="30000",
                  sequence=5),
            _node("kst_36496_72", "document", kind="Motie", dossier_number="36496",
                  sequence=72),
            _node("kst_36496_73", "document", kind="Motie", dossier_number="36496",
                  sequence=73),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cases",
        [_node(f"z_{n}", "case") for n in range(1, 6)],
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node("s_1", "decision", date="2026-09-08", passed=True),
            _node("s_1b", "decision", date="2026-09-15", passed=False),
            _node("s_2", "decision", date="2025-03-01", passed=True),
            _node("s_3", "decision", date="2016-05-01", passed=False),
            # withdrawn: a decision without an outcome, no vote
            _node(
                "s_5",
                "decision",
                date="2026-09-20",
                decision_kind="Stemmen - ingetrokken",
            ),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("p1", "documents/kst_36496_71", "cases/z_1", "PART_OF"),
            _edge("a1", "decisions/s_1", "cases/z_1", "ABOUT"),
            _edge("a1b", "decisions/s_1b", "cases/z_1", "ABOUT"),
            _edge("p2", "documents/kst_36600_viii_12", "cases/z_2", "PART_OF"),
            _edge("a2", "decisions/s_2", "cases/z_2", "ABOUT"),
            # decided before 2018
            _edge("p3", "documents/kst_30000_5", "cases/z_3", "PART_OF"),
            _edge("a3", "decisions/s_3", "cases/z_3", "ABOUT"),
            # never decided: kst_36496_72 is PART_OF a case without a decision
            _edge("p4", "documents/kst_36496_72", "cases/z_4", "PART_OF"),
            # withdrawn, never voted on
            _edge("p5", "documents/kst_36496_73", "cases/z_5", "PART_OF"),
            _edge("a5", "decisions/s_5", "cases/z_5", "ABOUT"),
        ]
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("36600_viii", "dossier", number="36600-VIII", label="36600-VIII",
                  last_activity="2026-09-30"),
            _node("36496", "dossier", number="36496"),
        ],
    )  # fmt: skip


def _paths(kinds: dict[str, Any], kind: str) -> list[tuple[str, str | None]]:
    return [(e.path, e.lastmod) for e in kinds[kind]]


def test_each_kind_by_its_readable_address(store: GraphStore) -> None:
    _seed(store)
    kinds = command.kinds(store)
    # no stub, no publication; the day of the version in force
    assert _paths(kinds, "wetten") == [
        ("/wetten/BWBR0001854", None),
        ("/wetten/BWBR0005289", "2025-07-01"),
    ]
    # per law in its order; a repealed article left out
    assert _paths(kinds, "artikelen") == [
        ("/wetten/BWBR0001854/artikel/1", None),
        ("/wetten/BWBR0005289/artikel/6:162", "2025-07-01"),
        ("/wetten/BWBR0005289/artikel/6:163", "2025-07-01"),
    ]
    # voted on since 2018, on the last day; one withdrawn is no page of a vote
    assert _paths(kinds, "moties") == [("/kamerstukken/36496/71", "2026-09-15")]
    assert _paths(kinds, "amendementen") == [
        ("/kamerstukken/36600-VIII/12", "2025-03-01")
    ]
    assert _paths(kinds, "dossiers") == [
        ("/dossiers/36496", None),
        ("/dossiers/36600-VIII", "2026-09-30"),
    ]


def test_only_the_most_cited_laws_have_their_articles(store: GraphStore) -> None:
    _seed(store)
    listed = [row["id"] for row in queries.articles(store, top=1)]
    assert listed == ["articles/bwbr0005289_162", "articles/bwbr0005289_163"]


def test_the_command_writes_the_index_and_its_parts(
    store: GraphStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store)
    index = tmp_path / "build" / "index.html"
    index.parent.mkdir()
    index.write_text("<!doctype html><html><head></head><body></body></html>")
    (index.parent / "spa-routes.json").write_text(
        json.dumps([{"path": "/", "title": "Concordans"}, {"path": "/actueel"}])
    )
    monkeypatch.setattr(settings, "SPA_INDEX", str(index))
    monkeypatch.setattr(command, "GraphStore", lambda: store)
    shell.forget()
    out = tmp_path / "sitemaps"
    try:
        result = command.main(["--out", str(out), "--base", "https://concordans.nl/"])
    finally:
        shell.forget()
    assert result.updated == 11
    listed = (out / "sitemap.xml").read_text()
    assert "<loc>https://concordans.nl/sitemap-moties.xml.gz</loc>" in listed
    assert "<lastmod>2026-09-15</lastmod>" in listed
    pages = gzip.decompress((out / "sitemap-paginas.xml.gz").read_bytes()).decode()
    assert "<loc>https://concordans.nl/actueel</loc>" in pages
