"""The text of Tweede Kamer papers from their XML (KOOP repository), not from the PDF."""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.core.identifiers import KST_ID_PATTERN, kamerstuk_identifier
from lawgraph.pipelines.retrieve import tk_content
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline, xml_text

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


# ── the XML ──────────────────────────────────────────────────────────────────


def test_the_text_of_a_real_kamerstuk_xml() -> None:
    text = xml_text(FIXTURE)
    assert text is not None and len(text) > 1000
    assert (
        "Vaststelling van de begrotingsstaten van het ministerie van Defensie" in text
    )
    assert "<" not in text  # markup is gone


def test_a_byte_order_mark_does_not_matter() -> None:
    assert xml_text("﻿" + FIXTURE) == xml_text(FIXTURE)


def test_xml_without_text_is_none_and_broken_xml_raises() -> None:
    assert xml_text("<root><a/></root>") is None
    with pytest.raises(ET.ParseError):
        xml_text("<html>Bad gateway")


# ── the client ───────────────────────────────────────────────────────────────


def _client(responses: list[Any], calls: list[str]) -> KamerstukClient:
    client = KamerstukClient.__new__(KamerstukClient)
    client.base_url = "https://repository.overheid.nl/"

    def fake_get(url, *, params=None, timeout=30, **_kw):
        calls.append(url)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(text=response)

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


class _Store:
    def __init__(self, papers: list[dict]) -> None:
        self.papers = papers
        self.updates: list[dict] = []
        self.queries: list[str] = []

    def query(self, aql: str, bind_vars: dict | None = None, **kw: Any):
        self.queries.append(aql)
        if "UPDATE" in aql:
            bind = dict(bind_vars or {})
            # ``_set_prop`` binds a name and a value; the tests read it as {key, <name>}.
            self.updates.append({"key": bind["key"], bind["name"]: bind["value"]})
            return iter([])
        self.missing_before = (bind_vars or {}).get("missing_before")
        return iter(self.papers)


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
    number: str, sequence: int, suffix: str | None = None, key: str = ""
) -> dict:
    return {
        "key": key or f"doc-{number}-{sequence}",
        "title": f"Paper {number} {sequence}",
        "number": number,
        "suffix": suffix,
        "sequence": sequence,
    }


def _run(papers, xml=None, **kw):
    store = _Store(papers)
    client = _Client(xml or {})
    result = TKContentRetrievePipeline(store=store, client=client).run(**kw)
    return result, store, client


def test_each_paper_is_fetched_by_its_identifier_and_its_text_stored() -> None:
    result, store, client = _run([_paper("37020", 1, "X"), _paper("36867", 3)])
    assert client.fetched == ["kst-37020-X-1", "kst-36867-3"]
    assert result.created == 2 and result.errors == []
    assert [u["key"] for u in store.updates] == ["doc-37020-1", "doc-36867-3"]
    assert "Vaststelling van de begrotingsstaten" in store.updates[0]["text"]


def test_the_query_joins_the_dossier_and_asks_for_tk_papers_without_text() -> None:
    _, store, _ = _run([_paper("36867", 3)])
    aql = store.queries[0]
    assert '"TK" IN pub.labels' in aql and "@part_of" in aql
    assert "pub.props.text == null" in aql and "dossier.props.suffix" in aql
    assert "kind || " in aql  # not the ``??`` AQL does not have


def test_a_paper_the_repository_does_not_have_is_skipped() -> None:
    not_found = _Client({})
    not_found.fetch_kamerstuk_xml = lambda identifier: None  # type: ignore[method-assign]
    store = _Store([_paper("36867", 3)])
    result = TKContentRetrievePipeline(store=store, client=not_found).run()
    assert (result.created, result.skipped, result.errors) == (0, 1, [])
    # No text, but the paper remembers that it was asked for: not again for 30 days.
    (update,) = store.updates
    assert update["key"] == "doc-36867-3" and update["text_missing_at"].endswith("Z")
    assert store.missing_before < update["text_missing_at"]
    assert "text_missing_at < @missing_before" in store.queries[0]


def test_a_failing_fetch_is_an_error_and_the_rest_goes_on() -> None:
    result, store, _ = _run(
        [_paper("1", 1), _paper("2", 2), _paper("3", 3)],
        {"kst-2-2": requests.ConnectionError("dropped")},
    )
    assert result.created == 2
    assert len(result.errors) == 1 and "kst-2-2" in result.errors[0]
    assert [u["key"] for u in store.updates] == ["doc-1-1", "doc-3-3"]


def test_a_repository_that_is_down_fails_the_step() -> None:
    papers = [_paper(str(n), 1) for n in range(1, 61)]
    down = requests.ConnectionError("no route")
    result, store, client = _run(papers, {f"kst-{n}-1": down for n in range(1, 61)})
    assert result.created == 0 and store.updates == []
    assert "seems to be down" in result.errors[-1]
    assert len(client.fetched) == 25  # it stopped at the 25th failure in a row


def test_xml_that_cannot_be_read_is_an_error_not_an_empty_paper() -> None:
    result, store, _ = _run([_paper("36867", 3)], {"kst-36867-3": "<html>Bad gateway"})
    assert store.updates == [] and "cannot be read" in result.errors[0]


def test_xml_without_text_is_skipped() -> None:
    result, store, _ = _run([_paper("36867", 3)], {"kst-36867-3": "<root><a/></root>"})
    assert result.skipped == 1 and store.updates == []


def test_a_very_long_text_is_cut_and_says_so(monkeypatch, caplog) -> None:
    monkeypatch.setattr(tk_content, "_STORE_TEXT_LIMIT", 100)
    with caplog.at_level("WARNING"):
        _, store, _ = _run([_paper("36867", 3)])
    assert len(store.updates[0]["text"]) == 100
    assert any(
        "longer than 100 chars; storing the first part" in m for m in caplog.messages
    )


def test_a_dry_run_fetches_and_stores_nothing() -> None:
    result, store, client = _run([_paper("36867", 3)], dry_run=True)
    assert client.fetched == [] and store.updates == [] and result.skipped == 1


def test_without_papers_there_is_nothing_to_do() -> None:
    result, store, client = _run([])
    assert client.fetched == [] and result.created == 0
