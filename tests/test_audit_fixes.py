"""Fixes from the review of legacy code: dead sources, silent caps and memory."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.core.models import PipelineResult
from lawgraph.pipelines.normalize.rechtspraak import RechtspraakNormalizePipeline
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.base import FETCH_WORKERS, FailureStreak, SourceDown
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from lawgraph.pipelines.semantic.rechtspraak import (
    RechtspraakSemanticPipeline,
)
from lawgraph.pipelines.semantic.staatscourant import (
    StaatscourantSemanticPipeline,
)
from tests.fakes import RawSourcesFake

# ── a source that is down fails the step ─────────────────────────────────────


def test_a_streak_of_failures_means_the_source_is_down() -> None:
    streak = FailureStreak("Source", limit=3)
    streak.failed("a", RuntimeError("x"))
    streak.failed("b", RuntimeError("x"))
    with pytest.raises(
        SourceDown, match="3 requests in a row failed.*seems to be down"
    ):
        streak.failed("c", RuntimeError("boom"))


def test_a_success_ends_the_streak() -> None:
    streak = FailureStreak("Source", limit=3)
    for _ in range(10):
        streak.failed("a", RuntimeError("x"))
        streak.failed("b", RuntimeError("x"))
        streak.ok()  # never three in a row


class _Store(RawSourcesFake):
    def query(self, aql, bind_vars=None):
        return []

    def insert_raw_source(self, **kw: Any) -> None:
        self.stored = getattr(self, "stored", []) + [kw["external_id"]]


class _DeadRs:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def fetch_ecli_content(self, ecli: str) -> str:
        self.calls += 1
        raise self.error


def test_rechtspraak_that_is_down_fails_instead_of_storing_nothing() -> None:
    rs = _DeadRs(requests.ConnectionError("no route"))
    pipeline = RechtspraakRetrievePipeline(store=_Store(), rs_client=rs)
    result = pipeline.run(eclis=[f"ECLI:{n}" for n in range(200)])

    assert result.created == 0
    assert "seems to be down" in result.errors[0]
    # it stopped at the 25th failure; a few more were under way, it did not try all 200
    assert 25 <= rs.calls <= 25 + 4 * FETCH_WORKERS


def test_rechtspraak_missing_judgments_are_not_a_dead_source() -> None:
    not_found = requests.HTTPError("404", response=SimpleNamespace(status_code=404))
    rs = _DeadRs(not_found)
    pipeline = RechtspraakRetrievePipeline(store=_Store(), rs_client=rs)
    result = pipeline.run(eclis=[f"ECLI:{n}" for n in range(60)])
    assert result.errors == [] and rs.calls == 60


class _DeadEu:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
        raise self.error


def test_eurlex_that_is_down_fails_the_step() -> None:
    pipeline = EurlexRetrievePipeline(
        store=_Store(), eu_client=_DeadEu(requests.ConnectionError("no route"))
    )
    result = pipeline.run(celex_ids=[f"3201{n:04d}L0001" for n in range(200)])
    assert "seems to be down" in result.errors[0]
    assert result.skipped == 25


def test_eurlex_acts_without_html_are_not_a_dead_source() -> None:
    error = requests.HTTPError("404", response=SimpleNamespace(status_code=404))
    pipeline = EurlexRetrievePipeline(store=_Store(), eu_client=_DeadEu(error))
    result = pipeline.run(celex_ids=[f"3201{n:04d}L0001" for n in range(60)])
    assert result.errors == [] and result.skipped == 60


# ── no silent caps ───────────────────────────────────────────────────────────


def test_the_staatscourant_text_scan_has_no_row_cap_and_lets_errors_out() -> None:
    queries: list[str] = []

    class Store:
        def query(self, aql, bind_vars=None):
            queries.append(aql)
            raise RuntimeError("query failed")

    pipeline = StaatscourantSemanticPipeline(store=Store())
    with pytest.raises(RuntimeError, match="query failed"):
        pipeline._text_scan_match(set())
    assert "LIMIT" not in queries[0]


def test_a_gaps_run_says_when_it_takes_only_the_first_stubs(caplog) -> None:
    rows = [f"ECLI:{n}" for n in range(_gaps.MAX_GAPS_PER_RUN + 5)]
    with caplog.at_level("WARNING"):
        taken = _gaps._capped(rows, "stub judgments")
    assert len(taken) == _gaps.MAX_GAPS_PER_RUN
    assert any(
        "takes the first" in m and "stub judgments" in m for m in caplog.messages
    )


def test_below_the_cap_nothing_is_said(caplog) -> None:
    with caplog.at_level("WARNING"):
        assert _gaps._capped(["a", "b"], "x") == ["a", "b"]
    assert not caplog.messages


def test_the_gap_queries_are_not_capped_in_aql() -> None:
    seen: list[str] = []

    class Store:
        def query(self, aql, bind_vars=None):
            seen.append(aql)
            return iter([])

    _gaps.rechtspraak_gaps(Store())
    assert not any("LIMIT" in aql for aql in seen)


# ── memory: judgments are streamed, not loaded ───────────────────────────────


def test_the_rechtspraak_normalizer_streams_its_raw_records() -> None:
    calls: list[dict] = []

    class Store:
        def query(self, aql, bind_vars=None, *, batch_size=1000, **kw):
            calls.append({"batch_size": batch_size})
            return iter([])

    raw = RechtspraakNormalizePipeline(store=Store()).fetch_raw()
    assert not isinstance(raw["content"], list)  # a generator: nothing is read yet
    assert calls == []
    list(raw["content"])
    # calls[0] counts them for the progress line; small batches: a judgment is tens of KB
    assert calls[-1]["batch_size"] <= 200


def test_the_normalizer_keeps_no_nodes_after_writing_them() -> None:
    class Store:
        def bulk_insert_or_update_nodes(self, collection, docs):
            return len(docs), 0

    xml = "<open-rechtspraak><uitspraak><para>Tekst.</para></uitspraak></open-rechtspraak>"
    rows = iter(
        [
            {
                "external_id": f"ECLI:NL:HR:2025:{n}",
                "kind": "rs-content",
                "payload_text": xml,
                "meta": {"ecli": f"ECLI:NL:HR:2025:{n}"},
            }
            for n in range(3)
        ]
    )
    result = PipelineResult()
    out = RechtspraakNormalizePipeline(store=Store()).normalize_nodes(
        {"content": rows}, result
    )
    assert out == {"judgments": 3}


class _JudgmentStore:
    """raw_sources holds the XML of three judgments; the query carries the date filter."""

    def __init__(self) -> None:
        self.binds: list[dict] = []
        self.pulled = 0

    def query(self, aql, bind_vars=None, **kw):
        assert "raw_sources" in aql and "judgments" not in aql.split("RETURN")[0]
        if "COLLECT WITH COUNT" in aql:  # the total for the progress line
            return iter([3])
        self.binds.append(dict(bind_vars or {}))

        def cursor():
            for n in range(3):
                self.pulled += 1
                yield {
                    "ecli": f"ECLI:NL:HR:2020:{n}",
                    "xml": "<open>geen artikel</open>",
                }

        return cursor()


def _linker(store):
    pipeline = RechtspraakSemanticPipeline(store=store)
    pipeline._load_code_aliases = lambda: {"Sr": "BWBR0001854"}  # type: ignore[method-assign]
    pipeline._load_instrument_aliases = dict  # type: ignore[method-assign,assignment]
    return pipeline


def test_the_article_linker_reads_the_xml_where_retrieve_stored_it() -> None:
    """Not from the judgment node: the XML is not kept there (a third of the collection)."""
    store = _JudgmentStore()
    result = _linker(store).run()
    assert result.errors == [] and store.pulled == 3
    assert store.binds == [{"source": "rechtspraak", "kind": "rs-content"}]


def test_an_incremental_run_asks_for_the_judgments_fetched_since() -> None:
    store = _JudgmentStore()
    _linker(store).run(since=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc))
    assert store.binds[0]["since"] == "2025-01-01T00:00:00Z"


# ── the BWB article linker ───────────────────────────────────────────────────


def test_recent_bwb_ids_are_asked_for_once_not_once_per_regulation() -> None:
    from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline

    queries: list[str] = []

    class Store:
        def query(self, aql, bind_vars=None, **kw):
            queries.append(aql)
            return iter(["BWBR0000002"] if "raw_sources" in aql else [])

    pipeline = BWBSemanticPipeline(store=Store())
    ids = [f"BWBR{n:07d}" for n in range(1, 500)]
    list(pipeline._load_articles(ids, since_iso="2025-01-01T00:00:00Z"))
    assert sum("raw_sources" in q for q in queries) == 1


def test_a_failing_bwb_id_query_is_an_error_not_an_empty_graph() -> None:
    from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline

    class Store:
        def query(self, aql, bind_vars=None, **kw):
            raise RuntimeError("database gone")

    with pytest.raises(RuntimeError, match="database gone"):
        BWBSemanticPipeline(store=Store())._load_bwb_ids_from_graph()


# ── a failing write is an error of the step ──────────────────────────────────


def test_tk_dossiers_a_failing_write_is_an_error_not_only_a_log_line() -> None:
    from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline

    class Store(RawSourcesFake):
        def insert_raw_source(self, *, external_id, **kw):
            if external_id == "d2":
                raise RuntimeError("write failed")

    class Client:
        def fetch_dossiers(self, since=None):
            return iter([{"Id": "d1"}, {"Id": "d2"}, {"Id": "d3"}])

        def __getattr__(self, name):
            return lambda *a, **k: iter([])

    result = TKDossiersRetrievePipeline(store=Store(), client=Client()).run(
        since=dt.datetime(2024, 1, 1), skip_members=True
    )
    assert result.created == 2  # d1 and d3
    assert any("d2" in e and "write failed" in e for e in result.errors)


# ── a cursor that is worked on slowly must stay open ─────────────────────────


def test_the_query_cursor_outlives_a_consumer_that_works_on_every_batch() -> None:
    """The server drops a cursor unread for 30 s ("cursor not found"): semantic tk and
    tk-amends failed on it after streaming their documents."""
    from lawgraph.db.store import CURSOR_TTL_SECONDS, ArangoStore

    seen: dict[str, Any] = {}

    class Aql:
        def execute(self, aql, **kwargs):
            seen.update(kwargs)
            return iter([])

    store = ArangoStore.__new__(ArangoStore)
    store.db = SimpleNamespace(aql=Aql())
    store.query("FOR d IN docs RETURN d")

    assert seen["ttl"] == CURSOR_TTL_SECONDS >= 1800
    assert seen["batch_size"] == 1000


def test_a_caller_can_ask_for_a_different_ttl() -> None:
    from lawgraph.db.store import ArangoStore

    seen: dict[str, Any] = {}

    class Aql:
        def execute(self, aql, **kwargs):
            seen.update(kwargs)
            return iter([])

    store = ArangoStore.__new__(ArangoStore)
    store.db = SimpleNamespace(aql=Aql())
    store.query("RETURN 1", ttl=60)
    assert seen["ttl"] == 60
