"""The XML of Tweede Kamer papers (KOOP repository) as raw records: identifiers, the client and
``retrieve tk-content``."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

import pytest
import requests

from lawgraph.clients.base import UnexpectedAnswer
from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import (
    RAW_KIND_MISSING_SUFFIX,
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.core.identifiers import KST_ID_PATTERN, kamerstuk_identifier
from lawgraph.db import raw_key
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.pipelines.retrieve.tk_content import (
    DEFAULT_KINDS,
    TKContentRetrievePipeline,
)
from tests.fakes import (
    InMemoryStore,
    ScriptedSession,
    Sent,
    external_ids,
    http_error,
    raw_record,
)
from tests.paths import fixture_text

# kst-37020-X-1, a real "Voorstel van wet" (22 KB)
FIXTURE = fixture_text("kst_37020_x_1.xml")


# ── identifiers ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("number", "suffix", "sequence", "expected"),
    [
        ("37020", "X", 2, "kst-37020-X-2"),
        ("36867", None, 7, "kst-36867-7"),
        ("36867", "", "7", "kst-36867-7"),
        ("35925", "VII", 12, "kst-35925-VII-12"),
        # a Rijkswet: its number is no part of the dossier in the repository
        ("36984", "(R2222)", 4, "kst-36984-4"),
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
    """A client answered *responses* in turn; the URL of every request goes into *calls*."""

    def step(response: Any):
        def answer(sent: Sent) -> Any:
            calls.append(sent.url)
            return response

        return answer

    return KamerstukClient(session=ScriptedSession(*map(step, responses)))


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


@pytest.mark.parametrize("status", [404, 500])
def test_a_failed_request_raises_with_its_status(status: int) -> None:
    with pytest.raises(requests.HTTPError) as raised:
        _client([http_error(status)], []).fetch_kamerstuk_xml("kst-37020-2")
    assert raised.value.response.status_code == status


def test_an_identifier_that_is_not_a_kamerstuk_is_not_requested() -> None:
    calls: list[str] = []
    for identifier in ("kst-1259252", "stb-2020-1"):
        with pytest.raises(UnexpectedAnswer):
            _client([], calls).fetch_kamerstuk_xml(identifier)
    assert calls == []


def test_an_error_page_that_answered_200_is_not_the_paper() -> None:
    with pytest.raises(UnexpectedAnswer):
        _client(["<html>Bad gateway"], []).fetch_kamerstuk_xml("kst-37020-2")


# ── the pipeline ─────────────────────────────────────────────────────────────


class _Store(InMemoryStore):
    """The papers of the graph, and what the pipeline asked about them."""

    def __init__(self, papers: list[dict], have: Iterable[dict[str, Any]] = ()) -> None:
        super().__init__(raw=have)
        self.papers = papers
        self.kinds: list[list[str]] = []  # the kinds the papers were asked for by
        self.lookups: list[tuple[list[str], str | None]] = []  # (keys, retry_after_iso)


@pytest.fixture(autouse=True)
def _gap_reads(monkeypatch: pytest.MonkeyPatch) -> None:

    def papers_with_dossier(store: _Store, kinds: list[str]) -> Any:
        store.kinds.append(kinds)
        return iter([dict(p) for p in store.papers])

    def existing_raw_keys(
        store: _Store, keys: list[str], *, retry_after_iso: str | None = None
    ) -> Any:
        store.lookups.append((keys, retry_after_iso))
        return iter(
            key
            for key in keys
            if key in store.raw
            and (
                retry_after_iso is None
                or (store.raw[key].get("meta") or {}).get("retry_after", "")
                > retry_after_iso
            )
        )

    monkeypatch.setattr(gap_queries, "papers_with_dossier", papers_with_dossier)
    monkeypatch.setattr(gap_queries, "existing_raw_keys", existing_raw_keys)


class _Client:
    def __init__(self, xml: dict[str, Any]) -> None:
        self.xml = xml
        self.fetched: list[str] = []

    def fetch_kamerstuk_xml(self, identifier: str) -> str:
        self.fetched.append(identifier)
        outcome = self.xml.get(identifier, FIXTURE)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _document(
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


def _run(papers, xml=None, have=(), **kw):
    store = _Store(papers, have)
    client = _Client(xml or {})
    result = TKContentRetrievePipeline(store=store, client=client).run(**kw)
    return result, store, client


def _xml_key(identifier: str) -> str:
    return raw_key(SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, identifier)


def test_each_paper_is_fetched_by_its_identifier_and_its_xml_stored_unchanged() -> None:
    result, store, client = _run([_document("37020", 1, "X"), _document("36867", 3)])
    assert client.fetched == ["kst-37020-X-1", "kst-36867-3"]
    assert result.created == 2 and result.errors == []
    stored = list(store.raw.values())
    assert [(r["source"], r["kind"], r["external_id"]) for r in stored] == [
        (SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, "kst-37020-X-1"),
        (SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, "kst-36867-3"),
    ]
    assert all(r["payload_text"] == FIXTURE for r in stored)
    # The record says which document it is the text of: normalize needs no second lookup.
    assert stored[0]["meta"] == {"document": "doc-37020-1"}


def test_the_papers_are_asked_for_by_their_kinds_in_lower_case() -> None:
    _, store, _ = _run([_document("36867", 3)], kinds=["Toelichting", "Motie"])
    assert store.kinds == [["toelichting", "motie"]]


@pytest.mark.parametrize(
    ("kind", "fetched"),
    [
        # the kinds of the Tweede Kamer's papers as stored (props.kind)
        ("Memorie van toelichting", True),
        ("Advies Afdeling advisering Raad van State en Nader rapport", True),
        ("Advies Afdeling advisering Raad van State", True),
        (
            "Advies Afdeling advisering Raad van State en Reactie van de initiatiefnemer(s)",
            True,
        ),
        ("Voorlichting Afdeling advisering Raad van State", True),
        ("Nader rapport", True),
        ("Advies van andere adviesorganen", False),
        ("Brief regering", False),
    ],
)
def test_the_default_kinds_hold_the_advice_of_the_raad_van_state(
    kind: str, fetched: bool
) -> None:
    assert any(word in kind.lower() for word in DEFAULT_KINDS) is fetched


def test_a_paper_with_its_xml_stored_is_not_fetched_again() -> None:
    result, _, client = _run(
        [_document("1", 1), _document("2", 2)],
        have=[raw_record(SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML, "kst-1-1")],
    )
    assert client.fetched == ["kst-2-2"] and result.created == 1


def test_a_paper_that_answered_404_lately_waits_and_one_whose_wait_is_over_is_asked() -> (
    None
):
    """The wait is the ``retry_after`` of the record: the lookup of the missing records
    filters on it, the lookup of the XML itself does not."""
    waiting = raw_record(
        SOURCE_TK,
        RAW_KIND_TK_KAMERSTUK_XML + RAW_KIND_MISSING_SUFFIX,
        "kst-1-1",
        meta={"retry_after": "2999-01-01T00:00:00Z"},
    )
    missing = waiting["key"]
    result, store, client = _run([_document("1", 1), _document("2", 2)], have=[waiting])
    assert client.fetched == ["kst-2-2"]
    (xml_keys, xml_retry), (missing_keys, missing_retry) = store.lookups
    assert _xml_key("kst-1-1") in xml_keys and xml_retry is None
    assert missing in missing_keys and missing_retry is not None


def test_a_paper_the_repository_does_not_have_becomes_a_missing_record() -> None:
    not_found = _Client({"kst-36867-3": http_error(404)})
    store = _Store([_document("36867", 3)])
    result = TKContentRetrievePipeline(store=store, client=not_found).run()
    assert (result.created, result.skipped, result.errors) == (0, 1, [])
    (record,) = store.raw.values()
    assert record["kind"] == RAW_KIND_TK_KAMERSTUK_XML + RAW_KIND_MISSING_SUFFIX
    assert record["external_id"] == "kst-36867-3" and record["payload_text"] is None
    assert record["meta"]["status"] == 404
    retry = dt.datetime.fromisoformat(
        record["meta"]["retry_after"].replace("Z", "+00:00")
    )
    long_wait = dt.datetime.now(dt.UTC) + dt.timedelta(days=29)
    assert retry > long_wait  # an old paper: a month, like every missing document


def _retry_after(days_old: int) -> dt.datetime:
    """When a paper *days_old* days old that the repository has no XML for is asked again."""
    day = (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=days_old)).isoformat()
    not_found = _Client({"kst-36867-3": http_error(404)})
    store = _Store([_document("36867", 3, date=day)])
    TKContentRetrievePipeline(store=store, client=not_found).run()
    (record,) = store.raw.values()
    return dt.datetime.fromisoformat(
        record["meta"]["retry_after"].replace("Z", "+00:00")
    )


def test_a_paper_of_the_last_two_weeks_that_has_no_xml_yet_is_asked_again_tomorrow() -> (
    None
):
    """A new paper is a PDF first ("Onopgemaakt"); its XML follows within about two working
    days, sometimes a week or more (prod, Oct 2026). Till 14 days old it is asked every night;
    after that a month on, like any missing document."""
    now = dt.datetime.now(dt.UTC)
    for days_old in (0, 6, 14):
        retry = _retry_after(days_old)
        assert now < retry <= now + dt.timedelta(days=1, minutes=1), days_old
    assert _retry_after(15) > now + dt.timedelta(days=29)


def test_a_failing_fetch_is_an_error_and_the_rest_goes_on() -> None:
    result, store, _ = _run(
        [_document("1", 1), _document("2", 2), _document("3", 3)],
        {"kst-2-2": requests.ConnectionError("dropped")},
    )
    assert result.created == 2
    assert len(result.errors) == 1 and "kst-2-2" in result.errors[0]
    assert external_ids(store) == ["kst-1-1", "kst-3-3"]


def test_a_repository_that_is_down_fails_the_step() -> None:
    papers = [_document(str(n), 1) for n in range(1, 61)]
    down = requests.ConnectionError("no route")
    result, store, client = _run(papers, {f"kst-{n}-1": down for n in range(1, 61)})
    assert result.created == 0 and store.raw == {}
    assert any("seems to be down" in e for e in result.errors)
    # it stopped at the 25th failure in a row, with the few asked ahead of it
    assert 25 <= len(client.fetched) < 30


def test_an_error_page_that_answered_200_is_an_error_not_a_stored_paper() -> None:
    page = UnexpectedAnswer("an HTML page: kst-36867-3")
    result, store, _ = _run([_document("36867", 3)], {"kst-36867-3": page})
    assert store.raw == {}
    assert result.errors == [
        "1 x download failed (UnexpectedAnswer) (first: kst-36867-3)"
    ]


def test_a_paper_whose_number_makes_no_kamerstuk_identifier_is_no_gap() -> None:
    result, _, client = _run([_document("1", 1), _document("2", "2 bis")])  # type: ignore[arg-type]
    assert client.fetched == ["kst-1-1"]


def test_a_limit_fetches_the_first_papers_and_leaves_the_rest_for_the_next_run() -> (
    None
):
    papers = [_document("1", 1), _document("2", 2), _document("3", 3)]
    result, _, client = _run(papers, limit=2)
    assert client.fetched == ["kst-1-1", "kst-2-2"] and result.created == 2
    assert result.notes == ["2 of 3 Kamerstukken without XML, again for the rest"]


def test_a_dry_run_fetches_and_stores_nothing() -> None:
    result, store, client = _run([_document("36867", 3)], dry_run=True)
    assert client.fetched == [] and store.raw == {} and result.skipped == 1


def test_without_papers_there_is_nothing_to_do() -> None:
    result, store, client = _run([])
    assert client.fetched == [] and result.created == 0
