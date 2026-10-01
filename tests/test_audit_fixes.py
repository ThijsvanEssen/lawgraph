"""Fixes from the review of legacy code: dead sources, silent caps and memory."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.core.models import PipelineResult
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
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
    def insert_raw_source(self, **kw: Any) -> None:
        self.stored = getattr(self, "stored", []) + [kw["external_id"]]


@pytest.fixture
def nothing_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    """No record stored before, none waiting for a retry."""
    for name in ("fetch_times", "ids_stored_since", "ids_waiting_for_retry"):
        monkeypatch.setattr(raw_queries, name, lambda store, **kw: iter([]))


class _DeadRs:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def fetch_ecli_content(self, ecli: str) -> str:
        self.calls += 1
        raise self.error


def test_rechtspraak_that_is_down_fails_instead_of_storing_nothing(
    nothing_stored: None,
) -> None:
    rs = _DeadRs(requests.ConnectionError("no route"))
    pipeline = RechtspraakRetrievePipeline(store=_Store(), rs_client=rs)
    result = pipeline.run(eclis=[f"ECLI:{n}" for n in range(200)])

    assert result.created == 0
    assert "seems to be down" in result.errors[0]
    # it stopped at the 25th failure; a few more were under way, it did not try all 200
    assert 25 <= rs.calls <= 25 + 4 * FETCH_WORKERS


def test_rechtspraak_missing_judgments_are_not_a_dead_source(
    nothing_stored: None,
) -> None:
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


def test_eurlex_that_is_down_fails_the_step(nothing_stored: None) -> None:
    pipeline = EurlexRetrievePipeline(
        store=_Store(), eu_client=_DeadEu(requests.ConnectionError("no route"))
    )
    result = pipeline.run(celex_ids=[f"3201{n:04d}L0001" for n in range(200)])
    assert "seems to be down" in result.errors[0]
    assert result.skipped == 25


def test_eurlex_acts_without_html_are_not_a_dead_source(nothing_stored: None) -> None:
    error = requests.HTTPError("404", response=SimpleNamespace(status_code=404))
    pipeline = EurlexRetrievePipeline(store=_Store(), eu_client=_DeadEu(error))
    result = pipeline.run(celex_ids=[f"3201{n:04d}L0001" for n in range(60)])
    assert result.errors == [] and result.skipped == 60


# ── no silent caps ───────────────────────────────────────────────────────────


def test_the_staatscourant_text_scan_lets_errors_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """That the texts have no row cap: ``tests/integration/test_large_results.py``."""

    def staatscourant_texts(store, since_date):
        raise RuntimeError("query failed")

    monkeypatch.setattr(semantic_bwb, "staatscourant_texts", staatscourant_texts)
    pipeline = StaatscourantSemanticPipeline(store=object())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="query failed"):
        pipeline._text_scan_match(set())


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


# ── memory: judgments are streamed, not loaded ───────────────────────────────


def test_the_rechtspraak_normalizer_streams_its_raw_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def iter_raw_records(store, *, batch_size, **kw):
        calls.append({"batch_size": batch_size})
        return iter([])

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)
    monkeypatch.setattr(
        raw_queries,
        "count_raw_records",  # the total for the progress line
        lambda *a, **kw: calls.append({"count": True}),
    )

    raw = RechtspraakNormalizePipeline(store=RawSourcesFake()).fetch_raw()  # type: ignore[arg-type]
    assert not isinstance(raw["content"], list)  # a generator: nothing is read yet
    assert calls == []
    list(raw["content"])
    # small batches: a judgment is tens of KB
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


class _Judgments:
    """Three judgments as ``normalize rechtspraak`` made them; the calls record the filters."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.eclis: list[list[str] | None] = []  # the filter of each paragraphs query
        self.recent: list[str] = []  # the since of each query for the recent ECLIs
        self.pulled = 0
        monkeypatch.setattr(
            semantic_rechtspraak, "judgment_paragraphs", self.judgment_paragraphs
        )
        monkeypatch.setattr(
            semantic_rechtspraak, "count_rechtspraak_judgments", lambda store: 3
        )
        monkeypatch.setattr(
            raw_queries, "judgment_eclis_fetched_since", self.eclis_fetched_since
        )
        # the citations the text no longer makes
        monkeypatch.setattr(semantic_edges, "remove_edges_from", lambda *a, **kw: 0)

    def eclis_fetched_since(self, store, since_iso):
        self.recent.append(since_iso)
        return iter(["ECLI:NL:HR:2020:1"])

    def judgment_paragraphs(self, store, *, eclis, batch_size):
        self.eclis.append(eclis)
        for n in range(3):
            self.pulled += 1
            yield {
                "_key": f"ecli_nl_hr_2020_{n}",
                "type": "judgment",
                "labels": ["Rechtspraak"],
                "props": {
                    "ecli": f"ECLI:NL:HR:2020:{n}",
                    "paragraphs": [
                        {"id": "p-1", "number": None, "kind": "body", "text": "x"}
                    ],
                },
            }


def _linker(store):
    pipeline = RechtspraakSemanticPipeline(store=store)
    pipeline._load_code_aliases = lambda: {"Sr": "BWBR0001854"}  # type: ignore[method-assign]
    pipeline._load_instrument_aliases = dict  # type: ignore[method-assign,assignment]
    return pipeline


def test_the_article_linker_reads_the_paragraphs_normalize_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not the XML: the paragraphs it serves are the ones whose ids it records."""
    judgments = _Judgments(monkeypatch)
    result = _linker(RawSourcesFake()).run()
    assert result.errors == [] and judgments.pulled == 3
    assert judgments.eclis == [None] and judgments.recent == []


def test_an_incremental_run_asks_for_the_judgments_retrieved_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judgments = _Judgments(monkeypatch)
    _linker(RawSourcesFake()).run(since=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc))
    assert judgments.recent == ["2025-01-01T00:00:00Z"]
    assert judgments.eclis == [["ECLI:NL:HR:2020:1"]]


# ── the BWB article linker ───────────────────────────────────────────────────


def test_recent_bwb_ids_are_asked_for_once_not_once_per_regulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline

    recent: list[str] = []
    asked: list[list[str]] = []

    def bwb_ids_fetched_since(store, since_iso):
        recent.append(since_iso)
        return iter(["BWBR0000002"])

    def articles_with_references(store, bwb_ids):
        asked.append(bwb_ids)
        return iter([])

    monkeypatch.setattr(raw_queries, "bwb_ids_fetched_since", bwb_ids_fetched_since)
    monkeypatch.setattr(
        semantic_bwb, "articles_with_references", articles_with_references
    )
    pipeline = BWBSemanticPipeline(store=object())  # type: ignore[arg-type]
    ids = [f"BWBR{n:07d}" for n in range(1, 500)]
    list(pipeline._load_articles(ids, since_iso="2025-01-01T00:00:00Z"))
    assert recent == ["2025-01-01T00:00:00Z"]
    assert asked == [["BWBR0000002"]]  # only the recent one of the 499


def test_a_failing_bwb_id_query_is_an_error_not_an_empty_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline

    def article_bwb_ids(store):
        raise RuntimeError("database gone")

    monkeypatch.setattr(semantic_bwb, "article_bwb_ids", article_bwb_ids)
    with pytest.raises(RuntimeError, match="database gone"):
        BWBSemanticPipeline(store=object())._load_bwb_ids_from_graph()  # type: ignore[arg-type]


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
