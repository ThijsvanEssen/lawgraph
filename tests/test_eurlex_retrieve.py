"""EUR-Lex retrieval: what is listed, what is skipped, and what an interrupted run keeps."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.eu import EUClient
from lawgraph.config.constants import RAW_KIND_EU_CELEX, SOURCE_EURLEX
from lawgraph.core.time import iso_timestamp
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from tests.fakes import InMemoryStore, raw_record

pytestmark = pytest.mark.usefixtures("raw_reads")


def _http_error(status: int) -> requests.HTTPError:
    return requests.HTTPError(
        f"{status} Client Error", response=SimpleNamespace(status_code=status)
    )


# ── listing ──────────────────────────────────────────────────────────────────


def _client(pages: list[Any], queries: list[str]) -> EUClient:
    client = EUClient.__new__(EUClient)  # no HTTP session needed

    def fake_get(url, *, params=None, timeout=30, **_kw):
        queries.append(params["query"])
        page = pages.pop(0)
        if isinstance(page, Exception):
            raise page
        bindings = [{"celex": {"value": celex}} for celex in page]
        return SimpleNamespace(json=lambda: {"results": {"bindings": bindings}})

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


def test_only_directives_are_listed_by_default() -> None:
    queries: list[str] = []
    ids = _client([["32010L0064"]], queries).enumerate_all_ids()
    assert ids == ["32010L0064"]
    assert len(queries) == 1
    assert "cdm:directive" in queries[0]


def test_the_types_can_be_chosen() -> None:
    queries: list[str] = []
    _client([[], []], queries).enumerate_all_ids(cdm_types=("regulation", "decision"))
    assert ["cdm:regulation" in queries[0], "cdm:decision" in queries[1]] == [True] * 2


def test_corrigenda_are_left_out_of_the_query() -> None:
    queries: list[str] = []
    _client([[]], queries).enumerate_all_ids()
    assert 'FILTER(!CONTAINS(?celex, "("))' in queries[0]


def test_a_failing_page_raises_instead_of_returning_a_cut_off_list() -> None:
    client = _client([["32010L0064"] * 500, requests.HTTPError("500 Server Error")], [])
    with pytest.raises(RuntimeError, match="offset=500"):
        client.enumerate_all_ids()


def test_a_failed_listing_is_an_error_of_the_full_run() -> None:
    pipeline = EurlexRetrievePipeline(
        store=InMemoryStore(), eu_client=_client([requests.HTTPError("500")], [])
    )
    result = pipeline.run_full()
    assert result.errors and "enumeration failed" in result.errors[0]
    assert result.created == 0


def test_an_empty_nim_listing_is_an_error_not_a_silent_success() -> None:
    pipeline = EurlexRetrievePipeline(
        store=InMemoryStore(), eu_client=_client([[]], [])
    )
    result = pipeline.run_nim()
    assert result.errors and "no national implementation measures" in result.errors[0]


# ── retrieving ───────────────────────────────────────────────────────────────


# When an interrupted run stored what a rerun finds.
AN_HOUR_AGO = iso_timestamp(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))


def _store(events: list[str], recent: Iterable[str] = ()) -> InMemoryStore:
    """A store that adds a ``store`` event per record written to *events*."""
    store = InMemoryStore(
        raw=[
            raw_record(SOURCE_EURLEX, RAW_KIND_EU_CELEX, celex, fetched_at=AN_HOUR_AGO)
            for celex in recent
        ]
    )
    write = store.insert_raw_sources

    def logged(docs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
        events.extend(f"store {doc['external_id']}" for doc in docs)
        return write(docs)

    store.insert_raw_sources = logged  # type: ignore[method-assign]
    return store


def _written(store: InMemoryStore) -> list[str]:
    """The acts this run stored."""
    return [
        doc["external_id"]
        for doc in store.raw.values()
        if doc["fetched_at"] != AN_HOUR_AGO
    ]


class _Eu:
    def __init__(self, outcomes: dict[str, Any], events: list[str]) -> None:
        self.outcomes = outcomes
        self.events = events

    def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
        self.events.append(f"fetch {celex}")
        outcome = self.outcomes[celex]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _run(outcomes: dict[str, Any]) -> tuple[Any, InMemoryStore, list[str]]:
    events: list[str] = []
    store = _store(events)
    pipeline = EurlexRetrievePipeline(store=store, eu_client=_Eu(outcomes, events))
    return pipeline.run(celex_ids=list(outcomes)), store, events


def test_an_act_without_html_is_skipped_not_an_error() -> None:
    result, store, _ = _run(
        {"32010L0064": "<html/>", "31983L0091R(03)": _http_error(404)}
    )
    assert (result.created, result.skipped, result.errors) == (1, 1, [])
    assert sorted(_written(store)) == [
        "31983L0091R(03)",
        "32010L0064",
    ]  # one as missing


def test_other_failures_are_skipped_too_and_the_run_continues() -> None:
    result, store, _ = _run(
        {
            "31990L0001": _http_error(503),
            "31990L0002": requests.ConnectionError("reset"),
            "31990L0003": "<html/>",
        }
    )
    assert (result.created, result.skipped) == (1, 2)
    assert _written(store) == ["31990L0003"]


def test_an_interrupted_run_keeps_what_it_stored() -> None:
    events: list[str] = []
    store = _store(events)

    class Interrupted(_Eu):
        def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
            if celex == "32010L0065":
                raise KeyboardInterrupt
            return super().fetch_celex_html(celex, lang)

    pipeline = EurlexRetrievePipeline(
        store=store,
        eu_client=Interrupted({"32010L0064": "<html/>", "32010L0065": ""}, events),
    )
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(celex_ids=["32010L0064", "32010L0065"])
    assert _written(store) == ["32010L0064"]


def test_a_store_failure_is_an_error() -> None:
    pipeline = EurlexRetrievePipeline(
        store=InMemoryStore(refuse={"32010L0064"}),
        eu_client=_Eu({"32010L0064": "<html/>"}, []),
    )
    result = pipeline.run(celex_ids=["32010L0064"])
    assert result.created == 0
    assert result.errors and "32010L0064" in result.errors[0]


# ── retrieve all ─────────────────────────────────────────────────────────────


def test_retrieve_all_never_lists_eu_acts() -> None:
    from lawgraph.sources.registry import RetrieveCtx, find

    eurlex = find("retrieve", "eurlex")
    assert eurlex is not None and eurlex.argv_for_all is not None
    assert eurlex.argv_for_all(RetrieveCtx(since="1d", mode="full")) == []


def test_a_rerun_skips_the_acts_an_interrupted_run_stored() -> None:
    events: list[str] = []
    store = _store(events, recent=["32010L0064"])
    eu = _Eu({"32010L0064": "<html/>", "32010L0065": "<html/>"}, events)
    result = EurlexRetrievePipeline(store=store, eu_client=eu).run(
        celex_ids=["32010L0064", "32010L0065"]
    )
    assert _written(store) == ["32010L0065"]
    assert events == ["fetch 32010L0065", "store 32010L0065"]
    assert result.created == 1
