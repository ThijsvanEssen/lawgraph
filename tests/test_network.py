# tests/test_network.py

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
    """
    Check: TK Zaak-endpoint bereikbaar en geeft zinvolle JSON.

    - Gebruikt de echte zaken_modified_since
    - Resultaat moet een list zijn, elk item een dict
    """
    client = TKClient()
    since = dt.datetime.now() - dt.timedelta(days=7)

    zaken = client.zaken_modified_since(since, top=5)

    assert isinstance(zaken, list)
    if zaken:
        assert isinstance(zaken[0], dict)
        # typische TK-velden, maar niet te hard checken
        assert "Id" in zaken[0] or "ZaakId" in zaken[0]


@skip_if_no_net
def test_rechtspraak_search_endpoint_reachable_and_returns_xml() -> None:
    """
    Check: Rechtspraak 'zoeken'-endpoint leeft en geeft XML-achtige content terug.
    """
    client = RechtspraakClient()

    xml_index = client.search_ecli_index(modified_since=None, extra_params=None)

    assert isinstance(xml_index, str)
    # minimale sanity check: XML-achtig
    assert "<" in xml_index or xml_index.strip() == ""


@skip_if_no_net
def test_eurlex_returns_html_for_known_celex() -> None:
    """
    Check: EUR-Lex levert HTML terug voor een bekende CELEX (32019L1158).
    """
    client = EUClient()
    html = client.fetch_celex_html("32019L1158", lang="NL")

    assert isinstance(html, str)
