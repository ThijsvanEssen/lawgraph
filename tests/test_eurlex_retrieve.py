"""EUR-Lex retrieval: what is listed, what is skipped, and what an interrupted run keeps."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.eu import EUClient
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from lawgraph.sources.registry import SOURCES
from tests.fakes import RawSourcesFake


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
        store=_Store(), eu_client=_client([requests.HTTPError("500")], [])
    )
    result = pipeline.run_full()
    assert result.errors and "enumeration failed" in result.errors[0]
    assert result.created == 0


def test_an_empty_nim_listing_is_an_error_not_a_silent_success() -> None:
    pipeline = EurlexRetrievePipeline(store=_Store(), eu_client=_client([[]], []))
    result = pipeline.run_nim()
    assert result.errors and "no national implementation measures" in result.errors[0]


# ── retrieving ───────────────────────────────────────────────────────────────


class _Store(RawSourcesFake):
    def __init__(
        self, events: list[str] | None = None, recent: list[str] | None = None
    ) -> None:
        self.stored: list[str] = []
        self.events = events if events is not None else []
        self.recent = (
            recent or []
        )  # what an interrupted run stored in the last 24 hours

    def query(self, aql: str, bind_vars: dict | None = None) -> list[str]:
        return list(self.recent)

    def insert_raw_source(self, *, external_id: str, **_kw: Any) -> None:
        self.stored.append(external_id)
        self.events.append(f"store {external_id}")


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


def _run(outcomes: dict[str, Any]) -> tuple[Any, _Store, list[str]]:
    events: list[str] = []
    store = _Store(events)
    pipeline = EurlexRetrievePipeline(store=store, eu_client=_Eu(outcomes, events))
    return pipeline.run(celex_ids=list(outcomes)), store, events


def test_an_act_without_html_is_skipped_not_an_error() -> None:
    result, store, _ = _run(
        {"32010L0064": "<html/>", "31983L0091R(03)": _http_error(404)}
    )
    assert (result.created, result.skipped, result.errors) == (1, 1, [])
    assert sorted(store.stored) == ["31983L0091R(03)", "32010L0064"]  # one as missing


def test_other_failures_are_skipped_too_and_the_run_continues() -> None:
    result, store, _ = _run(
        {
            "31990L0001": _http_error(503),
            "31990L0002": requests.ConnectionError("reset"),
            "31990L0003": "<html/>",
        }
    )
    assert (result.created, result.skipped) == (1, 2)
    assert store.stored == ["31990L0003"]


def test_an_interrupted_run_keeps_what_it_stored() -> None:
    events: list[str] = []
    store = _Store(events)

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
    assert store.stored == ["32010L0064"]


def test_a_store_failure_is_an_error() -> None:
    class Broken(_Store):
        def insert_raw_source(self, **kw: Any) -> None:
            raise RuntimeError("database gone")

    pipeline = EurlexRetrievePipeline(
        store=Broken(), eu_client=_Eu({"32010L0064": "<html/>"}, [])
    )
    result = pipeline.run(celex_ids=["32010L0064"])
    assert result.created == 0
    assert result.errors and "32010L0064" in result.errors[0]


# ── retrieve all ─────────────────────────────────────────────────────────────


def test_retrieve_all_never_lists_eu_acts() -> None:
    from lawgraph.sources.registry import RetrieveCtx

    eurlex = next(s for s in SOURCES if s.id == "eurlex")
    assert eurlex.retrieve_argv_builder is not None
    assert eurlex.retrieve_argv_builder(RetrieveCtx(since="1d", mode="full")) == []


def test_a_rerun_skips_the_acts_an_interrupted_run_stored() -> None:
    events: list[str] = []
    store = _Store(events, recent=["32010L0064"])
    eu = _Eu({"32010L0064": "<html/>", "32010L0065": "<html/>"}, events)
    result = EurlexRetrievePipeline(store=store, eu_client=eu).run(
        celex_ids=["32010L0064", "32010L0065"]
    )
    assert store.stored == ["32010L0065"]
    assert events == ["fetch 32010L0065", "store 32010L0065"]
    assert result.created == 1
