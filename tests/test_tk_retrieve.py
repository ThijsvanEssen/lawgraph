"""``retrieve tk``: the cases stored while the pages come in."""

from __future__ import annotations

import datetime as dt

import pytest
import requests

from lawgraph.pipelines.retrieve.tk import TKRetrievePipeline
from tests.fakes import (
    InMemoryStore,
    external_ids,
)

pytestmark = pytest.mark.usefixtures("raw_reads")


class _TkClient:
    def __init__(self, cases: list[dict], fail_after: int | None = None) -> None:
        self.cases = cases
        self.fail_after = fail_after
        self.top: object = "not called"

    def zaken_modified_since(self, since, *, top=100, **kw):
        self.top = top
        for number, case in enumerate(self.cases):
            if self.fail_after is not None and number >= self.fail_after:
                raise requests.ConnectionError("dropped")
            yield case

    def fetch_documents(self, **kw):
        raise AssertionError("tk-dossiers retrieves the documents, not tk")


def test_tk_cases_are_stored_while_the_pages_come_in() -> None:
    cases = [{"Id": f"zaak-{n}"} for n in range(5)]
    client = _TkClient(cases, fail_after=3)
    store = InMemoryStore()
    result = TKRetrievePipeline(store, client).run(since=dt.datetime(2024, 1, 1))

    assert external_ids(store) == ["zaak-0", "zaak-1", "zaak-2"]
    assert result.created == 3 and "after 3 records" in result.errors[0]


def test_tk_asks_for_every_case_and_for_no_documents() -> None:
    """``$top=0`` answers no records at all; the documents belong to tk-dossiers."""
    client = _TkClient([{"Id": "zaak-1"}])
    store = InMemoryStore()
    TKRetrievePipeline(store, client).run(since=dt.datetime(2024, 1, 1))

    assert client.top is None
    assert external_ids(store) == ["zaak-1"]
