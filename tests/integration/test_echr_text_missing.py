"""A text HUDOC cannot convert does not fail ``retrieve echr``, on the test server.

HUDOC answers HTTP 500 for some items, run after run (001-208029 on lawgraph_small: 2 of
30 texts), and a migration chained with ``&&`` stopped there. Such an item is skipped and
remembered as missing: the run succeeds and the next run does not ask for it again.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import requests

from lawgraph.clients.echr import EchrClient
from lawgraph.config.constants import (
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_ECHR_TEXT,
    RAW_KIND_MISSING_SUFFIX,
    SOURCE_ECHR,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline

BROKEN = "001-208029"


class _Hudoc(EchrClient):
    """No new judgments; every text but that of ``BROKEN``."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def search_judgments(self, **_kw: Any) -> list[dict[str, Any]]:
        return []

    def fetch_document_xml(self, item_id: str) -> str:
        self.asked.append(item_id)
        if item_id == BROKEN:
            raise requests.HTTPError(
                "500 Server Error", response=SimpleNamespace(status_code=500)
            )
        return f"<w:document>{item_id}</w:document>"


def _judgment(item_id: str, number: int) -> dict[str, Any]:
    return {
        "itemid": item_id,
        "ecli": f"ECLI:CE:ECHR:2021:0101JUD00{number:05d}20",
        "languageisocode": "ENG",
        "docname": f"CASE OF X v. THE NETHERLANDS ({number})",
        "respondent": "NLD",
    }


def test_a_text_hudoc_cannot_convert_is_skipped_and_not_asked_for_again(
    database: str,
) -> None:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for number, item_id in enumerate(("001-200001", BROKEN, "001-200003")):
            writer.add(
                raw_source_doc(
                    source=SOURCE_ECHR,
                    kind=RAW_KIND_ECHR_JUDGMENT,
                    external_id=item_id,
                    payload_json=_judgment(item_id, number),
                )
            )

    hudoc = _Hudoc()
    result = ECHRRetrievePipeline(store, client=hudoc).run(respondent="NLD")
    assert result.errors == [] and result.skipped == 1 and result.created == 2

    kinds = {
        row["external_id"]: row["kind"]
        for row in store.query(
            "FOR r IN raw_sources FILTER r.source == @s AND r.kind LIKE 'echr-judgment-docx%' "
            "RETURN r",
            {"s": SOURCE_ECHR},
        )
    }
    assert kinds == {
        "001-200001": RAW_KIND_ECHR_TEXT,
        "001-200003": RAW_KIND_ECHR_TEXT,
        BROKEN: RAW_KIND_ECHR_TEXT + RAW_KIND_MISSING_SUFFIX,
    }

    again = _Hudoc()
    result = ECHRRetrievePipeline(store, client=again).run(respondent="NLD")
    assert result.errors == [] and again.asked == []
