"""The Grondwet as a BWB toestand, and the raw records of it the normalize tests read."""

from __future__ import annotations

from typing import Any

from tests.paths import fixture_text

XML = fixture_text("bwb_grondwet_toestand.xml")


GRONDWET = "BWBR0001840"


def bwb_record(xml: str, start: str, end: str) -> dict[str, Any]:
    return {
        "key": f"r-{start}",
        "external_id": f"{GRONDWET}@{start}",
        "payload_text": xml,
        "meta": {"bwb_id": GRONDWET, "start_date": start, "end_date": end},
    }


def older_toestand(xml: str) -> str:
    """The same regulation as it was before artikel 7 last changed (real XML, 2 attrs edited)."""
    old = xml.replace('versie-id="25689252"', 'versie-id="111"')
    return old.replace('inwerking="2018-12-21"', 'inwerking="2002-03-21"', 1)
