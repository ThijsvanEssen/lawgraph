from __future__ import annotations

import datetime as dt
import os

import pytest

from lawgraph.clients.eu import EUClient
from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.clients.tk import TKClient

RUN_NETWORK = os.getenv("ALLOW_NETWORK_TESTS") == "1"
skip_if_no_net = pytest.mark.skipif(
    not RUN_NETWORK,
    reason="Network tests disabled (set ALLOW_NETWORK_TESTS=1 to enable).",
)


@skip_if_no_net
def test_tk_api_reachable_and_returns_valid_json() -> None:
    client = TKClient()
    since = dt.datetime.now() - dt.timedelta(days=7)

    cases = client.zaken_modified_since(since, top=5)

    assert isinstance(cases, list)
    if cases:
        assert isinstance(cases[0], dict)
        # A TK record always carries one of these identifiers.
        assert "Id" in cases[0] or "ZaakId" in cases[0]


@skip_if_no_net
def test_rechtspraak_search_endpoint_reachable_and_returns_xml() -> None:
    client = RechtspraakClient()

    entries = client.iter_index(courts=["Hoge_Raad_der_Nederlanden"])

    first = next(entries)
    assert first.ecli.startswith("ECLI:")


@skip_if_no_net
def test_eurlex_returns_html_for_known_celex() -> None:
    client = EUClient()
    html = client.fetch_celex_html("32019L1158", lang="NL")

    assert isinstance(html, str)
