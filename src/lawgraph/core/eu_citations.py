"""EU citation patterns and hit collectors shared by the semantic pipelines.

The EU-article linker and the TK-article linker recognise the same literal EU
citation forms in Dutch text (``CELEX:...``, ``Richtlijn 2010/64/EU``,
``artikel 6 van Richtlijn ...``, bare BWB ids).  The patterns and the
``collect_*`` helpers live here once; each pipeline supplies what genuinely
differs between them:

* the confidence of each kind of hit (:class:`EUCitationConfidence`),
* the shape of the article number (:data:`ARTICLE_NUMBER_ONE_LETTER` or
  :data:`ARTICLE_NUMBER_ANY_LETTERS`),
* whether ``de`` / ``het`` may precede the instrument name and which instrument
  kinds (directive, regulation, decision, framework decision) are recognised
  (:func:`build_article_patterns`).

Pure functions and constants only — no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Literal

from lawgraph.core.citations import CitationHit, format_celex, make_snippet
from lawgraph.core.identifiers import BWB_ID_PATTERN, has_possible_year

EUInstrumentKind = Literal["directive", "regulation", "decision", "framework_decision"]
HitRecorder = Callable[[CitationHit], None]

# Article numbers: one optional trailing letter ("12a") or any number of them ("12ab").
ARTICLE_NUMBER_ONE_LETTER = r"\d+[a-z]?"
ARTICLE_NUMBER_ANY_LETTERS = r"\d+[a-z]*"


@dataclass(frozen=True)
class EUCitationConfidence:
    """Per-caller confidence for each kind of EU/BWB citation hit."""

    article_with_instrument: float  # "artikel X van Richtlijn/Besluit YYYY/N"
    celex_literal: float  # "CELEX:32010L0064"
    instrument_year_number: float  # "Richtlijn YYYY/N" without an article
    bwb_id: float  # bare BWBR/BWBV id


# ---------------------------------------------------------------------------
# Instrument-level patterns (identical for every caller)
# ---------------------------------------------------------------------------

CELEX_LITERAL_PATTERN = re.compile(r"\bCELEX:([0-9A-Z()\\/.\-]+)\b", re.IGNORECASE)
RICHTLIJN_PATTERN = re.compile(
    r"\bRichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)
VERORDENING_PATTERN = re.compile(
    r"\bVerordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)
YEAR_NUMBER_PATTERNS: tuple[tuple[re.Pattern[str], EUInstrumentKind], ...] = (
    (RICHTLIJN_PATTERN, "directive"),
    (VERORDENING_PATTERN, "regulation"),
)

# ---------------------------------------------------------------------------
# Article-level patterns
# ---------------------------------------------------------------------------

# kind -> (Dutch noun, determiner that may precede it, allowed year/number suffixes)
_INSTRUMENT_FORMS: dict[EUInstrumentKind, tuple[str, str, str]] = {
    "directive": ("Richtlijn", "de", "/EU|/EG"),
    "regulation": ("Verordening", "de", "/EU|/EG"),
    "decision": ("Besluit", "het", "/EU|/EG|/GBVB"),
    "framework_decision": ("Kaderbesluit", "het", "/JBZ|/EU"),
}


def build_article_patterns(
    article_number: str,
    *,
    kinds: Iterable[EUInstrumentKind],
    allow_determiner: bool,
) -> tuple[tuple[re.Pattern[str], EUInstrumentKind], ...]:
    """Compile ``artikel X van <instrument> YYYY/N`` patterns, one per kind.

    *article_number* is the regex for the article number (group 1);
    *allow_determiner* lets ``de`` (directive, regulation) or ``het`` (decision,
    framework decision) stand between ``van`` and the instrument name.  Groups 2
    and 3 are year and number.
    """
    compiled: list[tuple[re.Pattern[str], EUInstrumentKind]] = []
    for kind in kinds:
        noun, determiner, suffixes = _INSTRUMENT_FORMS[kind]
        det = rf"(?:{determiner}\s+)?" if allow_determiner else ""
        pattern = re.compile(
            rf"\bartikel\s+({article_number})\s+van\s+{det}{noun}"
            rf"\s+(\d{{4}})/(\d+)(?:{suffixes})?\b",
            re.IGNORECASE,
        )
        compiled.append((pattern, kind))
    return tuple(compiled)


# ---------------------------------------------------------------------------
# Hit collectors
# ---------------------------------------------------------------------------


def collect_article_hits(
    text: str,
    patterns: Iterable[tuple[re.Pattern[str], EUInstrumentKind]],
    confidence: float,
    record: HitRecorder,
) -> None:
    """Record ``artikel X van <instrument> YYYY/N`` hits (kind ``article``)."""
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            record(
                CitationHit(
                    kind="article",
                    celex=format_celex(kind, match.group(2), match.group(3)),
                    article_number=match.group(1),
                    confidence=confidence,
                    raw_match=match.group(0),
                    snippet=make_snippet(text, match.span()),
                    start=match.start(),
                    end=match.end(),
                )
            )


def collect_celex_literal_hits(
    text: str, confidence: float, record: HitRecorder
) -> None:
    """Record literal ``CELEX:<id>`` mentions as instrument hits."""
    for match in CELEX_LITERAL_PATTERN.finditer(text):
        record(
            CitationHit(
                kind="instrument",
                celex=match.group(1).upper(),
                confidence=confidence,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
                start=match.start(),
                end=match.end(),
            )
        )


def collect_year_number_hits(text: str, confidence: float, record: HitRecorder) -> None:
    """Record ``Richtlijn/Verordening YYYY/N`` mentions as instrument hits."""
    for pattern, kind in YEAR_NUMBER_PATTERNS:
        for match in pattern.finditer(text):
            record(
                CitationHit(
                    kind="instrument",
                    celex=format_celex(kind, match.group(1), match.group(2)),
                    confidence=confidence,
                    raw_match=match.group(0),
                    snippet=make_snippet(text, match.span()),
                    start=match.start(),
                    end=match.end(),
                )
            )


def collect_bwb_id_hits(text: str, confidence: float, record: HitRecorder) -> None:
    """Record bare BWB ids (BWBR statutes, BWBV treaties) as instrument hits."""
    for match in BWB_ID_PATTERN.finditer(text):
        record(
            CitationHit(
                kind="instrument",
                bwb_id=match.group(1).upper(),
                confidence=confidence,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
                start=match.start(),
                end=match.end(),
            )
        )


# ---------------------------------------------------------------------------
# The EU acts a considerans says the regulation implements
# ---------------------------------------------------------------------------

# An EU act as Dutch legislation cites it, in the notation of every era: "Richtlijn
# 95/46/EG", "richtlijn nr. 2004/17/EG", "Verordening (EEG) nr. 1408/71", "Verordening (EU)
# 2016/679", "Gedelegeerde Verordening (EU) 2017/565", "Kaderbesluit 2008/977/JBZ".
_ACT_KINDS: dict[str, EUInstrumentKind] = {
    "richtlijn": "directive",
    "verordening": "regulation",
    "besluit": "decision",
    "beschikking": "decision",
    "kaderbesluit": "framework_decision",
}
_DOMAIN = r"(?:EU|EG|EEG|EGKS|Euratom|JBZ|GBVB)"
EU_ACT_PATTERN = re.compile(
    r"\b(?:gedelegeerde\s+|uitvoerings-?)?"
    r"(?P<kind>kaderbesluit|richtlijn|verordening|beschikking|besluit)\s+"
    r"(?:nr\.?\s*)?"
    rf"(?:\({_DOMAIN}(?:,\s*{_DOMAIN})*\)\s*)?"
    r"(?P<nr>nr\.?\s*)?"
    r"(?P<first>\d{2,4})/(?P<second>\d{1,4})"
    rf"(?:/{_DOMAIN})?\b",
    re.IGNORECASE,
)
# A clause that implements: "ter uitvoering van", "te implementeren", "geïmplementeerd",
# "uitvoering te geven aan", "uit te voeren", "omzetting", and the "Gelet op" of an order in
# council or a ministerial regulation, which names the act it implements.
_IMPLEMENTING_CLAUSE = re.compile(
    r"mplement|uitvoering\s+(?:van|te\s+geven|gegeven|geeft)|uit\s+te\s+voeren|omzet"
    r"|om\s+te\s+zetten|^\s*gelet\s+op",
    re.IGNORECASE,
)
# The reference to the Official Journal that closes the title of a cited act.
_JOURNAL_REFERENCE = re.compile(r"\((?:PbEU|PbEG|PB|Pb)\b[^()]*\)")
# The words in a title that name another act: "tot intrekking van Richtlijn 95/46/EG".
_ACT_IN_TITLE = re.compile(
    r"(?:wijziging|intrekking|aanvulling|vervanging|codificatie)\s+van\s+"
    r"(?:(?:de|het)\s+)?(?:\S+\s+\S+\s*(?:en|,)\s+)?$",
    re.IGNORECASE,
)


def eu_act_celex(match: re.Match[str]) -> str | None:
    """The CELEX number of an act matched by :data:`EU_ACT_PATTERN`, or None.

    A regulation before 2015 has its number first ("nr. 1408/71"), any other act its year;
    a year of two digits is one of the twentieth century.
    """
    kind = _ACT_KINDS[match["kind"].lower()]
    first, second = match["first"], match["second"]
    year, number = (
        (second, first) if kind == "regulation" and match["nr"] else (first, second)
    )
    if len(year) == 2:
        year = f"19{year}"
    if len(year) != 4:
        return None
    celex = format_celex(kind, year, number)
    return celex if has_possible_year(celex) else None


def implemented_acts(clauses: Iterable[str]) -> list[str]:
    """The CELEX numbers of the EU acts the *clauses* of a considerans say the regulation
    implements, in order.

    A clause counts when it implements (``ter uitvoering van``, ``te implementeren``,
    ``Gelet op`` …). An act cited in the title of another ("tot intrekking van Richtlijn
    95/46/EG") is not implemented: the title of a cited act runs to its reference in the
    Official Journal ("(PbEU 2016, L 119)"), and without one an act named after "wijziging
    van" or "intrekking van" is part of a title.
    """
    found: dict[str, None] = {}
    for clause in clauses:
        if not _IMPLEMENTING_CLAUSE.search(clause):
            continue
        title_end = -1
        for match in EU_ACT_PATTERN.finditer(clause):
            if match.start() < title_end:
                continue  # in the title of the act before it
            if _ACT_IN_TITLE.search(
                clause[max(0, match.start() - 120) : match.start()]
            ):
                continue
            celex = eu_act_celex(match)
            if celex:
                found.setdefault(celex)
            journal = _JOURNAL_REFERENCE.search(clause, match.end())
            title_end = journal.end() if journal else -1
    return list(found)
