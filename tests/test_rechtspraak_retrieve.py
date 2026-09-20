"""Rechtspraak index and content retrieval: paged, windowed, stored page by page."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import requests

from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline

PAGE_SIZE = 1000


def _index(entries: int) -> str:
    body = "".join(f"<entry><id>ECLI:NL:X:{n}</id></entry>" for n in range(entries))
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'


class _Rs:
    def __init__(
        self, pages: list[Any], contents: dict[str, Any] | None = None
    ) -> None:
        self.pages = pages
        self.contents = contents or {}
        self.index_calls: list[dict] = []

    def fetch_ecli_index_xml(self, modified_since=None, extra_params=None) -> str:
        self.index_calls.append({"since": modified_since, "params": extra_params})
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page

    def fetch_ecli_content(self, ecli: str) -> str:
        outcome = self.contents[ecli]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Store:
    def __init__(self, recent: list[str] | None = None) -> None:
        self.records: list[dict[str, Any]] = []
        self.recent = recent or []

    def query(self, aql: str, bind_vars: dict | None = None) -> list[str]:
        return list(self.recent)

    def insert_raw_source(self, **record: Any) -> None:
        self.records.append(record)


def _pipeline(rs: _Rs, store: _Store | None = None):
    store = store or _Store()
    return RechtspraakRetrievePipeline(store=store, rs_client=rs), store


SINCE = dt.datetime(2024, 9, 20, tzinfo=dt.timezone.utc)


def test_a_window_reads_every_page_not_just_the_first() -> None:
    rs = _Rs([_index(PAGE_SIZE), _index(PAGE_SIZE), _index(37)])
    pipeline, store = _pipeline(rs)

    result = pipeline.run_index(since=SINCE)

    assert result.created == 3 and result.errors == []
    assert [c["params"]["from"] for c in rs.index_calls] == ["0", "1000", "2000"]
    assert all(c["since"] == SINCE for c in rs.index_calls)
    assert all(c["params"]["max"] == "1000" for c in rs.index_calls)


def test_the_pages_of_a_window_are_keyed_by_window_and_offset() -> None:
    rs = _Rs([_index(PAGE_SIZE), _index(3)])
    pipeline, store = _pipeline(rs)
    pipeline.run_index(since=SINCE)

    assert [r["external_id"] for r in store.records] == [
        "index_2024-09-20_0",
        "index_2024-09-20_1000",
    ]
    assert store.records[0]["meta"]["full_load"] is False
    assert store.records[0]["meta"]["modified_since"] == SINCE.isoformat()


def test_a_full_load_is_marked_and_keyed_as_such() -> None:
    rs = _Rs([_index(2)])
    pipeline, store = _pipeline(rs)
    pipeline.run_full()

    assert store.records[0]["external_id"] == "index_all_0"
    assert store.records[0]["meta"]["full_load"] is True
    assert rs.index_calls[0]["since"] is None


def test_a_failing_page_keeps_the_pages_before_it_and_is_an_error() -> None:
    rs = _Rs([_index(PAGE_SIZE), requests.ConnectionError("dropped")])
    pipeline, store = _pipeline(rs)

    result = pipeline.run_index(since=SINCE)

    assert len(store.records) == 1  # page 0 is kept
    assert result.created == 1
    assert "from=1000" in result.errors[0] and "dropped" in result.errors[0]


def test_a_rerun_overwrites_the_same_pages() -> None:
    first, store = _pipeline(_Rs([_index(2)]))
    first.run_index(since=SINCE)
    second, _ = _pipeline(_Rs([_index(2)]), store)
    second.run_index(since=SINCE)
    assert [r["external_id"] for r in store.records] == ["index_2024-09-20_0"] * 2


# ── content ──────────────────────────────────────────────────────────────────


def test_each_ecli_is_stored_and_a_failing_one_is_skipped() -> None:
    rs = _Rs(
        [],
        {"ECLI:A": "<a/>", "ECLI:B": requests.ConnectionError("x"), "ECLI:C": "<c/>"},
    )
    pipeline, store = _pipeline(rs)
    result = pipeline.run(eclis=["ECLI:A", "ECLI:B", "ECLI:C"])
    assert [r["external_id"] for r in store.records] == ["ECLI:A", "ECLI:C"]
    assert result.created == 2


def test_a_rerun_skips_the_eclis_stored_in_the_last_24_hours() -> None:
    rs = _Rs([], {"ECLI:A": "<a/>", "ECLI:B": "<b/>"})
    pipeline, store = _pipeline(rs, _Store(recent=["ECLI:A"]))
    pipeline.run(eclis=["ECLI:A", "ECLI:B"])
    assert [r["external_id"] for r in store.records] == ["ECLI:B"]


def test_no_eclis_means_nothing_to_fetch() -> None:
    pipeline, store = _pipeline(_Rs([]))
    assert pipeline.run(eclis=[]).created == 0
    assert store.records == []


@pytest.mark.parametrize("mode", ["incremental", "full"])
def test_the_cli_reads_the_index_paged_in_both_modes(monkeypatch, mode) -> None:
    from lawgraph.pipelines import retrieve_cli

    rs = _Rs([_index(PAGE_SIZE), _index(5)])
    store = _Store()
    monkeypatch.setattr(retrieve_cli, "ArangoStore", lambda: store)
    monkeypatch.setattr(
        retrieve_cli,
        "RechtspraakRetrievePipeline",
        lambda s: RechtspraakRetrievePipeline(store=s, rs_client=rs),
    )
    retrieve_cli.retrieve_rechtspraak(["--mode", mode, "--since", "2024-09-20"])
    assert len(store.records) == 2
    assert (rs.index_calls[0]["since"] is None) == (mode == "full")
