"""Every source downloads its documents one way: stored, missing, failed, or the source is down.

A fake client per source answers one document, one HTTP 404 and then HTTP 500 until the
step stops; a listing that fails or comes back empty fails the step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from lawgraph.clients.base import UnexpectedAnswer
from lawgraph.config.constants import (
    RAW_KIND_ECHR_TEXT,
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_VERDRAG,
)
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.base import MAX_FAILURES_IN_A_ROW
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from lawgraph.pipelines.retrieve.rechtspraak import RechtspraakRetrievePipeline
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from lawgraph.pipelines.retrieve.staatscourant import StaatscourantRetrievePipeline
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline
from lawgraph.pipelines.retrieve.verdragenbank import VerdragenbankRetrievePipeline
from tests.fakes import InMemoryStore, http_error


def _answers() -> dict[str, Any]:
    answers: dict[str, Any] = {"doc-01": "<doc/>", "doc-02": http_error(404)}
    answers.update(
        {f"doc-{n:02d}": http_error(500) for n in range(3, 3 + MAX_FAILURES_IN_A_ROW)}
    )
    return answers


def _answer(answers: dict[str, Any], one: str) -> str:
    answer = answers[one]
    if isinstance(answer, Exception):
        raise answer
    return answer


def _kinds(store: InMemoryStore) -> list[tuple[str, str]]:
    """``(external_id, kind)`` of each raw record of *store*, in the order stored."""
    return [(doc["external_id"], doc["kind"]) for doc in store.raw.values()]


@pytest.fixture(autouse=True)
def nothing_stored(raw_reads: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raw_queries, "echr_items", lambda store: iter([]))


# ── one pipeline per source, run over the answers ───────────────────────────


def _rechtspraak(store: InMemoryStore, answers: dict[str, Any]) -> PipelineResult:
    client = type("RS", (), {})()
    client.fetch_ecli_content = lambda ecli: _answer(answers, ecli)
    return RechtspraakRetrievePipeline(store, rs_client=client).run(  # type: ignore[arg-type]
        eclis=list(answers)
    )


def _eurlex(store: InMemoryStore, answers: dict[str, Any]) -> PipelineResult:
    client = type("EU", (), {})()
    client.fetch_celex_html = lambda celex, lang="NL": _answer(answers, celex)
    return EurlexRetrievePipeline(store, eu_client=client).run(  # type: ignore[arg-type]
        celex_ids=list(answers)
    )


def _staatscourant(store: InMemoryStore, answers: dict[str, Any]) -> PipelineResult:
    client = type("Stcrt", (), {})()
    client.fetch_publication_xml = lambda identifier: _answer(answers, identifier)
    return StaatscourantRetrievePipeline(store, client=client).run(  # type: ignore[arg-type]
        identifiers=list(answers)
    )


def _tk_content(
    store: InMemoryStore, answers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> PipelineResult:
    papers = [{"identifier": one, "key": one, "date": None} for one in answers]
    monkeypatch.setattr(_gaps, "kamerstuk_gaps", lambda store, kinds: papers)
    client = type("Kst", (), {})()
    client.fetch_kamerstuk_xml = lambda identifier: _answer(answers, identifier)
    return TKContentRetrievePipeline(store=store, client=client).run()  # type: ignore[arg-type]


def _verdragenbank(store: InMemoryStore, answers: dict[str, Any]) -> PipelineResult:
    client = type("Vb", (), {})()
    client.enumerate_treaties = lambda max_records=None: [
        {"uri": f"https://x/vd/{one}", "item_url": f"https://x/{one}.xml"}
        for one in answers
    ]
    client.fetch_treaty_xml = lambda url: _answer(
        answers, url.rsplit("/", 1)[-1].removesuffix(".xml")
    )
    return VerdragenbankRetrievePipeline(store, client=client).run()  # type: ignore[arg-type]


def _echr(store: InMemoryStore, answers: dict[str, Any]) -> PipelineResult:
    client = type("Hudoc", (), {})()
    client.search_judgments = lambda **kw: [
        {"itemid": one, "ecli": None, "languageisocode": "ENG"} for one in answers
    ]
    client.fetch_document_xml = lambda item_id: _answer(answers, item_id)
    return ECHRRetrievePipeline(store, client=client).run()  # type: ignore[arg-type]


def _run(
    source: str,
    store: InMemoryStore,
    answers: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> PipelineResult:
    if source == "tk-content":
        return _tk_content(store, answers, monkeypatch)
    runs: dict[str, Callable[[InMemoryStore, dict[str, Any]], PipelineResult]] = {
        "rechtspraak": _rechtspraak,
        "eurlex": _eurlex,
        "staatscourant": _staatscourant,
        "verdragenbank": _verdragenbank,
    }
    return runs[source](store, answers)


@pytest.mark.parametrize(
    "source",
    ["rechtspraak", "eurlex", "staatscourant", "tk-content", "verdragenbank"],
)
def test_a_document_a_404_and_a_source_that_goes_down(
    source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = InMemoryStore()
    result = _run(source, store, _answers(), monkeypatch)

    documents = [(one, kind) for one, kind in _kinds(store) if kind != RAW_KIND_VERDRAG]
    assert documents[0][0] == "doc-01"
    assert not documents[0][1].endswith(RAW_KIND_MISSING_SUFFIX)
    assert documents[1][0] == "doc-02"
    assert documents[1][1].endswith(RAW_KIND_MISSING_SUFFIX)
    assert len(documents) == 2  # a failed download stores nothing
    assert result.created == len(store.raw) - 1  # all but the missing record
    assert any("seems to be down" in error for error in result.errors)
    assert any("download failed (HTTP 500)" in error for error in result.errors)


def test_hudoc_has_no_text_for_a_5xx_but_many_in_a_row_are_the_host() -> None:
    store = InMemoryStore()
    result = _echr(store, _answers())

    texts = [
        (one, kind)
        for one, kind in _kinds(store)
        if kind.startswith(RAW_KIND_ECHR_TEXT)
    ]
    assert texts[0] == ("doc-01", RAW_KIND_ECHR_TEXT)
    missing = [one for one, kind in texts if kind.endswith(RAW_KIND_MISSING_SUFFIX)]
    # the 404 and every 5xx before the last are remembered as missing
    assert missing == [f"doc-{n:02d}" for n in range(2, 2 + MAX_FAILURES_IN_A_ROW)]
    assert any("seems to be down" in error for error in result.errors)


def test_hudoc_answer_that_is_no_docx_is_missing_and_a_bug_ends_the_step() -> None:
    store = InMemoryStore()
    result = _echr(store, {"doc-01": UnexpectedAnswer("HUDOC doc-01: no DOCX")})
    assert result.errors == []
    ((_, kind),) = [r for r in _kinds(store) if r[1].startswith(RAW_KIND_ECHR_TEXT)]
    assert kind.endswith(RAW_KIND_MISSING_SUFFIX)

    result = _echr(InMemoryStore(), {"doc-01": AttributeError("no such thing")})
    assert any("AttributeError" in error for error in result.errors)


@pytest.mark.parametrize(
    "source",
    ["rechtspraak", "eurlex", "staatscourant", "tk-content", "verdragenbank"],
)
def test_a_bug_in_a_client_is_no_failure_of_the_source(
    source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = {f"doc-{n}": AttributeError("no such thing") for n in range(30)}
    result = _run(source, InMemoryStore(), answers, monkeypatch)
    assert any("AttributeError" in error for error in result.errors)
    assert not any("down" in error for error in result.errors)


# ── listings ─────────────────────────────────────────────────────────────────


class _Lister:
    """Every listing of a source fails with *answer*, or comes back as *answer*."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def listing(*args: Any, **kwargs: Any) -> Any:
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

        return listing


LISTINGS: dict[str, Callable[[Any], PipelineResult]] = {
    "bwb full": lambda c: BWBRetrievePipeline(InMemoryStore(), client=c).run_full(),  # type: ignore[arg-type]
    "staatsblad full": lambda c: StaatsbladRetrievePipeline(
        InMemoryStore(), client=c
    ).run_full(),  # type: ignore[arg-type]
    "staatscourant full": lambda c: StaatscourantRetrievePipeline(  # type: ignore[arg-type]
        InMemoryStore(), client=c
    ).run_full(),
    "eurlex full": lambda c: EurlexRetrievePipeline(
        InMemoryStore(), eu_client=c
    ).run_full(),  # type: ignore[arg-type]
    "eurlex nim": lambda c: EurlexRetrievePipeline(
        InMemoryStore(), eu_client=c
    ).run_nim(),  # type: ignore[arg-type]
    "eurlex cjeu": lambda c: EurlexRetrievePipeline(
        InMemoryStore(), eu_client=c
    ).run_cjeu(),  # type: ignore[arg-type]
    "eurlex cjeu of acts": lambda c: EurlexRetrievePipeline(  # type: ignore[arg-type]
        InMemoryStore(), eu_client=c
    ).run_cjeu(celex_ids=["32016R0679"]),
    "eurlex com": lambda c: EurlexRetrievePipeline(
        InMemoryStore(), eu_client=c
    ).run_com(  # type: ignore[arg-type]
        celex_ids=["32016R0679"]
    ),
}


@pytest.mark.parametrize("mode", LISTINGS)
@pytest.mark.parametrize(
    "answer", [RuntimeError("SPARQL endpoint down"), [], {}], ids=["fails", "[]", "{}"]
)
def test_a_listing_that_fails_or_is_empty_fails_the_step(
    mode: str, answer: Any
) -> None:
    result = LISTINGS[mode](_Lister(answer))
    assert result.errors, mode


def test_com_proposals_without_acts_to_look_them_up_for_fail_the_step() -> None:
    lister = _Lister(["52020PC0001"])
    result = EurlexRetrievePipeline(InMemoryStore(), eu_client=lister).run_com(
        celex_ids=[]
    )  # type: ignore[arg-type]
    assert result.errors


def test_an_empty_staatscourant_window_is_nothing_to_do() -> None:
    result = StaatscourantRetrievePipeline(InMemoryStore(), client=_Lister([])).run(  # type: ignore[arg-type]
        since="2026-10-01"
    )
    assert result.errors == []
