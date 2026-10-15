"""BWB normalization on the real (trimmed) Grondwet fixture."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.core import bwb_xml
from lawgraph.core.bwb_xml import article_version_key, historical_article_key
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import (
    BWBHistoryNormalizePipeline,
    Toestanden,
    valid_until_by_key,
)
from tests.fakes.bwb_normalize import BwbStore, patch_bwb_queries
from tests.normalize.bwb_records import GRONDWET, XML, bwb_record, older_toestand


@pytest.fixture(autouse=True)
def _store_queries(monkeypatch: pytest.MonkeyPatch, raw_reads: None) -> None:
    patch_bwb_queries(monkeypatch)


# ── current toestand ─────────────────────────────────────────────────────────


def test_normalize_current_writes_articles_and_part_of_edges() -> None:
    store = BwbStore()
    pipeline = BWBNormalizePipeline(store=store)

    pipeline.write([bwb_record(XML, "2023-02-22", "9999-12-31")], PipelineResult())

    instrument = store.nodes["instruments"][make_node_key(GRONDWET)]["props"]
    assert instrument["citation_title"] == "Grondwet" and instrument["kind"] == "wet"
    assert instrument["dossier_numbers"] == []  # the Grondwet of 1840 names none
    art7 = store.nodes["articles"][make_node_key(GRONDWET, "7")]["props"]
    assert (art7["stam_id"], art7["versie_id"]) == ("2990103", "25689252")
    assert (
        art7["source_publication"] == "Stb.2019-33"
        and art7["valid_from"] == "2018-12-21"
    )
    assert art7["text"].startswith("1. Niemand heeft voorafgaand verlof")
    assert len(store.edges) == len(store.nodes["articles"])  # PART_OF each


def test_normalize_current_stores_structured_references_and_flags_repealed() -> None:
    store = BwbStore()
    BWBNormalizePipeline(store=store).write(
        [bwb_record(XML, "2023-02-22", "9999-12-31")], PipelineResult()
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


def _run_history(store: BwbStore, records: list[dict]) -> None:
    BWBHistoryNormalizePipeline(store=store).write(
        Toestanden(records, incremental=False), PipelineResult()
    )


def test_history_stores_one_version_per_real_change_not_one_per_toestand() -> None:
    store = BwbStore()

    _run_history(
        store,
        [
            bwb_record(older_toestand(XML), "2002-03-21", "2023-02-21"),
            bwb_record(XML, "2023-02-22", "9999-12-31"),
        ],
    )

    versions = store.nodes["article_versions"]
    articles_in_toestand = XML.count("<artikel ")
    assert len(versions) == articles_in_toestand + 1  # only artikel 7 has two versions
    assert len(store.nodes["instrument_versions"]) == 2  # one per toestand


def test_history_reads_the_text_only_of_versions_it_has_not_met(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read: list[str | None] = []
    parse = bwb_xml._parse_article

    def counted(element: Any, *args: Any) -> Any:
        read.append(element.get("versie-id"))
        return parse(element, *args)

    monkeypatch.setattr(bwb_xml, "_parse_article", counted)
    _run_history(
        BwbStore(),
        [
            bwb_record(older_toestand(XML), "2002-03-21", "2023-02-21"),
            bwb_record(XML, "2023-02-22", "9999-12-31"),
        ],
    )

    # every article of the first toestand, and of the second only the new artikel 7
    assert len(read) == XML.count("<artikel ") + 1
    assert read[-1] == "25689252"


def test_history_derives_valid_until_from_the_next_version() -> None:
    store = BwbStore()

    _run_history(
        store,
        [
            bwb_record(older_toestand(XML), "2002-03-21", "2023-02-21"),
            bwb_record(XML, "2023-02-22", "9999-12-31"),
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
    store = BwbStore()
    _run_history(store, [bwb_record(older_toestand(XML), "2002-03-21", "2023-02-21")])
    old_key = article_version_key(GRONDWET, "2990103", "111")
    assert store.nodes["article_versions"][old_key]["props"].get("valid_until") is None

    _run_history(
        store, [bwb_record(XML, "2023-02-22", "9999-12-31")]
    )  # only the new toestand

    assert (
        store.nodes["article_versions"][old_key]["props"]["valid_until"] == "2018-12-21"
    )


def test_versions_link_to_the_article_with_the_same_stam_id() -> None:
    store = BwbStore(
        {
            "articles": [
                {
                    "_key": make_node_key(GRONDWET, "7"),
                    "props": {"bwb_id": GRONDWET, "stam_id": "2990103"},
                }
            ]
        }
    )

    _run_history(
        store,
        [
            bwb_record(older_toestand(XML), "2002-03-21", "2023-02-21"),
            bwb_record(XML, "2023-02-22", "9999-12-31"),
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
    store = BwbStore()  # no current articles at all

    _run_history(store, [bwb_record(XML, "2023-02-22", "9999-12-31")])

    key = historical_article_key(GRONDWET, "7", "2990103")
    props = store.nodes["articles"][key]["props"]
    assert props["repealed"] is True
    # article_number stays empty: (bwb_id, article_number) is a unique index
    assert "article_number" not in props and props["last_article_number"] == "7"


def test_existing_instruments_are_not_overwritten_by_history() -> None:
    store = BwbStore(
        {
            "instruments": [
                {
                    "_key": make_node_key(GRONDWET),
                    "props": {"title": "Grondwet (current)"},
                }
            ]
        }
    )

    _run_history(store, [bwb_record(older_toestand(XML), "2002-03-21", "2023-02-21")])

    assert (
        store.nodes["instruments"][make_node_key(GRONDWET)]["props"]["title"]
        == "Grondwet (current)"
    )


def test_database_calls_do_not_grow_with_the_number_of_versions() -> None:
    store = BwbStore()
    records = [bwb_record(XML, f"20{i:02d}-01-01", "9999-12-31") for i in range(1, 30)]

    _run_history(store, records)

    # versions, toestand starts and articles, once for the single chunk
    assert store.queries == [
        "article_versions",
        "toestand_starts",
        "article_identities",
    ]


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


def test_only_the_current_toestand_is_normalized_not_the_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A historical toestand has the bwb_id of the regulation too: it must not be read."""
    from lawgraph.config.constants import (
        RAW_KIND_BWB_TOESTAND,
        RAW_KIND_BWB_TOESTAND_ALL,
    )

    asked: list[list[str]] = []

    def iter_raw_records(store: Any, *, kinds: list[str], **_: Any) -> Iterator:
        asked.append(kinds)
        return iter([])

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)

    list(BWBNormalizePipeline(store=BwbStore()).fetch_raw())
    assert asked == [[RAW_KIND_BWB_TOESTAND]]
    assert RAW_KIND_BWB_TOESTAND_ALL not in asked[0]


def _run_history_pipeline(
    store: BwbStore, records: list[dict[str, Any]]
) -> PipelineResult:
    pipeline = BWBHistoryNormalizePipeline(store=store)
    pipeline.fetch_raw = lambda *, since=None: Toestanden(records, incremental=False)  # type: ignore[method-assign]
    return pipeline.run()


@pytest.mark.parametrize("start", [None, "2020-13-40"])
def test_a_toestand_without_a_valid_start_date_is_skipped_not_dated_unknown(
    start: str | None,
) -> None:
    store = BwbStore()
    undated = bwb_record(older_toestand(XML), "2002-03-21", "2023-02-21")
    undated["meta"]["start_date"] = start

    result = _run_history_pipeline(
        store, [undated, bwb_record(XML, "2023-02-22", "9999-12-31")]
    )

    assert (result.skipped, result.errors) == (1, [])
    assert list(store.nodes["instrument_versions"]) == [
        make_node_key(GRONDWET, "2023-02-22")
    ]
    seen = {d["props"]["last_seen"] for d in store.nodes["article_versions"].values()}
    assert seen == {"2023-02-22"}


def test_a_toestand_with_an_unreadable_end_date_is_skipped() -> None:
    store = BwbStore()

    result = _run_history_pipeline(
        store,
        [
            bwb_record(older_toestand(XML), "2002-03-21", "2023-02-31"),
            bwb_record(XML, "2023-02-22", "9999-12-31"),
        ],
    )

    assert (result.skipped, result.errors) == (1, [])
    assert len(store.nodes["instrument_versions"]) == 1


def test_an_unreadable_toestand_fails_the_step_and_names_the_record() -> None:
    store = BwbStore()

    result = _run_history_pipeline(
        store,
        [
            bwb_record("<toestand><bad", "2002-03-21", "2023-02-21"),
            bwb_record(XML, "2023-02-22", "9999-12-31"),
        ],
    )

    assert result.skipped == 1
    (error,) = result.errors
    assert "not XML" in error and f"{GRONDWET}@2002-03-21" in error
    assert len(store.nodes["instrument_versions"]) == 1


def test_a_current_toestand_without_payload_is_skipped_and_one_not_xml_fails() -> None:
    pipeline = BWBNormalizePipeline(store=BwbStore())
    progress = pipeline.progress
    empty = {**bwb_record(XML, "2023-02-22", "9999-12-31"), "payload_text": ""}
    broken = bwb_record("<toestand><bad", "2023-02-22", "9999-12-31")
    result = PipelineResult()

    pipeline.write([empty, broken, bwb_record(XML, "2023-02-22", "9999-12-31")], result)
    pipeline.add_outcomes(result)

    assert progress.skips == {"no payload or BWB id": 1}
    assert progress.failures == {"toestand not XML": 1}
    assert result.skipped == 2
    (error,) = result.errors
    assert "toestand not XML" in error and GRONDWET in error


def test_a_wti_record_without_payload_is_skipped_and_one_not_xml_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.config.constants import RAW_KIND_BWB_WTI_GENERAL

    wti = [
        {"_key": "w-1", "external_id": "BWBR0002656", "payload_text": ""},
        {"_key": "w-2", "external_id": GRONDWET, "payload_text": "<wti><bad"},
    ]

    def iter_raw_records(store: Any, *, kinds: list[str], **_: Any) -> Iterator:
        return iter(wti if kinds == [RAW_KIND_BWB_WTI_GENERAL] else [])

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)
    pipeline = BWBNormalizePipeline(store=BwbStore())
    result = PipelineResult()

    pipeline.write([], result)
    pipeline.add_outcomes(result)

    assert result.skipped == 2
    (error,) = result.errors
    assert "WTI not XML" in error and GRONDWET in error
