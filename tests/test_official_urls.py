"""The official page of a law, an article and a publication."""

from __future__ import annotations

from lawgraph.core.official_urls import article_url, instrument_url, publication_url


def test_a_bwb_regulation_and_its_articles_are_on_wetten_overheid_nl() -> None:
    assert instrument_url({"bwb_id": "BWBR0001854"}) == (
        "https://wetten.overheid.nl/BWBR0001854"
    )
    assert instrument_url({"bwb_id": "BWBR0001854"}, on="2020-01-01") == (
        "https://wetten.overheid.nl/BWBR0001854/2020-01-01"
    )
    assert article_url("BWBR0005290", "7:658") == (
        "https://wetten.overheid.nl/jci1.3:c:BWBR0005290&artikel=7:658"
    )
    assert article_url("BWBR0001840", "1", on="2023-02-22") == (
        "https://wetten.overheid.nl/jci1.3:c:BWBR0001840&artikel=1&g=2023-02-22"
    )
    # no number the JCI can address: the regulation
    assert article_url("BWBR0001840", None) == "https://wetten.overheid.nl/BWBR0001840"
    assert article_url("BWBR0001840", "bijlage 2 artikel 9") == (
        "https://wetten.overheid.nl/BWBR0001840"
    )
    # not the BWB
    assert instrument_url({"bwb_id": "ECHR-CONVENTION"}) is None
    assert article_url("ECHR-CONVENTION", "8") is None


def test_eu_acts_treaties_and_publications_have_their_own_sites() -> None:
    assert instrument_url({"celex": "32016R0679"}) == (
        "https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=CELEX:32016R0679"
    )
    treaty = "https://verdragenbank.overheid.nl/nl/Verdrag/Details/000001"
    assert instrument_url({"uri": treaty}) == treaty
    assert (
        instrument_url(
            {
                "publication_kind": "Stb",
                "publication_year": 2019,
                "publication_number": "33",
            }
        )
        == "https://zoek.officielebekendmakingen.nl/stb-2019-33.html"
    )
    assert publication_url({"id": "trb-2001-12", "year": 2001}) == (
        "https://zoek.officielebekendmakingen.nl/trb-2001-12.html"
    )
    # zoek.officielebekendmakingen.nl begins in 1995
    assert publication_url({"id": "stb-1988-157", "year": 1988}) is None
    assert instrument_url({}) is None
