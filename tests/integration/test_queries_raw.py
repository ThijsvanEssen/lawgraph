"""The reads of ``raw_sources`` in ``db/queries/raw.py`` that the retrieve pipelines stand on,
run for real: the unit tests replace them with what they answer here."""

from __future__ import annotations

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_STB_AMVB,
    SOURCE_BWB,
    SOURCE_STAATSBLAD,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries import raw as raw_queries


def _write(store: GraphStore, *records: tuple[str, str, str]) -> None:
    with RawSourceWriter(store) as writer:
        for source, kind, external_id in records:
            writer.add(
                raw_source_doc(
                    source=source,
                    kind=kind,
                    external_id=external_id,
                    payload_text=f"<xml>{external_id}</xml>",
                )
            )


def test_the_toestand_payloads_are_those_of_the_toestanden_alone(database: str) -> None:
    """The WTI record of the same regulation holds no Staatsblad reference: before, the last
    XML per regulation id won, and that was the WTI."""
    store = GraphStore()
    _write(
        store,
        (SOURCE_BWB, RAW_KIND_BWB_TOESTAND, "BWBR0004092"),
        (SOURCE_BWB, "bwb-wti-algemene-informatie-xml", "BWBR0004092"),
        (SOURCE_STAATSBLAD, RAW_KIND_BWB_TOESTAND, "BWBR0000001"),  # another source
    )
    rows = list(store.with_payloads(raw_queries.toestand_payload_refs(store)))
    assert [(row["bwb_id"], row["payload_text"]) for row in rows] == [
        ("BWBR0004092", "<xml>BWBR0004092</xml>")
    ]


def test_the_stored_staatsblad_ids_are_those_asked_for_and_stored(
    database: str,
) -> None:
    store = GraphStore()
    _write(
        store,
        (SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB, "stb-2001-1"),
        (SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB, "stb-2003-3"),  # not asked for
        (SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB + RAW_KIND_MISSING_SUFFIX, "stb-2002-2"),
    )
    asked = ["stb-2001-1", "stb-2002-2", "stb-2004-4"]
    assert set(raw_queries.stored_staatsblad_ids(store, asked)) == {"stb-2001-1"}


def test_the_toestanden_of_each_law_are_read_from_the_oldest(database: str) -> None:
    """What bwb-history makes of the toestanden depends on the order it reads them in: each
    law's from the oldest, not in the order they were fetched (BWBR0005290 of the parity
    build had its newest toestanden fetched first)."""
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        for bwb_id, start in [
            ("BWBR2", "2020-01-01"),
            ("BWBR1", "2010-01-01"),
            ("BWBR2", "2000-01-01"),
            ("BWBR1", "2005-06-01"),
        ]:
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND_ALL,
                    external_id=f"{bwb_id}@{start}",
                    payload_text="<xml/>",
                    meta={"bwb_id": bwb_id, "start_date": start},
                )
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
