"""Delegation clauses in the text of an article, and which regulations fill them — pure, no I/O.

A law delegates rule-making with a fixed formula: "bij of krachtens algemene maatregel van
bestuur", "bij algemene maatregel van bestuur", "bij ministeriële regeling", "bij regeling van
Onze Minister". :func:`delegation_clauses` finds those formulas in the text of an article,
each with the part (lid, onderdeel) it stands in. A formula that names rules already made
("de bij algemene maatregel van bestuur gestelde regels") delegates nothing and is left out.

A regulation names the articles it is issued under in its preamble ("Gelet op artikel 16,
eerste lid, van de Cyberbeveiligingswet"); ``semantic bwb-grondslagen`` writes that as
``BASED_ON``. :func:`fills` decides whether such a regulation fills a clause: its BWB type fits
the formula (an AMvB for "algemene maatregel van bestuur"; with "krachtens" also a ministerial
regulation, which the AMvB may delegate to), and the preamble names the lid of the clause or
no lid at all.

Not every article a preamble names gives a power: a policy rule names Awb 3:4, which only says
how to weigh interests. :func:`basis_kind` tells the two apart from the text of the article:
``delegates`` when the leden named hold a formula or another wording of a power to make
rules or to designate ("bij besluit van Onze Minister", "kan nadere regels stellen", "kan
beleidsregels vaststellen"), else ``mentioned``. :func:`basis_text`, :func:`basis_range_end`
and :func:`basis_qualifier` read the text of one reference of a preamble ("artikelen 26 tot
en met 30 van de wet").
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.core.bwb_xml import PART_LID
from lawgraph.core.qualifiers import Qualifier, parse_qualifier, part_slug

DelegationKind = Literal["amvb", "ministeriele_regeling"]
BasisKind = Literal["delegates", "mentioned"]

_CLAUSE = re.compile(
    r"\bbij\s+(?P<krachtens>of\s+krachtens\s+)?(?:een\s+)?"
    r"(?:(?P<amvb>algemene\s+maatregel(?:en)?\s+van\s+(?:rijks)?bestuur)"
    r"|ministeri[eë]le\s+regeling|regeling\s+van\s+Onze\s+Minister(?:s)?)\b",
    re.IGNORECASE,
)
# What follows a formula that names rules already made, not a power to make them.
_MADE = re.compile(r"\s+(?:vast)?gestelde\b|\s+gegeven(?:e)?\b", re.IGNORECASE)

# Other wordings of a power a regulation is made under: to make rules or policy rules, or to
# decide or designate by a decision ("bij koninklijk besluit te bepalen tijdstip", "de bij
# besluit van Onze Minister aangewezen ambtenaren"). Not rules already made ("de regels
# gesteld bij de wet") nor a decision of a date ("bij besluit van 12 juli 2020").
_POWER = re.compile(
    r"\bbij\s+(?:of\s+krachtens\s+)?(?:een\s+)?"
    r"(?:koninklijk\s+besluit|besluit|regeling)\b(?!\s+van\s+\d)"
    r"|(?<!\bde\s)(?<!\bdie\s)\b(?:nadere\s+)?regels\s+(?:kunnen\s+)?(?:worden\s+)?"
    r"(?:gesteld|stellen|vastgesteld|vaststellen)\b"
    r"|\bbeleidsregels\s+(?:worden\s+)?vast(?:stellen|gesteld)\b",
    re.IGNORECASE,
)
# What follows a decision that was taken already: "de bij regeling van Onze Minister gestelde".
_POWER_USED = re.compile(
    r"(?:\s+van\s+(?:Onze\s+Ministers?|\w+\s+\w+))?\s+"
    r"(?:(?:vast)?gestelde|gegevene?|genomen)\b",
    re.IGNORECASE,
)

# The list word that opens a reference of a preamble, and the law it closes with: what the
# BWB links in "Gelet op de artikelen 3, 16, eerste lid, en 107 van de Cyberbeveiligingswet".
_LIST_WORD = re.compile(r"^\s*artikel(?:en)?\s+", re.IGNORECASE)
_LAW_TAIL = re.compile(r",?\s+van\s+(?:de|het|Boek)\s.*$", re.IGNORECASE | re.DOTALL)
# The article number a reference opens with: "673e" of "673e, eerste lid" is no ordinal lid.
_ARTICLE_HEAD = re.compile(r"^[0-9][^\s,]*")
# A range of articles in one link: "artikelen 26 tot en met 30", "3:41 tot en met 3:45".
_ARTICLE_RANGE = re.compile(
    r"^(?P<first>[^\s,]+)\s*,?\s+tot\s+en\s+met\s+(?:artikel\s+)?"
    r"(?P<last>\d[0-9A-Za-z.:]*?)[.,]?(?:\s|$)",
    re.IGNORECASE,
)

# BWB types (``props.kind``, the ``soort`` of the toestand) per formula, folded to lower case:
# the source writes ``amvb`` and ``AMvB`` alike.
_AMVB_KINDS = frozenset({"amvb", "rijksamvb", "amvb-bes"})
_REGELING_KINDS = frozenset(
    {
        "ministeriele-regeling",
        "ministeriele-regeling-bes",
        "ministeriele-regeling-archiefselectielijst",
    }
)


@dataclass(frozen=True)
class DelegationClause:
    """A delegation formula as a span of the text of an article."""

    start: int
    end: int
    text: str
    kind: DelegationKind
    krachtens: bool
    part: str | None
    lid: str | None


def delegation_clauses(
    text: str | None, parts: Iterable[Mapping[str, Any]] | None = None
) -> list[DelegationClause]:
    """The delegation formulas in *text*, in text order, each with the innermost part of
    *parts* (``props.parts`` of the article) it stands in and the number of its lid."""
    if not text:
        return []
    spans = [p for p in parts or () if _fits(p, len(text))]
    clauses: list[DelegationClause] = []
    for match in _CLAUSE.finditer(text):
        if _MADE.match(text, match.end()):
            continue
        inside = [p for p in spans if p["start"] <= match.start() < p["end"]]
        innermost = min(inside, key=lambda p: p["end"] - p["start"], default=None)
        lid = next((p for p in inside if p.get("kind") == PART_LID), None)
        clauses.append(
            DelegationClause(
                start=match.start(),
                end=match.end(),
                text=match.group(0),
                kind="amvb" if match["amvb"] else "ministeriele_regeling",
                krachtens=bool(match["krachtens"]),
                part=str(innermost["id"]) if innermost else None,
                lid=(part_slug(lid.get("number")) or None) if lid else None,
            )
        )
    return clauses


def _fits(part: Mapping[str, Any], length: int) -> bool:
    start, end = part.get("start"), part.get("end")
    return (
        isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= length
    )


def fills(clause: DelegationClause, kind: str | None, leden: Iterable[str]) -> bool:
    """Whether a regulation of BWB type *kind*, issued under the article of *clause* with
    *leden* named in its preamble (none: the whole article), fills the clause."""
    if clause.kind == "amvb":
        kinds = _AMVB_KINDS | _REGELING_KINDS if clause.krachtens else _AMVB_KINDS
    else:
        kinds = _REGELING_KINDS
    if (kind or "").lower() not in kinds:
        return False
    named = set(leden)
    return not named or clause.lid is None or clause.lid in named


def kind_rank(kind: str | None) -> int:
    """The order of regulations of BWB type *kind* under an article: AMvBs, then ministerial
    regulations, then the others."""
    folded = (kind or "").lower()
    if folded in _AMVB_KINDS:
        return 0
    return 1 if folded in _REGELING_KINDS else 2


def basis_kind(
    text: str | None,
    parts: Iterable[Mapping[str, Any]] | None = None,
    leden: Iterable[str] = (),
) -> BasisKind | None:
    """Whether the article of *text* gives the power a regulation that names *leden* of it
    in its preamble (none: the whole article) is made under: ``delegates`` when those leden
    hold a delegation formula or another wording of a power, else ``mentioned``. A lid the
    article does not have counts as the whole article; no text: None."""
    if not text:
        return None
    spans = [
        p for p in parts or () if _fits(p, len(text)) and p.get("kind") == PART_LID
    ]
    named = set(leden)
    chosen = [p for p in spans if part_slug(p.get("number")) in named]
    windows = [(p["start"], p["end"]) for p in chosen] or [(0, len(text))]
    for start, end in windows:
        piece = text[start:end]
        if delegation_clauses(piece) or any(
            not _POWER_USED.match(piece, m.end()) for m in _POWER.finditer(piece)
        ):
            return "delegates"
    return "mentioned"


def basis_text(text: str) -> str:
    """One reference of a preamble without the list word before it and the law after it:
    "artikelen 3" is "3", "1:25, derde lid, onderdeel b, van de Wet op het financieel
    toezicht" is "1:25, derde lid, onderdeel b"."""
    return _LAW_TAIL.sub("", _LIST_WORD.sub("", text)).strip()


def basis_range_end(text: str, first: str) -> str | None:
    """The last article of a range of articles one reference names from *first* on
    ("artikelen 26 tot en met 30": "30"); None when it names one article, or a range of
    leden ("artikel 3:11, tweede tot en met derde lid")."""
    match = _ARTICLE_RANGE.match(basis_text(text))
    if match is None or match["first"] != first:
        return None
    return match["last"]


def basis_qualifier(text: str | None) -> Qualifier:
    """The leden, onderdelen and aanhef one reference of a preamble names of its article,
    read after the article number: "673e, eerste lid" names lid 1, not lid 673."""
    if not text:
        return Qualifier()
    return parse_qualifier(_ARTICLE_HEAD.sub("", basis_text(text)))
