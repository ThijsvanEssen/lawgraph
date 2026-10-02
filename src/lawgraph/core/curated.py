"""The lists kept by hand, because no official source gives them: ``data/curated/``.

Every list is a JSON file (or a part of one) under ``src/lawgraph/data/curated/``, with an
``about`` that says what it holds and why no source does. ``lawgraph curated`` lists, checks
and changes them (``commands/curated.py``); nothing else writes them, and ``lawgraph check``
checks them all.

What is kept here is data: facts a person decides and may change (a party colour, the
landmark name of a judgment, our key of a ministry). Parser vocabulary (month names, name
particles, the words of a legal form) and facts of a specification (ECLI country codes) stay
in code: they describe how a source is written, not what it says.

A list is a mapping from a key to a value, in order: ``entries`` reads it from the file,
``store`` writes it back. ``problems`` checks it on its own and, given a database, against
it (a faction key that no faction has).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CURATED = Path(__file__).resolve().parents[1] / "data" / "curated"

Entries = dict[str, Any]


@dataclass(frozen=True)
class CuratedList:
    name: str  # as the command line names it: ``party-colors``
    file: str  # under ``data/curated/``
    description: str
    # the part of the file the list is, and how its entries are read from and written to it
    read: Callable[[dict[str, Any]], Entries]
    write: Callable[[dict[str, Any], Entries], None]
    # what is wrong with the entries, on their own
    check: Callable[[Entries], list[str]]
    ordered: bool = False  # the order is part of the list (``--after``)

    @property
    def path(self) -> Path:
        return CURATED / self.file

    def document(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return data

    def entries(self) -> Entries:
        return self.read(self.document())

    def store(self, entries: Entries) -> None:
        document = self.document()
        self.write(document, entries)
        self.path.write_text(
            json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )


# ── Reading and writing the parts of a file ──────────────────────────────────


def _records(part: str, key: str) -> tuple[Callable[..., Entries], Callable[..., None]]:
    """A list of records under *part*, keyed by their field *key*."""

    def read(document: dict[str, Any]) -> Entries:
        return {
            r[key]: {k: v for k, v in r.items() if k != key} for r in document[part]
        }

    def write(document: dict[str, Any], entries: Entries) -> None:
        document[part] = [{key: k, **(v or {})} for k, v in entries.items()]

    return read, write


def _mapping(part: str) -> tuple[Callable[..., Entries], Callable[..., None]]:
    """A mapping under *part*."""

    def read(document: dict[str, Any]) -> Entries:
        return dict(document[part])

    def write(document: dict[str, Any], entries: Entries) -> None:
        document[part] = dict(entries)

    return read, write


def _keys(part: str) -> tuple[Callable[..., Entries], Callable[..., None]]:
    """A list of keys under *part* (the value of an entry is ``None``)."""

    def read(document: dict[str, Any]) -> Entries:
        return dict.fromkeys(document[part])

    def write(document: dict[str, Any], entries: Entries) -> None:
        document[part] = list(entries)

    return read, write


def _outside_courts() -> tuple[Callable[..., Entries], Callable[..., None]]:
    """The courts outside the value list, keyed ``ECHR`` or ``XX:<court>``."""

    def read(document: dict[str, Any]) -> Entries:
        return {
            (f"{c['code']}:{c['court']}" if c.get("court") else c["code"]): {
                k: v for k, v in c.items() if k not in ("code", "court")
            }
            for c in document["courts"]
        }

    def write(document: dict[str, Any], entries: Entries) -> None:
        courts = []
        for key, value in entries.items():
            code, _, court = key.partition(":")
            courts.append(
                {"code": code, **({"court": court} if court else {}), **value}
            )
        document["courts"] = courts

    return read, write


# ── What makes an entry wrong ────────────────────────────────────────────────

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ECLI = re.compile(r"^ECLI:[A-Z]{2}:[A-Z0-9.]{1,7}:\d{4}:[A-Z0-9.]{1,25}$")


CHAMBERS = ("TK", "EK")


def _party_colors(entries: Entries) -> list[str]:
    found = []
    seen: dict[str, str] = {}
    for name, value in entries.items():
        chambers = value.get("chambers") or {}
        # a faction only one Kamer draws (``Fractie-Walenkamp``) has no house colour
        if (chambers and "color" not in value) or _COLOR.match(str(value.get("color"))):
            pass
        else:
            found.append(f"{name}: color {value.get('color')!r} is no #rrggbb")
        found += [
            f"{name}: {chamber} is no Kamer ({', '.join(CHAMBERS)})"
            for chamber in chambers
            if chamber not in CHAMBERS
        ]
        found += [
            f"{name}: {chamber} colour {color!r} is no #rrggbb"
            for chamber, colors in chambers.items()
            for color in (colors if isinstance(colors, list) and colors else [None])
            if not _COLOR.match(str(color))
        ]
        for label in (name, *(value.get("aliases") or [])):
            other = seen.setdefault(label.lower(), name)
            if other != name:
                found.append(f"{label}: a name or alias of both {other} and {name}")
    return found


def _seating_entries() -> tuple[Callable[..., Entries], Callable[..., None]]:
    """The factions of the seating plan, keyed by faction key, written in order of angle."""
    read, write = _records("factions", "key")

    def sorted_write(document: dict[str, Any], entries: Entries) -> None:
        write(
            document,
            dict(sorted(entries.items(), key=lambda e: (e[1] or {}).get("angle", 999))),
        )

    return read, sorted_write


def _seating(entries: Entries) -> list[str]:
    found = []
    for key, value in entries.items():
        angle = (value or {}).get("angle")
        if not re.match(r"^[a-z0-9_]+$", key):
            found.append(f"{key}: not a faction key")
        if not isinstance(angle, int | float) or not 0 <= angle <= 180:
            found.append(f"{key}: angle {angle!r} is no number from 0 to 180")
        if not (value or {}).get("abbreviation"):
            found.append(f"{key}: needs an abbreviation")
        seats = (value or {}).get("seats")
        if not isinstance(seats, int) or seats < 1:
            found.append(f"{key}: seats {seats!r} is no number of seats on the plan")
    total = sum((v or {}).get("seats") or 0 for v in entries.values())
    if total > 150:
        found.append(f"the plan has {total} seats; the Kamer has 150")
    source = LISTS["seating"].document().get("source") or {}
    dated = str(source.get("dated"))
    if not source.get("url") or not re.match(r"^\d{4}-\d{2}-\d{2}$", dated):
        found.append(
            "source: needs the url and the date (dated: YYYY-MM-DD) of the plan"
        )
    return found


def _judgment_names(entries: Entries) -> list[str]:
    found = []
    for ecli, value in entries.items():
        if not _ECLI.match(ecli):
            found.append(f"{ecli}: not an ECLI in upper case")
        names = value.get("names") or []
        if not names or any(not n or n != n.strip() for n in names):
            found.append(f"{ecli}: names must be non-empty and trimmed")
    return found


def _instrument_abbreviations(entries: Entries) -> list[str]:
    from lawgraph.core.identifiers import is_bwb_id, parse_celex

    found = []
    claimed: dict[str, str] = {}
    for law_id, value in entries.items():
        if not (is_bwb_id(law_id) or parse_celex(law_id)) or law_id != law_id.upper():
            found.append(f"{law_id}: not a BWB id or CELEX number in upper case")
        abbreviations = (value or {}).get("abbreviations") or []
        if not abbreviations or any(
            not isinstance(a, str) or not a or a != a.strip() for a in abbreviations
        ):
            found.append(f"{law_id}: abbreviations must be non-empty and trimmed")
            continue
        for abbreviation in abbreviations:
            other = claimed.setdefault(abbreviation.upper(), law_id)
            if other != law_id:
                found.append(
                    f"{abbreviation}: an abbreviation of both {other} and {law_id}"
                )
    return found


def _echr_protocols(entries: Entries) -> list[str]:
    from lawgraph.core.identifiers import is_bwb_id

    found = []
    claimed: dict[str, str] = {}
    for protocol, value in entries.items():
        bwb_id = str((value or {}).get("bwb_id") or "")
        if not re.match(r"^P\d{1,2}$", protocol):
            found.append(f"{protocol}: not a Protocol as HUDOC numbers it (P1)")
        if not is_bwb_id(bwb_id) or bwb_id != bwb_id.upper():
            found.append(f"{protocol}: bwb_id {bwb_id!r} is no BWB id in upper case")
        elif claimed.setdefault(bwb_id, protocol) != protocol:
            found.append(
                f"{bwb_id}: the treaty of both {claimed[bwb_id]} and {protocol}"
            )
        if not (value or {}).get("title"):
            found.append(f"{protocol}: needs the title the BWB gives the treaty")
    return found


def _in(values: set[str], what: str) -> Callable[[Entries], list[str]]:
    def check(entries: Entries) -> list[str]:
        return [
            f"{k}: {v!r} is no {what}" for k, v in entries.items() if v not in values
        ]

    return check


def _decision_kinds(entries: Entries) -> list[str]:
    from lawgraph.core.courts import COURT_KINDS
    from lawgraph.core.judgments import DECISION_KINDS

    return [f"{k}: unknown court_kind" for k in entries if k not in COURT_KINDS] + _in(
        set(DECISION_KINDS), "decision kind"
    )(entries)


def _procedure_kinds(entries: Entries) -> list[str]:
    from lawgraph.core.judgments import DECISION_KINDS

    return _in(set(DECISION_KINDS), "decision kind")(entries)


def _general_courts(entries: Entries) -> list[str]:
    from lawgraph.core.courts import COURT_KINDS

    return [f"{k}: unknown court_kind" for k in entries if k not in COURT_KINDS]


def _outside(entries: Entries) -> list[str]:
    from lawgraph.core.courts import TIERS

    found = []
    for key, value in entries.items():
        if value.get("tier") not in TIERS:
            found.append(f"{key}: tier {value.get('tier')!r} is not one of TIERS")
        if not value.get("name") or not value.get("court_kind"):
            found.append(f"{key}: needs a name and a court_kind")
    return found


def _ministries(entries: Entries) -> list[str]:
    return [
        f"{key}: needs a name"
        for key, value in entries.items()
        if not (value or {}).get("name") or not re.match(r"^[a-z0-9_]+$", key)
    ]


def _ministry_keys(entries: Entries) -> list[str]:
    known = set(LISTS["ministries"].entries())
    return [f"{k}: not a curated ministry" for k in entries if k not in known] + [
        f"{k} -> {v}: not a curated ministry"
        for k, v in entries.items()
        if v not in known
    ]


def _aliases(entries: Entries) -> list[str]:
    known = set(LISTS["ministries"].entries())
    return [
        f"{k} -> {v}: not a curated ministry"
        for k, v in entries.items()
        if v not in known
    ]


_PHASE_PARTS = ("documents", "activities", "decisions")


def _phases(entries: Entries) -> list[str]:
    found = []
    seen: dict[str, str] = {}
    for name, value in entries.items():
        value = value or {}
        if set(value) - set(_PHASE_PARTS):
            found.append(f"{name}: only {', '.join(_PHASE_PARTS)}")
        values = [v for part in _PHASE_PARTS for v in value.get(part) or []]
        if not values:
            found.append(f"{name}: needs a value of the Kamer that marks it")
        for v in values:
            if not isinstance(v, str) or not v or v != v.strip():
                found.append(f"{name}: {v!r} is no trimmed value")
            elif seen.setdefault(v, name) != name:
                found.append(f"{v}: marks both {seen[v]} and {name}")
    return found


# ── The lists ────────────────────────────────────────────────────────────────


def _list(
    name: str,
    file: str,
    description: str,
    part: tuple[Any, Any],
    check: Callable[[Entries], list[str]],
    *,
    ordered: bool = False,
) -> CuratedList:
    return CuratedList(name, file, description, part[0], part[1], check, ordered)


LISTS: dict[str, CuratedList] = {
    c.name: c
    for c in (
        _list(
            "party-colors",
            "party_colors.json",
            "party -> {color, aliases, chambers}: the house colour of a party, its other "
            "names and the colours each Kamer draws it in",
            _records("parties", "name"),
            _party_colors,
        ),
        _list(
            "seating",
            "seating.json",
            "faction key -> {abbreviation, angle, seats}: where it sits, after the TK plan",
            _seating_entries(),
            _seating,
        ),
        _list(
            "phases",
            "phases.json",
            "phase -> {documents, activities, decisions}: the phase bar of a bill, in order",
            _records("phases", "name"),
            _phases,
            ordered=True,
        ),
        _list(
            "judgment-names",
            "judgment_names.json",
            "ECLI -> {names, note}: the names lawyers call landmark judgments by",
            _records("judgments", "ecli"),
            _judgment_names,
        ),
        _list(
            "instrument-abbreviations",
            "instrument_abbreviations.json",
            "BWB id or CELEX -> {abbreviations, note}: how lawyers abbreviate an instrument "
            "whose source gives no abbreviation",
            _records("instruments", "id"),
            _instrument_abbreviations,
        ),
        _list(
            "echr-protocols",
            "echr_protocols.json",
            "HUDOC Protocol (P1) -> {bwb_id, signed, title}: the BWB treaty of a Protocol "
            "to the ECHR, whose articles HUDOC names as P1-1",
            _records("protocols", "protocol"),
            _echr_protocols,
        ),
        _list(
            "decision-kinds",
            "decision_kinds.json",
            "court_kind -> the kind of decision it gives when nothing else tells",
            _mapping("kinds"),
            _decision_kinds,
        ),
        _list(
            "procedure-kinds",
            "decision_kinds.json",
            "procedure (psi:procedure) -> the kind of decision it names",
            _mapping("procedures"),
            _procedure_kinds,
        ),
        _list(
            "general-courts",
            "decision_kinds.json",
            "the kinds of court of every area of law (an uitspraak in administrative law)",
            _keys("general_courts"),
            _general_courts,
        ),
        _list(
            "courts-outside",
            "courts_outside.json",
            "ECHR or XX:<court> -> {name, tier, court_kind, ...}: courts no value list holds",
            _outside_courts(),
            _outside,
        ),
        _list(
            "ministries",
            "ministries.json",
            "ministry key -> {name}, in protocol order",
            _records("ministries", "key"),
            _ministries,
            ordered=True,
        ),
        _list(
            "ministry-successions",
            "ministries.json",
            "ministry key -> the key that followed it, before 2010",
            _mapping("successions"),
            _ministry_keys,
        ),
        _list(
            "ministry-aliases",
            "ministries.json",
            "another way the sources write a ministry -> its key",
            _mapping("aliases"),
            _aliases,
        ),
    )
}


def problems(entries_by_list: dict[str, Entries] | None = None) -> list[str]:
    """What is wrong with every list (``<list>: <problem>``); with *entries_by_list*, those
    entries instead of the files' for the lists it names."""
    found = []
    for name, curated in LISTS.items():
        entries = (entries_by_list or {}).get(name)
        for problem in curated.check(curated.entries() if entries is None else entries):
            found.append(f"{name}: {problem}")
    return found


def place(entries: Entries, key: str, value: Any, after: str | None = None) -> Entries:
    """*entries* with *key* set to *value*: in its place when it is there, else at the end;
    with *after* right after that key (``""``: first)."""
    rest = {k: v for k, v in entries.items() if k != key}
    if after is None:
        return {**entries, key: value} if key in entries else {**rest, key: value}
    if after and after not in rest:
        raise KeyError(f"{after}: not in the list")
    placed: Entries = {} if after else {key: value}
    for k, v in rest.items():
        placed[k] = v
        if k == after:
            placed[key] = value
    return placed
