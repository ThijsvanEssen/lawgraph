"""A regulation of one article: the BWB gives it as ``<enig-artikel>`` (no ``<kop>``, no
number) at ``/Enig-artikel``, where an article is ``<artikel>``.

The fixtures are toestanden the repository served on 20 October 2026, whole: the Aanpassing
bedragen reis- en verblijfkosten leden Eerste Kamer (BWBR0007846, 1996-01-01) and the
Aanwijzing opsporingsambtenaren Wet tarieven gezondheidszorg (BWBR0003481, 1982-12-13), an
enig artikel with a list and links to other regulations.
"""

from __future__ import annotations

import pytest

from lawgraph.core.bwb_definitions import definitions
from lawgraph.core.bwb_xml import (
    ENIG_ARTIKEL,
    article_address,
    article_key,
    article_props,
    article_version_props,
    parse_toestand,
    read_toestand,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.names import article_name, article_title
from lawgraph.core.official_urls import article_url
from lawgraph.core.readable_paths import Pad, parse_path, path_of
from tests.paths import fixture_text

REISKOSTEN = "BWBR0007846"
OPSPORING = "BWBR0003481"


@pytest.fixture(scope="module")
def reiskosten():
    return parse_toestand(fixture_text("bwb_enig_artikel_toestand.xml"))


@pytest.fixture(scope="module")
def opsporing():
    return parse_toestand(fixture_text("bwb_enig_artikel_lijst_toestand.xml"))


def test_the_one_article_is_read_with_its_text(reiskosten) -> None:
    (article,) = reiskosten.articles
    assert article.number == ENIG_ARTIKEL == "enig-artikel"
    assert article.label == "Enig artikel"
    assert article.path == "/Enig-artikel"
    assert (article.stam_id, article.versie_id) == ("4481543", "6287772")
    assert article.text.startswith(
        "Artikel 17\nVanaf 1 januari 1996 bedraagt de vergoeding van de reiskosten op "
        "jaarbasis"
    )
    assert "de vergoeding van de verblijfkosten" in article.text
    assert article.valid_from == "1996-01-01"
    assert article.origin is not None and article.origin.identifier == "stcrt-1996-19"


def test_its_list_and_its_links_are_read(opsporing) -> None:
    (article,) = opsporing.articles
    assert article.number == ENIG_ARTIKEL
    assert article.text.startswith("in overeenstemming met de Ministers")
    assert [part.id for part in article.parts][:2] == ["aanhef", "onder-1"]
    assert "BWBR0003356" in {ref.bwb_id for ref in article.references}


def test_history_reads_it_as_a_version(opsporing) -> None:
    _, heads = read_toestand(fixture_text("bwb_enig_artikel_lijst_toestand.xml"))
    (head,) = heads
    assert (head.stam_id, head.article.number) == ("3675833", ENIG_ARTIKEL)


def test_its_key_address_and_props_follow_its_number(reiskosten) -> None:
    (article,) = reiskosten.articles
    key = article_key(REISKOSTEN, article.number, article.stam_id)
    assert key == "bwbr0007846_enig_artikel"
    address = article_address(REISKOSTEN, key, article.number)
    assert address == "enig-artikel"
    # the article routes make the key of the address again
    assert make_node_key(REISKOSTEN, address) == key
    title = reiskosten.citation_title
    props = article_props(article, REISKOSTEN, title, 0)
    assert props["article_number"] == "enig-artikel"
    assert props["display_name"] == f"Enig artikel {title}"
    version = article_version_props(article, REISKOSTEN, title, 0)
    assert version["label"] == "Enig artikel"


def test_it_has_a_readable_address_and_a_title(reiskosten) -> None:
    (article,) = reiskosten.articles
    props = article_props(article, REISKOSTEN, reiskosten.citation_title, 0)
    path = path_of(f"articles/{article_key(REISKOSTEN, article.number, None)}", props)
    assert path == "/wetten/BWBR0007846/artikel/enig-artikel"
    assert parse_path(path) == Pad("artikel", REISKOSTEN, "enig-artikel")
    law = {"bwb_id": REISKOSTEN, "citation_title": reiskosten.citation_title}
    assert article_title(props, law) == f"Enig artikel {reiskosten.citation_title}"
    assert article_name(REISKOSTEN, "enig-artikel", "Wet") == "Enig artikel Wet"


def test_its_official_page_is_that_of_its_regulation() -> None:
    # The JCI has no address for it: wetten.overheid.nl shows it on the regulation's page.
    assert (
        article_url(REISKOSTEN, ENIG_ARTIKEL)
        == f"https://wetten.overheid.nl/{REISKOSTEN}"
    )


def test_a_definition_in_it_names_it() -> None:
    xml = fixture_text("bwb_enig_artikel_toestand.xml").replace(
        "<al>Vanaf 1 januari 1996 bedraagt",
        "<al>In deze regeling wordt verstaan onder:</al><lijst><li><li.nr>a.</li.nr>"
        "<al><nadruk>wet</nadruk>: de Wet vergoedingen leden Eerste Kamer;</al></li>"
        "</lijst><al>Vanaf 1 januari 1996 bedraagt",
        1,
    )
    (found,) = definitions(REISKOSTEN, xml)
    assert (found["article_key"], found["article_number"], found["term"]) == (
        "bwbr0007846_enig_artikel",
        "enig-artikel",
        "wet",
    )
