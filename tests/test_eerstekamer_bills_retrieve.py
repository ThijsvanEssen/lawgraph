"""Which bill pages ``retrieve eerstekamer-bills`` reads: those its committees list (the older
pages only on a run over everything) and those voted on since the window, each once."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.core.eerstekamer_bills import FINISHED, ListedBill
from lawgraph.pipelines.retrieve import eerstekamer_bills as retrieve

SITE = "https://www.eerstekamer.nl"


class _Client:
    def __init__(self) -> None:
        self.older: list[bool] = []

    def listed_bills(self, *, older: bool) -> list[ListedBill]:
        self.older.append(older)
        return [
            ListedBill("/wetsvoorstel/2_b", "2", "In schriftelijke voorbereiding"),
            # on the lists of two committees: the first heading stays
            ListedBill("/wetsvoorstel/2_b", "2", "Gereed voor plenaire behandeling"),
            # finished: on a window only when voted on in it
            ListedBill("/wetsvoorstel/3_c", "3", FINISHED),
            ListedBill("/wetsvoorstel/1_a", "1", FINISHED),
        ]

    def bill_page(self, path: str) -> tuple[str, str]:
        return SITE + path, f"<html>{path}</html>"


def _fetch(monkeypatch: Any, since: dt.date | None) -> tuple[list[Any], _Client, list]:
    asked: list[Any] = []

    def voted(store: Any, day: str | None) -> list[str]:
        asked.append(day)
        return [SITE + "/wetsvoorstel/1_a", SITE + "/wetsvoorstel/2_b", "https://x/y"]

    monkeypatch.setattr(retrieve.normalize_ek, "voted_bill_urls", voted)
    pipeline = object.__new__(retrieve.EerstekamerBillsRetrievePipeline)
    client = _Client()
    pipeline.client = client  # type: ignore[assignment]
    pipeline.store = None  # type: ignore[assignment]
    return list(pipeline.fetch(since=since)), client, asked


def test_the_bills_listed_and_voted_on_each_once(monkeypatch: Any) -> None:
    records, client, asked = _fetch(monkeypatch, dt.date(2026, 9, 1))
    assert [(r.external_id, r.meta["status"]) for r in records] == [
        ("/wetsvoorstel/1_a", None),
        ("/wetsvoorstel/2_b", "In schriftelijke voorbereiding"),
    ]
    assert records[0].meta["url"] == SITE + "/wetsvoorstel/1_a"
    # a window reads the lists' first pages and the votes since its start
    assert (client.older, asked) == ([False], ["2026-09-01"])


def test_a_run_over_everything_reads_the_older_pages(monkeypatch: Any) -> None:
    records, client, asked = _fetch(monkeypatch, None)
    assert (client.older, asked) == ([True], [None])
    assert [(r.external_id, r.meta["status"]) for r in records] == [
        ("/wetsvoorstel/1_a", FINISHED),
        ("/wetsvoorstel/2_b", "In schriftelijke voorbereiding"),
        ("/wetsvoorstel/3_c", FINISHED),
    ]
