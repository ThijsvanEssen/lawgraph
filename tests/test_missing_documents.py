"""A document the source does not have is remembered, not asked for again on every run."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from lawgraph.config.constants import RAW_KIND_EU_CELEX, RAW_KIND_MISSING_SUFFIX
from lawgraph.pipelines.retrieve.base import FailureStreak, SourceDown
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline

MISSING_KIND = RAW_KIND_EU_CELEX + RAW_KIND_MISSING_SUFFIX


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


class _Store:
    """raw_sources as ``{(kind, external_id): doc}``; answers the 'stored since' query."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.cutoffs: dict[str, str] = {}

    def insert_raw_sources(self, docs: list[dict[str, Any]]) -> list:
        for doc in docs:
            self.docs[(doc["kind"], doc["external_id"])] = doc
        return []

    def query(self, aql: str, bind_vars: dict | None = None, **_kw: Any) -> list[str]:
        bind = bind_vars or {}
        self.cutoffs[bind["kind"]] = bind["cutoff"]
        return [
            external_id
            for (kind, external_id), doc in self.docs.items()
            if kind == bind["kind"] and doc["fetched_at"] >= bind["cutoff"]
        ]


class _Eu:
    def __init__(self, outcomes: dict[str, Any]) -> None:
        self.outcomes = outcomes
        self.asked: list[str] = []

    def fetch_celex_html(self, celex: str, *, lang: str = "NL") -> str:
        self.asked.append(celex)
        outcome = self.outcomes[celex]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_a_404_is_stored_as_missing_and_not_asked_for_again() -> None:
    store = _Store()
    eu = _Eu({"32010L0064": "<html/>", "31958R0001(01)": _http_error(404)})
    ids = ["32010L0064", "31958R0001(01)"]

    first = EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=ids)  # type: ignore[arg-type]
    assert (first.created, first.skipped, first.errors) == (1, 1, [])
    missing = store.docs[(MISSING_KIND, "31958R0001(01)")]
    assert missing["payload_text"] is None
    assert missing["meta"] == {"kind": RAW_KIND_EU_CELEX, "status": 404}

    eu.asked.clear()
    # The next iteration of expand-graph: the act that exists was stored today (resume), the
    # missing one is known to be missing.
    second = EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=ids)  # type: ignore[arg-type]
    assert eu.asked == [] and second.created == 0


def test_a_missing_document_is_tried_again_after_thirty_days() -> None:
    store = _Store()
    eu = _Eu({"31958R0001(01)": _http_error(404)})
    EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=["31958R0001(01)"])  # type: ignore[arg-type]

    store.docs[(MISSING_KIND, "31958R0001(01)")]["fetched_at"] = "2020-01-01T00:00:00Z"
    eu.asked.clear()
    EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=["31958R0001(01)"])  # type: ignore[arg-type]
    assert eu.asked == ["31958R0001(01)"]


def test_a_failure_that_is_not_a_404_is_not_remembered() -> None:
    store = _Store()
    eu = _Eu({"32010L0064": _http_error(503)})
    EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=["32010L0064"])  # type: ignore[arg-type]
    assert store.docs == {}


def test_a_run_of_4xx_answers_does_not_mean_the_source_is_down() -> None:
    streak = FailureStreak("EUR-Lex", limit=3)
    for _ in range(10):
        streak.failed("some act", _http_error(400))
    for status in (500, 429):
        streak.failed("some act", _http_error(status))
    with pytest.raises(SourceDown):
        streak.failed("some act", requests.ConnectionError("no route"))
