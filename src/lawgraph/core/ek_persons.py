"""The page of a member of the Eerste Kamer (``/persoon/<slug>`` on eerstekamer.nl): who they
are and in which faction they sat, from when to when, as the page itself says it.

The page opens with their periods, the current one first: "Boris Dittrich (1955) is vanaf
11 juni 2019 lid van de D66-fractie in de Eerste Kamer.", "Henk Otten (1967) was van 28 juli
2019 tot 13 juni 2023 lid en voorzitter van de Fractie-Otten in de Eerste Kamer. Eerder was
hij van 11 juni 2019 tot 28 juli 2019 lid van de FVD-fractie in de Eerste Kamer." A sitting
member's page gives their birth date too ("geboren te Utrecht, 21 juli 1955"); a former
member's only the year.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from lawgraph.core.ek_changes import _DAY, iso_day, plain

PERSON_PREFIX = "/persoon/"

_TITLE = re.compile(
    r"<title>\s*(.*?)\s*(?:-\s*Eerste Kamer der Staten-Generaal)?\s*</title>", re.S
)
_INTRO = re.compile(
    r"\((\d{4})\)\s+(.+?)(?:\s+Contact:|\s+Personalia|\s+Anciënniteit|$)"
)
_BORN = re.compile(rf"geboren te [^,]+, {_DAY}")
# "is vanaf 11 juni 2019 lid van de D66-fractie", "was van 28 juli 2019 tot 13 juni 2023 lid
# en voorzitter van de Fractie-Otten"
_PERIOD = re.compile(
    rf"(?:is (?:hij |zij )?vanaf ({_DAY})|was (?:hij |zij )?van ({_DAY}) tot ({_DAY}))"
    r" lid(?: en [\w-]+)? van de (.+?) in de Eerste Kamer"
)


@dataclass(frozen=True)
class Period:
    """A faction the member sat in, from a day to the last day they did (None: they still
    do). The page's "tot" is the day the next began (Otten "was van 11 juni 2019 tot 28 juli
    2019 lid van de FVD-fractie" and from 28 juli of the Fractie-Otten), so the last day is
    the day before it, as ``to_date`` of a period of the Tweede Kamer is."""

    faction: str  # "D66", "Fractie-Otten"
    from_date: str
    to_date: str | None


@dataclass
class PersonPage:
    """What the page of a member says of them."""

    name: str
    birth_year: str | None = None
    birth_date: str | None = None
    periods: list[Period] = field(default_factory=list)


def faction_name(phrase: str) -> str:
    """The faction a phrase names: "de D66-fractie" is D66, "de Fractie-Otten" itself."""
    phrase = phrase.strip()
    return phrase[: -len("-fractie")] if phrase.endswith("-fractie") else phrase


def person_page(page: str) -> PersonPage | None:
    """The member a page of ``/persoon`` is about; None for a page that is no member's."""
    title = _TITLE.search(page)
    text = plain(page)
    intro = _INTRO.search(text)
    if not title or not intro:
        return None
    found = PersonPage(name=re.sub(r"\s+", " ", title.group(1)).strip())
    found.birth_year = intro.group(1)
    born = _BORN.search(text)
    if born:
        found.birth_date = iso_day(born.group(0), 0)
    for m in _PERIOD.finditer(intro.group(2)):
        if m.group(1):
            start, end = iso_day(m.group(1), 0), None
        else:
            start, until = iso_day(m.group(5), 0), iso_day(m.group(9), 0)
            end = (
                (dt.date.fromisoformat(until) - dt.timedelta(days=1)).isoformat()
                if until
                else None
            )
        if start:
            found.periods.append(Period(faction_name(m.group(13)), start, end))
    return found
