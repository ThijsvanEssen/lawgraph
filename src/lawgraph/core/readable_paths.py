"""A bron at an address a lawyer can read and type: the official identifier in the path.

    /uitspraken/ECLI:NL:HR:2019:2006     a judgment, by its ECLI (as rechtspraak.nl)
    /wetten/BWBR0005289                  a law, by its BWB id
    /wetten/BWBR0005289/artikel/6:162    an article, by its law and number
    /dossiers/36600-VIII                 a dossier, by its number
    /kamerstukken/36799/31               a Kamerstuk, by its dossier and number
    /kamerstukken/36600-VIII/AB          one of the Eerste Kamer, by its letter
    /stb/2026/94                         a publication, by series, year and number
    /leden/rob-jetten                    a lid or bewindspersoon, by its slug
    /kabinetten/rutte_iv                 a cabinet, by its key
    /fracties/d66                        a fractie, by its key
    /commissies/szw                      a commissie, by its slug
    /toezeggingen/TZ202609-124           a toezegging, by its number
    /stemmingen/decision_154df5db_…      a decision (a vote), by its key

The same addresses as the front end (``src/lib/bron/leesbaar.ts`` of lawgraph-explorer:
``parsePad``, ``padHref``, ``padOfFocus``); ``readable-paths.json`` holds the cases both
are tested against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

from lawgraph.core.models import make_node_key

ECLI = re.compile(r"^ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[A-Z0-9.]+$", re.IGNORECASE)
DOSSIER = re.compile(r"^\d{4,6}(-[A-Z0-9()]+)*$", re.IGNORECASE)
# A law in the BWB by its id, which is its node key too: BWBR0005290.
BWB = re.compile(r"^BWBR\d{7}$", re.IGNORECASE)
# A key or slug as the API gives it: ``rutte_iv``, ``ek_democraten_1966``.
SLEUTEL = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# The number of a toezegging: ``TZ202609-124``.
COMMITMENT_NUMBER = re.compile(r"^TZ\d+-\d+$", re.IGNORECASE)
# The number of a stuk: a figure in the Tweede Kamer, letters in the Eerste (A, AB).
STUK = re.compile(r"^(\d+|[A-Z]{1,3})$", re.IGNORECASE)
REEKSEN = ("stb", "stcrt", "trb")
_JUDGMENT_KEY = re.compile(r"^ecli_[a-z]{2}_[a-z0-9]+_\d{4}_[a-z0-9.]+$")
_PUBLICATION_ID = re.compile(r"^(stb|stcrt|trb)-(\d{4})-(\d+)$")

# The boeken of the Burgerlijk Wetboek and their BWB ids: an article is cited with its
# book before the number (6:162).
BW_BOOKS = {
    "1": "BWBR0002656",
    "2": "BWBR0003045",
    "3": "BWBR0005291",
    "4": "BWBR0002761",
    "5": "BWBR0005288",
    "6": "BWBR0005289",
    "7": "BWBR0005290",
    "7a": "BWBR0006000",
    "8": "BWBR0005034",
    "10": "BWBR0030068",
}
_BOOK_OF = {bwb: book.upper() for book, bwb in BW_BOOKS.items()}


@dataclass(frozen=True)
class Pad:
    """A readable address: its kind (``soort``) and its parts, as the front end has them.
    ``a``, ``b`` and ``c`` are, per kind: an ECLI; a law; a law and a number; a dossier;
    a dossier and a number; a series, a year and a number; a slug or key; a number."""

    soort: str
    a: str
    b: str = ""
    c: str = ""


def book_number(bwb_id: str | None, number: str) -> str:
    """The number an article is cited by: ``6:162`` for article 162 of Boek 6."""
    book = _BOOK_OF.get((bwb_id or "").upper())
    return f"{book}:{number}" if book and ":" not in number else number


def parse_path(pathname: str) -> Pad | None:
    """The readable address in a path, or None for any other page."""
    try:
        parts = [unquote(p, errors="strict") for p in pathname.split("/") if p]
    except UnicodeDecodeError:
        return None
    first, a, b, c = (parts + ["", "", "", ""])[:4]
    n = len(parts)
    if first == "uitspraken" and n == 2 and ECLI.match(a):
        return Pad("uitspraak", a.upper())
    if first == "wetten" and n == 2 and BWB.match(a):
        return Pad("wet", a.upper())
    if first == "wetten" and n == 4 and b == "artikel" and a and c:
        return Pad("artikel", a.upper(), c)
    if first == "dossiers" and n == 2 and DOSSIER.match(a):
        return Pad("dossier", a.upper())
    if first == "leden" and n == 2 and SLUG.match(a):
        return Pad("lid", a)
    if first == "kabinetten" and n == 2 and SLEUTEL.match(a):
        return Pad("kabinet", a)
    if first == "fracties" and n == 2 and SLEUTEL.match(a):
        return Pad("fractie", a)
    if first == "commissies" and n == 2 and SLEUTEL.match(a):
        return Pad("commissie", a)
    if first == "stemmingen" and n == 2 and SLEUTEL.match(a):
        return Pad("stemming", a)
    if first == "toezeggingen" and n == 2 and COMMITMENT_NUMBER.match(a):
        return Pad("toezegging", a.upper())
    if (
        first in REEKSEN
        and n == 3
        and re.fullmatch(r"\d{4}", a)
        and re.fullmatch(r"\d+", b)
    ):
        return Pad("publicatie", first, a, b)
    if first == "kamerstukken" and n == 3 and DOSSIER.match(a) and STUK.match(b):
        return Pad("kamerstuk", a.upper(), b.upper())
    return None


def _e(part: str) -> str:
    """``encodeURIComponent``."""
    return quote(part, safe="-_.!~*'()")


def _keep(part: str) -> str:
    """``encodeURIComponent`` with the colon kept: it is safe in a segment."""
    return _e(part).replace("%3A", ":")


def pad_href(pad: Pad) -> str:
    """The path of a readable address."""
    s = pad.soort
    if s == "uitspraak":
        return f"/uitspraken/{_keep(pad.a)}"
    if s == "artikel":
        return f"/wetten/{_e(pad.a)}/artikel/{_keep(pad.b)}"
    if s == "wet":
        return f"/wetten/{_e(pad.a)}"
    if s == "dossier":
        return f"/dossiers/{_e(pad.a)}"
    if s == "kamerstuk":
        return f"/kamerstukken/{_e(pad.a)}/{_e(pad.b)}"
    if s == "publicatie":
        return f"/{pad.a}/{pad.b}/{pad.c}"
    prefix = {
        "lid": "leden",
        "kabinet": "kabinetten",
        "fractie": "fracties",
        "commissie": "commissies",
        "toezegging": "toezeggingen",
        "stemming": "stemmingen",
    }[s]
    return f"/{prefix}/{pad.a}"


def judgment_key(ecli: str) -> str:
    """A judgment's node key from its ECLI: ``ecli_nl_hr_2019_2006``."""
    return ecli.lower().replace(":", "_")


def key_ecli(key: str) -> str | None:
    """The ECLI of a judgment's node key, or None."""
    return key.upper().replace("_", ":") if _JUDGMENT_KEY.match(key) else None


def focus_of_pad(pad: Pad) -> str | None:
    """The node id an address names without a lookup: a judgment, a law, a dossier, a
    cabinet and a fractie (their key is their id); None for the others."""
    if pad.soort == "uitspraak":
        return f"judgments/{judgment_key(pad.a)}"
    if pad.soort == "wet":
        return f"instruments/{pad.a.lower()}"
    if pad.soort == "dossier":
        return f"dossiers/{make_node_key(pad.a)}"
    if pad.soort == "kabinet":
        return f"cabinets/{pad.a}"
    if pad.soort == "fractie":
        return f"factions/{pad.a}"
    if pad.soort == "stemming":
        return f"decisions/{pad.a}"
    return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _judgment(key: str, props: dict[str, Any]) -> str | None:
    ecli = _text(props.get("ecli")) or key_ecli(key)
    return (
        pad_href(Pad("uitspraak", ecli.upper())) if ecli and ECLI.match(ecli) else None
    )


def _dossier(key: str, props: dict[str, Any]) -> str | None:
    """The address of a dossier by its label: its key is the label made a key
    (``36600_viii``). The label is in its props (a dossier answer has it as its ``number``),
    or is its number and its suffix (``lookup.answer``); a key of figures alone is it."""
    label = _text(props.get("label"))
    if not label and (number := _text(props.get("number"))):
        suffix = _text(props.get("suffix"))
        label = f"{number}-{suffix}" if suffix and "-" not in number else number
    if not label and re.fullmatch(r"\d+", key):
        label = key
    return (
        pad_href(Pad("dossier", label.upper()))
        if label and DOSSIER.match(label)
        else None
    )


def _article(key: str, props: dict[str, Any]) -> str | None:
    law = _text(props.get("bwb_id")) or _text(props.get("celex"))
    number = _text(props.get("article_number"))
    # A number with a space ("bijlage 2 artikel 6") has no address of its own.
    if not law or not number or re.search(r"\s", number):
        return None
    return pad_href(Pad("artikel", law, book_number(law, number)))


def _instrument(key: str, props: dict[str, Any]) -> str | None:
    if BWB.match(key):
        return pad_href(Pad("wet", key.upper()))
    official = _text(props.get("official_id")) or key.replace("_", "-")
    m = _PUBLICATION_ID.match(official.lower())
    return pad_href(Pad("publicatie", m[1], m[2], m[3])) if m else None


def _slug(soort: str, pattern: re.Pattern[str]) -> Any:
    def by_slug(key: str, props: dict[str, Any]) -> str | None:
        slug = _text(props.get("slug"))
        return pad_href(Pad(soort, slug)) if slug and pattern.match(slug) else None

    return by_slug


def _by_key(soort: str) -> Any:
    def by_key(key: str, props: dict[str, Any]) -> str | None:
        return pad_href(Pad(soort, key)) if SLEUTEL.match(key) else None

    return by_key


def _commitment(key: str, props: dict[str, Any]) -> str | None:
    number = _text(props.get("number"))
    if not number or not COMMITMENT_NUMBER.match(number):
        return None
    return pad_href(Pad("toezegging", number.upper()))


def _paper(key: str, props: dict[str, Any]) -> str | None:
    # Dossier and number as the stuk is cited: 36600-VIII, and 31 in the Tweede Kamer or
    # AB in the Eerste (``number``, the letter).
    number = _text(props.get("dossier_number"))
    suffix = _text(props.get("dossier_suffix"))
    dossier = f"{number}-{suffix}" if number and suffix else number
    sequence = props.get("sequence")
    paper = (
        str(sequence)
        if isinstance(sequence, int) and not isinstance(sequence, bool)
        else _text(props.get("number"))
    )
    if not dossier or not paper or not STUK.match(paper):
        return None
    return pad_href(Pad("kamerstuk", dossier, paper.upper()))


# The readable address of a node of each collection that has one.
_PATHS: dict[str, Any] = {
    "judgments": _judgment,
    "dossiers": _dossier,
    "articles": _article,
    "instruments": _instrument,
    "members": _slug("lid", SLUG),
    "committees": _slug("commissie", SLEUTEL),
    "cabinets": _by_key("kabinet"),
    "factions": _by_key("fractie"),
    "decisions": _by_key("stemming"),
    "commitments": _commitment,
    "documents": _paper,
}


def path_of(node_id: str, props: dict[str, Any] | None = None) -> str | None:
    """The readable address of a node, from its key or the props of its node; None
    where it has none (an activity, an annex: still /explore)."""
    collection, _, key = node_id.partition("/")
    build = _PATHS.get(collection)
    return build(key, props or {}) if key and build else None
