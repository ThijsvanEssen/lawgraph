"""Every kind of readable address has its page (``api/seo/sources.SOURCE_PAGES``), and a
publication is to find by one rule, on its page and in the sitemap (pure)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lawgraph.api.seo.pages.base import SITE_IMAGE, source_link
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


# The kinds whose page is shared with the image of the site.
_WITH_SITE_IMAGE = (
    "lid",
    "fractie",
    "kabinet",
    "commissie",
    "publicatie",
    "toezegging",
    "stemming",
)


def test_the_image_of_each_kind() -> None:
    images = {kind: page.image for kind, page in SOURCE_PAGES.items()}
    assert images == {
        "wet": "/og/wet.png",
        "artikel": "/og/artikel.png",
        "uitspraak": "/og/uitspraak.png",
        "kamerstuk": "/og/kamerstuk.png",
        "dossier": "/og/dossier.png",
        "bijlage": "/og/wet.png",
        "zaak": "/og/dossier.png",
        "activiteit": "/og/dossier.png",
        **dict.fromkeys(_WITH_SITE_IMAGE, SITE_IMAGE),
    }


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
