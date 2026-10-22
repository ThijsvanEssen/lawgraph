"""The reads of ``raw_sources`` in ``db/queries/raw.py`` that the retrieve pipelines stand on,
run for real: the unit tests replace them with what they answer here."""

from __future__ import annotations

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_EURLEX_CELEX,
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_STAATSBLAD_AMVB,
    SOURCE_BWB,
    SOURCE_EURLEX,
    SOURCE_STAATSBLAD,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries import raw as raw_queries
from tests.integration.seed import write_toestanden


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


def test_the_staatsblad_refs_are_those_of_the_toestanden_alone(
    store: GraphStore,
) -> None:
    """The publication each toestand comes from, from its meta; the WTI record of the same
    regulation holds none and is not read."""
    with RawSourceWriter(store) as writer:
        for source, kind, external_id, ref in (
            (SOURCE_BWB, RAW_KIND_BWB_TOESTAND, "BWBR0004092", "stb-2012-79"),
            (SOURCE_BWB, RAW_KIND_BWB_TOESTAND, "BWBR0000002", None),
            (SOURCE_BWB, "bwb-wti-algemene-informatie-xml", "BWBR0004092", None),
            (SOURCE_STAATSBLAD, RAW_KIND_BWB_TOESTAND, "BWBR0000001", "stb-1-1"),
        ):
            writer.add(
                raw_source_doc(
                    source=source,
                    kind=kind,
                    external_id=external_id,
                    payload_text="<xml/>",
                    meta={"staatsblad_ref": ref},
                )
            )
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id="BWBR0000003",
                payload_text="<xml/>",
            )
        )
    rows = list(raw_queries.toestand_staatsblad_refs(store))
    assert sorted((row["bwb_id"], row["ref"]) for row in rows) == [
        ("BWBR0000002", None),
        ("BWBR0004092", "stb-2012-79"),
    ]
    without = raw_queries.toestanden_without_staatsblad_ref(store)
    assert [r["external_id"] for r in without] == ["BWBR0000003"]
    of = raw_queries.toestanden_of(store, ["BWBR0004092", "BWBR0000001"])
    assert [(r["source"], r["external_id"]) for r in of] == [
        (SOURCE_BWB, "BWBR0004092")
    ]


def test_the_stored_staatsblad_ids_are_those_asked_for_and_stored(
    store: GraphStore,
) -> None:
    _write(
        store,
        (SOURCE_STAATSBLAD, RAW_KIND_STAATSBLAD_AMVB, "stb-2001-1"),
        (SOURCE_STAATSBLAD, RAW_KIND_STAATSBLAD_AMVB, "stb-2003-3"),  # not asked for
        (
            SOURCE_STAATSBLAD,
            RAW_KIND_STAATSBLAD_AMVB + RAW_KIND_MISSING_SUFFIX,
            "stb-2002-2",
        ),
    )
    asked = ["stb-2001-1", "stb-2002-2", "stb-2004-4"]
    assert set(raw_queries.stored_staatsblad_ids(store, asked)) == {"stb-2001-1"}


def test_the_toestanden_of_each_law_are_read_from_the_oldest(store: GraphStore) -> None:
    """What bwb-history makes of the toestanden depends on the order it reads them in: each
    law's from the oldest, not in the order they were fetched (BWBR0005290 of the parity
    build had its newest toestanden fetched first)."""
    write_toestanden(
        store,
        [
            (
                RAW_KIND_BWB_TOESTAND_ALL,
                f"{bwb_id}@{start}",
                "<xml/>",
                {"bwb_id": bwb_id, "start_date": start},
            )
            for bwb_id, start in [
                ("BWBR2", "2020-01-01"),
                ("BWBR1", "2010-01-01"),
                ("BWBR2", "2000-01-01"),
                ("BWBR1", "2005-06-01"),
            ]
        ],
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


def test_a_meta_value_of_each_record_is_read_without_its_payload(
    store: GraphStore,
) -> None:
    """``meta.modified`` of the EUR-Lex acts, null for an act stored without it; other kinds
    are not read."""
    with RawSourceWriter(store) as writer:
        for kind, celex, meta in [
            (
                RAW_KIND_EURLEX_CELEX,
                "32016R0679",
                {"modified": "2024-12-31T20:10:26+01:00"},
            ),
            (RAW_KIND_EURLEX_CELEX, "31995L0046", {}),
            (RAW_KIND_EURLEX_CELEX + RAW_KIND_MISSING_SUFFIX, "39999R9999", {}),
        ]:
            writer.add(
                raw_source_doc(
                    source=SOURCE_EURLEX,
                    kind=kind,
                    external_id=celex,
                    payload_text="<html/>",
                    meta=meta,
                )
            )
    rows = raw_queries.meta_values(
        store, source=SOURCE_EURLEX, kind=RAW_KIND_EURLEX_CELEX, field="modified"
    )
    assert {row["id"]: row["value"] for row in rows} == {
        "32016R0679": "2024-12-31T20:10:26+01:00",
        "31995L0046": None,
    }
