"""What a criminal judgment decided on the charge: proven or not, and the main sentence (pure
functions, no I/O).

Read from the clauses of the decision (``core.judgment_outcome.dispositive_clauses``) of a
judgment of a court of first instance or of appeal:

- **proven** (``ja``, ``deels``, ``nee``): ``verklaart bewezen`` is a yes; ``verklaart niet
  bewezen`` and ``spreekt vrij van`` name a charge that fell, and with a proven charge beside
  it the answer is ``deels``. The formula ``verklaart niet bewezen wat meer of anders is ten
  laste gelegd dan bewezen verklaard en spreekt vrij`` closes nearly every conviction and is
  no acquittal. ``ontslaat van alle rechtsvervolging`` is proven without a sentence;
- **sentences**: the main punishments (imprisonment, community service, fine, detention,
  juvenile detention, hospital order) as the decision words them, each with its kind and the
  duration or amount it names;
- **flags**: more than one charge or case, the prosecution inadmissible for a part and the
  appeal court setting the judgment appealed against aside.

A decision that is none of these (a complaint, a confiscation order, a Hoge Raad ruling, the
prosecution inadmissible as a whole) has no ``proven``: that is no conviction or acquittal to
tell.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from lawgraph.core.display import shorten
from lawgraph.core.judgment_outcome import (
    decision_paragraphs,
    dispositive_clauses,
    dispositive_segments,
)

Proven = Literal["ja", "deels", "nee"]
PROVEN: Final[Proven] = "ja"
PARTLY_PROVEN: Final[Proven] = "deels"
NOT_PROVEN: Final[Proven] = "nee"

# The characters of a sentence kept at most.
SENTENCE_CHARS = 240

# (kind, words naming it), tried in this order in a clause.
_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gevangenisstraf", re.compile(r"\bgevangenisstraf\b", re.I)),
    ("taakstraf", re.compile(r"\b(?:taak|werk)straf\b", re.I)),
    ("geldboete", re.compile(r"\bgeldboete\b", re.I)),
    ("jeugddetentie", re.compile(r"\bjeugddetentie\b", re.I)),
    ("hechtenis", re.compile(r"(?<!voorlopige )(?<!vervangende )\bhechtenis\b", re.I)),
    (
        "tbs",
        re.compile(
            r"\bter\s+beschikking\s+(?:te\s+)?(?:wordt\s+)?gesteld\b|\bterbeschikkingstelling\b",
            re.I,
        ),
    ),
)
# A clause that imposes a sentence: the verb, then (after "tot" or "op") a kind of sentence.
_IMPOSES = re.compile(r"^(?:veroordeelt|legt|gelast)\b", re.I)
# "bij gebreke van betaling … hechtenis" is no sentence of its own.
_SUBSTITUTE = re.compile(r",?\s*(?:bij\s+gebreke|te\s+vervangen|subsidiair)\b.*$", re.I)
_UNITS = (
    "een|twee|drie|vier|vijf|zes|zeven|acht|negen|tien|elf|twaalf|dertien|veertien|"
    "vijftien|zestien|zeventien|achttien|negentien"
)
_TENS = "twintig|dertig|veertig|vijftig|zestig|zeventig|tachtig|negentig"
# A duration as digits ("22 maanden", "5 (vijf) jaren") or as words ("tweeëntwintig maanden").
_NUMBER = rf"\d+|(?:(?:{_UNITS})(?:en|ën)(?:{_TENS})|{_TENS}|{_UNITS})(?:honderd)?"
_DURATION = re.compile(
    rf"\b({_NUMBER})\s*(?:\([^)]*\)\s*)?(jaren|jaar|maanden|maand|weken|week|dagen|dag|uren|uur)\b",
    re.I,
)
_AMOUNT = re.compile(r"€\s*[\d.]+(?:,\d+)?")
_NOT_PROVEN = re.compile(
    r"^verklaart\b.*\bniet\s+(?:wettig\s+en\s+overtuigend\s+)?bewezen\b", re.I
)
# The formula behind nearly every conviction.
_BOILERPLATE = re.compile(r"\bmeer\s+of\s+anders\b|\bte\s+veel\b", re.I)
_PROVEN_CLAUSE = re.compile(r"^verklaart\b.*\bbewezen(?!\s*verklaard)", re.I)
_NOT_PUNISHABLE = re.compile(r"\bstrafbaar\b", re.I)
_ACQUITTAL = re.compile(r"^spreekt\b.*\bvrij\b", re.I)
_NO_PROSECUTION = re.compile(r"^ontslaat\b.*\brechtsvervolging\b", re.I)
_NO_SENTENCE = re.compile(
    r"^(?:ziet\s+af\s+van|legt\s+geen)\b.*\b(?:straf|maatregel)", re.I
)
_INADMISSIBLE_PROSECUTION = re.compile(
    r"^verklaart\s+(?:de\s+)?(?:officier|openbaar|ovj|het\s+openbaar)\b.*"
    r"\bniet[-‐‑\s]?ontvankelijk\b",
    re.I,
)
# The prosecution inadmissible for a part of the charges (not the appeal of a party, which
# "hoger beroep" names).
_PARTLY = re.compile(
    r"^(?!.*\bberoep\b).*(?:\bvoor\s*zover\b|\bin\s+de\s+(?:straf)?vervolging\s+(?:van|voor)\b"
    r"|\bwat\s+betreft\b)",
    re.I,
)
_QUASHES_JUDGMENT = re.compile(r"^vernietigt\b.*\b(?:vonnis|arrest|uitspraak)\b", re.I)
_CHARGES = re.compile(r"\bonder\s+(\d+(?:\s*(?:,|en|tot en met)\s*\d+)*)", re.I)
# The Hoge Raad rules on the appeal in cassation: no verdict on the charge.
_SUPREME_COURT = re.compile(r"^(?:de\s+)?hoge\s+raad\b", re.I)
_CASE = re.compile(r"\bzaak\s+([A-Z])\b")


@dataclass(frozen=True)
class Sentence:
    """A main punishment: its ``kind``, the words of the decision (``text``) and the
    durations or amounts they name."""

    kind: str
    text: str
    amounts: tuple[str, ...]


@dataclass(frozen=True)
class CriminalDecision:
    """What a criminal decision says on the charge (see the module)."""

    proven: Proven | None
    sentences: tuple[Sentence, ...]
    no_sentence: bool
    several: bool
    partly_inadmissible: bool
    quashes: bool


def _text(paragraph: Mapping[str, Any]) -> str:
    return str(paragraph.get("text") or "").strip()


def _kinds(clause: str) -> list[str]:
    return [kind for kind, pattern in _KINDS if pattern.search(clause)]


def _sentence(clause: str) -> Sentence | None:
    """The main punishment a clause imposes, None when it imposes none."""
    if not _IMPOSES.match(clause):
        return None
    clause = _SUBSTITUTE.sub("", clause)
    kinds = _kinds(clause)
    if clause.lower().startswith("gelast"):
        # only a hospital order: "gelast de tenuitvoerlegging van de gevangenisstraf" is none
        kinds = [kind for kind in kinds if kind == "tbs"]
    if not kinds:
        return None
    amounts = tuple(m.group(0) for m in _AMOUNT.finditer(clause)) + tuple(
        f"{m.group(1)} {m.group(2).lower()}" for m in _DURATION.finditer(clause)
    )
    kind = kinds[0] if len(kinds) == 1 else "meerdere"
    return Sentence(kind, shorten(clause, SENTENCE_CHARS), amounts)


def _proven(clauses: Sequence[str]) -> Proven | None:
    """Whether the charges were proven, by the clauses that say so."""
    yes = any(
        _PROVEN_CLAUSE.search(c)
        and not _NOT_PROVEN.search(c)
        and not _NOT_PUNISHABLE.search(c)
        for c in clauses
    )
    yes = yes or any(_NO_PROSECUTION.search(c) for c in clauses)
    fell = any(
        (_NOT_PROVEN.search(c) and not _BOILERPLATE.search(c))
        or (
            _ACQUITTAL.search(c)
            and not _BOILERPLATE.search(c)
            and not re.search(r"\bdaarvan\b|\bhem\b|\bhaar\b", c)
        )
        for c in clauses
    )
    fell = fell or any(
        _INADMISSIBLE_PROSECUTION.search(c) and _PARTLY.search(c) for c in clauses
    )
    if yes and fell:
        return PARTLY_PROVEN
    if yes:
        return PROVEN
    return NOT_PROVEN if fell else None


def _several(clauses: Sequence[str], sentences: Sequence[Sentence]) -> bool:
    if len(sentences) > 1:
        return True
    text = " ".join(clauses)
    cases = {m.group(1) for m in _CASE.finditer(text)}
    charges = {
        n for m in _CHARGES.finditer(text) for n in re.findall(r"\d+", m.group(1))
    }
    return len(cases) > 1 or len(charges) > 1


def criminal_decision(
    paragraphs: Sequence[Mapping[str, Any]] | None,
) -> CriminalDecision | None:
    """What the criminal judgment with these *paragraphs* (``{id, kind, text}``) decided on the
    charge; None without a decision."""
    decision = decision_paragraphs(paragraphs or [])
    found = dispositive_clauses(decision)
    if not found or _SUPREME_COURT.match(_text(decision[0])):
        return None
    clauses = [clause for clause, _ in found]
    sentences = tuple(s for c in dispositive_segments(decision) if (s := _sentence(c)))
    return CriminalDecision(
        proven=_proven(clauses),
        sentences=sentences,
        no_sentence=any(
            _NO_PROSECUTION.search(c) or _NO_SENTENCE.search(c) for c in clauses
        ),
        several=_several(clauses, sentences),
        partly_inadmissible=any(
            _INADMISSIBLE_PROSECUTION.search(c) and _PARTLY.search(c) for c in clauses
        ),
        quashes=any(_QUASHES_JUDGMENT.search(c) for c in clauses),
    )
