"""The official page of a law, an article and a publication."""

from __future__ import annotations

from lawgraph.core.official_urls import (
    article_url,
    document_url,
    instrument_url,
    judgment_url,
    publication_url,
)


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
    assert instrument_url({"bwb_id": "NOT-A-BWB-ID"}) is None
    assert article_url("NOT-A-BWB-ID", "8") is None


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


def test_a_judgment_is_on_rechtspraak_nl_or_hudoc() -> None:
    assert judgment_url({"source": "echr", "external_id": "001-208058"}) == (
        "https://hudoc.echr.coe.int/eng?i=001-208058"
    )
    assert judgment_url({"source": "rechtspraak", "ecli": "ECLI:NL:HR:2019:1278"}) == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2019:1278"
    )
    assert judgment_url({"ecli": "ECLI:BE:GHANT:2020:1"}) is None  # a foreign stub
    assert judgment_url({"source": "echr"}) is None


def test_a_path_of_the_eerste_kamer_is_its_page_on_the_site() -> None:
    from lawgraph.core.official_urls import ek_path, ek_url

    page = "https://www.eerstekamer.nl/wetsvoorstel/36123_wet"
    assert ek_url("/wetsvoorstel/36123_wet") == page
    assert ek_url(page) == page  # an absolute URL stays as it is
    assert ek_url("https://www.example.org/x.pdf") == "https://www.example.org/x.pdf"
    assert ek_url(None) is None
    assert ek_path(page) == "/wetsvoorstel/36123_wet"
    assert ek_path("https://www.example.org/x") is None  # not on the site
    assert ek_path(ek_url("/") or "") == "/"


def test_a_paper_is_on_officielebekendmakingen_nl() -> None:
    ob = "https://zoek.officielebekendmakingen.nl/{}.html".format
    # of the Eerste Kamer: the page its record names
    ek = {
        "source": "eerstekamer",
        "external_id": "kst-1274216",
        "url": ob("kst-1274216"),
    }
    assert document_url(ek) == ob("kst-1274216")
    # of the Staatsblad and the Staatscourant: by its identifier, from 1995
    assert document_url({"identifier": "stb-2010-350", "year": "2010"}) == ob(
        "stb-2010-350"
    )
    assert document_url({"identifier": "stcrt-2026-24789"}) == ob("stcrt-2026-24789")
    assert document_url({"identifier": "stb-1990-12"}) is None
    # a Kamerstuk of the Tweede Kamer: by its address, once its text was read from there
    kamerstuk = {"dossier_number": "37020", "dossier_suffix": "X", "sequence": 53}
    assert document_url({**kamerstuk, "text_source": "kst-xml"}) == ob("kst-37020-X-53")
    assert document_url(kamerstuk) is None  # not (yet) read from the repository
    assert document_url({"text_source": "kst-xml"}) is None  # no Kamerstuk
    assert document_url({"url": "/not-absolute"}) is None
