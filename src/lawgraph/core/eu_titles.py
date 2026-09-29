"""The names of an EU act, from its CELEX number and its printed title — pure, no I/O.

The citation title is the form the Official Journal cites an act by:

* from 2015 the number is year/number with the domain before it: ``Verordening (EU)
  2016/679``, ``Richtlijn (EU) 2019/1937``;
* before 2015 a regulation has the domain and ``nr.`` before number/year (``Verordening
  (EEG) nr. 295/91``, ``Verordening (EU) nr. 1093/2010``), any other act year/number/domain
  (``Richtlijn 95/46/EG``, ``Kaderbesluit 2002/584/JBZ``);
* the year has two digits up to 1998 and four from 1999 (``Richtlijn 1999/93/EG``);
* the domain is that of the treaty in force on the day the act was adopted: ``EEG`` before
  the Treaty of Maastricht (1 November 1993), ``EG`` before the Treaty of Lisbon
  (1 December 2009), ``EU`` from then on; a framework decision is ``JBZ``. Without a date
  in the title the year of the CELEX number counts from its first day.

The word before the number is the one the title starts with ("Beschikking",
"Gedelegeerde Verordening"), else the one of the kind of act.

The title is the printed one. A first paragraph in capitals ("VERORDENING (EU) 2022/868 VAN
HET EUROPEES PARLEMENT EN DE RAAD") is written as the citation title with its authors in
their own capitals ("… van het Europees Parlement en de Raad"); a closing paragraph between
brackets ("(Voor de EER relevante tekst)") is a note, not title. A name between brackets at
the end of the title that names the kind of act ("(Datagovernanceverordening)",
"(algemene verordening gegevensbescherming)") is its short title.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from lawgraph.core.identifiers import parse_celex
from lawgraph.core.rijksoverheid import parse_date

# The Dutch word for each kind of act (CELEX letters live in core.identifiers).
_KIND_LABELS: dict[str, str] = {
    "directive": "Richtlijn",
    "regulation": "Verordening",
    "decision": "Besluit",
    "framework_decision": "Kaderbesluit",
}
_MAASTRICHT = "1993-11-01"
_LISBON = "2009-12-01"
_NEW_NUMBERING = 2015  # year/number with the domain before it
_FOUR_DIGIT_YEAR = 1999
_FRAMEWORK_DOMAIN = "JBZ"

# The words that are not capitalised in the authors of an act.
_AUTHOR_PARTICLES = frozenset({"van", "het", "de", "en", "der"})
# The designation of the act: the words before its number, "(EU)" or "van".
_DESIGNATION_RE = re.compile(r"((?:[^\W\d]+ )*?[^\W\d]+)(?= *[(\d]| +van\b)", re.I)
_SHORT_TITLE_RE = re.compile(r"\(([^()\d]+)\)$")
_QUOTES = " \"'„“”‘’"


@dataclass(frozen=True)
class EuActNames:
    title: str | None
    citation_title: str | None
    short_title: str | None


def citation_title(
    celex: str, *, adopted: str | None = None, designation: str | None = None
) -> str | None:
    """``Verordening (EU) 2022/868``, ``Richtlijn 95/46/EG``; *adopted* is the day of
    adoption (``YYYY-MM-DD``), *designation* the word before the number."""
    parsed = parse_celex(celex)
    if parsed is None or parsed.kind is None:
        return None
    label = designation or _KIND_LABELS.get(parsed.kind)
    if not label:
        return None
    year = int(parsed.year)
    number = str(int(parsed.number))
    domain = _domain(parsed.kind, adopted or f"{year:04d}-01-01")
    if year >= _NEW_NUMBERING:
        return f"{label} ({domain}) {year}/{number}"
    printed_year = str(year) if year >= _FOUR_DIGIT_YEAR else f"{year % 100:02d}"
    if parsed.kind == "regulation":
        return f"{label} ({domain}) nr. {number}/{printed_year}"
    return f"{label} {printed_year}/{number}/{domain}"


def _domain(kind: str, adopted: str) -> str:
    if kind == "framework_decision":
        return _FRAMEWORK_DOMAIN
    if adopted < _MAASTRICHT:
        return "EEG"
    return "EG" if adopted < _LISBON else "EU"


def act_names(celex: str, printed: Sequence[str]) -> EuActNames:
    """The title, citation title and short title of an act from its printed title (the
    paragraphs of ``core.eurlex_html.EuAct.title``)."""
    # NFKC: the old format writes "Richtlĳn" with the ligature "ĳ"
    paragraphs = [unicodedata.normalize("NFKC", paragraph) for paragraph in printed]
    while len(paragraphs) > 1 and _is_note(paragraphs[-1]):
        paragraphs.pop()
    printed_title = " ".join(paragraphs)
    designation = _designation(paragraphs[0]) if paragraphs else None
    cited = citation_title(
        celex, adopted=parse_date(printed_title), designation=designation
    )
    if not paragraphs:
        return EuActNames(None, cited, None)
    first = paragraphs[0]
    if cited:
        _, van, authors = first.partition(" VAN ")
        if van:
            first = f"{cited} van {_authors(authors)}"
        elif first.isupper():
            first = cited
    title = " ".join([first, *paragraphs[1:]])
    parsed = parse_celex(celex)
    kind = designation or _KIND_LABELS.get(parsed.kind or "", "") if parsed else ""
    return EuActNames(title, cited, _short_title(title, kind))


def _is_note(paragraph: str) -> bool:
    return paragraph.startswith("(") and paragraph.endswith(")")


def _designation(first: str) -> str | None:
    """ "Richtlijn" of "RICHTLIJN 95/46/EG VAN …", "Gedelegeerde Verordening" of
    "GEDELEGEERDE VERORDENING (EU) 2019/980 VAN …"."""
    match = _DESIGNATION_RE.match(first)
    if not match:
        return None
    return " ".join(word.capitalize() for word in match[1].split())


def _authors(authors: str) -> str:
    """ "HET EUROPEES PARLEMENT EN DE RAAD" -> "het Europees Parlement en de Raad"."""
    return " ".join(
        word.lower() if word.lower() in _AUTHOR_PARTICLES else word.capitalize()
        for word in authors.split()
    )


def _short_title(title: str, kind: str) -> str | None:
    """The name between brackets that ends the title when it names the *kind* of act
    ("Verordening", "Gedelegeerde Verordening")."""
    match = _SHORT_TITLE_RE.search(title)
    word = kind.split()[-1].lower() if kind else ""
    if not match or not word or word not in match[1].lower():
        return None
    name = match[1].strip(_QUOTES)
    return name[:1].upper() + name[1:]
