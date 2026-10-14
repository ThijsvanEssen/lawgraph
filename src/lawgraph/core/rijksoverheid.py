"""A cabinet page of Rijksoverheid (``/regering/over-de-regering/kabinetten-sinds-1945/<slug>``).

Rijksoverheid describes every cabinet since 1945 on one page (CC0). ``parse_page`` reads
from it:

- ``name`` (``kabinet-Schoof``) and the ``intro``: the period (``3 juli 1946 - 7 augustus
  1948``, ``regeerde van 22 juli 2002 tot 27 mei 2003``) or the day of the beëdiging;
- ``seats``: every item of the lists under ``Ministers`` and ``Staatssecretarissen``. An item
  starts with a heading (``Minister van Infrastructuur en Waterstaat``, ``Vice-minister-president
  en minister van Financiën``, ``Buitenlandse Zaken`` under Staatssecretarissen) followed by
  one line per holder: ``Drs. S.Th.M. (Sophie) Hermans (VVD), 3 juni 2025 - 19 juni 2025``,
  ``J. Smallenbroek (ARP), afgetreden 31 aug. 1966``, ``dr. I. Samkalden (PvdA), a.i.,
  31 aug.-5 sep. 1966`` (``parse_holder``);
- ``facts``: the lines ``<label>: <day>`` (``Beëdiging kabinet: 2 juli 2024``,
  ``Ontslagaanvraag ingetrokken: 8 juni 1999``), with the block they stand in;
- ``resignations``: the sentences that say on a day that the cabinet or some of its members
  offered their resignation (``Op 3 juni 2025 boden de bewindspersonen van de PVV hun ontslag
  aan de Koning aan.``), in the source's words.

Nothing is completed here: a date the page does not give stays ``None``.
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.core.dutch_dates import (
    DATE_ABBREVIATED,
    MONTH_OR_ABBREVIATION,
    dutch_day,
)
from lawgraph.core.dutch_names import TITLES
from lawgraph.core.xml import collapse_ws, html_text

# ``3 juni 2025``, ``15 sept. 1947``, ``8 sep.1977``: the page abbreviates its months.
_DAY = DATE_ABBREVIATED
_DATE = re.compile(_DAY, re.IGNORECASE)
# ``3 juni 2025 - 19 juni 2025``, ``31 aug.-5 sep. 1966``, ``7-14 jan. 1970``,
# ``15 mei-10 juli 1950``: what the first day leaves out, it shares with the second.
_RANGE = re.compile(
    rf"(\d{{1,2}})\s*(?:({MONTH_OR_ABBREVIATION})\b\.?\s*(\d{{4}})?)?\s*[-–]\s*"
    rf"(\d{{1,2}})\s*({MONTH_OR_ABBREVIATION})\b\.?\s*(\d{{4}})",
    re.IGNORECASE,
)

SECTION_MINISTERS = "ministers"
SECTION_STATE_SECRETARIES = "staatssecretarissen"


def _date(text: str) -> str | None:
    return dutch_day(text, abbreviations=True)


def _range(match: re.Match[str]) -> tuple[str | None, str | None]:
    d1, m1, y1, d2, m2, y2 = match.groups()
    return _date(f"{d1} {m1 or m2} {y1 or y2}"), _date(f"{d2} {m2} {y2}")


def _lines(fragment: str) -> list[str]:
    """The lines of *fragment*: split at ``<br>``, empty ones left out."""
    return [line for line in map(html_text, re.split(r"<br\s*/?>", fragment)) if line]


def _blocks(page: str) -> list[tuple[str, str]]:
    """``(heading, html)`` of every text block of the page, in order; a block with two
    headings (Ministers and Staatssecretarissen in one) is split at the second."""
    blocks = []
    for block in re.findall(r'<div class="rich-text">(.*?)</div>', page, re.S):
        parts = re.split(r"<h[23][^>]*>(.*?)</h[23]>", block, flags=re.S)
        if parts[0].strip() and html_text(parts[0]):
            blocks.append(("", parts[0]))
        for heading, body in zip(parts[1::2], parts[2::2], strict=True):
            blocks.append((html_text(heading), body))
    return blocks


def _section(heading: str) -> str | None:
    plain = heading.lower()
    if plain.startswith("staatssecretaris"):
        return SECTION_STATE_SECRETARIES
    if plain.startswith("minister"):
        return SECTION_MINISTERS
    return None


def _intro(page: str) -> str:
    match = re.search(r'<div class="rich-text larger-text">(.*?)</div>', page, re.S)
    return html_text(match.group(1)) if match else ""


def intro_period(intro: str) -> tuple[str | None, str | None]:
    """The period the introduction gives: ``(from, to)``, ``to`` ``None`` when it names
    only the beëdiging."""
    match = _RANGE.search(intro)
    if match and match.start() < 5:
        return _range(match)
    governed = re.search(rf"regeerde van ({_DAY}) tot ({_DAY})", intro, re.IGNORECASE)
    if governed:
        return _date(governed[1]), _date(governed[2])
    sworn = re.search(rf"Op ({_DAY}) was de beëdiging", intro, re.IGNORECASE)
    return (_date(sworn[1]) if sworn else None), None


# A line ``<label>: <day>``: ``Tweede Kamerverkiezingen: 15 mei 2002``.
_FACT = re.compile(rf"^([^:]{{3,60}}?)\s*:\s*({_DAY})\s*\.?$", re.IGNORECASE)


def _facts(heading: str, body: str) -> list[dict[str, Any]]:
    facts = []
    for item in re.split(r"<br\s*/?>|</?(?:li|p|ul)[^>]*>", body):
        line = html_text(item)
        match = _FACT.match(line)
        if match:
            facts.append(
                {
                    "label": match.group(1).strip(),
                    "text": line,
                    "date": _date(match[2]),
                    "block": heading,
                }
            )
    return facts


# A sentence that says on a day that the cabinet or some of its members resigned:
# ``bood op 3 mei 1989 zijn ontslag aan``, ``diende op 16 april 2002 zijn ontslag in``,
# ``trad op 14 oktober 1966 af``, ``hun ontslagaanvragen indienden``.
_RESIGNED = re.compile(
    r"\bontslag\w*\b.*\b(aan|in|indienden|ingediend)\b|\b(bood|boden|bieden)\b.*\bontslag"
    r"|\btrad\b.*\baf\b",
    re.IGNORECASE,
)
# A day that is not the day of the act: ``Na de Tweede Kamerverkiezingen van 22 november 2006``.
_NOT_THE_DAY = re.compile(r"verkiezing(?:en)? van\s*$", re.IGNORECASE)


def _resignations(text: str) -> list[dict[str, Any]]:
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
        if not _RESIGNED.search(sentence):
            continue
        for match in _DATE.finditer(sentence):
            if _NOT_THE_DAY.search(sentence[: match.start()]):
                continue
            found.append({"label": sentence.strip(), "date": _date(match[0])})
            break
    return found


def parse_page(page: str) -> dict[str, Any]:
    """What a cabinet page says; see the module docstring."""
    title = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    intro = _intro(page)
    seats: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    resignations = _resignations(intro)
    section: str | None = None
    for heading, body in _blocks(page):
        section = _section(heading) or (section if not heading else None)
        if section is not None:
            seats.extend(_seats(section, body))
            continue
        facts.extend(_facts(heading, body))
        resignations.extend(_resignations(html_text(body)))
    start, end = intro_period(intro)
    return {
        "name": html_text(title.group(1)) if title else None,
        "intro": intro,
        "intro_from": start,
        "intro_to": end,
        "seats": seats,
        "facts": facts,
        "resignations": _unique(resignations),
    }


# ``Van 3 februari 1987 tot 6 mei 1987 ... werden de volgende tijdelijke voorzieningen
# getroffen:``: the items after it stood in for that period.
_TEMPORARY = re.compile(
    rf"\bVan ({_DAY}) tot ({_DAY}).*tijdelijke voorziening", re.IGNORECASE
)


def _is_dates(line: str) -> bool:
    """A line of days only: the rest of the line above (``7 aug. 1946-25 nov. 1947``)."""
    return bool(re.match(r"^\d", line)) and parse_holder(line) is None


def _seats(section: str, body: str) -> list[dict[str, Any]]:
    """The items of one list: ``{section, heading, lines, notes, temporary}``.

    The heading can run over several lines (``Minister van Defensie en minister voor
    Nederlands-Antilliaanse`` / ``en Arubaanse Zaken``) up to the first holder; a line of
    days only belongs to the holder above it; a line that names no one is a note. After a
    note about ``tijdelijke voorzieningen`` from one day to another, the items that follow
    are those arrangements: ``temporary`` is ``{from_date, to_date, note}``."""
    seats: list[dict[str, Any]] = []
    temporary: dict[str, Any] | None = None
    for item in re.findall(r"<li[^>]*>(.*?)</li>", body, re.S):
        lines = _lines(item)
        if not lines:
            continue
        heading, rest = lines[0], lines[1:]
        while rest and parse_holder(rest[0]) is None and not _is_dates(rest[0]):
            if re.match(r"^(toelichting|deze taken)", rest[0], re.IGNORECASE):
                break
            heading = f"{heading} {rest.pop(0)}"
        holders: list[str] = []
        notes: list[str] = []
        for line in rest:
            if _is_dates(line) and holders:
                holders[-1] = f"{holders[-1]}, {line}"
            elif parse_holder(line) is not None:
                holders.append(line)
            else:
                notes.append(line)
        if holders:
            seats.append(
                {
                    "section": section,
                    "heading": heading,
                    "lines": holders,
                    "notes": notes,
                    "temporary": temporary,
                }
            )
        for note in notes:
            match = _TEMPORARY.search(note)
            if match:
                temporary = {
                    "from_date": _date(match[1]),
                    "to_date": _date(match[2]),
                    "note": note,
                }
    return seats


def _unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str | None] = set()
    kept = []
    for item in items:
        if item["date"] not in seen:
            seen.add(item["date"])
            kept.append(item)
    return kept


# ── Holders ──────────────────────────────────────────────────────────────────

# Titles and degrees before or after a name.
_TITLES = re.compile(
    rf"\b(?:{'|'.join(TITLES)}|mw|mevr|dhr|mmr|ds|jhr|jkvr|bc|ba|ma|msc|mba|mpa|phd"
    r"|ll\.?\s?m|baron|viceadmiraal|generaal|luitenant-generaal)\b\.?",
    re.IGNORECASE,
)
_INITIALS = re.compile(r"^((?:(?:IJ|[A-Z][a-z]{0,2})\.\s*|[A-Z]\s+(?=\S))+)")


def split_name(text: str) -> dict[str, Any]:
    """``{initials, letters, first_name, surname}`` of a name as Rijksoverheid writes it:
    ``Drs. S.Th.M. (Sophie) Hermans`` -> ``S.Th.M.``, ``stm``, ``Sophie``, ``Hermans``."""
    text = re.sub(r"\.{2,}", ".", text)  # ``L..J.M.``
    first = re.search(r"\(([^)]*)\)", text)
    rest = re.sub(r"\([^)]*\)", " ", text)
    rest = re.sub(r"\s+", " ", _TITLES.sub(" ", rest)).strip(" ,.")
    # ``H.G.J Kamp``: the last initial without its dot
    rest = re.sub(r"^((?:[A-Z][a-z]{0,2}\.)+[A-Z])\s", r"\1. ", rest)
    match = _INITIALS.match(rest)
    initials = re.sub(r"\s+", "", match.group(1)) if match else ""
    # ``B de Vries``: an initial without its dot
    initials = re.sub(r"([A-Z])(?=[A-Z]|$)", r"\1.", initials)
    surname = rest[match.end() :].strip() if match else rest
    letters = "".join(
        ("ij" if part == "IJ" else part[0]).lower()
        for part in initials.split(".")
        if part
    )
    return {
        "initials": initials,
        "letters": letters,
        "first_name": first.group(1).strip() if first else None,
        "surname": surname,
    }


# A bracket right after initials holds a first name (``S.Th.M. (Sophie) Hermans``); the
# first other bracket holds the party.
_BRACKET = re.compile(r"\(([^()]*)\)")
_AFTER_INITIALS = re.compile(r"(?:\b[A-Z][a-z]{0,2}\.|\b[A-Z])\s*$")
_ACTING = re.compile(r"\ba\.\s?i\b\.?", re.IGNORECASE)
_STARTS = re.compile(
    rf"\b(?:vanaf|per|aangetreden|sinds)\s*(?:op\s+)?{_DAY}", re.IGNORECASE
)
_ENDS = re.compile(rf"\b(tot|afgetreden|overleden)\s+(?:op\s+)?{_DAY}", re.IGNORECASE)
_DEFINITIVE = re.compile(rf"\bdefinitief\s+{_DAY}", re.IGNORECASE)
_KEYWORD_BEFORE = re.compile(
    r"(vanaf|per|aangetreden|sinds|tot|afgetreden|overleden|definitief|op)\s*$",
    re.IGNORECASE,
)
# ``26 oktober 2017 - 1 november 2019 en sinds 14 april 2020``: two periods.
_NEXT_PERIOD = re.compile(r"\s+en\s+(?=(?:sinds|vanaf)?\s*\d)", re.IGNORECASE)
_TAKEN_OVER = re.compile(
    r"beheer portefeuille overgenomen door de (minister van [^,;]+)", re.IGNORECASE
)
_OWN_PORTFOLIO = re.compile(r"\b(staatssecretaris\s+[^,;]+)", re.IGNORECASE)
# ``tijdelijk afwezig van 30 oktober 2023 - 23 november 2023``: the holder kept the post.
_ABSENT = re.compile(rf"tijdelijk afwezig van\s*({_RANGE.pattern})", re.IGNORECASE)
_ALSO_DEPUTY = re.compile(r"\bOok vice-?\s?minister-president\b", re.IGNORECASE)
# ``L. de Graaf CDA) afgetreden``: a party without its opening bracket.
_UNOPENED_PARTY = re.compile(r"^([^()]+?)\s+([A-Z][A-Z0-9'-]+)\)")


def _party(text: str) -> str | None:
    """``VVD`` of ``VVD``; ``partijloos`` of ``op voordracht van NSC; partijloos``."""
    plain = collapse_ws(text)
    if not plain:
        return None
    if "partijloos" in plain.lower():
        return "partijloos"
    return plain


def _looks_like_a_name(name: str, party: str | None) -> bool:
    """Initials (``S.Th.M.``), or a single capital before a party (``dr. B de Vries (CDA)``)."""
    if len(name) >= 80 or name.startswith("("):
        return False
    if re.search(r"\b[A-Z][a-z]{0,2}\.", name):
        return True
    return party is not None and len(party) < 40 and bool(re.search(r"\b[A-Z]\b", name))


def _period(text: str) -> dict[str, Any]:
    """``{from_date, to_date, ended}`` that one stretch of a holder line gives."""
    period: dict[str, Any] = {"from_date": None, "to_date": None, "ended": None}
    span = _RANGE.search(text)
    if span:
        period["from_date"], period["to_date"] = _range(span)
        text = text[: span.start()] + text[span.end() :]
    start = _STARTS.search(text)
    if start:
        period["from_date"] = _date(start[0])
    end = _ENDS.search(text)
    if end:
        period["ended"] = end.group(1).lower()
        period["to_date"] = _date(end[0])
    if period["from_date"] is None:
        # a bare day is the start: ``Dr. B.R. Bot, 3 december 2003``
        for bare in _DATE.finditer(text):
            if not _KEYWORD_BEFORE.search(text[: bare.start()]):
                period["from_date"] = _date(bare[0])
                break
    return period


def parse_holder(line: str) -> dict[str, Any] | None:
    """One holder line of a seat: ``{name, party, periods, acting, until_acting,
    portfolio, also_deputy, absent, taken_over_by}``, or ``None`` for a line that names no one
    (``Deze taken werden vervolgens opgedragen aan:``).

    ``periods`` are ``{from_date, to_date, ended}``, usually one: what the line says
    (``vanaf``, ``tot``, ``afgetreden``, a range, or a bare day for the start), ``None``
    where it says nothing; ``ended`` is the word the end was given with (``afgetreden``,
    ``overleden``, ``tot``). ``acting`` is ``a.i.``; ``until_acting`` the day an ``a.i.``
    post became ``definitief``; ``absent`` ``(from, to)`` of a ``tijdelijk afwezig``."""
    line = _UNOPENED_PARTY.sub(r"\1 (\2),", line)
    bracket = next(
        (
            b
            for b in _BRACKET.finditer(line)
            if not _AFTER_INITIALS.search(line[: b.start()])
        ),
        None,
    )
    if bracket:
        name, party = line[: bracket.start()], _party(bracket.group(1))
        rest = line[bracket.end() :]
    else:
        name, _, rest = line.partition(",")
        party = None
    name = name.strip(" ,.")
    if not _looks_like_a_name(name, party):
        return None
    definitive = _DEFINITIVE.search(rest)
    taken = _TAKEN_OVER.search(rest)
    own = _OWN_PORTFOLIO.search(rest)
    absent = _ABSENT.search(rest)
    dated = _ABSENT.sub("", _DEFINITIVE.sub("", rest))
    periods = [_period(part) for part in _NEXT_PERIOD.split(dated)]
    return {
        "name": name,
        "party": party,
        "periods": [p for p in periods if p["from_date"] or p["to_date"]]
        or [periods[0]],
        "acting": bool(_ACTING.search(rest)),
        "until_acting": _date(definitive[0]) if definitive else None,
        "portfolio": re.sub(rf",?\s*{_DAY}.*$", "", own.group(1)).strip()
        if own
        else None,
        "also_deputy": bool(_ALSO_DEPUTY.search(rest)),
        "absent": _range(_RANGE.search(absent.group(1))) if absent else None,  # type: ignore[arg-type]
        "taken_over_by": taken.group(1).strip() if taken else None,
    }
