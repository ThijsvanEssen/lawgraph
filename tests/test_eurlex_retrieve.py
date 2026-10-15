"""EUR-Lex retrieval: what is listed, what is skipped, and what an interrupted run keeps."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, cast

import pytest
import requests

from lawgraph.clients import eu
from lawgraph.clients.eu import EUClient
from lawgraph.config.constants import (
    RAW_KIND_EURLEX_CELEX,
    SOURCE_EURLEX,
)
from lawgraph.core.time import iso_timestamp
from lawgraph.pipelines.retrieve.eurlex import EurlexRetrievePipeline
from tests.fakes import InMemoryStore, ScriptedSession, Sent, http_error, raw_record
from tests.optional import present

pytestmark = pytest.mark.usefixtures("raw_reads")

XSD_STRING = "^^<http://www.w3.org/2001/XMLSchema#string>"


# ── listing ──────────────────────────────────────────────────────────────────


def _client(pages: list[Any], queries: list[str]) -> EUClient:
    """A client answered the CELEX numbers of *pages* in turn (or an exception); the
    queries it sends go into *queries*."""

    def page_of(page: Any, variable: str = "celex") -> Any:
        if isinstance(page, Exception):
            return page
        return {"results": {"bindings": [{variable: {"value": c}} for c in page]}}

    def step(page: Any):
        def answer(sent: Sent) -> Any:
            queries.append(sent.params["query"])
            variable = sent.params["query"].split("SELECT DISTINCT ?")[1].split()[0]
            return page_of(page, variable)

        return answer

    return EUClient(session=ScriptedSession(*map(step, pages)))


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
    failure = http_error(500)
    client = _client([["32010L0064"] * 500, failure], [])
    with pytest.raises(requests.HTTPError) as raised:
        client.enumerate_all_ids()
    assert raised.value is failure  # its status is still there for the step
    assert raised.value.__notes__ == ["SPARQL page (cdm_type=directive) at offset 500"]


def test_a_page_that_is_not_json_raises_with_its_offset() -> None:
    client = EUClient(session=ScriptedSession("<html>Bad gateway</html>"))
    with pytest.raises(RuntimeError, match="offset 0 is not JSON"):
        client.enumerate_all_ids()


def test_an_id_found_twice_comes_back_once_in_the_order_found() -> None:
    """Under two types, and in two batches of the proposals."""
    ids = _client([["A", "B"], ["B", "C"]], []).enumerate_all_ids(
        cdm_types=("directive", "regulation")
    )
    assert ids == ["A", "B", "C"]
    acts = [f"32010R{n:04d}" for n in range(51)]
    proposals = _client([["5X", "5Y"], ["5Y"]], []).enumerate_com_ids(celex_ids=acts)
    assert proposals == ["5X", "5Y"]


def test_the_celex_numbers_of_a_query_are_asked_in_batches_typed_and_escaped() -> None:
    """Typed as CELLAR stores them: a plain ``"32010R0000"`` matches nothing there."""
    queries: list[str] = []
    celex = [f"32010R{n:04d}" for n in range(51)] + ['bad"\\id']
    _client([[], []], queries).enumerate_cjeu_ids(celex_ids=celex)
    assert len(queries) == 2  # 50 and 2
    assert f'"32010R0000"{XSD_STRING}, "32010R0001"{XSD_STRING}' in queries[0]
    assert f'"32010R0050"{XSD_STRING}, "bad\\"\\\\id"{XSD_STRING}' in queries[1]


@pytest.mark.parametrize(
    ("builder", "args", "snapshot"),
    [
        (
            eu._acts_of_type_sparql,
            ("directive", 500),
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT DISTINCT "
            "?celex WHERE { ?s a cdm:directive ; cdm:resource_legal_id_celex ?celex . "
            'FILTER(!CONTAINS(?celex, "(")) } ORDER BY ?celex LIMIT 500 OFFSET 500',
        ),
        (
            eu._implemented_acts_sparql,
            ("NLD", 0),
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT DISTINCT "
            "?celex WHERE { ?eu_act cdm:resource_legal_id_celex ?celex . ?nim "
            "cdm:measure_national_implementing_implements_resource_legal ?eu_act ; "
            "cdm:measure_national_implementing_implemented_by_country "
            "<http://publications.europa.eu/resource/authority/country/NLD> . } "
            "ORDER BY ?celex LIMIT 500 OFFSET 0",
        ),
        (
            eu._country_judgments_sparql,
            ("NLD", 0),
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT DISTINCT "
            "?celex WHERE { ?j a cdm:judgement ; cdm:resource_legal_id_celex ?celex ; "
            "cdm:case-law_originates_in_country "
            "<http://publications.europa.eu/resource/authority/country/NLD> . } "
            "ORDER BY ?celex LIMIT 500 OFFSET 0",
        ),
        (
            eu._judgments_citing_sparql,
            (f'"32016R0679"{XSD_STRING}', 0),
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT DISTINCT "
            "?judgment_celex WHERE { ?j a cdm:judgement ; cdm:resource_legal_id_celex "
            "?judgment_celex ; cdm:work_cites_work ?cited . ?cited "
            "cdm:resource_legal_id_celex ?cited_celex . "
            f'FILTER(?cited_celex IN ("32016R0679"{XSD_STRING})) }} '
            "ORDER BY ?judgment_celex LIMIT 500 OFFSET 0",
        ),
        (
            eu._proposals_of_sparql,
            (f'"32016R0679"{XSD_STRING}', 0),
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT DISTINCT "
            "?com_celex WHERE { ?act cdm:resource_legal_id_celex ?act_celex ; "
            "cdm:resource_legal_adopts_resource_legal ?proposal . ?proposal "
            "cdm:resource_legal_id_celex ?com_celex . "
            f'FILTER(?act_celex IN ("32016R0679"{XSD_STRING})) '
            'FILTER(STRSTARTS(?com_celex, "5")) } '
            "ORDER BY ?com_celex LIMIT 500 OFFSET 0",
        ),
    ],
)
def test_a_query_builder_writes_what_it_always_wrote(builder, args, snapshot) -> None:
    assert builder(*args) == snapshot


# ── retrieving ───────────────────────────────────────────────────────────────


# When an interrupted run stored what a rerun finds.
AN_HOUR_AGO = iso_timestamp(dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))


def _store(events: list[str], recent: Iterable[str] = ()) -> InMemoryStore:
    """A store that adds a ``store`` event per record written to *events*."""
    store = InMemoryStore(
        raw=[
            raw_record(
                SOURCE_EURLEX,
                RAW_KIND_EURLEX_CELEX,
                celex,
                fetched_at=present(AN_HOUR_AGO),
            )
            for celex in recent
        ]
    )
    write = store.insert_raw_sources

    def logged(docs: list[dict[str, Any]]) -> None:
        events.extend(f"store {doc['external_id']}" for doc in docs)
        write(docs)

    store.insert_raw_sources = logged
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
    pipeline = EurlexRetrievePipeline(
        store=store, eu_client=cast(EUClient, _Eu(outcomes, events))
    )
    return pipeline.run(celex_ids=list(outcomes)), store, events


def test_an_act_without_html_is_skipped_not_an_error() -> None:
    result, store, _ = _run(
        {"32010L0064": "<html/>", "31983L0091R(03)": http_error(404)}
    )
    assert (result.created, result.skipped, result.errors) == (1, 1, [])
    assert sorted(_written(store)) == [
        "31983L0091R(03)",
        "32010L0064",
    ]  # one as missing


def test_other_failures_are_skipped_too_and_the_run_continues() -> None:
    result, store, _ = _run(
        {
            "31990L0001": http_error(503),
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
        eu_client=cast(
            EUClient, Interrupted({"32010L0064": "<html/>", "32010L0065": ""}, events)
        ),
    )
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(celex_ids=["32010L0064", "32010L0065"])
    assert _written(store) == ["32010L0064"]


# ── retrieve all ─────────────────────────────────────────────────────────────


def test_retrieve_all_never_lists_eu_acts() -> None:
    from lawgraph.pipelines.retrieve_commands import RetrieveMode
    from lawgraph.sources.registry import RetrieveCtx, find

    eurlex = find("retrieve", "eurlex")
    assert eurlex is not None and eurlex.argv_for_all is not None
    assert eurlex.argv_for_all(RetrieveCtx(since="1d", mode=RetrieveMode.FULL)) == []


def test_a_rerun_skips_the_acts_an_interrupted_run_stored() -> None:
    events: list[str] = []
    store = _store(events, recent=["32010L0064"])
    eu = _Eu({"32010L0064": "<html/>", "32010L0065": "<html/>"}, events)
    result = EurlexRetrievePipeline(store=store, eu_client=cast(EUClient, eu)).run(
        celex_ids=["32010L0064", "32010L0065"]
    )
    assert _written(store) == ["32010L0065"]
    assert events == ["fetch 32010L0065", "store 32010L0065"]
    assert result.created == 1


class _DeadEu:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
        raise self.error


def test_eurlex_that_is_down_fails_the_step(raw_reads: None) -> None:
    pipeline = EurlexRetrievePipeline(
        store=InMemoryStore(),
        eu_client=cast(EUClient, _DeadEu(requests.ConnectionError("no route"))),
    )
    result = pipeline.run(celex_ids=[f"3201{n:04d}L0001" for n in range(200)])
    assert "seems to be down" in result.errors[0]
    assert result.skipped == 25


def test_eurlex_acts_without_html_are_not_a_dead_source(raw_reads: None) -> None:
    error = requests.HTTPError("404", response=SimpleNamespace(status_code=404))
    pipeline = EurlexRetrievePipeline(
        store=InMemoryStore(), eu_client=cast(EUClient, _DeadEu(error))
    )
    result = pipeline.run(celex_ids=[f"3201{n:04d}L0001" for n in range(60)])
    assert result.errors == [] and result.skipped == 60
