"""HTML to text and accent folding: the output of every caller, and each written once."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from lawgraph.core import (
    cabinets,
    judgment_counsel,
    models,
    post_ministries,
)
from lawgraph.core.citations import strip_xml
from lawgraph.core.text_fold import ascii_slug, fold, plain_words, slug
from lawgraph.core.xml import html_text
from tests.paths import SRC

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


def test_fold() -> None:
    assert [fold(name) for name in NAMES] == FOLDED
    assert fold(None) == ""


@pytest.mark.parametrize("words", [post_ministries.phrase_of, plain_words])
def test_plain_words(words: Callable[[str], str]) -> None:
    assert [words(name) for name in NAMES] == WORDS


def test_cabinet_key() -> None:
    keys = [cabinets.cabinet_key(f"kabinet-{name}") for name in NAMES]
    assert keys == [*_joined(WORDS, "_")[:-1], None]


@pytest.mark.parametrize("sep", ["_", "-"])
def test_slug(sep: str) -> None:
    assert [slug(name, sep) for name in NAMES] == _joined(WORDS, sep)


def test_division_anchor_keeps_dots() -> None:
    assert [slug(name, keep=".") for name in NAMES] == [
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
    assert models.make_node_key("a__b_ -c_", "d") == "a_b_c_d"


def test_ascii_slug() -> None:
    assert [ascii_slug(name) for name in NAMES] == _joined(ASCII_WORDS, "-")


def test_counsel_words_leave_out_titles() -> None:
    assert [judgment_counsel._person_words(name) for name in NAMES] == [
        "roell",
        "yesilgoz zegerius",
        "curacao",
        "straße",
        "æbelø",
        "ijsselmeer",
        "ijsselmeer",
        "titel 10 2",
        "staats en bestuursrecht",
        "financien",
        "a de wit",
        "x2",
        "",
    ]


# ── one copy each ────────────────────────────────────────────────────────────

# What is written once, by the module (or modules) that may write it.
_HOMES: dict[str, tuple[re.Pattern[str], tuple[str, ...]]] = {
    # HTML to text and collapsed whitespace: core/xml.py
    "tag pattern": (re.compile(r"<\[\^>\]\+>"), ("core/xml.py",)),
    "collapsed whitespace": (
        re.compile(r'" "\.join\((?!.* for )[^()]*(?:\([^()]*\))?[^()]*\.split\(\)\)'),
        ("core/xml.py",),
    ),
    "child by local name": (
        re.compile(r"for \w+ in \w+ if local_name\(\w+\.tag\) == "),
        ("core/xml.py",),
    ),
    # accent folding: core/text_fold.py
    "compatibility decomposition": (re.compile(r'"NFKD"'), ("core/text_fold.py",)),
    # db/schema.py writes the same fold in SQL (``lg_fold``)
    "combining marks": (
        re.compile(r"unicodedata\.combining|\\u0300|\u0300"),
        ("core/text_fold.py", "db/schema.py"),
    ),
    "ASCII by dropping": (
        re.compile(r"""encode\(["']ascii["'], ["']ignore["']\)"""),
        ("core/text_fold.py",),
    ),
}


def _copies(pattern: re.Pattern[str], homes: tuple[str, ...]) -> list[str]:
    return [
        f"{path.relative_to(SRC)}:{n}"
        for path in sorted(SRC.rglob("*.py"))
        if path.relative_to(SRC).as_posix() not in homes
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]


@pytest.mark.parametrize("what", sorted(_HOMES))
def test_written_once(what: str) -> None:
    pattern, homes = _HOMES[what]
    assert _copies(pattern, homes) == [], f"{what} belongs in {homes[0]}"


def test_the_scan_would_catch_a_copy() -> None:
    lines = {
        "tag pattern": 'TAG = re.compile(r"<[^>]+>")',
        "collapsed whitespace": 'name = " ".join(text_of(node).split())',
        "child by local name": 'next((c for c in group if local_name(c.tag) == "nr"), None)',
        "compatibility decomposition": 'unicodedata.normalize("NFKD", text)',
        "combining marks": 'bare = "".join(c for c in text if not "\u0300" <= c)',
        "ASCII by dropping": 'text.encode("ascii", "ignore")',
    }
    for what, line in lines.items():
        assert _HOMES[what][0].search(line), what
    assert not _HOMES["collapsed whitespace"][0].search(
        '" ".join(word.capitalize() for word in title.split())'
    )
