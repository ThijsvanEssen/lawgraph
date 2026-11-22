"""The court map per municipality: the arrondissement and ressort of each municipality, as the
CBS gives them per year, checked against the text of the Wet op de rechterlijke indeling.

The CBS table "Gebieden in Nederland" (``retrieve cbs``) holds per municipality its
arrondissement and ressort; its columns are found by the title of their group, as their keys
differ per year. The Wet op de rechterlijke indeling (RI, ``BWBR0002080``) draws the same map in
words: articles 4 to 13 each give an arrondissement the provinces and the municipalities it
covers ("Het arrondissement Noord-Holland omvat het grondgebied van de gemeenten Alkmaar, …"),
articles 14 to 17 each give a ressort its arrondissementen. ``check`` says per municipality
whether the text puts it where the CBS does. The text in the graph is that of today, so only
the table of this year is checked; a municipality the text does not name as the CBS does is a
gap that is shown, never corrected by hand.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.core.xml import collapse_ws

# The present court map: eleven rechtbanken and four gerechtshoven since 2013.
FIRST_YEAR = 2013
LAW_BWB_ID = "BWBR0002080"

# The groups of columns of the CBS table, by their title.
MUNICIPALITIES = "Codes en namen van gemeenten"
DISTRICTS = "Arrondissementen (rechtsgebieden)"
CIRCUITS = "Ressorten (rechtsgebieden)"
PROVINCES = "Provincies"
# What the CBS writes in a column that has no value (yet).
UNFILLED = ("", ".")
GROUPS = (MUNICIPALITIES, DISTRICTS, CIRCUITS, PROVINCES)

Check = Literal["agrees", "differs", "not_in_text"]

_DISTRICT = re.compile(
    r"Het arrondissement (?P<name>[^.]+?) omvat het grondgebied van (?P<body>[^.]+)\."
)
_CIRCUIT = re.compile(
    r"Het ressort (?P<name>[^.]+?) omvat de volgende arrondissementen: (?P<body>[^.]+)\."
)
_PROVINCES = re.compile(r"provincies? (?P<list>.+?)(?: alsmede |$)")
_MUNICIPALITIES = re.compile(r"gemeenten (?P<list>.+)$")
# The province the CBS adds to a name two municipalities share: "Bergen (NH.)".
_SUFFIX = re.compile(r"\s*\([^)]*\)$")


@dataclass(frozen=True)
class Municipality:
    """A municipality of one year's table, with its areas as the CBS names them."""

    code: str
    name: str
    province: str
    district: str
    district_code: str
    circuit: str
    circuit_code: str


@dataclass(frozen=True)
class LawDistrict:
    """An arrondissement as an article of the RI draws it."""

    article: str
    provinces: tuple[str, ...]
    municipalities: str  # the list as the text writes it: a name may hold a comma


@dataclass(frozen=True)
class Law:
    """The map the text of the RI draws: arrondissement and ressort by name."""

    districts: dict[str, LawDistrict]
    circuits: dict[
        str, tuple[str, tuple[str, ...]]
    ]  # name: (article, arrondissementen)


def plain(name: str) -> str:
    """*name* to compare: the curly quotes straight, "Gerechtshof " and the province the CBS
    adds left out, spaces single."""
    name = name.replace("’", "'").replace("‘", "'")
    name = _SUFFIX.sub("", name).removeprefix("Gerechtshof ")
    return collapse_ws(name)


def read_table(payload: Mapping[str, Any]) -> list[Municipality]:
    """The municipalities of a stored table (``{properties, rows}``) that have an
    arrondissement and a ressort: the CBS writes "." where a year is not filled in yet, and
    that is no map. Raises when a group of ``GROUPS`` or its code or name is missing: the
    table has changed."""
    properties = payload.get("properties") or []
    titles = {
        p.get("ID"): p.get("Title") for p in properties if p.get("Type") == "TopicGroup"
    }
    keys: dict[tuple[str, str], str] = {}
    for p in properties:
        group = titles.get(p.get("ParentID"))
        if (
            p.get("Type") == "Topic"
            and group in GROUPS
            and p.get("Title") in ("Code", "Naam")
        ):
            keys[(group, p["Title"])] = p["Key"]
    missing = [
        f"{g} {t}" for g in GROUPS for t in ("Code", "Naam") if (g, t) not in keys
    ]
    if missing:
        raise ValueError(f"the CBS table has no column {', '.join(missing)}")

    def value(row: Mapping[str, Any], group: str, title: str) -> str:
        return str(row.get(keys[(group, title)]) or "").strip()

    municipalities = [
        Municipality(
            code=value(row, MUNICIPALITIES, "Code"),
            name=value(row, MUNICIPALITIES, "Naam"),
            province=value(row, PROVINCES, "Naam"),
            district=value(row, DISTRICTS, "Naam"),
            district_code=value(row, DISTRICTS, "Code"),
            circuit=value(row, CIRCUITS, "Naam"),
            circuit_code=value(row, CIRCUITS, "Code"),
        )
        for row in payload.get("rows") or []
        if value(row, MUNICIPALITIES, "Code")
    ]
    return [
        m
        for m in municipalities
        if m.district not in UNFILLED and m.circuit not in UNFILLED
    ]


def _items(text: str, separator: str) -> tuple[str, ...]:
    """The items of a list in words: "A, B en C" (*separator* ", ") or "A; B" ("; ")."""
    head, _, last = text.rpartition(" en ") if separator == ", " else ("", "", "")
    parts = (head.split(separator) + [last]) if head else text.split(separator)
    return tuple(plain(p) for p in parts if p.strip())


def read_law(articles: Mapping[str, str]) -> Law:
    """The map of the RI from the text of its articles, by article number."""
    districts: dict[str, LawDistrict] = {}
    circuits: dict[str, tuple[str, tuple[str, ...]]] = {}
    for number, text in articles.items():
        line = collapse_ws(text)
        if m := _DISTRICT.search(line):
            body = m["body"]
            provinces = _PROVINCES.search(body) if "provincie" in body else None
            listed = _MUNICIPALITIES.search(body)
            districts[plain(m["name"])] = LawDistrict(
                article=number,
                provinces=_items(provinces["list"], ", ") if provinces else (),
                municipalities=plain(listed["list"]) if listed else "",
            )
        elif m := _CIRCUIT.search(line):
            circuits[plain(m["name"])] = (number, _items(m["body"], "; "))
    return Law(districts, circuits)


def _named(municipalities: str, name: str) -> bool:
    """Whether the list *municipalities* names *name* whole ("Nuenen, Gerwen en
    Nederwetten" holds a comma itself)."""
    return bool(
        re.search(rf"(?:^|, | en ){re.escape(name)}(?:,| en |$)", municipalities)
    )


def law_district(law: Law, municipality: Municipality, shared: bool) -> str | None:
    """The arrondissement the text puts *municipality* in; None when it puts it in none or
    in more than one. A name another municipality of the year also bears (*shared*:
    Bergen in Noord-Holland and in Limburg) is taken from the province the text names whole
    first, as the text does not say which Bergen it means."""
    name = plain(municipality.name)
    province = plain(municipality.province)
    named = [d for d, x in law.districts.items() if _named(x.municipalities, name)]
    whole = [d for d, x in law.districts.items() if province in x.provinces]
    found = (whole or named) if shared else (named or whole)
    return found[0] if len(found) == 1 else None


def law_circuit(law: Law, district: str) -> tuple[str, str] | None:
    """``(name, article)`` of the ressort the text puts the arrondissement *district* in."""
    for name, (article, districts) in law.circuits.items():
        if plain(district) in districts:
            return name, article
    return None


def check(found: str | None, given: str) -> Check:
    """How the text compares to the CBS: the same area, another, or none."""
    if found is None:
        return "not_in_text"
    return "agrees" if found == plain(given) else "differs"


def rows(
    year: int, municipalities: Iterable[Municipality], law: Law, checked: bool
) -> list[dict[str, Any]]:
    """The rows of ``lg_court_districts`` of one *year*, each with the articles of the RI
    that draw its arrondissement and ressort. *checked* (the year of the text the graph
    holds): each says how the text compares; else the checks stay null."""
    municipalities = list(municipalities)
    names = Counter(plain(m.name) for m in municipalities)
    out: list[dict[str, Any]] = []
    for m in municipalities:
        given = law.districts.get(plain(m.district))
        circuit = law_circuit(law, m.district)
        row: dict[str, Any] = {
            "year": year,
            "municipality_code": m.code,
            "municipality": m.name,
            "province": m.province,
            "district": m.district,
            "district_code": m.district_code,
            "circuit": m.circuit,
            "circuit_code": m.circuit_code,
            "district_article": given.article if given else None,
            "circuit_article": circuit[1] if circuit else None,
            "law_district": None,
            "district_check": None,
            "circuit_check": None,
        }
        if checked:
            found = law_district(law, m, names[plain(m.name)] > 1)
            row |= {
                "law_district": found,
                "district_check": check(found, m.district),
                "circuit_check": check(circuit[0] if circuit else None, m.circuit),
            }
        out.append(row)
    return out
