"""The composition of the Eerste Kamer, as eerstekamer.nl shows it today (pure functions).

* ``/fracties`` lists every faction with its seats (``PRO (14 zetels)``), linking
  ``/fractie/<slug>``: its board (``fractievoorzitter: <name> (sinds 13 juni 2023)``) and its
  members (``Samenstelling``), each with a link to ``/persoon/<slug>``, the name as the
  Kamer writes it (``mr. B.O. Dittrich``), the days served (``Anciënniteit: 2668 dagen``),
  and where given the place of residence and the date of birth.
* ``/commissies`` lists every committee (``Financiën (FIN)``), linking ``/commissies/<slug>``:
  its members, each with the faction and, where it has one, the role (``voorzitter``).

The site gives no start or end of a membership as data (only in sentences), so none is read:
what is read is who sits where on the day of reading. Only the page structure and its
labelled fields are parsed, never a sentence.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from lawgraph.core.rijksoverheid import parse_date

FACTIONS_PATH = "/fracties"
COMMITTEES_PATH = "/commissies"

_MAIN = re.compile(r"<main.*?</main>", re.S)
_FACTION = re.compile(r'<a href="(/fractie/[^"#?]+)"[^>]*>(.*?)</a>', re.S)
_SEATS = re.compile(r"^(.*?)\s*\((\d+) zetels?\)$")
_COMMITTEE = re.compile(r'<a href="(/commissies/[^"#?]+)"[^>]*>(.*?)</a>', re.S)
_NAME_ABBREVIATION = re.compile(r"^(.*?)\s*\(([^()]+)\)$")
_BOARD = re.compile(
    r'([a-z][a-z -]*):\s*<a href="(/persoon/[^"]+)">([^<]+)</a>\s*\(sinds ([^)]+)\)'
)
_PERSON = re.compile(
    r'<li class="persoon[^"]*">\s*<a href="(/persoon/[^"]+)">(.*?)</a>\s*</li>', re.S
)
_NAME = re.compile(r'<div class="naam">([^<]+)</div>')
_FIELD = re.compile(r"<div>([^<:]+):\s*([^<]*)</div>")
_CAPTION = re.compile(r'<div class="persoon_bijschrift">(.*?)<div class="cell', re.S)
_PLAIN_DIV = re.compile(r"<div>([^<:]+)</div>")
_DAYS = re.compile(r"^(\d+) dagen$")
_BIRTH = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")

LABEL_SENIORITY = "Anciënniteit"
LABEL_RESIDENCE = "Woonplaats"
LABEL_BIRTH = "Geboortedatum"


@dataclass(frozen=True)
class Listed:
    """A faction or committee as a list names it."""

    path: str
    name: str
    abbreviation: str | None = None
    seats: int | None = None


@dataclass(frozen=True)
class Person:
    """A member as a faction or committee page shows them."""

    path: str  # /persoon/mr_b_o_dittrich_d66
    name: str  # mr. B.O. Dittrich
    seniority_days: int | None = None
    residence: str | None = None
    birth_date: str | None = None  # YYYY-MM-DD
    faction: str | None = None  # the abbreviation a committee page gives
    role: str | None = None  # voorzitter, ondervoorzitter


@dataclass(frozen=True)
class BoardSeat:
    """A seat on the board of a faction: ``fractievoorzitter`` and the day since."""

    function: str
    path: str
    name: str
    since: str | None


@dataclass(frozen=True)
class Page:
    """What a faction or committee page shows."""

    title: str | None
    members: list[Person] = field(default_factory=list)
    board: list[BoardSeat] = field(default_factory=list)


def text(fragment: str) -> str:
    plain = html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", plain.replace("\xa0", " ")).strip()


def _main(page: str) -> str:
    match = _MAIN.search(page)
    return match[0] if match else page


def factions(page: str) -> list[Listed]:
    """The factions of ``/fracties`` with their seats."""
    found = []
    for path, label in _FACTION.findall(_main(page)):
        match = _SEATS.match(text(label))
        if match:
            found.append(
                Listed(
                    path=path, name=match[1], abbreviation=match[1], seats=int(match[2])
                )
            )
    return found


def committees(page: str) -> list[Listed]:
    """The committees of ``/commissies``: ``Financiën (FIN)`` is ``Financiën``, ``FIN``."""
    found = []
    for path, label in _COMMITTEE.findall(_main(page)):
        name = text(label)
        match = _NAME_ABBREVIATION.match(name)
        found.append(
            Listed(path=path, name=match[1], abbreviation=match[2])
            if match
            else Listed(path=path, name=name)
        )
    return found


def _birth_date(value: str | None) -> str | None:
    match = _BIRTH.match((value or "").strip())
    return f"{match[3]}-{match[2]}-{match[1]}" if match else None


def _person(path: str, body: str) -> Person:
    fields = {text(k): text(v) for k, v in _FIELD.findall(body)}
    days = _DAYS.match(fields.get(LABEL_SENIORITY, ""))
    caption = _CAPTION.search(body)
    # the unlabelled lines of the caption after the name: the faction, then a role
    plain = [text(v) for v in _PLAIN_DIV.findall(caption[1])] if caption else []
    name = _NAME.search(body)
    return Person(
        path=path,
        name=text(name[1]) if name else "",
        seniority_days=int(days[1]) if days else None,
        residence=fields.get(LABEL_RESIDENCE) or None,
        birth_date=_birth_date(fields.get(LABEL_BIRTH)),
        faction=plain[0] if plain else None,
        role=plain[1] if len(plain) > 1 else None,
    )


def page(html: str) -> Page:
    """A faction or committee page: its title (``<h1>``), members and board."""
    title = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
    main = _main(html)
    return Page(
        title=text(title[1]) if title else None,
        members=[_person(path, body) for path, body in _PERSON.findall(main)],
        board=[
            BoardSeat(
                function=function.strip(),
                path=path,
                name=text(name),
                since=parse_date(since),
            )
            for function, path, name, since in _BOARD.findall(main)
        ],
    )
