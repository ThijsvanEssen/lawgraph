"""The words of a title (pure): a day as the explorer writes it, a judgment as a lawyer cites
it, and what an article is about."""

from __future__ import annotations

from lawgraph.core.article_caption import captions
from lawgraph.core.judgment_cite import author_cite, court_cite, judgment_cite
from lawgraph.core.time import long_date


def test_a_day_in_words() -> None:
    assert long_date("2019-12-20") == "20 december 2019"
    assert long_date("1992-01-01T00:00:00") == "1 januari 1992"
    assert (
        long_date("2019-13-01") == "" and long_date(None) == "" and long_date("") == ""
    )


def test_a_court_as_it_is_cited() -> None:
    assert court_cite("ECLI:NL:HR:2019:2006") == "HR"
    assert court_cite("ECLI:NL:PHR:2001:AB0289") == "Conclusie"
    assert court_cite("ECLI:NL:RVS:2020:1") == "ABRvS"
    assert court_cite("ECLI:NL:RBDHA:2026:1", "Rechtbank Den Haag") == "Rb. Den Haag"
    assert (
        court_cite("ECLI:NL:GHAMS:2026:2", "Gerechtshof Amsterdam") == "Hof Amsterdam"
    )
    assert court_cite("ECLI:CE:ECHR:2020:1") == "EHRM"
    assert court_cite("ECLI:EU:C:2020:1") == "HvJ EU"


def test_a_judgment_as_it_is_cited() -> None:
    assert judgment_cite("ECLI:NL:HR:2019:2006", "2019-12-20") == "HR 20 december 2019"
    author = author_cite("T. Hartlief")
    assert author == "A-G Hartlief"
    assert (
        judgment_cite("ECLI:NL:PHR:2020:1", "2020-05-08", None, author)
        == "Conclusie A-G Hartlief 8 mei 2020"
    )


def _crumbs(*titles: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"type": t, "label": label, "title": title} for t, label, title in titles]


def test_an_article_is_about_the_deepest_title_its_law_has_once() -> None:
    boek = ("boek", "Boek 6", "Algemeen gedeelte van het verbintenissenrecht")
    articles = [
        # every titel of Boek 6 opens with an afdeling "Algemene bepalingen"
        {"key": "a162", "breadcrumb": _crumbs(boek, ("titeldeel", "Titel 3",
         "Onrechtmatige daad"), ("afdeling", "Afdeling 1", "Algemene bepalingen"))},
        {"key": "a1", "breadcrumb": _crumbs(boek, ("titeldeel", "Titel 1",
         "Verbintenissen in het algemeen"), ("afdeling", "Afdeling 1",
         "Algemene bepalingen"))},
        {"key": "a6", "breadcrumb": _crumbs(boek, ("titeldeel", "Titel 1",
         "Verbintenissen in het algemeen"), ("afdeling", "Afdeling 2",
         "Pluraliteit van schuldenaren"))},
        {"key": "flat", "breadcrumb": None},
    ]  # fmt: skip
    assert captions(articles) == {
        "a162": "Onrechtmatige daad",
        "a1": "Verbintenissen in het algemeen",
        "a6": "Pluraliteit van schuldenaren",
        "flat": None,
    }


def test_two_articles_with_one_caption_have_their_own_titles() -> None:
    from lawgraph.api.seo.pages import article_title, version_title

    law = {"bwb_id": "BWBR0005289", "short_title": "BW6"}
    one = {
        "bwb_id": "BWBR0005289",
        "article_number": "162",
        "caption": "Onrechtmatige daad",
    }
    two = {**one, "article_number": "163"}
    assert article_title(one, law) == "Art. 6:162 BW, Onrechtmatige daad"
    assert article_title(two, law) == "Art. 6:163 BW, Onrechtmatige daad"
    version = {
        "bwb_id": "BWBR0001840",
        "instrument_citation_title": "Grondwet",
        "valid_from": "2002-03-21",
        "valid_until": "2005-02-08",
    }
    assert (
        version_title(version)
        == "Grondwet, geldend van 21 maart 2002 tot 8 februari 2005"
    )
