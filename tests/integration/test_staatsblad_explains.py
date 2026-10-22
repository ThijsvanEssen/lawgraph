"""A Staatsblad note explains its regulation, for real: the XML of stb-2025-263 as the
repository serves it (its note is ``<nota-toelichting>``), stored by ``retrieve staatsblad``
for the toestand of the Mediabesluit 2008 that named it, through ``normalize staatsblad`` and
``semantic staatsblad``. The regulation retrieve kept counts only where its stored toestand
names the publication: a treaty whose ``Trb. 2018, 100`` an older reading took for
``Stb. 2018, 100`` is not what that decree explains, and the edge an earlier run made goes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_STAATSBLAD_AMVB,
    RELATION_EXPLAINS,
    SOURCE_BWB,
    SOURCE_STAATSBLAD,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.edges import make_edge_doc

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "stb_2025_263.xml"
MEDIABESLUIT = "BWBR0024248"  # Mediabesluit 2008
TREATY = "BWBV0001911"  # Aruba and Ireland, published in Trb. 2018, 100


def _toestand(series: str, year: int, number: int) -> str:
    return (
        f"<toestand><brondata><oorspronkelijk><publicatie soort='{series}'"
        " effect='nieuwe-regeling'>"
        f"<publicatiejaar>{year}</publicatiejaar><publicatienr>{number}</publicatienr>"
        "</publicatie></oorspronkelijk></brondata></toestand>"
    )


def _decree(title: str) -> str:
    return (
        f"<officiele-publicatie><intitule>{title}</intitule><nota-toelichting>"
        "<al>Dit besluit regelt het tijdstip van inwerkingtreding van een wet, en"
        " daarmee de toepassing van de bepalingen die deze wet bevat.</al>"
        "</nota-toelichting></officiele-publicatie>"
    )


def test_the_note_explains_the_regulation_its_toestand_names(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "key": bwb_id.lower(),
                "type": "instrument",
                "labels": ["BWB"],
                "props": {"bwb_id": bwb_id, "title": title},
            }
            for bwb_id, title in (
                (MEDIABESLUIT, "Mediabesluit 2008"),
                (TREATY, "Briefwisseling met Ierland"),
            )
        ],
    )
    with RawSourceWriter(store) as writer:
        for bwb_id, xml in (
            (MEDIABESLUIT, _toestand("Stb", 2025, 263)),
            (TREATY, _toestand("Trb", 2018, 100)),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=xml,
                    meta={"bwb_id": bwb_id},
                )
            )
        for identifier, xml, bwb_id in (
            ("stb-2025-263", FIXTURE.read_text(), MEDIABESLUIT),
            ("stb-2018-100", _decree("Besluit van 23 maart 2018"), TREATY),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_STAATSBLAD,
                    kind=RAW_KIND_STAATSBLAD_AMVB,
                    external_id=identifier,
                    payload_text=xml,
                    meta={"identifier": identifier, "bwb_id": bwb_id},
                )
            )
    # the document and the edge a run made before the toestand was read again
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {
                "key": "stb_stb_2018_100",
                "type": "document",
                "labels": ["Staatsblad", "NvT"],
                "props": {"source": SOURCE_STAATSBLAD, "bwb_id": TREATY},
            }
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "documents/stb_stb_2018_100",
                f"instruments/{TREATY.lower()}",
                RELATION_EXPLAINS,
                source="staatsblad-nvt-linker",
                confidence=0.85,
            )
        ]
    )
    cli("normalize", "staatsblad")
    cli("semantic", "staatsblad")

    bwb_ids = {
        row["key"]: row["bwb_id"]
        for row in store.query(
            "SELECT key, lg_str(props -> 'bwb_id') AS bwb_id FROM documents"
        )
    }
    assert bwb_ids == {"stb_stb_2018_100": None, "stb_stb_2025_263": MEDIABESLUIT}
    edges = {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'EXPLAINS'"
        )
    }
    assert edges == {
        ("documents/stb_stb_2025_263", f"instruments/{MEDIABESLUIT.lower()}")
    }
