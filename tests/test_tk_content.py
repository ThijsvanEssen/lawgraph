"""The XML of Tweede Kamer papers (KOOP repository) as raw records: identifiers, the client and
``retrieve tk-content``."""

from __future__ import annotations

import datetime as dt
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import (
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.core.identifiers import KST_ID_PATTERN, kamerstuk_identifier
from lawgraph.db import raw_key
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline
from tests.fakes import FakeResponse, RawSourcesFake

FIXTURE = (
    pathlib.Path(__file__).parent / "fixtures" / "kst_37020_x_1.xml"
).read_text()  # kst-37020-X-1, a real "Voorstel van wet" (22 KB)


# ── identifiers ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("number", "suffix", "sequence", "expected"),
    [
        ("37020", "X", 2, "kst-37020-X-2"),
        ("36867", None, 7, "kst-36867-7"),
        ("36867", "", "7", "kst-36867-7"),
        ("35925", "VII", 12, "kst-35925-VII-12"),
    ],
)
def test_the_identifier_of_a_paper(number, suffix, sequence, expected) -> None:
    assert kamerstuk_identifier(number, suffix, sequence) == expected
    assert KST_ID_PATTERN.fullmatch(expected)


def test_the_dossier_and_number_come_out_of_an_identifier() -> None:
    assert KST_ID_PATTERN.fullmatch("kst-37020-X-2").groups() == ("37020-X", "2")
    assert KST_ID_PATTERN.fullmatch("kst-37020-2").groups() == ("37020", "2")
    assert KST_ID_PATTERN.fullmatch("kst-1259252") is None  # an Eerste Kamer paper


# ── the client ───────────────────────────────────────────────────────────────


def _client(responses: list[Any], calls: list[str]) -> KamerstukClient:
    client = KamerstukClient.__new__(KamerstukClient)
    client.base_url = "https://repository.overheid.nl/"

    def fake_get(url, *, params=None, timeout=30, **_kw):
        calls.append(url)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)

    client._get_raw_absolute_with_retry = fake_get  # type: ignore[method-assign]
    return client


def test_a_paper_is_filed_under_its_dossier() -> None:
    calls: list[str] = []
    _client(["<xml/>", "<xml/>"], calls).fetch_kamerstuk_xml("kst-37020-2")
    _client(["<xml/>"], calls).fetch_kamerstuk_xml("kst-37020-X-2")
    assert calls[0] == (
        "https://repository.overheid.nl/frbr/officielepublicaties/kst/37020/"
        "kst-37020-2/1/xml/kst-37020-2.xml"
    )
    assert calls[1] == (
        "https://repository.overheid.nl/frbr/officielepublicaties/kst/37020-X/"
        "kst-37020-X-2/1/xml/kst-37020-X-2.xml"
    )


def test_a_missing_paper_is_none_and_other_failures_raise() -> None:
    not_found = requests.HTTPError("404", response=SimpleNamespace(status_code=404))
    assert _client([not_found], []).fetch_kamerstuk_xml("kst-37020-2") is None
    error = requests.HTTPError("500", response=SimpleNamespace(status_code=500))
    with pytest.raises(requests.HTTPError):
        _client([error], []).fetch_kamerstuk_xml("kst-37020-2")


def test_an_identifier_that_is_not_a_kamerstuk_is_not_requested() -> None:
    calls: list[str] = []
    assert _client([], calls).fetch_kamerstuk_xml("kst-1259252") is None
    assert _client([], calls).fetch_kamerstuk_xml("stb-2020-1") is None
    assert calls == []


# ── the pipeline ─────────────────────────────────────────────────────────────


class _Store(RawSourcesFake):
    """What the pipeline asks of the store: the papers of the graph, the raw keys it has."""

    def __init__(self, papers: list[dict], have: set[str] | None = None) -> None:
        self.papers = papers
        self.have = have or set()  # raw keys that exist (whatever their kind)
        self.kinds: list[list[str]] = []  # the kinds the papers were asked for by
        self.lookups: list[tuple[list[str], str | None]] = []  # (keys, retry_after_iso)
        self.stored: list[dict[str, Any]] = []

    def insert_raw_source(self, **fields: Any) -> None:
        self.stored.append(fields)


@pytest.fixture(autouse=True)
def _gap_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The papers of the graph and the raw keys that exist, answered from the ``_Store``."""

    def papers_with_dossier(store: _Store, kinds: list[str]) -> Any:
        store.kinds.append(kinds)
        return iter([dict(p) for p in store.papers])

    def existing_raw_keys(
        store: _Store, keys: list[str], *, retry_after_iso: str | None = None
    ) -> Any:
        store.lookups.append((keys, retry_after_iso))
        return iter([key for key in keys if key in store.have])

    monkeypatch.setattr(gap_queries, "papers_with_dossier", papers_with_dossier)
    monkeypatch.setattr(gap_queries, "existing_raw_keys", existing_raw_keys)


class _Client:
    def __init__(self, xml: dict[str, Any]) -> None:
        self.xml = xml
        self.fetched: list[str] = []

    def fetch_kamerstuk_xml(self, identifier: str) -> str | None:
        self.fetched.append(identifier)
        outcome = self.xml.get(identifier, FIXTURE)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _paper(
    number: str,
    sequence: int,
    suffix: str | None = None,
    key: str = "",
    date: str = "2020-01-02",
) -> dict:
    return {
        "key": key or f"doc-{number}-{sequence}",
        "title": f"Paper {number} {sequence}",
        "number": number,
        "suffix": suffix,
        "sequence": sequence,
        "date": date,
    }


def _run(papers, xml=None, have=None, **kw):
    store = _Store(papers, have)
    client = _Client(xml or {})
    result = TKContentRetrievePipeline(store=store, client=client).run(**kw)
    return result, store, client


def _xml_key(identifier: str) -> str:
    return raw_key(SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, identifier)


def test_each_paper_is_fetched_by_its_identifier_and_its_xml_stored_unchanged() -> None:
    result, store, client = _run([_paper("37020", 1, "X"), _paper("36867", 3)])
    assert client.fetched == ["kst-37020-X-1", "kst-36867-3"]
    assert result.created == 2 and result.errors == []
    assert [(r["source"], r["kind"], r["external_id"]) for r in store.stored] == [
        (SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, "kst-37020-X-1"),
        (SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, "kst-36867-3"),
    ]
    assert all(r["payload_text"] == FIXTURE for r in store.stored)
    # The record says which document it is the text of: normalize needs no second lookup.
    assert store.stored[0]["meta"] == {"document": "doc-37020-1"}


def test_the_papers_are_asked_for_by_their_kinds_in_lower_case() -> None:
    _, store, _ = _run([_paper("36867", 3)], kinds=["Toelichting", "Motie"])
    assert store.kinds == [["toelichting", "motie"]]


def test_a_paper_with_its_xml_stored_is_not_fetched_again() -> None:
    result, _, client = _run(
        [_paper("1", 1), _paper("2", 2)], have={_xml_key("kst-1-1")}
    )
    assert client.fetched == ["kst-2-2"] and result.created == 1


def test_a_paper_that_answered_404_lately_waits_and_one_whose_wait_is_over_is_asked() -> (
    None
):
    """The wait is the ``retry_after`` of the record: the lookup of the missing records
    filters on it, the lookup of the XML itself does not."""
    missing = raw_key(
        SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML + RAW_KIND_MISSING_SUFFIX, "kst-1-1"
    )
    result, store, client = _run([_paper("1", 1), _paper("2", 2)], have={missing})
    assert client.fetched == ["kst-2-2"]
    (xml_keys, xml_retry), (missing_keys, missing_retry) = store.lookups
    assert _xml_key("kst-1-1") in xml_keys and xml_retry is None
    assert missing in missing_keys and missing_retry is not None


def test_a_paper_the_repository_does_not_have_becomes_a_missing_record() -> None:
    not_found = _Client({})
    not_found.fetch_kamerstuk_xml = lambda identifier: None  # type: ignore[method-assign]
    store = _Store([_paper("36867", 3)])
    result = TKContentRetrievePipeline(store=store, client=not_found).run()
    assert (result.created, result.skipped, result.errors) == (0, 1, [])
    (record,) = store.stored
    assert record["kind"] == RAW_KIND_TK_KAMERSTUK_XML + RAW_KIND_MISSING_SUFFIX
    assert record["external_id"] == "kst-36867-3" and record["payload_text"] is None
    assert record["meta"]["status"] == 404
    retry = dt.datetime.fromisoformat(
        record["meta"]["retry_after"].replace("Z", "+00:00")
    )
    long_wait = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=29)
    assert retry > long_wait  # an old paper: a month, like every missing document


def _retry_after(days_old: int) -> dt.datetime:
    """When a paper *days_old* days old that the repository has no XML for is asked again."""
    day = (
        dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=days_old)
    ).isoformat()
    not_found = _Client({})
    not_found.fetch_kamerstuk_xml = lambda identifier: None  # type: ignore[method-assign]
    store = _Store([_paper("36867", 3, date=day)])
    TKContentRetrievePipeline(store=store, client=not_found).run()
    (record,) = store.stored
    return dt.datetime.fromisoformat(
        record["meta"]["retry_after"].replace("Z", "+00:00")
    )


def test_a_paper_of_the_last_two_weeks_that_has_no_xml_yet_is_asked_again_tomorrow() -> (
    None
):
    """A new paper is a PDF first ("Onopgemaakt"); its XML follows within about two working
    days, sometimes a week or more (prod, Oct 2026). Till 14 days old it is asked every night;
    after that a month on, like any missing document."""
    now = dt.datetime.now(dt.timezone.utc)
    for days_old in (0, 6, 14):
        retry = _retry_after(days_old)
        assert now < retry <= now + dt.timedelta(days=1, minutes=1), days_old
    assert _retry_after(15) > now + dt.timedelta(days=29)


def test_a_failing_fetch_is_an_error_and_the_rest_goes_on() -> None:
    result, store, _ = _run(
        [_paper("1", 1), _paper("2", 2), _paper("3", 3)],
        {"kst-2-2": requests.ConnectionError("dropped")},
    )
    assert result.created == 2
    assert len(result.errors) == 1 and "kst-2-2" in result.errors[0]
    assert [r["external_id"] for r in store.stored] == ["kst-1-1", "kst-3-3"]


def test_a_repository_that_is_down_fails_the_step() -> None:
    papers = [_paper(str(n), 1) for n in range(1, 61)]
    down = requests.ConnectionError("no route")
    result, store, client = _run(papers, {f"kst-{n}-1": down for n in range(1, 61)})
    assert result.created == 0 and store.stored == []
    assert any("seems to be down" in e for e in result.errors)
    assert len(client.fetched) == 25  # it stopped at the 25th failure in a row


def test_an_error_page_that_answered_200_is_an_error_not_a_stored_paper() -> None:
    result, store, _ = _run([_paper("36867", 3)], {"kst-36867-3": "<html>Bad gateway"})
    assert store.stored == [] and "cannot be read" in result.errors[0]


def test_a_dry_run_fetches_and_stores_nothing() -> None:
    result, store, client = _run([_paper("36867", 3)], dry_run=True)
    assert client.fetched == [] and store.stored == [] and result.skipped == 1


def test_without_papers_there_is_nothing_to_do() -> None:
    result, store, client = _run([])
    assert client.fetched == [] and result.created == 0
