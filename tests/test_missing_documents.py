"""A document the source does not have is remembered, not asked for again on every run."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from lawgraph.config.constants import (
    RAW_KIND_EU_CELEX,
    RAW_KIND_MISSING_SUFFIX,
    SOURCE_EURLEX,
)
from lawgraph.db import raw_key
from lawgraph.pipelines.retrieve.base import FailureStreak, SourceDown
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from tests.fakes import InMemoryStore, http_error

pytestmark = pytest.mark.usefixtures("raw_reads")

MISSING_KIND = RAW_KIND_EU_CELEX + RAW_KIND_MISSING_SUFFIX


def _missing(store: InMemoryStore, celex: str) -> dict[str, Any]:
    return store.raw[raw_key(SOURCE_EURLEX, MISSING_KIND, celex)]


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
    store = InMemoryStore()
    eu = _Eu({"32010L0064": "<html/>", "31958R0001(01)": http_error(404)})
    ids = ["32010L0064", "31958R0001(01)"]

    first = EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=ids)  # type: ignore[arg-type]
    assert (first.created, first.skipped, first.errors) == (1, 1, [])
    missing = _missing(store, "31958R0001(01)")
    assert missing["payload_text"] is None
    assert {k: missing["meta"][k] for k in ("kind", "status")} == {
        "kind": RAW_KIND_EU_CELEX,
        "status": 404,
    }
    # Read in a citation, not listed by the source: left alone for thirty days.
    assert missing["meta"]["retry_after"] > missing["fetched_at"][:4]

    eu.asked.clear()
    # The next iteration of expand-graph: the act that exists was stored today (resume), the
    # missing one is known to be missing.
    second = EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=ids)  # type: ignore[arg-type]
    assert eu.asked == [] and second.created == 0


def test_a_missing_document_is_tried_again_after_thirty_days() -> None:
    store = InMemoryStore()
    eu = _Eu({"31958R0001(01)": http_error(404)})
    EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=["31958R0001(01)"])  # type: ignore[arg-type]

    _missing(store, "31958R0001(01)")["meta"]["retry_after"] = "2020-01-01T00:00:00Z"
    eu.asked.clear()
    EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=["31958R0001(01)"])  # type: ignore[arg-type]
    assert eu.asked == ["31958R0001(01)"]


def test_a_failure_that_is_not_a_404_is_not_remembered() -> None:
    store = InMemoryStore()
    eu = _Eu({"32010L0064": http_error(503)})
    EurlexRetrievePipeline(store=store, eu_client=eu).run(celex_ids=["32010L0064"])  # type: ignore[arg-type]
    assert store.raw == {}


def test_a_run_of_4xx_answers_does_not_mean_the_source_is_down() -> None:
    streak = FailureStreak("EUR-Lex", limit=3)
    for _ in range(10):
        streak.failed("some act", http_error(400))
    for status in (500, 429):
        streak.failed("some act", http_error(status))
    with pytest.raises(SourceDown):
        streak.failed("some act", requests.ConnectionError("no route"))


def test_a_listed_document_is_asked_for_again_after_three_days() -> None:
    """The source named it itself: it is probably on its way, or the source is in maintenance."""
    import datetime as dt

    from lawgraph.pipelines.retrieve.base import missing_record

    now = dt.datetime.now(dt.UTC)

    def days(record) -> int:
        retry = dt.datetime.fromisoformat(
            record.meta["retry_after"].replace("Z", "+00:00")
        )
        return round((retry - now).total_seconds() / 86400)

    assert days(missing_record("rechtspraak", "rs-content", "ECLI:X", listed=True)) == 3
    assert days(missing_record("rechtspraak", "rs-content", "ECLI:X")) == 30


def test_a_source_that_refuses_everything_is_down_not_a_list_of_skips() -> None:
    streak = FailureStreak("Rechtspraak", limit=3)
    with pytest.raises(SourceDown):
        for _ in range(3):
            streak.failed("some judgment", http_error(403))
