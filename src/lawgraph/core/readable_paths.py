"""A bron at an address a lawyer can read and type: the official identifier in the path.

    /uitspraken/ECLI:NL:HR:2019:2006     a judgment, by its ECLI (as rechtspraak.nl)
    /wetten/BWBR0005289                  a law, by its BWB id
    /wetten/32022L2555                   an EU act, by its CELEX number
    /wetten/BWBR0005289/artikel/6:162    an article, by its law and number
    /wetten/BWBR0002741/bijlage/II       an annex, by its law and label
    /dossiers/36600-VIII                 a dossier, by its number
    /kamerstukken/36799/31               a Kamerstuk, by its dossier and number
    /kamerstukken/36600-VIII/AB          one of the Eerste Kamer, by its letter
    /zaken/2025Z15468                    a zaak of the Tweede Kamer, by its number
    /activiteiten/2026A01323             an activity of the Tweede Kamer (a debate), by its
                                         number
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

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.core.code_families import cited_number
from lawgraph.core.ecli import PATH_ECLI, ecli_of_key
from lawgraph.core.identifiers import CELEX_MATCH_LETTERS, COMMITMENT_NUMBER
from lawgraph.core.models import make_node_key, node_id, parse_node_id
from lawgraph.core.publications import (
    SERIES,
    official_of_instrument_key,
    parse_koop_id,
)

DOSSIER = re.compile(r"^\d{4,6}(-[A-Z0-9()]+)*$", re.IGNORECASE)
# A law in the BWB by its id, which is its node key too: BWBR0005290.
BWB = re.compile(r"^BWBR\d{7}$", re.IGNORECASE)
# An EU act by its CELEX number (sector 3, its year, its kind and its number), its node key
# too in lower case: 32022L2555 (``core/identifiers.parse_celex``).
CELEX = re.compile(rf"^3\d{{4}}[{CELEX_MATCH_LETTERS}]\d+$", re.IGNORECASE)
# A law at ``/wetten``: one of the BWB or an EU act.
LAW = re.compile(rf"{BWB.pattern}|{CELEX.pattern}", re.IGNORECASE)
# A key or slug as the API gives it: ``rutte_iv``, ``ek_democraten_1966``.
SLEUTEL = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# The number of a stuk: a figure in the Tweede Kamer, letters in the Eerste (A, AB).
STUK = re.compile(r"^(\d+|[A-Z]{1,3})$", re.IGNORECASE)
# The number of a zaak of the Tweede Kamer: ``2025Z15468``.
CASE_NUMBER = re.compile(r"^\d{4}Z\d+$", re.IGNORECASE)
# The number of an activity of the Tweede Kamer: ``2026A01323``.
ACTIVITY_NUMBER = re.compile(r"^\d{4}A\d+$", re.IGNORECASE)
# The label of an annex as cited in the text of its law: ``II``, ``2``, ``A``, ``1a``.
ANNEX_LABEL = re.compile(r"^[A-Z0-9]+(?:[.-][A-Z0-9]+)*$", re.IGNORECASE)


@dataclass(frozen=True)
class Pad:
    """A readable address: its kind (``soort``) and its parts, as the front end has them.
    ``a``, ``b`` and ``c`` are, per kind: an ECLI; a law (a BWB id or a CELEX number); a
    law and a number; a law and the label of an annex; a dossier; a dossier and a number;
    a series, a year and a number; a slug or key; a number."""

    soort: str
    a: str
    b: str = ""
    c: str = ""


# The addresses of one segment after their prefix: the kind, the pattern of the segment
# and whether it is written in capitals (an ECLI, a BWB id, a number).
_ONE_PART: dict[str, tuple[str, re.Pattern[str], bool]] = {
    "uitspraken": ("uitspraak", PATH_ECLI, True),
    "wetten": ("wet", LAW, True),
    "dossiers": ("dossier", DOSSIER, True),
    "leden": ("lid", SLUG, False),
    "kabinetten": ("kabinet", SLEUTEL, False),
    "fracties": ("fractie", SLEUTEL, False),
    "commissies": ("commissie", SLEUTEL, False),
    "stemmingen": ("stemming", SLEUTEL, False),
    "toezeggingen": ("toezegging", COMMITMENT_NUMBER, True),
    "zaken": ("zaak", CASE_NUMBER, True),
    "activiteiten": ("activiteit", ACTIVITY_NUMBER, True),
}


def parse_path(pathname: str) -> Pad | None:
    """The readable address in a path, or None for any other page."""
    try:
        parts = [unquote(p, errors="strict") for p in pathname.split("/") if p]
    except UnicodeDecodeError:
        return None
    first, a, b, c = (parts + ["", "", "", ""])[:4]
    n = len(parts)
    if n == 2 and first in _ONE_PART:
        soort, pattern, upper = _ONE_PART[first]
        return Pad(soort, a.upper() if upper else a) if pattern.match(a) else None
    if first == "wetten" and n == 4 and b == "artikel" and a and c:
        return Pad("artikel", a.upper(), c)
    if first == "wetten" and n == 4 and b == "bijlage" and BWB.match(a):
        return Pad("bijlage", a.upper(), c.upper()) if ANNEX_LABEL.match(c) else None
    if (
        first in SERIES
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
    if s == "bijlage":
        return f"/wetten/{_e(pad.a)}/bijlage/{_e(pad.b)}"
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
        "zaak": "zaken",
        "activiteit": "activiteiten",
    }[s]
    return f"/{prefix}/{pad.a}"


def focus_of_pad(pad: Pad) -> str | None:
    """The node id an address names without a lookup: a judgment, a law, a dossier, a
    cabinet and a fractie (their key is their id); None for the others."""
    if pad.soort == "uitspraak":
        return node_id(COLLECTION_JUDGMENTS, make_node_key(pad.a))
    if pad.soort == "wet":
        return node_id(COLLECTION_INSTRUMENTS, pad.a.lower())
    if pad.soort == "dossier":
        return node_id(COLLECTION_DOSSIERS, make_node_key(pad.a))
    if pad.soort == "kabinet":
        return node_id(COLLECTION_CABINETS, pad.a)
    if pad.soort == "fractie":
        return node_id(COLLECTION_FACTIONS, pad.a)
    if pad.soort == "stemming":
        return node_id(COLLECTION_DECISIONS, pad.a)
    return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _judgment(key: str, props: dict[str, Any]) -> str | None:
    ecli = _text(props.get("ecli")) or ecli_of_key(key)
    return (
        pad_href(Pad("uitspraak", ecli.upper()))
        if ecli and PATH_ECLI.match(ecli)
        else None
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
    return pad_href(Pad("artikel", law, cited_number(law, number)))


def _instrument(key: str, props: dict[str, Any]) -> str | None:
    if BWB.match(key):
        return pad_href(Pad("wet", key.upper()))
    celex = _text(props.get("celex")) or key
    if CELEX.match(celex):
        return pad_href(Pad("wet", celex.upper()))
    official = _text(props.get("official_id")) or official_of_instrument_key(key)
    parsed = parse_koop_id(official)
    if parsed is None:
        return None
    series, year, number = parsed
    return pad_href(Pad("publicatie", series, str(year), number))


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


def _annex(key: str, props: dict[str, Any]) -> str | None:
    # The one annex of a regulation, without a label, has no address of its own.
    law = _text(props.get("bwb_id"))
    label = _text(props.get("label"))
    if not law or not BWB.match(law) or not label or not ANNEX_LABEL.match(label):
        return None
    return pad_href(Pad("bijlage", law.upper(), label.upper()))


def _case(key: str, props: dict[str, Any]) -> str | None:
    number = _text(props.get("number"))
    if not number or not CASE_NUMBER.match(number):
        return None
    return pad_href(Pad("zaak", number.upper()))


def _activity(key: str, props: dict[str, Any]) -> str | None:
    # One of the Eerste Kamer (``ek_…``) has no number: no address of its own.
    number = _text(props.get("number"))
    if not number or not ACTIVITY_NUMBER.match(number):
        return None
    return pad_href(Pad("activiteit", number.upper()))


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
    COLLECTION_JUDGMENTS: _judgment,
    COLLECTION_DOSSIERS: _dossier,
    COLLECTION_ARTICLES: _article,
    COLLECTION_INSTRUMENTS: _instrument,
    COLLECTION_MEMBERS: _slug("lid", SLUG),
    COLLECTION_COMMITTEES: _slug("commissie", SLEUTEL),
    COLLECTION_CABINETS: _by_key("kabinet"),
    COLLECTION_FACTIONS: _by_key("fractie"),
    COLLECTION_DECISIONS: _by_key("stemming"),
    COLLECTION_COMMITMENTS: _commitment,
    COLLECTION_DOCUMENTS: _paper,
    COLLECTION_ANNEXES: _annex,
    COLLECTION_CASES: _case,
    COLLECTION_ACTIVITIES: _activity,
}


def path_of(node_id: str, props: dict[str, Any] | None = None) -> str | None:
    """The readable address of a node, from its key or the props of its node; None
    where it has none (an activity of the Eerste Kamer, an annex without a label: still
    /explore)."""
    collection, key = parse_node_id(node_id)
    build = _PATHS.get(collection)
    return build(key, props or {}) if key and build else None
