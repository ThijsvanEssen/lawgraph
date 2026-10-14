"""HTML to text and accent folding: the output every caller gives, pinned per caller."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from lawgraph.core import (
    bwb_wti,
    cabinet_posts,
    cabinets,
    court_sources,
    division_anchor,
    government,
    judgment_counsel,
    member_slugs,
    ministries,
    ministry_sources,
    models,
    post_ministries,
)
from lawgraph.core.citations import strip_xml
from lawgraph.core.xml import html_text

# ── HTML to text ─────────────────────────────────────────────────────────────

HTML = [
    "<p>Wet&nbsp;op het <b>notariaat</b></p>",
    "a<br>b<br/>c",
    "  \n\t x \xa0 y  ",
    "R&amp;D &lt;tag&gt; &eacute;&#233;",
    "<script>var x=1;</script><style>p{}</style><!-- c --><p>tekst</p>",
    "on<i>line</i>",
    "",
    "1 &lt; 2 > 3",
]
FRAGMENT_TEXT = [
    "Wet op het notariaat",
    "a b c",
    "x y",
    "R&D <tag> éé",
    "var x=1; p{} tekst",
    "on line",
    "",
    "1 < 2 > 3",
]
PAGE_TEXT = [*FRAGMENT_TEXT[:4], "tekst", *FRAGMENT_TEXT[5:]]


def test_html_fragment_text() -> None:
    assert [html_text(fragment) for fragment in HTML] == FRAGMENT_TEXT


def test_html_page_text_leaves_out_script_style_and_comments() -> None:
    assert [html_text(fragment, page=True) for fragment in HTML] == PAGE_TEXT


def test_strip_xml_keeps_entities() -> None:
    assert [strip_xml(fragment) for fragment in HTML] == [
        "Wet&nbsp;op het notariaat",
        "a b c",
        "x y",
        "R&amp;D &lt;tag&gt; &eacute;&#233;",
        "var x=1; p{} tekst",
        "on line",
        "",
        "1 &lt; 2 > 3",
    ]


# ── accent folding and slugs ─────────────────────────────────────────────────

NAMES = [
    "Röell",
    "Yeşilgöz-Zegerius",
    "Curaçao",
    "Straße",
    "Æbelø",
    "ĳsselmeer",
    "IJsselmeer",
    "Titel 10.2",
    "Staats- en bestuursrecht",
    "ﬁnanciën",
    " Mr. Ä. de Wit ",
    "x²",
    "",
]

FOLDED = [
    "roell",
    "yesilgoz-zegerius",
    "curacao",
    "straße",
    "æbelø",
    "ijsselmeer",
    "ijsselmeer",
    "titel 10.2",
    "staats- en bestuursrecht",
    "financien",
    " mr. a. de wit ",
    "x2",
    "",
]
# A letter with no accent to take off (ß, æ, ø) parts the words.
WORDS = [
    "roell",
    "yesilgoz zegerius",
    "curacao",
    "stra e",
    "bel",
    "ijsselmeer",
    "ijsselmeer",
    "titel 10 2",
    "staats en bestuursrecht",
    "financien",
    "mr a de wit",
    "x2",
    "",
]
# Keys and member slugs leave such a letter out.
ASCII_WORDS = [
    "roell",
    "yesilgoz zegerius",
    "curacao",
    "strae",
    "bel",
    "ijsselmeer",
    "ijsselmeer",
    "titel 10 2",
    "staats en bestuursrecht",
    "financien",
    "mr a de wit",
    "x2",
    "",
]


def _joined(words: list[str], sep: str) -> list[str]:
    return [w.replace(" ", sep) for w in words]


@pytest.mark.parametrize("fold", [government._plain])
def test_fold(fold: Callable[[str], str]) -> None:
    assert [fold(name) for name in NAMES] == FOLDED


def test_cabinets_fold_strips() -> None:
    assert [cabinets._plain(name) for name in NAMES] == [f.strip() for f in FOLDED]


@pytest.mark.parametrize(
    "words", [post_ministries.phrase_of, ministry_sources._plain, ministries._plain]
)
def test_plain_words(words: Callable[[str], str]) -> None:
    assert [words(name) for name in NAMES] == WORDS


def test_cabinet_key() -> None:
    keys = [cabinets.cabinet_key(f"kabinet-{name}") for name in NAMES]
    assert keys == [*_joined(WORDS, "_")[:-1], None]


def test_court_slug() -> None:
    assert [court_sources.slug(name) for name in NAMES] == _joined(WORDS, "_")


def test_cabinet_post_slug() -> None:
    assert [cabinet_posts.slug(name) for name in NAMES] == _joined(WORDS, "-")


def test_division_anchor_keeps_dots() -> None:
    assert [division_anchor._slug(name) for name in NAMES] == [
        "roell",
        "yesilgoz-zegerius",
        "curacao",
        "stra-e",
        "bel",
        "ijsselmeer",
        "ijsselmeer",
        "titel-10.2",
        "staats-en-bestuursrecht",
        "financien",
        "mr.-a.-de-wit",
        "x2",
        "",
    ]


def test_node_key() -> None:
    keys = [models.make_node_key(name) for name in NAMES]
    assert keys == [*_joined(ASCII_WORDS, "_")[:-1], "node"]


@pytest.mark.parametrize("slugify", [member_slugs.slugify, bwb_wti.slugify])
def test_ascii_slug(slugify: Callable[[str], str]) -> None:
    assert [slugify(name) for name in NAMES] == _joined(ASCII_WORDS, "-")


def test_counsel_fold_leaves_out_titles() -> None:
    assert [judgment_counsel.fold(name) for name in NAMES] == [
        "roell",
        "yesilgoz zegerius",
        "curacao",
        "straße",
        "æbelø",
        "ĳsselmeer",
        "ijsselmeer",
        "titel 10 2",
        "staats en bestuursrecht",
        "ﬁnancien",
        "a de wit",
        "x²",
        "",
    ]
