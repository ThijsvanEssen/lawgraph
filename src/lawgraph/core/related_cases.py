"""The cases a judgment's summary (inhoudsindicatie) names as connected to it.

The metadata of the Rechtspraak relates a judgment only along its chain of instances
(``dcterms:relation``, "Formele relatie"). Connected cases are told in the summary the
court writes: "Samenhang met 24/03860 E en 24/03859 P (niet gepubliceerd)", "Samenhang met
HR:2025:404 en HR:2025:405", "Zie ook: ECLI:NL:GHDHA:2025:1539, ECLI:NL:GHDHA:2025:1536 en
ECLI:NL:GHDHA:2025:1535", "Zie ook 25/02365, ECLI:NL:HR:2026:1416".

Each sentence is read as written: the ECLIs it names (also as the courts abbreviate them,
``HR:2025:404``, which is ``ECLI:NL:HR:2025:404``) and its case numbers. A case number is
compared exactly, per court: lower case and without spaces (``core.judgments
.case_number_keys``). The Hoge Raad's type letter is not part of the comparison: it writes
its type of case after the number ("24/03860 E", "16/01894 UA") where its metadata gives the
number alone, and the number is unique within the Hoge Raad. What a sentence says between
brackets ("(niet gepubliceerd)", "(einduitspraak)") names no case; an old LJN ("LJN
BU3634") is not read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lawgraph.core.judgments import case_number_keys

# "Samenhang met ...", "Zie ook: ...", "Zie tevens ...": up to the end of the sentence, a
# dot before a capital or the end ("nrs. 07/11290" and "d.d. 20 maart" go on).
_SENTENCE = re.compile(
    r"(?P<lead>Samenhang\s+met|Zie\s+(?:ook|tevens))\s*:?\s*(?P<rest>.+?)"
    r"(?=\.\s+[A-Z]|\.?\s*$)",
    re.IGNORECASE,
)
# An ECLI anywhere in the sentence, also as the courts abbreviate it: "HR:2025:404".
_ECLI_IN_TEXT = re.compile(
    r"\b(?:ECLI:NL:)?(?P<court>[A-Z]{2,8}):(?P<year>\d{4}):(?P<number>[A-Z0-9]{1,8})\b"
)
_BRACKETS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_ITEMS = re.compile(r"\s*(?:,|;|\ben\s+met\b|\ben\b|\bmet\b)\s*", re.IGNORECASE)
_LEAD_WORDS = re.compile(
    r"^(?:(?:de\s+)?(?:zaken?|nrs?\.?|nummers?)\s+)+", re.IGNORECASE
)
# A case number: digits with / . - between them ("24/03860", "200.343.752/01"), and the
# Hoge Raad's type of case after it ("E", "P", "UA", "Bv").
_CASE_NUMBER = re.compile(
    r"^(?P<number>\d[\d./-]*\d(?:/\d+)?)(?:\s+(?P<type>[A-Z][A-Za-z]{0,2}))?$"
)


@dataclass
class RelatedCases:
    """What one sentence of a summary names: its ECLIs and its case numbers as compared
    (each a list of keys, the first as written), and the sentence itself."""

    text: str
    eclis: list[str] = field(default_factory=list)
    case_numbers: list[list[str]] = field(default_factory=list)


def _case_number(item: str) -> list[str] | None:
    """The keys of a case number as written, then without the type of case."""
    match = _CASE_NUMBER.match(item)
    if not match:
        return None
    keys = case_number_keys(item)
    if match["type"]:
        keys += [k for k in case_number_keys(match["number"]) if k not in keys]
    return keys or None


def read_related_cases(summary: str | None) -> list[RelatedCases]:
    """The sentences of *summary* that name connected cases, each with what it names; a
    sentence that names nothing readable is left out."""
    found: list[RelatedCases] = []
    summary = summary or ""
    for match in _SENTENCE.finditer(summary):
        end = match.end() + (summary[match.end() : match.end() + 1] == ".")
        text = re.sub(r"\s+", " ", summary[match.start() : end]).strip()
        related = RelatedCases(text=text)
        rest = _BRACKETS.sub(" ", match["rest"])
        for found_ecli in _ECLI_IN_TEXT.finditer(rest):
            ecli = "ECLI:NL:{court}:{year}:{number}".format(**found_ecli.groupdict())
            if ecli not in related.eclis:
                related.eclis.append(ecli)
        for raw in _ITEMS.split(_ECLI_IN_TEXT.sub(" ", rest)):
            item = _LEAD_WORDS.sub("", raw.strip(" .:;"))
            keys = _case_number(item) if item else None
            if keys is not None and keys not in related.case_numbers:
                related.case_numbers.append(keys)
        if related.eclis or related.case_numbers:
            found.append(related)
    return found
