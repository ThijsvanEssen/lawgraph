"""The bills of the Eerste Kamer, as eerstekamer.nl shows them (pure functions).

* A committee's page links the list of the bills it handles
  (``/wetsvoorstellen_bij_commissie?key=<committee>``): under each heading of the Kamer's
  own words (``In schriftelijke voorbereiding``, ``Gereed voor plenaire behandeling door de
  Eerste Kamer``, ``Plenaire behandeling Eerste Kamer afgerond``) the bills with their number
  (``36.945 XXII``) and page (``/wetsvoorstel/<number>_<words>``); ``verder`` pages back to
  the older ones.
* A bill's page holds its number in its title (``Wet … (36.791)``), the day it was submitted
  under ``Kerngegevens`` (``ingediend``), and the progress of the bill (``voortgangModule``):
  one block per step, each with the name of the phase (``Schriftelijke voorbereiding``,
  ``Plenair``, ``Afkondiging``; the first block has none), the house it is in (``Tweede
  Kamer``, ``Eerste Kamer``, ``Staatsblad(en)``), its state as the page marks it (``vol``,
  ``geblokt``, ``leeg``) and its papers, each with its kind, date and number (``EK, B``).

Only the page structure and its labelled fields are read, never a sentence (the page also
says in words how each house voted: the votes come from the list of votes).
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from lawgraph.core.eerstekamer_composition import text
from lawgraph.core.rijksoverheid import parse_date

_BILL_LIST = re.compile(r"/wetsvoorstellen_bij_commissie\?key=[a-z0-9]+")
_HEADING = re.compile(r'<h2><a id="p\d+"></a>([^<]+)</h2>')
_LISTED = re.compile(
    r'<a href="(/wetsvoorstel/[^"#?]+)"[^>]*>.*?<span>\s*([0-9.]+(?:\s+[^<\s]+)?)\s*<br',
    re.S,
)
_NEXT = re.compile(r'<li class="plus volgende">\s*<a href="([^"]+)"')
_TITLE_NUMBER = re.compile(r"<title>[^<]*\(([0-9.]+(?:\s+[A-Za-z0-9-]+)?)\)")
_SUBMITTED = re.compile(r"<h3[^>]*>\s*ingediend\s*</h3>\s*([^<]+)")
_BLOCK = re.compile(
    r'<div class="voortgangBlok\d+">(.*?)(?=<div class="voortgangBlok\d+">|$)', re.S
)
_STATE = re.compile(r'^\s*<div class="([a-z]+)"')
_PHASE = re.compile(r'<span class="fase ellip">([^<]*)</span>')
_HOUSE = re.compile(r'<div class="[a-z0-9]+ ellip voortgangM inst">([^<]*)</div>')
_DOCS = re.compile(r'<div class="docs grid-x nowr">(.*)', re.S)
_DOC = re.compile(
    r'<div class="doc"><a href="([^"]+)"[^>]*data-bs-title="([^"]*)"[^>]*data-bs-content="([^"]*)"'
)
_DOC_NUMBER = re.compile(r"</a>\s*((?:TK|EK), [^<&\s]+)")


# The heading of a committee's list over the bills it finished: their pages no longer change.
FINISHED = "Plenaire behandeling Eerste Kamer afgerond"


@dataclass(frozen=True)
class ListedBill:
    """A bill as a committee's list names it."""

    path: str  # /wetsvoorstel/36791_wet_toekomstbestendige
    label: str  # 36791, 36945-XXII
    status: str  # the heading it is under, in the Kamer's words


@dataclass(frozen=True)
class Paper:
    """A paper of a step, as the progress of a bill lists it."""

    kind: str  # verslag, nota naar aanleiding van het verslag, stemming (hamerstuk)
    date: str | None
    number: str | None  # EK, B; TK, 2
    url: str


@dataclass(frozen=True)
class Step:
    """A block of the progress of a bill."""

    phase: str | None  # Schriftelijke voorbereiding, Plenair, Afkondiging
    house: str | None  # Tweede Kamer, Eerste Kamer, Staatsblad(en)
    state: str | None  # as the page marks it: vol, geblokt, leeg
    papers: list[Paper] = field(default_factory=list)


@dataclass(frozen=True)
class Bill:
    """What a bill's page shows."""

    label: str | None
    submitted_on: str | None
    progress: list[Step] = field(default_factory=list)


def label(number: str) -> str:
    """``36.945 XXII`` -> ``36945-XXII``, ``36.791`` -> ``36791``: a dossier label."""
    digits, _, suffix = number.strip().partition(" ")
    digits = digits.replace(".", "")
    return f"{digits}-{suffix.strip()}" if suffix.strip() else digits


def bill_lists(committee_page: str) -> list[str]:
    """The lists of bills a committee's page links (one per committee)."""
    return sorted(set(_BILL_LIST.findall(committee_page)))


def listed_bills(page: str) -> tuple[list[ListedBill], str | None]:
    """The bills of a list, each under its heading, and the page of the older ones."""
    found: list[ListedBill] = []
    headings = [(m.start(), text(m[1])) for m in _HEADING.finditer(page)]
    for match in _LISTED.finditer(page):
        status = next((h for at, h in reversed(headings) if at < match.start()), "")
        found.append(ListedBill(match[1], label(text(match[2])), status))
    following = _NEXT.search(page)
    return found, html_lib.unescape(following[1]) if following else None


def _paper(url: str, title: str, content: str) -> Paper:
    kind, _, day = html_lib.unescape(title).rpartition(" - ")
    number = _DOC_NUMBER.search(html_lib.unescape(content))
    return Paper(
        kind=text(kind or day),
        date=parse_date(day) if kind else None,
        number=number[1].strip() if number else None,
        url=html_lib.unescape(url),
    )


def _step(block: str) -> Step:
    state = _STATE.match(block)
    phase = _PHASE.search(block)
    house = _HOUSE.search(block)
    docs = _DOCS.search(block)
    return Step(
        phase=text(phase[1]) or None if phase else None,
        house=text(house[1]) or None if house else None,
        state=state[1] if state else None,
        # the papers only: the "i" of a phase opens an explanation, no paper
        papers=[_paper(*m) for m in _DOC.findall(docs[1])] if docs else [],
    )


def bill(page: str) -> Bill:
    """A bill's page: its label, the day it was submitted, and its progress."""
    number = _TITLE_NUMBER.search(page)
    submitted = _SUBMITTED.search(page)
    return Bill(
        label=label(number[1]) if number else None,
        submitted_on=parse_date(text(submitted[1])) if submitted else None,
        progress=[_step(block) for block in _BLOCK.findall(page)],
    )
