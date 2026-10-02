"""Shared citation-detection primitives used across semantic pipelines.

This module provides a single source of truth for the ``CitationHit`` dataclass,
helper utilities, and the ``DutchCitationExtractor`` class that all semantic
pipelines use to detect Dutch legal article citations.

Public API
----------
CitationHit
    Unified dataclass for any detected legal citation.
ArticleKind
    ``Literal["article", "instrument"]`` discriminant.
DutchCitationExtractor
    Registry-driven extractor for Dutch article citations in natural-language text.
make_snippet
    Extract surrounding text context around a regex match span.
normalize_code_aliases
    Normalise a ``{alias: identifier}`` mapping to uppercase keys.
format_celex
    Render a numeric CELEX identifier from directive/regulation kind, year and number.
coerce_text
    Safely coerce any value to a stripped non-empty string, or ``None``.
strip_xml
    Strip XML/HTML tags and normalise whitespace for clean regex matching.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.core.code_families import CODE_FAMILIES
from lawgraph.core.identifiers import CELEX_KIND_TO_LETTER, parse_celex
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import XML_TAG_RE

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ArticleKind = Literal["article", "instrument"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNIPPET_WINDOW = 300

# ---------------------------------------------------------------------------
# CitationHit dataclass
# ---------------------------------------------------------------------------


@dataclass
class CitationHit:
    """A detected reference to an article or instrument found in a document.

    *kind* discriminates between a reference to a specific article (``"article"``)
    and a reference to a whole instrument (``"instrument"``).

    At most one of *bwb_id* / *celex* is populated, identifying the target law.
    For article-level references *article_number* is always set.
    """

    kind: ArticleKind = "article"
    bwb_id: str | None = None
    article_number: str | None = None
    celex: str | None = None
    confidence: float = 0.0
    raw_match: str | None = None
    snippet: str | None = None
    qualifier: str | None = None  # e.g. "derde lid", "eerste en tweede lid"
    # Where the citation stands in the text it was found in: ``text[start:end]`` is the
    # ``raw_match``. Unset for a hit that was not read from a text.
    start: int | None = None
    end: int | None = None
    # The law as the text writes it ("Rv", "Vw 2000"), for a citation of a law the registry
    # does not know: then *bwb_id* and *celex* are unset (``extract(unknown_laws=True)``).
    unknown_law: str | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def make_snippet(text: str, span: tuple[int, int]) -> str:
    """Return a context window of *SNIPPET_WINDOW* chars around *span*."""
    start, end = span
    begin = max(0, start - SNIPPET_WINDOW)
    finish = min(len(text), end + SNIPPET_WINDOW)
    return text[begin:finish].strip()


def normalize_code_aliases(mapping: dict[str, str]) -> dict[str, str]:
    """Normalise a code-alias → BWB/CELEX mapping to uppercase keys and values."""
    normalized: dict[str, str] = {}
    for alias, target in mapping.items():
        if not alias or not target:
            continue
        normalized[alias.strip().upper()] = target.strip().upper()
    return normalized


def format_celex(
    kind: Literal["directive", "regulation", "decision", "framework_decision"],
    year: str,
    number: str,
) -> str:
    """Render a numeric CELEX identifier.

    Supported kinds and their CELEX sector-3 letters (see
    :data:`lawgraph.core.identifiers.CELEX_KIND_TO_LETTER`):
    - ``"directive"`` → ``L``
    - ``"regulation"`` → ``R``
    - ``"decision"`` → ``D``
    - ``"framework_decision"`` → ``F``

    Example: ``format_celex("directive", "2010", "64")`` → ``"32010L0064"``
    """
    letter = CELEX_KIND_TO_LETTER.get(kind, "L")
    padded = 0
    try:
        padded = int(number)
    except ValueError:
        logger.debug("Could not parse CELEX number %r; using 0 as fallback", number)
    return f"3{year}{letter}{padded:04d}"


def hit_reason(hit: CitationHit) -> str:
    """Derive a short reason label from a CitationHit's populated fields."""
    if hit.bwb_id and hit.article_number:
        return "bwb_article"
    if hit.celex and hit.article_number:
        return "celex_article"
    if hit.bwb_id:
        return "bwb_instrument"
    if hit.celex:
        return "celex_instrument"
    return "unknown"


def coerce_text(value: object) -> str | None:
    """Safely coerce *value* to a stripped non-empty string, or ``None``."""
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate if candidate else None


def strip_xml(text: str) -> str:
    """Remove XML/HTML tags and collapse whitespace for clean regex matching."""
    stripped = XML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", stripped).strip()


# ---------------------------------------------------------------------------
# DutchCitationExtractor — registry-driven article citation detection
# ---------------------------------------------------------------------------

# Article number: plain (140), with letters (36e, 189a, 126aa, 420bis), with colon or dot parts
# (6:162, 7a:1576h, 3.26, 6.2.8, 1.1a). The letters are lower case also where the rest of a
# citation is matched without regard to case: in "artikel 82Sr" the "Sr" is the law.
ARTICLE_NUMBER_PATTERN = r"\d+(?-i:[a-z])?(?:[.:]\d+)*(?-i:[a-z]{0,3})"

# A code made of a family and a book, like ``BW6`` or ``BW7A``: the family (``BW``) is what
# a citation names, the book comes from the article number (``artikel 6:162 BW``).
_BOOK_CODE_RE = re.compile(r"^(?P<family>[A-Z]{2,})(?P<book>\d{1,2}[A-Z]?)$")

# Ordinal words used in "lid" qualifiers
_ORDINALS_PAT = (
    r"eerste|tweede|derde|vierde|vijfde|zesde|zevende|achtste|negende|tiende|\d+e"
)

# Qualifiers of an article: "derde lid", "eerste en tweede lid", "lid 5", "leden 1 en 2",
# "aanhef en onder a", "onder 1°", "onderdeel b", "sub c", "tweede volzin", "eerste zin"
_LID_ORD_PAT = (
    rf"(?:{_ORDINALS_PAT})(?:\s*(?:,|en|of)\s*(?:{_ORDINALS_PAT}))*\s+lid(?:en)?"
)
_LID_NUM_PAT = (
    r"(?:lid|leden)\s+\d+[a-z]?"
    r"(?:\s*(?:,|en|of|t/m|tot en met)\s*(?:lid\s+)?\d+[a-z]?)*"
)
_SUB_TOKEN = r"(?!(?:de|het|een|dat|die|deze)\b)(?:[a-z]{1,2}|\d{1,2}°?)\b"
_SUB_PAT = (
    rf"(?:aanhef(?:\s+en\s+(?:onder(?:deel)?|sub)\s+{_SUB_TOKEN})?"
    rf"|(?:onder(?:deel)?|sub)\s+{_SUB_TOKEN}"
    rf"(?:\s+(?:en|of)\s+(?:onder(?:deel)?\s+)?{_SUB_TOKEN})?)"
)
_ZIN_PAT = rf"(?:(?:{_ORDINALS_PAT}|laatste)\s+(?:volzin|zin)|volzin)"
_QUALIFIER_PAT = (
    rf"(?:\s*,?\s*(?:{_LID_ORD_PAT}|{_LID_NUM_PAT}|{_SUB_PAT}|{_ZIN_PAT}))*"
)

# One article number, optionally with a parenthesis: "338 (lid 2)", "218 (of 218a)"
_NUM_PAREN_PAT = rf"{ARTICLE_NUMBER_PATTERN}(?:\s*\((?:lid|leden|of|en)[^)]{{1,25}}\))?"

# Article number groups
# Range: "2 tot en met 5"
_ART_RANGE_PAT = (
    rf"{ARTICLE_NUMBER_PATTERN}\s+tot\s+en\s+met\s+{ARTICLE_NUMBER_PATTERN}"
)
# Enumeration: "36e", "36e en 36f", "282a, 282b en 282c", "338 (lid 2) en 339"
_ART_ENUM_PAT = (
    rf"{_NUM_PAREN_PAT}"
    rf"(?:\s*,\s*{_NUM_PAREN_PAT})*"
    rf"(?:\s+(?:en|of)\s+{_NUM_PAREN_PAT})?"
)
# Range takes priority over enum to avoid "2 tot" being parsed as just "2"
ARTICLE_NUMBERS_PATTERN = rf"(?:{_ART_RANGE_PAT}|{_ART_ENUM_PAT})"

# The head of a citation: the keyword, the article numbers and their qualifiers. Which law
# is meant follows in the text after it (``DutchCitationExtractor._resolve_law``).
ARTICLE_HEAD_RE = re.compile(
    rf"\b(?:artikel(?:en)?|art\.?)\s+(?P<nums>{ARTICLE_NUMBERS_PATTERN})(?P<qual>{_QUALIFIER_PAT})",
    re.IGNORECASE,
)

# What comes between the article and the law: "van", "in", "uit", and a determiner.
LAW_CONNECTOR_RE = re.compile(
    r"\s*,?\s*(?:(?:van|in|uit|krachtens|ingevolge)\s+)?(?:(?:de|het)\s+)?",
    re.IGNORECASE,
)
# "van die wet": the law that was named last.
_ANAPHORA_RE = re.compile(
    r"\s*,?\s*(?:van|in|uit)\s+(?:de\s+)?(?:die|deze|dezelfde|genoemde|voornoemde|bedoelde"
    r"|gemelde)\s+(?:wet|regeling|besluit|verordening|wetboek|richtlijn|verdrag|reglement)\b",
    re.IGNORECASE,
)
# "(hierna: de Awb)", "(verder: Aw)" or "(Aw)": a name the text gives to the law it just
# cited. Without "hierna" or "verder" only an abbreviation, its year allowed ("(Vw 2000)").
_HIERNA_RE = re.compile(
    r"\s*\((?:(?i:hierna|verder):?\s*(?i:de\s+|het\s+)?(?i:te noemen\s+)?"
    r"(?P<alias>[^()]{1,40}?)|(?P<short>[A-Z][A-Za-z]{0,9}(?:\s(?:18|19|20)\d{2})?))\s*\)"
)


def _defined_alias(text: str, end: int) -> str | None:
    """The name the text gives, right after *end*, to the law it just cited, upper case."""
    defined = _HIERNA_RE.match(text, end)
    if not defined:
        return None
    if defined["alias"]:
        return defined["alias"].strip().upper() or None
    short = defined["short"].upper()
    return None if short in _NOT_A_LAW else short


# A law the registry does not know, as a citation writes it after the article: an
# abbreviation (``Rv``, ``RO``, ``AWR``, ``Vw 2000``) or a name of one word (``Opiumwet``,
# ``Vreemdelingenwet 2000``), with its year. A name of several words ("Wet op de rechterlijke
# organisatie") has no end the text marks, so it is not read, nor is the first word of one
# ("Invoeringswet Boeken 3, 5 en 6", "Rijkswet op het Nederlanderschap").
_UNKNOWN_LAW_RE = re.compile(
    r"(?P<law>(?:[A-Z][A-Za-z]*[A-Z][A-Za-z]*|[A-Z][a-z]{1,3}"
    r"|(?P<name>[A-Z][a-z]+(?:wet|wetboek|besluit|verordening|reglement)))"
    r"(?:\s+(?:18|19|20)\d{2})?)(?![\w-])"
    r"(?(name)(?!\s+(?:[A-Z]|(?:op|van|tot|inzake|betreffende|houdende)\b)))"
)
# Words that stand after an article number without naming a law: the start of a sentence or
# of a name of several words, a court, a part of a law, and a heading in capitals ("EN").
_NOT_A_LAW = frozenset(
    "AAN AARD ALLE ALS BIJ BOEK CODE DAN DAT DE DEZE DIE DIT DOOR DRIE EEN ELKE EN ER GEEN "
    "HET HIJ HOF HR IK IN IS JO LID MET NA NOTA NU OF OM ONZE OOK OP SUB TE TEN TER TITEL "
    "TOT TWEE UIT UW VAN VIER VOOR WET WIJ ZIJ ZO".split()
)
CONFIDENCE_UNKNOWN_LAW = 0.8
_MAX_NAME_WORDS = 12
_MIN_NAME_LENGTH = 5
# How far back "die wet" may look for the law it means.
_ANAPHORA_REACH = 3000
CONFIDENCE_DIRECT = 0.95
CONFIDENCE_LOCAL_ALIAS = 0.9
CONFIDENCE_ANAPHORA = 0.7


def parse_article_numbers(raw: str) -> list[str]:
    """Split a raw article-number string into individual article numbers.

    Handles ranges (``2 tot en met 5`` → ``["2", "5"]``), enumerations
    (``36e en 36f`` → ``["36e", "36f"]``), parentheses (``338 (lid 2)`` → ``338``) and simple
    numbers. Ranges return only start/end — the caller decides whether to expand.
    """
    raw = re.sub(r"\s*\([^)]*\)", "", raw.strip())
    range_m = re.match(
        rf"^({ARTICLE_NUMBER_PATTERN})\s+tot\s+en\s+met\s+({ARTICLE_NUMBER_PATTERN})$",
        raw,
        re.IGNORECASE,
    )
    if range_m:
        return [range_m.group(1), range_m.group(2)]
    parts = re.split(r"\s*,\s*|\s+(?:en|of)\s+", raw, flags=re.IGNORECASE)
    result = [
        p.strip()
        for p in parts
        if p.strip() and re.fullmatch(ARTICLE_NUMBER_PATTERN, p.strip(), re.IGNORECASE)
    ]
    # No article is numbered with a leading zero: "047" is a typing error.
    return [n for n in result or [raw] if not n.startswith("0")]


def number_shape(number: str) -> str:
    """How an article number is built: every run of digits is ``9``, every run of letters
    ``a`` (``6:162`` is ``9:9``, ``36e`` is ``9a``, ``420bis.1`` is ``9a.9``); an article of
    an annex (``bijlage 2 artikel 9``) is ``annex``.

    A law numbers its articles in a few ways (the Awb ``9:9`` and ``9:9a``, the Omgevingswet
    ``9.9``, the Wetboek van Strafrecht ``9``, ``9a`` and ``9a.9``), so a number of a shape
    none of its articles has does not cite one of them: ``140.1 Sr`` (``9.9``) is article
    140, first lid, written short.
    """
    if number.startswith("bijlage "):
        return "annex"
    return re.sub(r"[a-z]+", "a", re.sub(r"\d+", "9", number.lower()))


def name_key(text: str) -> str:
    """A law name as compared: lower case, single spaces, no quotes or trailing punctuation."""
    return re.sub(r"\s+", " ", text.lower()).strip(" .,;:\"'“”‘’()")


@dataclass
class _Law:
    """The law a citation names, and how it was found."""

    law_id: str
    end: int  # where the law ends in the text
    confidence: float
    family: str | None = (
        None  # a family code (``BW``): the book is in the article number
    )


class DutchCitationExtractor:
    """Extract Dutch legal article citations from natural-language text.

    A citation is the head (``artikel 36e, derde lid``, with its numbers and qualifiers) and
    the law it names in the text after it. Patterns handled (``de`` prefix and ``art.``
    abbreviation are optional):

    - ``artikel 36e Sr``                                — direct code
    - ``artikel 36e, derde lid, Sr``                    — with lid qualifier
    - ``art. 1:88 lid 5 BW``                            — ``lid 5``, ``onder a``, ``volzin``
    - ``artikelen 36e en 36f Sr``                       — enumeration
    - ``artikelen 338 (lid 2) en 339 Fw``               — with a parenthesis
    - ``artikelen 2 tot en met 5 Sv``                   — range
    - ``artikel 3.26, eerste lid, van de Wet ruimtelijke ordening`` — dotted number, full name
    - ``artikel 3 van de Wwft``                         — "van de" + code
    - ``artikel 6:162 BW``                              — family code, book in the number
    - ``artikel 8:54 van de Algemene wet bestuursrecht (hierna: de Awb)`` and later
      ``artikel 8:55 van de Awb``                       — a name the text defines itself
    - ``artikel 8:54 van die wet``                      — the law named last

    A law is named by a code (``Sr``), by its full name (found by the longest run of words
    that is a known name, so any number of names costs nothing per citation), by a family
    code, or by a word that points back at the law named last.

    A family code (``CODE_FAMILIES``: ``BW``) never stands for one regulation: a citation
    of the family resolves through the book in front of the colon (``6`` → the BWB id of
    book 6) and cites the article number after it (``162``), whichever books are loaded
    and whatever the registry maps the family code to. Other codes made of a family and
    a book (``BW7A``) add their book to the family.

    The law registry is injected at construction time.  Adding a code alias
    to the domain config automatically makes it detectable without touching
    this class.
    """

    def __init__(
        self,
        code_aliases: dict[str, str],
        name_aliases: Mapping[str, str | None] | None = None,
        context_aliases: Mapping[str, tuple[str, Sequence[str]]] | None = None,
    ) -> None:
        self._code_map: dict[str, str] = {
            k.strip().upper(): v.strip()
            for k, v in code_aliases.items()
            if k and v and k.strip().upper() not in CODE_FAMILIES
        }
        self._name_map: dict[str, str] = {
            name_key(k): v.strip()
            for k, v in (name_aliases or {}).items()
            if k and v and len(name_key(k)) >= _MIN_NAME_LENGTH
        }
        self._books: dict[str, dict[str, str]] = self._group_books()
        # "EP" -> (law id, a pattern of the words a text must also name: "EVRM", ...)
        self._context: dict[str, tuple[str, re.Pattern[str]]] = {
            alias.strip().upper(): (
                law_id,
                re.compile(
                    r"(?<!\w)(?:"
                    + "|".join(
                        re.escape(w) for w in sorted(words, key=len, reverse=True)
                    )
                    + r")(?!\w)",
                    re.IGNORECASE,
                ),
            )
            for alias, (law_id, words) in (context_aliases or {}).items()
            if alias.strip() and law_id and words
        }
        self._code_re = self._alternation_re(
            self._code_map, prefix=r"(?:de\s+|het\s+)?"
        )
        self._family_re = self._alternation_re(self._books, prefix=r"(?:de\s+|het\s+)?")

    @staticmethod
    def _alternation_re(
        keys: Mapping[str, object], *, prefix: str = ""
    ) -> re.Pattern[str] | None:
        """A pattern for one of *keys*, longest first; ``None`` without keys."""
        if not keys:
            return None
        alternatives = "|".join(
            re.escape(k) for k in sorted(keys, key=len, reverse=True)
        )
        return re.compile(rf"{prefix}(?P<key>{alternatives})(?![\w])", re.IGNORECASE)

    def _group_books(self) -> dict[str, dict[str, str]]:
        """``{"BW": {"6": <BW6 id>, ...}}``: the known families, and the codes that split
        into family and book.

        A family that is a registered code itself is left alone (the code wins), unless it
        is a known family; a known book keeps the id ``CODE_FAMILIES`` gives it.
        """
        books: dict[str, dict[str, str]] = {}
        for code, law_id in self._code_map.items():
            match = _BOOK_CODE_RE.match(code)
            if match and match["family"] not in self._code_map:
                books.setdefault(match["family"], {})[match["book"]] = law_id
        for family, known in CODE_FAMILIES.items():
            books.setdefault(family, {}).update(known)
        return books

    # ── which law ─────────────────────────────────────────────────────────────

    def _resolve_law(
        self,
        text: str,
        start: int,
        local: dict[str, str],
        last: tuple[int, str] | None,
    ) -> _Law | None:
        """The law named in *text* after position *start*, or ``None``."""
        anaphora = _ANAPHORA_RE.match(text, start)
        if anaphora:
            if last and start - last[0] <= _ANAPHORA_REACH:
                return _Law(last[1], anaphora.end(), CONFIDENCE_ANAPHORA)
            return None
        pos = LAW_CONNECTOR_RE.match(text, start).end()  # type: ignore[union-attr]
        for law in (
            self._match_local(text, pos, local),
            self._match_alternation(self._code_re, self._code_map, text, pos, None),
            self._match_alternation(self._family_re, self._books, text, pos, "family"),
            self._match_name(text, pos),
        ):
            if law:
                return law
        return None

    @staticmethod
    def _match_local(text: str, pos: int, local: dict[str, str]) -> _Law | None:
        for alias, law_id in local.items():
            if text[pos : pos + len(alias)].upper() == alias and not (
                text[pos + len(alias) : pos + len(alias) + 1].isalnum()
            ):
                return _Law(law_id, pos + len(alias), CONFIDENCE_LOCAL_ALIAS)
        return None

    @staticmethod
    def _match_alternation(
        pattern: re.Pattern[str] | None,
        registry: dict[str, Any],
        text: str,
        pos: int,
        kind: str | None,
    ) -> _Law | None:
        if pattern is None:
            return None
        match = pattern.match(text, pos)
        if not match:
            return None
        key = match.group("key").upper()
        if kind == "family":
            return _Law("", match.end(), CONFIDENCE_DIRECT, family=key)
        return _Law(registry[key], match.end(), CONFIDENCE_DIRECT)

    def _match_name(self, text: str, pos: int) -> _Law | None:
        """The longest run of words from *pos* that is the name of a known law."""
        if not self._name_map:
            return None
        words = list(
            itertools.islice(
                re.finditer(r"\S+", text[pos : pos + 300]), _MAX_NAME_WORDS
            )
        )
        for count in range(len(words), 0, -1):
            end = words[count - 1].end()
            name = text[pos : pos + end]
            law_id = self._name_map.get(name_key(name))
            if law_id:
                # the punctuation that ends the sentence is not part of the citation
                return _Law(law_id, pos + len(name.rstrip(".,;:")), CONFIDENCE_DIRECT)
        return None

    def _apply_family(self, law: _Law, article_number: str) -> tuple[str | None, str]:
        """``(law_id, article_number)`` for one article of a citation.

        A family citation resolves through the book in front of the colon and drops it from
        the article number, because the book's own articles are stored without it.
        """
        if law.family is None:
            return law.law_id, article_number
        book, colon, number = article_number.partition(":")
        if not colon:
            return None, article_number
        return self._books[law.family].get(book.upper()), number

    # ── extraction ────────────────────────────────────────────────────────────

    def extract(
        self, text: str, *, every_occurrence: bool = False, unknown_laws: bool = False
    ) -> list[CitationHit]:
        """Return the detected Dutch article citations in *text*.

        An article is reported once, at its first citation, unless *every_occurrence* asks
        for a hit per citation. With *unknown_laws* a citation of a law the registry does not
        know (``artikel 392 Rv``) is a hit as well, with the law as written in
        ``unknown_law`` and no id.
        """
        if not text or not (
            self._code_map or self._name_map or self._books or unknown_laws
        ):
            return []

        hits: list[CitationHit] = []
        seen: set[tuple[str | None, str | None, str]] = set()
        local: dict[str, str] = {
            alias: law_id
            for alias, (law_id, beside) in self._context.items()
            if beside.search(text)
        }
        unknown_local: dict[str, str] = {}  # "AW" -> "Aanbestedingswet"
        last: tuple[int, str] | None = None

        for match in ARTICLE_HEAD_RE.finditer(text):
            law = self._resolve_law(text, match.end(), local, last)
            if law is None:
                if unknown_laws:
                    hits.extend(
                        self._unknown_hits(
                            text,
                            match,
                            None if every_occurrence else seen,
                            unknown_local,
                        )
                    )
                continue
            self._remember_alias(text, law, local)
            span = (match.start(), law.end)
            for hit in self._hits(
                text, match, law, span, None if every_occurrence else seen
            ):
                hits.append(hit)
                last = (law.end, hit.bwb_id or hit.celex or "")
        return hits

    @staticmethod
    def _unknown_hits(
        text: str,
        match: re.Match[str],
        seen: set[tuple[str | None, str | None, str]] | None,
        defined: dict[str, str],
    ) -> Iterator[CitationHit]:
        """The articles of a citation whose law is written as a law the registry does
        not know (``_UNKNOWN_LAW_RE``); nothing when no law is written there.

        A name the text gave such a law before ("artikel 4.16 van de Aanbestedingswet (Aw)",
        *defined*) is that law: "artikel 4.16 Aw" is the same article."""
        if _ANAPHORA_RE.match(text, match.end()):
            return
        pos = LAW_CONNECTOR_RE.match(text, match.end()).end()  # type: ignore[union-attr]
        named = _UNKNOWN_LAW_RE.match(text, pos)
        if not named or named["law"].split()[0].upper() in _NOT_A_LAW:
            return
        law = defined.get(named["law"].upper(), named["law"])
        alias = _defined_alias(text, named.end())
        if alias and alias != law.upper():
            defined.setdefault(alias, law)
        qualifier = (match.group("qual") or "").strip(", ") or None
        span = (match.start(), named.end())
        for number in parse_article_numbers(match.group("nums") or ""):
            key = (None, law.upper(), number)
            if seen is not None:
                if key in seen:
                    continue
                seen.add(key)
            yield CitationHit(
                kind="article",
                article_number=number,
                qualifier=qualifier,
                confidence=CONFIDENCE_UNKNOWN_LAW,
                raw_match=text[span[0] : span[1]],
                snippet=make_snippet(text, span),
                start=span[0],
                end=span[1],
                unknown_law=law,
            )

    def _remember_alias(self, text: str, law: _Law, local: dict[str, str]) -> None:
        """Register the name a citation gives its law: ``(hierna: de Awb)``."""
        if law.family is not None or not law.law_id:
            return
        alias = _defined_alias(text, law.end)
        if alias and alias not in self._code_map:
            local[alias] = law.law_id

    def _hits(
        self,
        text: str,
        match: re.Match[str],
        law: _Law,
        span: tuple[int, int],
        seen: set[tuple[str | None, str | None, str]] | None,
    ) -> Iterator[CitationHit]:
        qualifier = (match.group("qual") or "").strip(", ") or None
        for raw_num in parse_article_numbers(match.group("nums") or ""):
            law_id, art_num = self._apply_family(law, raw_num)
            if not law_id:
                continue
            is_bwb = (
                parse_celex(law_id) is None
            )  # a BWB id, or the pseudo id of the EVRM
            key = (law_id if is_bwb else None, None if is_bwb else law_id, art_num)
            if seen is not None:
                if key in seen:
                    continue
                seen.add(key)
            yield CitationHit(
                kind="article",
                bwb_id=law_id if is_bwb else None,
                celex=None if is_bwb else law_id,
                article_number=art_num,
                qualifier=qualifier,
                confidence=law.confidence,
                raw_match=text[span[0] : span[1]],
                snippet=make_snippet(text, span),
                start=span[0],
                end=span[1],
            )
