"""The words of a title (pure): a day as the explorer writes it, a judgment as a lawyer cites
it, and what an article is about."""

from __future__ import annotations

from lawgraph.core.article_caption import captions
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.judgment_cite import author_cite, court_cite, judgment_cite


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
    from lawgraph.api.seo.pages.titles import article_title, version_title

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


def test_a_zaak_is_titled_by_its_title_not_its_category() -> None:
    """The kind of a zaak is the source's category (``Brief van lid/fractie/commissie``),
    which the reader leaves out: only a zaak without a title is named by it."""
    from lawgraph.api.seo.pages.titles import case_title

    letter = {
        "number": "2025Z15468",
        "kind": "Brief van lid/fractie/commissie",
        "title": "Brief van de tijdelijke commissie Grondrechten",
    }
    assert case_title(letter, "k") == (
        "Brief van de tijdelijke commissie Grondrechten (2025Z15468)"
    )
    assert case_title({**letter, "title": None}, "k") == (
        "Brief van lid/fractie/commissie (2025Z15468)"
    )


def test_a_faction_named_after_the_member_is_left_out_of_their_title() -> None:
    """``Lid Keijzer`` says the name again (as the explorer's ``eigenFractie``)."""
    from lawgraph.api.seo.pages.titles import member_title

    def member(faction: str) -> dict[str, object]:
        return {
            "name": "Mona Keijzer",
            "faction_memberships": [{"abbreviation": faction, "to_date": None}],
        }

    assert member_title(member("Lid Keijzer")) == "Mona Keijzer, Tweede Kamerlid"
    assert member_title(member("BBB")) == "Mona Keijzer, Tweede Kamerlid (BBB)"


def test_an_annex_is_titled_by_the_law_its_page_reads() -> None:
    """The API title of an annex and its page name the law alike: from the instrument
    (``seo.law_of``), whatever its own props hold yet."""
    from lawgraph.api.seo.pages.titles import annex_title, title_of

    props = {"bwb_id": "BWBR0002741", "label": "II", "description": "Vervallen"}
    law = {"bwb_id": "BWBR0002741", "short_title": "Bds 1970", "citation_title": "x"}
    title, _ = title_of("annexes/bwbr0002741_annex_ii", props, law)
    assert title == annex_title(props, law) == "Bijlage II Bds 1970"


def test_a_book_of_a_code_is_named_as_it_is_cited() -> None:
    """``Boek 6 BW``, not the citation title with its short title after it; another law
    keeps its name."""
    from lawgraph.api.seo.pages.titles import law_name, title_of

    book = {
        "bwb_id": "BWBR0005289",
        "citation_title": "Burgerlijk Wetboek Boek 6",
        "short_title": "BW6",
    }
    assert law_name(book) == "Boek 6 BW"
    assert title_of("instruments/bwbr0005289", book)[0] == "Boek 6 BW"
    law = {"bwb_id": "BWBR0002741", "citation_title": "Opiumwet", "short_title": "Ow"}
    assert law_name(law) == "Opiumwet (Ow)"


def test_a_dossier_number_reads_in_its_official_notation() -> None:
    """``36600 VIII``: the suffix after a space, in the text a reader sees; the address
    keeps the label (``/dossiers/36600-VIII``). ``21501-20`` is a number of its own."""
    from lawgraph.api.seo.pages.parliament import dossier_page
    from lawgraph.api.seo.pages.titles import dossier_title, title_of
    from lawgraph.core.dossier_numbers import official_number

    assert official_number("36600-VIII") == "36600 VIII"
    assert official_number("23908-(R1519)") == "23908 (R1519)"
    assert official_number("21501-20") == "21501-20"
    assert official_number("36496") == "36496"
    props = {"label": "36600-VIII", "title": "Vaststelling begroting OCW 2026"}
    assert dossier_title(props, "36600_viii").startswith("36600 VIII ")
    assert title_of("dossiers/36600_viii", props)[0].startswith("36600 VIII ")
    page = dossier_page({"id": "dossiers/36600_viii", "key": "36600_viii",
                         "props": props, "papers": []})  # fmt: skip
    assert page.path == "/dossiers/36600-VIII"
    assert "36600-VIII" not in page.title + page.body
