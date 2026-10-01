"""``lawgraph code-families`` builds the table of codes from the stored WTI records."""

from __future__ import annotations

import json
from pathlib import Path

from lawgraph.commands import code_families
from lawgraph.config.constants import RAW_KIND_BWB_WTI_GENERAL, SOURCE_BWB
from lawgraph.core.code_families import DATA
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

WTI = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "bwb_wti_abbreviations.json"
    ).read_text()
)


def _general_info(abbreviations: list[str]) -> str:
    items = "".join(f"<afkorting>{a}</afkorting>" for a in abbreviations)
    return (
        f"<algemene-informatie><afkortingen>{items}</afkortingen></algemene-informatie>"
    )


def _store(store: GraphStore, wti: dict[str, list[str]]) -> None:
    with RawSourceWriter(store) as writer:
        for bwb_id, abbreviations in wti.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_WTI_GENERAL,
                    external_id=bwb_id,
                    payload_text=_general_info(abbreviations),
                )
            )


def test_the_stored_wti_builds_the_table_of_the_repository(
    database: str, tmp_path: Path
) -> None:
    store = GraphStore()
    _store(store, WTI)
    assert not code_families.main(["check"]).errors
    out = tmp_path / "code_families.json"
    assert not code_families.main(["build", "--output", str(out)]).errors
    built = json.loads(out.read_text())
    assert built["families"] == json.loads(DATA.read_text())["families"]


def test_a_book_that_moved_fails_the_check(database: str) -> None:
    store = GraphStore()
    _store(store, {**WTI, "BWBR0005289": ["BW"], "BWBR9999999": ["BW", "BW Boek 6"]})
    assert code_families.main(["check"]).errors
