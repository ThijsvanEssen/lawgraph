"""The reads of raw_sources on a real PostgreSQL."""

from __future__ import annotations

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_TK_STEMMING,
    SOURCE_BWB,
    SOURCE_RECHTSPRAAK,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore, raw_source_doc
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries import state as state_queries


def _raw(source: str, kind: str, external_id: str, at: str, **fields: object) -> dict:
    doc = raw_source_doc(source=source, kind=kind, external_id=external_id, **fields)  # type: ignore[arg-type]
    return {**doc, "fetched_at": at}


def _fill(store: ArangoStore) -> None:
    store.insert_raw_sources(
        [
            _raw(
                SOURCE_TK,
                RAW_KIND_TK_STEMMING,
                "v1",
                "2026-01-01T00:00:00Z",
                payload_json={"Besluit_Id": "b1"},
            ),
            _raw(
                SOURCE_TK,
                RAW_KIND_TK_STEMMING,
                "v2",
                "2026-02-01T00:00:00Z",
                payload_json={"Besluit_Id": "b2", "Verwijderd": True},
            ),
            _raw(
                SOURCE_RECHTSPRAAK,
                RAW_KIND_RS_CONTENT,
                "ECLI:A",
                "2026-03-01T00:00:00Z",
                payload_text="<x/>",
                meta={"ecli": ""},
            ),
            _raw(
                SOURCE_RECHTSPRAAK,
                RAW_KIND_RS_CONTENT,
                "e2",
                "2026-03-02T00:00:00Z",
                payload_text="<y/>",
                meta={"ecli": "ECLI:B"},
            ),
            _raw(
                SOURCE_BWB,
                "bwb-x-missing",
                "BWBR1",
                "2026-04-01T00:00:00Z",
                meta={"retry_after": "2026-05-01", "bwb_id": "BWBR1"},
            ),
        ]
    )


def test_records_of_a_kind_since_a_moment(store: ArangoStore) -> None:
    _fill(store)
    rows = list(
        raw_queries.iter_raw_records(
            store,
            source=SOURCE_TK,
            kinds=[RAW_KIND_TK_STEMMING],
            since_iso=None,
            batch_size=1,
        )
    )
    assert sorted(r["external_id"] for r in rows) == ["v1", "v2"]
    assert [r["_key"] for r in rows] == sorted(r["_key"] for r in rows)  # key order
    assert all(r["_id"] == f"raw_sources/{r['_key']}" for r in rows)
    since = raw_queries.iter_raw_records(
        store,
        source=SOURCE_TK,
        kinds=[RAW_KIND_TK_STEMMING],
        since_iso="2026-01-15",
        batch_size=10,
    )
    assert [r["external_id"] for r in since] == ["v2"]
    assert raw_queries.count_raw_records(store, SOURCE_TK, [RAW_KIND_TK_STEMMING]) == 2


def test_the_toestanden_of_each_law_are_read_from_the_oldest(
    store: ArangoStore,
) -> None:
    """What bwb-history makes of the toestanden depends on the order it reads them in:
    each law's from the oldest, not in the order of the keys (a hash) or of fetching."""
    toestanden = [
        ("BWBR2", "2020-01-01", "2026-01-01T00:00:00Z"),
        ("BWBR1", "2010-01-01", "2026-01-02T00:00:00Z"),
        ("BWBR2", "2000-01-01", "2026-01-03T00:00:00Z"),
        ("BWBR1", "2005-06-01", "2026-01-04T00:00:00Z"),
    ]
    store.insert_raw_sources(
        [
            _raw(
                SOURCE_BWB,
                RAW_KIND_BWB_TOESTAND_ALL,
                f"{bwb_id}@{start}",
                at,
                meta={"bwb_id": bwb_id, "start_date": start},
            )
            for bwb_id, start, at in toestanden
        ]
    )
    rows = raw_queries.iter_raw_records(
        store,
        source=SOURCE_BWB,
        kinds=[RAW_KIND_BWB_TOESTAND_ALL],
        since_iso=None,
        batch_size=2,
        chronological=True,
    )
    assert [r["external_id"] for r in rows] == [
        "BWBR1@2005-06-01",
        "BWBR1@2010-01-01",
        "BWBR2@2000-01-01",
        "BWBR2@2020-01-01",
    ]


def test_votes_and_deletions(store: ArangoStore) -> None:
    _fill(store)
    assert raw_queries.decisions_voted_since(store, None) == ["b1", "b2"]
    assert raw_queries.decisions_voted_since(store, "2026-01-15") == ["b2"]
    rows = raw_queries.vote_rows_of_decisions(store, ["b1"])
    assert [r["external_id"] for r in rows] == ["v1"]
    deleted = raw_queries.deleted_records_since(store, RAW_KIND_TK_STEMMING, None)
    assert [r["external_id"] for r in deleted] == ["v2"]
    assert [
        r["external_id"]
        for r in raw_queries.tk_records_of(store, RAW_KIND_TK_STEMMING, ["v1"])
    ] == ["v1"]


def test_judgments_with_payloads(store: ArangoStore) -> None:
    _fill(store)
    refs = list(raw_queries.judgment_payload_refs(store, since_iso=None, batch_size=10))
    assert sorted(r["ecli"] for r in refs) == ["ECLI:A", "ECLI:B"]
    assert all(r["payload_ref"] for r in refs)
    assert raw_queries.count_judgment_records(store) == 2
    assert sorted(raw_queries.judgment_eclis_fetched_since(store, "2026-03-02")) == [
        "ECLI:B"
    ]


def test_what_was_stored_when(store: ArangoStore) -> None:
    _fill(store)
    waiting = raw_queries.ids_waiting_for_retry(
        store, source=SOURCE_BWB, kind="bwb-x-missing", now_iso="2026-04-15"
    )
    assert list(waiting) == ["BWBR1"]
    later = raw_queries.ids_waiting_for_retry(
        store, source=SOURCE_BWB, kind="bwb-x-missing", now_iso="2026-06-01"
    )
    assert list(later) == []
    assert list(raw_queries.bwb_ids_fetched_since(store, "2026-01-01")) == ["BWBR1"]
    times = list(
        raw_queries.fetch_times(store, source=SOURCE_TK, kind=RAW_KIND_TK_STEMMING)
    )
    assert {t["id"]: t["at"] for t in times}["v1"] == "2026-01-01T00:00:00Z"


def test_counts(store: ArangoStore) -> None:
    _fill(store)
    counts = {(r["source"], r["kind"]): r["n"] for r in raw_queries.raw_counts(store)}
    assert counts[(SOURCE_TK, RAW_KIND_TK_STEMMING)] == 2
    assert sorted(raw_queries.record_counts(store, "-missing")) == [2, 2]
    sample = list(
        raw_queries.payload_refs_sample(
            store, source=SOURCE_RECHTSPRAAK, kind=RAW_KIND_RS_CONTENT, sample=1
        )
    )
    assert len(sample) == 1


def test_pipeline_state(store: ArangoStore) -> None:
    assert state_queries.covered_until(store, "normalize") is None
    state_queries.set_covered_until(store, "normalize", "2026-10-01T00:00:00Z")
    state_queries.set_covered_until(store, "normalize", "2026-10-02T00:00:00Z")
    assert state_queries.covered_until(store, "normalize") == "2026-10-02T00:00:00Z"
