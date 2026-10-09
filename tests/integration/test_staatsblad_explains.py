"""A Staatsblad note explains its regulation, for real: the XML of stb-2025-263 as the
repository serves it (its note is ``<nota-toelichting>``), stored by ``retrieve staatsblad``
for the toestand of the Mediabesluit 2008 that named it, through ``normalize staatsblad`` and
``semantic staatsblad``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_STB_AMVB, SOURCE_STAATSBLAD
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "stb_2025_263.xml"
MEDIABESLUIT = "BWBR0024248"  # Mediabesluit 2008


def test_the_note_explains_the_regulation_retrieve_found_it_for(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": MEDIABESLUIT.lower(),
                "type": "instrument",
                "labels": ["BWB"],
                "props": {"bwb_id": MEDIABESLUIT, "title": "Mediabesluit 2008"},
            }
        ],
    )
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_STAATSBLAD,
                kind=RAW_KIND_STB_AMVB,
                external_id="stb-2025-263",
                payload_text=FIXTURE.read_text(),
                meta={"identifier": "stb-2025-263", "bwb_id": MEDIABESLUIT},
            )
        )
    cli("normalize", "staatsblad")
    cli("semantic", "staatsblad")

    edges = {
        (row["from_id"], row["to_id"], row["match"])
        for row in store.query(
            "SELECT from_id, to_id, doc -> 'meta' ->> 'match_type' AS match FROM edges"
            " WHERE relation = 'EXPLAINS'"
        )
    }
    assert {(f, t) for f, t, _ in edges} == {
        ("documents/stb_stb_2025_263", f"instruments/{MEDIABESLUIT.lower()}")
    }
