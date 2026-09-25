"""BWB normalization on the real (trimmed) Grondwet fixture."""

from __future__ import annotations

import pathlib
from typing import Any

from lawgraph.core.bwb_xml import article_version_key, historical_article_key
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import (
    BWBHistoryNormalizePipeline,
    valid_until_by_key,
)
from tests.fakes import RawSourcesFake

XML = (
    pathlib.Path(__file__).parent.parent / "fixtures" / "bwb_grondwet_toestand.xml"
).read_text()
GRONDWET = "BWBR0001840"


class _Store(RawSourcesFake):
    """In-memory store: upserts merge props like the real bulk upsert does."""

    def __init__(self, nodes: dict[str, dict[str, dict]] | None = None) -> None:
        self.nodes: dict[str, dict[str, dict]] = nodes or {}
        self.edges: dict[str, dict] = {}
        self.queries: list[str] = []
        self.existence_calls = 0

    def _put(self, collection: str, doc: dict) -> bool:
        """Merge *doc* into the collection; True when the key was new."""
        bucket = self.nodes.setdefault(collection, {})
        created = doc["_key"] not in bucket
        old = bucket.get(doc["_key"], {"props": {}})
        bucket[doc["_key"]] = {"props": {**old["props"], **doc.get("props", {})}}
        return created

    def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict]):
        created = sum(self._put(collection, doc) for doc in docs)
        return created, len(docs) - created

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        created = self._put(node.collection, node.to_document())
        stored = Node(
            collection=node.collection,
            type=node.type,
            key=node.key,
            props=dict(self.nodes[node.collection][node.key]["props"]),
            _skip_validation=True,
        )
        return stored, created

    def bulk_insert_or_update_edges(self, docs: list[dict]):
        created = sum(doc["_key"] not in self.edges for doc in docs)
        for doc in docs:
            self.edges[doc["_key"]] = doc
        return created, len(docs) - created

    def existing_keys(self, collection: str, keys) -> set[str]:
        self.existence_calls += 1
        return set(keys) & set(self.nodes.get(collection, {}))

    def query(self, aql: str, bind_vars: dict | None = None, **_kw):
        self.queries.append(aql)
        ids = set((bind_vars or {}).get("ids", []))
        if "article_versions" in aql:
            return [
                {
                    "key": k,
                    "bwb_id": d["props"].get("bwb_id"),
                    "stam_id": d["props"].get("stam_id"),
                    "number": d["props"].get("article_number"),
                    "valid_from": d["props"].get("valid_from"),
                    "valid_until": d["props"].get("valid_until"),
                    "title": d["props"].get("instrument_citation_title"),
                }
                for k, d in self.nodes.get("article_versions", {}).items()
                if d["props"].get("bwb_id") in ids
            ]
        if "FROM" not in aql and "articles" in aql:
            return [
                {
                    "key": k,
                    "bwb_id": d["props"].get("bwb_id"),
                    "stam_id": d["props"].get("stam_id"),
                }
                for k, d in self.nodes.get("articles", {}).items()
                if d["props"].get("bwb_id") in ids
            ]
        return []


def _record(xml: str, start: str, end: str) -> dict[str, Any]:
    return {
        "_key": f"r-{start}",
        "external_id": f"{GRONDWET}@{start}",
        "payload_text": xml,
        "meta": {"bwb_id": GRONDWET, "start_date": start, "end_date": end},
    }


def _older(xml: str) -> str:
    """The same regulation as it was before artikel 7 last changed (real XML, 2 attrs edited)."""
    old = xml.replace('versie-id="25689252"', 'versie-id="111"')
    return old.replace('inwerking="2018-12-21"', 'inwerking="2002-03-21"', 1)


# ── current toestand ─────────────────────────────────────────────────────────


def test_normalize_current_writes_articles_and_part_of_edges() -> None:
    store = _Store()
    pipeline = BWBNormalizePipeline(store=store)

    normalized = pipeline.normalize_nodes(
        [_record(XML, "2023-02-22", "9999-12-31")], PipelineResult()
    )
    pipeline.build_edges([], normalized)

    instrument = store.nodes["instruments"][make_node_key(GRONDWET)]["props"]
    assert instrument["citation_title"] == "Grondwet" and instrument["kind"] == "wet"
    assert instrument["dossier_numbers"] == ["35786"]
    art7 = store.nodes["articles"][make_node_key(GRONDWET, "7")]["props"]
    assert (art7["stam_id"], art7["versie_id"]) == ("2990103", "25689252")
    assert (
        art7["source_publication"] == "Stb.2019-33"
        and art7["valid_from"] == "2018-12-21"
    )
    assert art7["text"].startswith("1. Niemand heeft voorafgaand verlof")
    assert len(store.edges) == len(store.nodes["articles"])  # PART_OF each


def test_normalize_current_stores_structured_references_and_flags_repealed() -> None:
    store = _Store()
    BWBNormalizePipeline(store=store).normalize_nodes(
        [_record(XML, "2023-02-22", "9999-12-31")], PipelineResult()
    )

    art92 = store.nodes["articles"][make_node_key(GRONDWET, "92")]["props"]
    (ref,) = art92["references"]
    assert (ref["bwb_id"], ref["article"]) == (GRONDWET, "91")
    assert art92["text"][ref["start"] : ref["end"]] == ref["text"]
    repealed = [
        d["props"]
        for d in store.nodes["articles"].values()
        if d["props"].get("repealed")
    ]
    assert repealed and all(p["text"] == "Vervallen" for p in repealed)


# ── history ──────────────────────────────────────────────────────────────────


def _run_history(store: _Store, records: list[dict]) -> int:
    pipeline = BWBHistoryNormalizePipeline(store=store)
    normalized = pipeline.normalize_nodes(records, PipelineResult())
    return pipeline.build_edges([], normalized)


def test_history_stores_one_version_per_real_change_not_one_per_toestand() -> None:
    store = _Store()

    _run_history(
        store,
        [
            _record(_older(XML), "2002-03-21", "2023-02-21"),
            _record(XML, "2023-02-22", "9999-12-31"),
        ],
    )

    versions = store.nodes["article_versions"]
    articles_in_toestand = XML.count("<artikel ")
    assert len(versions) == articles_in_toestand + 1  # only artikel 7 has two versions
    assert len(store.nodes["instrument_versions"]) == 2  # one per toestand


def test_history_derives_valid_until_from_the_next_version() -> None:
    store = _Store()

    _run_history(
        store,
        [
            _record(_older(XML), "2002-03-21", "2023-02-21"),
            _record(XML, "2023-02-22", "9999-12-31"),
        ],
    )

    old = store.nodes["article_versions"][
        article_version_key(GRONDWET, "2990103", "111")
    ]
    new = store.nodes["article_versions"][
        article_version_key(GRONDWET, "2990103", "25689252")
    ]
    assert (old["props"]["valid_from"], old["props"]["valid_until"]) == (
        "2002-03-21",
        "2018-12-21",
    )
    assert old["props"]["current"] is False
    assert new["props"].get("valid_until") is None and new["props"]["current"] is True
    assert new["props"]["effect"] == "tekstplaatsing-wijziging"
    assert (
        new["props"]["origin_publication"]["identifier" if False else "id"]
        == "stb-2019-33"
    )


def test_incremental_run_fixes_the_previous_version_from_the_database() -> None:
    store = _Store()
    _run_history(store, [_record(_older(XML), "2002-03-21", "2023-02-21")])
    old_key = article_version_key(GRONDWET, "2990103", "111")
    assert store.nodes["article_versions"][old_key]["props"].get("valid_until") is None

    _run_history(
        store, [_record(XML, "2023-02-22", "9999-12-31")]
    )  # only the new toestand

    assert (
        store.nodes["article_versions"][old_key]["props"]["valid_until"] == "2018-12-21"
    )


def test_versions_link_to_the_article_with_the_same_stam_id() -> None:
    store = _Store(
        {
            "articles": {
                make_node_key(GRONDWET, "7"): {
                    "props": {"bwb_id": GRONDWET, "stam_id": "2990103"}
                }
            }
        }
    )

    _run_history(
        store,
        [
            _record(_older(XML), "2002-03-21", "2023-02-21"),
            _record(XML, "2023-02-22", "9999-12-31"),
        ],
    )

    targets = {
        e["_to"]
        for e in store.edges.values()
        if e["_from"].endswith(article_version_key(GRONDWET, "2990103", "111"))
    }
    assert targets == {f"articles/{make_node_key(GRONDWET, '7')}"}


def test_an_identity_missing_from_the_current_toestand_gets_a_historical_article() -> (
    None
):
    store = _Store()  # no current articles at all

    _run_history(store, [_record(XML, "2023-02-22", "9999-12-31")])

    key = historical_article_key(GRONDWET, "7", "2990103")
    props = store.nodes["articles"][key]["props"]
    assert props["repealed"] is True
    # article_number stays empty: (bwb_id, article_number) is a unique index
    assert "article_number" not in props and props["last_article_number"] == "7"


def test_existing_instruments_are_not_overwritten_by_history() -> None:
    store = _Store(
        {
            "instruments": {
                make_node_key(GRONDWET): {"props": {"title": "Grondwet (current)"}}
            }
        }
    )

    _run_history(store, [_record(_older(XML), "2002-03-21", "2023-02-21")])

    assert (
        store.nodes["instruments"][make_node_key(GRONDWET)]["props"]["title"]
        == "Grondwet (current)"
    )


def test_database_calls_do_not_grow_with_the_number_of_versions() -> None:
    store = _Store()
    records = [_record(XML, f"20{i:02d}-01-01", "9999-12-31") for i in range(1, 30)]

    _run_history(store, records)

    # versions, toestand starts and articles, once for the single chunk
    assert len(store.queries) == 3


def test_valid_until_chain_handles_open_ends_and_missing_stam_ids() -> None:
    rows = [
        {"key": "a1", "bwb_id": "B", "stam_id": "1", "valid_from": "2000-01-01"},
        {"key": "a2", "bwb_id": "B", "stam_id": "1", "valid_from": "2010-01-01"},
        {"key": "a3", "bwb_id": "B", "stam_id": "1", "valid_from": "2020-01-01"},
        {"key": "b1", "bwb_id": "B", "stam_id": "2", "valid_from": "2005-01-01"},
        {"key": "c1", "bwb_id": "B", "stam_id": None, "valid_from": "2005-01-01"},
    ]

    assert valid_until_by_key(rows) == {
        "a1": "2010-01-01",
        "a2": "2020-01-01",
        "a3": None,
        "b1": None,
        "c1": None,
    }


def test_a_version_ends_when_it_lapses_or_its_article_leaves_the_law() -> None:
    rows = [
        # lapsed: holds on no date, and ends the version before it
        {"key": "a1", "bwb_id": "B", "stam_id": "1", "valid_from": "2000-01-01"},
        {
            "key": "a2",
            "bwb_id": "B",
            "stam_id": "1",
            "valid_from": "2006-02-01",
            "lapsed": True,
        },
        # last seen in the toestand of 2002, gone from the one of 2003
        {
            "key": "b1",
            "bwb_id": "B",
            "stam_id": "2",
            "valid_from": "1971-10-01",
            "last_seen": "2002-01-01",
        },
        # in the latest toestand: current
        {
            "key": "c1",
            "bwb_id": "B",
            "stam_id": "3",
            "valid_from": "2003-01-01",
            "last_seen": "2026-01-01",
        },
        # a bijlage article without stam-id: followed by its number
        {
            "key": "d1",
            "bwb_id": "B",
            "number": "bijlage 2 artikel 1",
            "valid_from": "2013-01-01",
        },
        {
            "key": "d2",
            "bwb_id": "B",
            "number": "bijlage 2 artikel 1",
            "valid_from": "2014-01-01",
        },
    ]
    starts = {"B": ["2002-01-01", "2003-01-01", "2026-01-01"]}
    assert valid_until_by_key(rows, starts) == {
        "a1": "2006-02-01",
        "a2": "2006-02-01",
        "b1": "2003-01-01",
        "c1": None,
        "d1": "2014-01-01",
        "d2": None,
    }


def test_placeholders_lapses_and_inclusive_ends_are_recognised() -> None:
    from lawgraph.pipelines.normalize.bwb_history import (
        exclusive_end,
        is_lapsed,
        is_placeholder,
    )

    assert is_placeholder("Dit onderdeel is nog niet inwerking getreden")
    assert is_placeholder("Dit onderdeel is nog niet in werking getreden.")
    assert not is_placeholder("1. Degene die een dienst ...")
    assert is_lapsed("vervallen", None) and is_lapsed(None, "Vervallen.")
    assert not is_lapsed("wijziging", "Met gevangenisstraf ...")
    assert exclusive_end("2024-12-31") == "2025-01-01"
    assert exclusive_end("9999-12-31") is None and exclusive_end(None) is None


def test_only_the_current_toestand_is_normalized_not_the_history() -> None:
    """A historical toestand has the bwb_id of the regulation too: it must not be read."""
    from lawgraph.config.constants import (
        RAW_KIND_BWB_TOESTAND,
        RAW_KIND_BWB_TOESTAND_ALL,
    )

    asked: list[dict] = []

    class Store(_Store):
        def query(self, aql, bind_vars=None, **kw):  # type: ignore[override]
            asked.append(dict(bind_vars or {}))
            return iter([])

    list(BWBNormalizePipeline(store=Store()).fetch_raw())
    assert asked[0]["kinds"] == [RAW_KIND_BWB_TOESTAND]
    assert RAW_KIND_BWB_TOESTAND_ALL not in asked[0]["kinds"]
