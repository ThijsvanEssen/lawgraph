"""ECHR HUDOC retrieval against a real (recorded) results page."""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.echr import EchrClient
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline
from tests.fakes import RawSourcesFake

PAGE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "hudoc_results_page.json").read_text()
)  # 2 real judgments, each wrapped as {"columns": {...}}


def _client(responses: list[Any], calls: list[dict]) -> EchrClient:
    client = EchrClient.__new__(EchrClient)  # no HTTP session needed

    def fake_get(path, *, params=None, timeout=30, **_kw):
        calls.append(params)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(json=lambda: response)

    client._get_raw_with_retry = fake_get  # type: ignore[method-assign]
    return client


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.stored: list[dict[str, Any]] = []

    def insert_raw_source(self, **kw: Any) -> None:
        self.stored.append(kw)


def test_the_columns_of_each_result_are_the_judgment() -> None:
    judgments = _client([PAGE], []).search_judgments(respondent="NLD")
    assert [j["itemid"] for j in judgments] == ["001-252409", "001-252192"]
    assert judgments[1]["docname"] == "CASE OF A.A. v. THE NETHERLANDS"
    assert judgments[0]["kpdate"] == "2026-09-08T00:00:00"


def test_every_judgment_becomes_a_raw_record() -> None:
    store = _Store()
    pipeline = ECHRRetrievePipeline(store=store, client=_client([PAGE], []))
    result = pipeline.run_full()
    assert (result.created, result.errors) == (2, [])
    assert [r["external_id"] for r in store.stored] == ["001-252409", "001-252192"]
    assert store.stored[0]["payload_json"]["itemid"] == "001-252409"
    assert store.stored[0]["meta"]["appno"] == "7481/23"


def test_a_failing_request_raises_instead_of_an_empty_result() -> None:
    client = _client([requests.ConnectionError("no route")], [])
    with pytest.raises(requests.ConnectionError):
        client.search_judgments()


def test_a_failing_request_is_an_error_of_the_run() -> None:
    pipeline = ECHRRetrievePipeline(
        store=_Store(), client=_client([requests.ConnectionError("no route")], [])
    )
    result = pipeline.run_full()
    assert result.created == 0
    assert result.errors and "no route" in result.errors[0]


def test_the_incremental_query_filters_on_the_date() -> None:
    calls: list[dict] = []
    _client([{"results": []}], calls).search_judgments(since_date="2026-01-01")
    assert "kpdate>=2026-01-01T00:00:00.000Z" in calls[0]["query"]
