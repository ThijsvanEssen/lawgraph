"""The download loop of the retrieve pipelines: what is stored, skipped, failed, or stops."""

from __future__ import annotations

from typing import Any, cast

import pytest
import requests

from lawgraph.clients.base import Unexpected, UnexpectedAnswer, xml_text
from lawgraph.clients.bwb import BWBClient, ToestandMeta
from lawgraph.clients.koop_publications import AMVB, KoopPublicationClient
from lawgraph.config.constants import RAW_KIND_MISSING_SUFFIX
from lawgraph.core.progress import Progress
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve.base import (
    MAX_FAILURES_IN_A_ROW,
    RetrievePipelineBase,
    RetrieveRecord,
    SourceDown,
    failure_reason,
    missing_record,
)
from lawgraph.pipelines.retrieve.bwb import BWBRetrievePipeline
from lawgraph.pipelines.retrieve.staatsblad import StaatsbladRetrievePipeline
from tests.asserts import show_items
from tests.fakes import (
    InMemoryStore,
    ScriptedSession,
    Sent,
    answer,
    external_ids,
    http_error,
)


def _record(one: str, text: str) -> list[RetrieveRecord]:
    return [RetrieveRecord(source="s", kind="k", external_id=one, payload_text=text)]


def _download(answers: dict[str, Any], **kwargs: Any) -> tuple[list, Progress]:
    pipeline = RetrievePipelineBase(store=cast(GraphStore, object()))
    pipeline.progress = Progress()

    def fetch(one: str) -> str:
        answer = answers[one]
        if isinstance(answer, Exception):
            raise answer
        return answer

    records: list[RetrieveRecord | SourceDown] = []
    try:
        for record in pipeline._download_each(
            list(answers),
            fetch,
            _record,
            label="Test",
            missing=lambda one, status: missing_record("s", "k", one, status=status),
            **kwargs,
        ):
            records.append(record)
    except SourceDown as exc:
        records.append(exc)
    return records, pipeline.progress


def test_ok_404_and_a_run_of_500s() -> None:
    answers: dict[str, Any] = {"ok": "<a/>", "gone": http_error(404)}
    answers.update({f"bad{n}": http_error(500) for n in range(MAX_FAILURES_IN_A_ROW)})
    records, progress = _download(answers)

    assert [r.external_id for r in records[:2]] == ["ok", "gone"]
    assert records[0].kind == "k"
    assert records[1].kind == "k" + RAW_KIND_MISSING_SUFFIX
    assert records[1].meta == {**records[1].meta, "status": 404}
    assert isinstance(records[-1], SourceDown)
    assert progress.skipped == 1
    assert progress.failed == MAX_FAILURES_IN_A_ROW


def test_a_failure_can_be_a_skip_that_is_asked_again_next_run() -> None:
    records, progress = _download(
        {"bad": http_error(500), "ok": "<a/>"}, failed_is_skipped=True
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
        "title": None,
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


IDS = [f"BWBR{n:07d}" for n in range(100)]


@pytest.mark.parametrize("history", [False, True])
def test_bwb_stops_when_the_source_is_down(raw_reads: None, history: bool) -> None:
    client = _BWBClient(http_error(503))
    pipeline = BWBRetrievePipeline(
        store=InMemoryStore(), client=cast(BWBClient, client)
    )
    result = (pipeline.run_history if history else pipeline.run)(bwb_ids=IDS)

    assert client.downloads < 2 * MAX_FAILURES_IN_A_ROW
    assert any("seems to be down" in error for error in result.errors), show_items(
        result.errors
    )


@pytest.mark.parametrize("history", [False, True])
def test_a_bug_in_the_bwb_client_fails_the_step_as_a_bug(
    raw_reads: None, history: bool
) -> None:
    client = _BWBClient(AttributeError("'NoneType' object has no attribute 'text'"))
    pipeline = BWBRetrievePipeline(
        store=InMemoryStore(), client=cast(BWBClient, client)
    )
    result = (pipeline.run_history if history else pipeline.run)(bwb_ids=IDS)

    assert client.downloads < 2 * 4 * 4  # ended within the window of the workers
    assert any("AttributeError" in error for error in result.errors), show_items(
        result.errors
    )
    found = [error for error in result.errors if "down" in error]
    assert not found, show_items(found)


# ── Staatsblad ───────────────────────────────────────────────────────────────


MAINTENANCE = (
    "<html><head><title>Onderhoud</title></head><body><p>Even geduld<br></body></html>"
)
XHTML = "<html><body><p>Onderhoud</p></body></html>"


@pytest.mark.parametrize("page", [MAINTENANCE, XHTML])
def test_an_error_page_with_http_200_is_not_the_document(page: str) -> None:
    client = KoopPublicationClient(
        AMVB,
        session=ScriptedSession(answer(page, headers={"Content-Type": "text/html"})),
    )
    with pytest.raises(UnexpectedAnswer):
        client.fetch_publication_xml("stb-2009-601")


def test_staatsblad_does_not_store_an_error_page(raw_reads: None) -> None:
    pages = {"stb-2009-601": MAINTENANCE, "stb-2009-602": "<officiele-publicatie/>"}

    def page(sent: Sent) -> str:
        return pages[sent.url.rsplit("/", 1)[-1].removesuffix(".xml")]

    client = KoopPublicationClient(AMVB, session=ScriptedSession(page, page))
    store = InMemoryStore()
    result = StaatsbladRetrievePipeline(store=store, client=client).run(
        identifiers=list(pages)
    )
    assert external_ids(store) == ["stb-2009-602"]
    assert result.created == 1 and result.skipped == 1


def _with_status(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError("https://example.org/doc?key=x", response=response)


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (_with_status(503), "HTTP 503"),
        (requests.ReadTimeout("https://example.org/doc"), "time-out"),
        (requests.ConnectTimeout("https://example.org/doc"), "time-out"),
        (requests.ConnectionError("https://example.org/doc"), "geen verbinding"),
        (requests.TooManyRedirects("https://example.org/doc"), "te veel redirects"),
        (requests.exceptions.ChunkedEncodingError("x"), "afgebroken antwoord"),
        (requests.RequestException("https://example.org/doc"), "verzoek mislukt"),
        (UnexpectedAnswer(Unexpected.NOT_PDF, "https://example.org/a.pdf"), "geen PDF"),
        (UnexpectedAnswer(Unexpected.EMPTY_XML, "https://example.org/a"), "lege XML"),
    ],
)
def test_a_failed_download_says_why_in_fixed_words(exc: Exception, reason: str) -> None:
    assert failure_reason(exc) == reason


def test_the_reason_of_a_failed_download_names_no_url() -> None:
    page = UnexpectedAnswer(Unexpected.HTML_PAGE, "https://example.org/kst-1.xml")
    _, progress = _download({"kst-1": page})
    assert progress.errors() == ["1 x download failed (HTML-pagina) (first: kst-1)"]


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", Unexpected.EMPTY_XML),
        (b"<a>", Unexpected.NOT_XML),
        (XHTML.encode(), Unexpected.HTML_PAGE),
    ],
)
def test_an_answer_that_is_no_xml_says_what_it_is(
    content: bytes, reason: Unexpected
) -> None:
    response = requests.Response()
    response.status_code = 200
    response._content = content
    response.url = "https://example.org/doc"
    with pytest.raises(UnexpectedAnswer) as raised:
        xml_text(response)
    assert raised.value.reason is reason
