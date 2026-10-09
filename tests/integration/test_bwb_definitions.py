"""``semantic bwb-definitions`` for real: the stored toestanden of the Besluit zorgverzekering
and the Wft (articles of the XML the repository served) give their definitions in
``lg_instrument_definitions``, a full run in slices (``--limit``, ``--after``), and a
regulation whose toestand no longer defines anything loses its row."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _toestand(store: GraphStore, bwb_id: str, xml: str) -> None:
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id=bwb_id,
                payload_text=xml,
                meta={"bwb_id": bwb_id},
            )
        )


def _kept(store: GraphStore) -> dict[str, list[dict[str, Any]]]:
    return {
        row["bwb_id"]: row["definitions"]
        for row in store.query(
            "SELECT bwb_id, definitions FROM lg_instrument_definitions"
        )
    }


def test_the_definitions_of_each_regulation_are_kept(database: str, cli: Any) -> None:
    store = GraphStore()
    _toestand(store, "BWBR0018492", (FIXTURES / "bwb_definitions_bzv.xml").read_text())
    _toestand(store, "BWBR0020368", (FIXTURES / "bwb_definitions_wft.xml").read_text())

    # a full run in two slices of one
    cli("semantic", "bwb-definitions", "--limit", "1")
    assert list(_kept(store)) == ["BWBR0018492"]
    cli("semantic", "bwb-definitions", "--after", "BWBR0018492", "--limit", "1")
    kept = _kept(store)
    assert sorted(kept) == ["BWBR0018492", "BWBR0020368"]
    wet = kept["BWBR0018492"][0]
    assert (wet["term"], wet["text"], wet["refers_to"]) == (
        "wet",
        "de Zorgverzekeringswet",
        "BWBR0018450",
    )
    assert len(kept["BWBR0020368"]) > 50
    (instrument,) = store.query(
        "SELECT instrument_id FROM lg_instrument_definitions WHERE bwb_id = 'BWBR0018492'"
    )
    assert instrument == "instruments/bwbr0018492"

    # a toestand that no longer defines anything
    _toestand(
        store,
        "BWBR0018492",
        '<toestand bwb-id="BWBR0018492"><wetgeving><wettekst><artikel label="Artikel 1">'
        "<kop><nr>1</nr></kop><al>Dit besluit treedt in werking.</al></artikel>"
        "</wettekst></wetgeving></toestand>",
    )
    cli("semantic", "bwb-definitions")
    assert list(_kept(store)) == ["BWBR0020368"]
    assert json.dumps(_kept(store)["BWBR0020368"][0]["scope"]) == json.dumps(
        {"kind": "wet", "path": ""}
    )
