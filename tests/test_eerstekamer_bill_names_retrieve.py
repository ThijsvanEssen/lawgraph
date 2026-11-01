"""Which part of the list of every bill ``retrieve eerstekamer-bill-names`` reads, and what it
stores of a bill."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import RAW_KIND_EERSTEKAMER_BILL_NAME
from lawgraph.core.ek_bills import ListedBill
from lawgraph.pipelines.retrieve import eerstekamer_bill_names as retrieve


class _Client:
    def __init__(self) -> None:
        self.pages: list[int | None] = []

    def indexed_bills(self, *, pages: int | None) -> list[ListedBill]:
        self.pages.append(pages)
        return [
            ListedBill("/wetsvoorstel/9_oud", None, "", "Een oud voorstel"),
            ListedBill("/wetsvoorstel/33899_o", "33899", "", "Ontwerpen"),
        ]


def _fetch(since: dt.date | None) -> tuple[list[Any], _Client]:
    pipeline = retrieve.EerstekamerBillNamesRetrievePipeline(
        cast(Any, None), cast(EerstekamerSiteClient, _Client())
    )
    return list(pipeline.fetch(since=since)), cast(_Client, pipeline.client)


def test_a_window_reads_the_first_pages_and_stores_a_bill_with_a_dossier() -> None:
    records, client = _fetch(dt.date(2026, 11, 1))
    assert client.pages == [retrieve.WINDOW_PAGES]
    assert [(r.kind, r.external_id, r.payload_json) for r in records] == [
        (
            RAW_KIND_EERSTEKAMER_BILL_NAME,
            "/wetsvoorstel/33899_o",
            {"label": "33899", "name": "Ontwerpen"},
        )
    ]


def test_a_run_over_everything_reads_the_whole_list() -> None:
    assert _fetch(None)[1].pages == [None]
