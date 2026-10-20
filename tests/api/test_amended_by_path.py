"""An amending publication of ``/api/instruments/{bwb_id}/amended-by`` has its address."""

from __future__ import annotations

from lawgraph.api.schemas.instruments import AmendingInstrumentDTO


def test_an_amending_publication_has_its_readable_address() -> None:
    row = {
        "instrument": {
            "id": "instruments/stb_2019_33",
            "key": "stb_2019_33",
            "props": {"official_id": "stb-2019-33", "publication_kind": "Stb"},
        },
        "amends": 2,
    }
    item = AmendingInstrumentDTO.from_row(row, {}).model_dump()
    assert item["path"] == "/stb/2019/33"
