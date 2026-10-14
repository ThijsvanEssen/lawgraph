"""Verdragenbank treaties over the KOOP SRU (``c.product-area==vd``), from a real page."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import requests

from lawgraph.clients.base import ATTEMPTS
from lawgraph.clients.verdragenbank import VerdragenbankClient
from tests.fakes import ScriptedSession, answer

PAGE = (
    pathlib.Path(__file__).parent / "fixtures" / "sru_verdragenbank_nl_page.xml"
).read_text()  # 2 real treaties (001610, ...), Dutch records, total 7769


def _dutch(total: int = 2) -> str:
    return PAGE.replace(
        "<sru:numberOfRecords>7769</sru:numberOfRecords>",
        f"<sru:numberOfRecords>{total}</sru:numberOfRecords>",
    )


def _english(total: int = 2) -> str:
    """The English records of the same treaties: same identifiers, English titles."""
    text = _dutch(total).replace('xml:lang="nl" xmlns:xsi', 'xml:lang="en" xmlns:xsi')
    text = text.replace(">nl</dcterms:language>", ">en</dcterms:language>")
    return text.replace(
        "Overeenkomst tussen het Koninkrijk der Nederlanden",
        "Agreement between the Kingdom of the Netherlands",
    )


def _client(responses: list[Any], calls: list[dict]) -> VerdragenbankClient:
    return VerdragenbankClient(session=ScriptedSession(*responses, asked=calls))


def test_a_treaty_joins_its_dutch_and_english_record() -> None:
    treaties = _client([_dutch(), _english()], []).enumerate_treaties()

    first = treaties[0]
    assert first["verdragsnummer"] == "001610"
    assert first["title_nl"].startswith("Overeenkomst tussen het Koninkrijk")
    assert first["title_en"].startswith("Agreement between the Kingdom")
    assert first["title"] == first["title_nl"]
    assert first["date_signed"] == "1874-09-23"
    assert first["date_in_force"] == "1875-03-01"
    assert first["treaty_type"] == "Bilateraal"
    assert first["status"] == "Inwerkinggetreden"
    assert first["uri"].endswith("/001610")


def test_the_uri_ends_in_the_verdragenbank_id_the_retrieve_uses_as_external_id() -> (
    None
):
    treaty = _client([_dutch(), _english()], []).enumerate_treaties()[0]
    assert treaty["uri"].rstrip("/").rsplit("/", 1)[-1] == treaty["verdragsnummer"]


def test_both_languages_are_queried_without_a_connection() -> None:
    calls: list[dict] = []
    _client([_dutch(), _english()], calls).enumerate_treaties()
    assert "dt.language==nl" in calls[0]["query"]
    assert "dt.language==en" in calls[1]["query"]
    for params in calls:
        assert "c.product-area==vd AND w.documenttype==verdrag" in params["query"]
        assert "x-connection" not in params


def test_a_missing_english_record_leaves_the_english_title_empty() -> None:
    empty_en = "<sru:numberOfRecords>0</sru:numberOfRecords>"
    english = (
        _english(total=0).split("<sru:records>")[0] + "</sru:searchRetrieveResponse>"
    )
    assert empty_en in english
    treaty = _client([_dutch(), english], []).enumerate_treaties()[0]
    assert treaty["title_en"] is None and treaty["title_nl"]


def test_limit_stops_early() -> None:
    treaties = _client(
        [_dutch(total=7769), _english(total=7769)], []
    ).enumerate_treaties(max_records=1)
    assert len(treaties) == 1


def test_no_treaties_at_all_means_the_endpoint_or_data_model_changed() -> None:
    empty = _dutch(total=0).split("<sru:records>")[0] + "</sru:searchRetrieveResponse>"
    with pytest.raises(RuntimeError, match="no treaties at all"):
        _client([empty, empty], []).enumerate_treaties()


def test_a_failing_request_raises_instead_of_an_empty_list(slept) -> None:
    gateway = [answer(status=504)] * ATTEMPTS
    with pytest.raises(requests.HTTPError):
        _client(gateway, []).enumerate_treaties()
    no_route = [requests.ConnectionError("no route")] * ATTEMPTS
    with pytest.raises(requests.ConnectionError):
        _client(no_route, []).enumerate_treaties()


def test_pages_that_do_not_add_up_to_the_total_raise() -> None:
    with pytest.raises(RuntimeError, match="reports 9"):
        _client([_dutch(total=9)], []).enumerate_treaties()
