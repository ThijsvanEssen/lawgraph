"""The download loop of the retrieve pipelines: what is stored, skipped, failed, or stops."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from lawgraph.clients.base import UnexpectedAnswer
from lawgraph.clients.bwb import ToestandMeta
from lawgraph.clients.staatsblad import StaatsbladClient
from lawgraph.config.constants import RAW_KIND_MISSING_SUFFIX
from lawgraph.core.progress import Progress
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.retrieve.base import (
    MAX_FAILURES_IN_A_ROW,
    RetrievePipelineBase,
    RetrieveRecord,
    SourceDown,
    missing_record,
)
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from tests.fakes import FakeResponse, RawSourcesFake


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def _record(one: str, text: str) -> list[RetrieveRecord]:
    return [RetrieveRecord(source="s", kind="k", external_id=one, payload_text=text)]


def _download(answers: dict[str, Any], **kwargs: Any) -> tuple[list, Progress]:
    pipeline = RetrievePipelineBase(store=object())  # type: ignore[arg-type]
    pipeline.progress = Progress()

    def fetch(one: str) -> str | None:
        answer = answers[one]
        if isinstance(answer, Exception):
            raise answer
        return answer

    records: list[RetrieveRecord] = []
    try:
        for record in pipeline._download_each(
            answers,
            fetch,
            _record,
            source="Test",
            missing=lambda one, status: missing_record("s", "k", one, status=status),
            **kwargs,
        ):
            records.append(record)
    except SourceDown as exc:
        records.append(exc)  # type: ignore[arg-type]
    return records, pipeline.progress


def test_ok_404_and_a_run_of_500s() -> None:
    answers: dict[str, Any] = {"ok": "<a/>", "gone": _http_error(404), "none": None}
    answers.update({f"bad{n}": _http_error(500) for n in range(MAX_FAILURES_IN_A_ROW)})
    records, progress = _download(answers)

    assert [r.external_id for r in records[:3]] == ["ok", "gone", "none"]
    assert records[0].kind == "k"
    assert records[1].kind == records[2].kind == "k" + RAW_KIND_MISSING_SUFFIX
    assert records[1].meta == {**records[1].meta, "status": 404}  # type: ignore[union-attr]
    assert isinstance(records[-1], SourceDown)
    assert progress.skipped == 2
    assert progress.failed == MAX_FAILURES_IN_A_ROW


def test_a_failure_can_be_a_skip_that_is_asked_again_next_run() -> None:
    records, progress = _download(
        {"bad": _http_error(500), "ok": "<a/>"}, failed_is_skipped=True
    )
    assert [r.external_id for r in records] == ["ok"]
    assert (progress.skipped, progress.failed) == (1, 0)


def test_a_bug_is_no_failure_of_the_source() -> None:
    with pytest.raises(AttributeError):
        _download({"ok": "<a/>", "bug": AttributeError("no such thing")})


# ── BWB ──────────────────────────────────────────────────────────────────────


def _meta(bwb_id: str, start: str = "2024-01-01") -> ToestandMeta:
    return {
        "bwb_id": bwb_id,
        "locatie_toestand": f"https://repo/{bwb_id}/{start}.xml",
        "locatie_wti": None,
        "locatie_manifest": None,
        "geldigheidsperiode_startdatum": start,
        "geldigheidsperiode_einddatum": "9999-12-31",
    }


class _BWBClient:
    """Every toestand download fails with *error*."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.downloads = 0

    def latest_toestand(self, bwb_id: str) -> ToestandMeta:
        return _meta(bwb_id)

    def search_toestanden(self, bwb_id: str) -> list[ToestandMeta]:
        return [_meta(bwb_id), _meta(bwb_id, "2020-01-01")]

    def fetch_toestand_xml(self, meta: ToestandMeta) -> str:
        self.downloads += 1
        raise self.error

    def fetch_wti_general_info(self, meta: ToestandMeta) -> str | None:
        return None


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.stored: list[str] = []

    def insert_raw_source(self, *, external_id: str, **_kw: Any) -> None:
        self.stored.append(external_id)


@pytest.fixture
def nothing_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    for query in ("ids_stored_since", "ids_waiting_for_retry", "fetch_times"):
        monkeypatch.setattr(raw_queries, query, lambda store, **kw: iter([]))


IDS = [f"BWBR{n:07d}" for n in range(100)]


@pytest.mark.parametrize("history", [False, True])
def test_bwb_stops_when_the_source_is_down(nothing_stored: None, history: bool) -> None:
    client = _BWBClient(_http_error(503))
    pipeline = BWBRetrievePipeline(store=_Store(), client=client)  # type: ignore[arg-type]
    result = (pipeline.run_history if history else pipeline.run)(bwb_ids=IDS)

    assert client.downloads < 2 * MAX_FAILURES_IN_A_ROW
    assert any("seems to be down" in error for error in result.errors)


@pytest.mark.parametrize("history", [False, True])
def test_a_bug_in_the_bwb_client_fails_the_step_as_a_bug(
    nothing_stored: None, history: bool
) -> None:
    client = _BWBClient(AttributeError("'NoneType' object has no attribute 'text'"))
    pipeline = BWBRetrievePipeline(store=_Store(), client=client)  # type: ignore[arg-type]
    result = (pipeline.run_history if history else pipeline.run)(bwb_ids=IDS)

    assert client.downloads < 2 * 4 * 4  # ended within the window of the workers
    assert any("AttributeError" in error for error in result.errors)
    assert not any("down" in error for error in result.errors)


# ── Staatsblad ───────────────────────────────────────────────────────────────


MAINTENANCE = (
    "<html><head><title>Onderhoud</title></head><body><p>Even geduld<br></body></html>"
)
XHTML = "<html><body><p>Onderhoud</p></body></html>"


@pytest.mark.parametrize("page", [MAINTENANCE, XHTML])
def test_an_error_page_with_http_200_is_not_the_document(page: str) -> None:
    client = StaatsbladClient.__new__(StaatsbladClient)
    client.base_url = "https://repository.overheid.nl"
    client._get_raw_absolute_with_retry = lambda url, **kw: FakeResponse(
        page, "text/html"
    )  # type: ignore[method-assign,assignment]
    with pytest.raises(UnexpectedAnswer):
        client.fetch_publication_xml("stb-2009-601")


def test_staatsblad_does_not_store_an_error_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(raw_queries, "ids_waiting_for_retry", lambda *_a, **_kw: [])
    client = StaatsbladClient.__new__(StaatsbladClient)
    client.base_url = "https://repository.overheid.nl"
    pages = {"stb-2009-601": MAINTENANCE, "stb-2009-602": "<officiele-publicatie/>"}
    client._get_raw_absolute_with_retry = lambda url, **kw: FakeResponse(  # type: ignore[method-assign,assignment]
        pages[url.rsplit("/", 1)[-1].removesuffix(".xml")]
    )
    store = _Store()
    result = StaatsbladRetrievePipeline(store=store, client=client).run(  # type: ignore[arg-type]
        identifiers=list(pages)
    )
    assert store.stored == ["stb-2009-602"]
    assert result.created == 1 and result.skipped == 1
