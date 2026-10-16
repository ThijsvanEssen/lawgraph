"""The paged SRU searches of ``clients/_sru.py``."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from lawgraph.clients import _sru
from lawgraph.clients.base import ATTEMPTS, BaseClient
from tests.fakes import (
    ScriptedSession,
)


def _sru_client(pages: list[Any]) -> BaseClient:
    return BaseClient(base_url="https://x.test", session=ScriptedSession(*pages))


def _page(identifiers: list[str], total: int) -> str:
    records = "".join(
        f"<sru:record><sru:recordData><dcterms:identifier>{i}</dcterms:identifier>"
        "</sru:recordData></sru:record>"
        for i in identifiers
    )
    return (
        '<sru:searchRetrieveResponse xmlns:sru="http://docs.oasis-open.org/ns/'
        'search-ws/sruResponse" xmlns:dcterms="http://purl.org/dc/terms/">'
        f"<sru:numberOfRecords>{total}</sru:numberOfRecords><sru:records>{records}"
        "</sru:records></sru:searchRetrieveResponse>"
    )


def _parse(root) -> list[dict[str, Any]]:
    return [{"identifier": i} for i in _identifiers(root)]


def _identifiers(root) -> list[str]:
    return [e.text for e in root.iter() if e.tag.endswith("}identifier") and e.text]


def test_the_records_of_earlier_pages_are_yielded_before_a_later_page_fails(
    slept,
) -> None:
    full = [f"id-{n:03d}" for n in range(100)]
    dropped = [requests.ConnectionError("dropped")] * ATTEMPTS
    client = _sru_client([_page(full, 250), *dropped])
    seen: list[str] = []
    with pytest.raises(requests.ConnectionError):
        for record in _sru.iter_publications(
            client, "https://x.test/sru", query="q", parse=_parse, context="t"
        ):
            seen.append(record["identifier"])
    assert seen == full  # the first page was in hand before the second failed
