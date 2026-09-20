"""A dead or changed source must fail the step, not end as "completed, nothing to do"."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from lawgraph.clients.bwb import BWBClient
from lawgraph.clients.verdragenbank import VerdragenbankClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SRU_DIAGNOSTIC = (FIXTURES / "bwb_sru_diagnostic.xml").read_text()


# ── Verdragenbank ────────────────────────────────────────────────────────────


def _treaties(bindings: list[dict]) -> dict:
    return {"results": {"bindings": bindings}}


def _binding(uri: str) -> dict:
    return {
        "treaty": {"value": uri},
        "title": {"value": f"Verdrag {uri}"},
        "verdragsnummer": {"value": "1"},
    }


class _Session:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls = 0

    def post(self, url, *, data=None, timeout=30):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _Response:
    def __init__(self, payload: dict | None = None, status: int = 200) -> None:
        self.payload = payload or {}
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(
                f"{self.status} Server Error",
                response=SimpleNamespace(status_code=self.status),
            )

    def json(self) -> dict:
        return self.payload


def _verdragenbank(responses: list[Any]) -> VerdragenbankClient:
    client = VerdragenbankClient.__new__(VerdragenbankClient)
    client.base_url = "https://example.test/sparql"
    client.session = _Session(responses)
    return client


def test_treaties_are_listed() -> None:
    client = _verdragenbank([_Response(_treaties([_binding("a"), _binding("b")]))])
    assert [t["uri"] for t in client.enumerate_treaties()] == ["a", "b"]


def test_a_bad_gateway_raises_instead_of_an_empty_list() -> None:
    with pytest.raises(requests.HTTPError, match="502"):
        _verdragenbank([_Response(status=502)]).enumerate_treaties()


def test_a_connection_failure_raises() -> None:
    with pytest.raises(requests.ConnectionError):
        _verdragenbank([requests.ConnectionError("no route")]).enumerate_treaties()


def test_an_empty_first_page_means_the_query_no_longer_matches() -> None:
    with pytest.raises(RuntimeError, match="no treaties at all"):
        _verdragenbank([_Response(_treaties([]))]).enumerate_treaties()


def test_an_empty_later_page_is_the_end_of_the_list() -> None:
    full_page = [_binding(str(i)) for i in range(500)]
    client = _verdragenbank([_Response(_treaties(full_page)), _Response(_treaties([]))])
    assert len(client.enumerate_treaties(max_records=1000)) == 500


# ── BWB toestanden ───────────────────────────────────────────────────────────


def _bwb(text: str) -> BWBClient:
    client = BWBClient.__new__(BWBClient)
    client._get_raw_absolute_with_retry = lambda url, **kw: SimpleNamespace(text=text)  # type: ignore[method-assign]
    return client


def test_an_sru_error_is_not_an_empty_list_of_toestanden() -> None:
    with pytest.raises(RuntimeError, match="record schema is known"):
        _bwb(SRU_DIAGNOSTIC).search_toestanden("BWBR0001840")


def test_an_unreadable_sru_response_raises() -> None:
    with pytest.raises(Exception, match="syntax error|not well-formed|no element"):
        _bwb("<html>Bad gateway").search_toestanden("BWBR0001840")
