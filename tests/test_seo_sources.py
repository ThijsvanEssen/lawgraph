"""Every kind of readable address has its page (``api/seo/sources.SOURCE_PAGES``), and a
publication is to find by one rule, on its page and in the sitemap (pure)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lawgraph.api.seo.pages.base import source_link
from lawgraph.api.seo.pages.parliament import member_image
from lawgraph.api.seo.sources import SOURCE_PAGES
from lawgraph.core.publications import own_title, publication_indexed
from lawgraph.core.readable_paths import parse_path

_CASES = json.loads(
    (Path(__file__).parent / "data" / "readable-paths.json").read_text()
)


def test_every_kind_of_address_has_a_read_and_a_page() -> None:
    kinds = set()
    for case in _CASES["paths"]:
        pad = parse_path(case["path"])
        assert pad is not None, case["path"]
        kinds.add(pad.soort)
    assert kinds == set(SOURCE_PAGES)


def test_the_image_of_each_kind() -> None:
    images = {kind: page.image for kind, page in SOURCE_PAGES.items()}
    assert images == {
        "wet": "/og/wet.png",
        "artikel": "/og/artikel.png",
        "uitspraak": "/og/uitspraak.png",
        "kamerstuk": "/og/kamerstuk.png",
        "dossier": "/og/dossier.png",
        "lid": member_image,
        "fractie": "/og/fractie.png",
        "kabinet": "/og/kabinet.png",
        "ministerie": "/og/ministerie.png",
        "commissie": "/og/commissie.png",
        "publicatie": "/og/publicatie.png",
        "toezegging": "/og/toezegging.png",
        "stemming": "/og/stemming.png",
        "bijlage": "/og/wet.png",
        "zaak": "/og/dossier.png",
        "activiteit": "/og/dossier.png",
    }


def test_a_member_is_shared_with_the_image_of_the_current_role() -> None:
    kamerlid = {"props": {"faction_memberships": [{"from_date": "2023-12-06"}]}}
    minister = {"props": {"government_functions": [{"from_date": "2023-12-06"}]}}
    assert member_image(kamerlid) == "/og/lid.png"
    assert member_image(minister) == "/og/bewindspersoon.png"
    assert member_image({"props": None}) == "/og/lid.png"


@pytest.mark.parametrize(
    ("title", "own"),
    [
        ("Besluit tot wijziging van het Mediabesluit 2008", True),
        (" Wet van 1 juli 2025 ", True),
        ("Staatsblad 2025/301", False),
        (" Staatsblad 2025/301 ", False),
        ("Staatsblad", False),
        ("TRACTATENBLAD", False),
        ("", False),
        (None, False),
    ],
)
def test_a_title_of_its_own(title: str | None, own: bool) -> None:
    assert bool(own_title(title)) is own
    assert publication_indexed(title, False) is own
    assert publication_indexed(title, True) is True


def test_an_article_of_a_book_of_a_code_is_cited_by_its_code() -> None:
    """A link to an article of Boek 5 BW reads ``Artikel 5:40 BW``, not by the short title
    of the book in the BWB (``BW5``, B39); an article of another law keeps its own."""
    book = {
        "collection": "articles",
        "id": "articles/bwbr0005288_40",
        "bwb_id": "BWBR0005288",
        "article_number": "40",
        "law": "BW5",
    }
    assert ">Artikel 5:40 BW<" in source_link(book)
    sr = {
        "collection": "articles",
        "id": "articles/bwbr0001854_287",
        "bwb_id": "BWBR0001854",
        "article_number": "287",
        "law": "Sr",
    }
    assert ">Artikel 287 Sr<" in source_link(sr)
