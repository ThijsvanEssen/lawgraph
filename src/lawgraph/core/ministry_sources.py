"""The ministries from the official sources: TOOI since 2010, the cabinet pages before.

``data/ministries.json`` holds the ministries ``core.ministries`` reads. ``build_ministries``
makes it from what the sources say, with the curated keys, order and successions:

- **TOOI** (``rwc_ministeries_compleet``, KOOP): every ministry since about 2010 with its
  code (``mnre1045``), abbreviation, begin and end, its former names (``HistorischeVersie``
  with the last day of each), and the events between them: an ``Oprichting``, a
  ``Samenvoeging`` (the merged ministries are succeeded by the new one), an ``Afsplitsing``,
  a ``Toestandswijziging`` (a new name), each with the Staatscourant decree it rests on.
  One name can come back: ``Economische Zaken`` is a ministry until 2010, a name of
  ``mnre1045`` from 2013 to 2017 and again from 2024 to 2026. So a ministry key (one per
  name) has **periods**, each with its own end, successor and basis.
- **The Rijksoverheid cabinet pages** for the names before TOOI: a name the posts use gets a
  period from its first post; it ends the day before its successor's first post where its
  last post ends that day (a handover the pages show), else its end stays unknown.

What no source gives is curated in ``data/curated/ministries.json``: our key of each name,
the protocol order, a succession before 2010 (Oorlog and Marine by Defensie) and the other
ways the sources write a name. A curated name no source names is left out.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

SOURCE_TOOI = "tooi"
SOURCE_RIJKSOVERHEID = "rijksoverheid"
SOURCE_CURATED = "curated"


def _plain(text: str | None) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _day(value: str | None) -> str | None:
    return value[:10] if value else None


def _shift(day: str, days: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


def _values(item: dict[str, Any], name: str) -> list[str]:
    found = []
    for key, values in item.items():
        if re.split(r"[/#]", key)[-1] == name:
            found += [v.get("@value", v.get("@id")) for v in values]
    return [v for v in found if v is not None]


def _one(item: dict[str, Any], name: str) -> str | None:
    values = _values(item, name)
    return values[0] if values else None


def _types(item: dict[str, Any]) -> set[str]:
    return {re.split(r"[/#]", t)[-1] for t in item.get("@type", [])}


def _short_id(uri: str | None) -> str:
    return uri.rsplit("/", 1)[-1] if uri else ""


def ministry_name(label: str | None) -> str:
    """``Economische Zaken`` of ``ministerie van Economische Zaken``."""
    return re.sub(
        r"^ministerie\s+(?:van|voor)\s+", "", (label or "").strip(), flags=re.I
    )


def _decrees(items: list[dict[str, Any]]) -> dict[str, str]:
    """TOOI id of a ministry or a former name -> the decree of the event that ended it."""
    ended = {}
    for event in items:
        basis = _one(event, "heeftJuridischeGrondslag")
        if basis:
            for gone in _values(event, "invalidated"):
                ended[gone] = basis
    return ended


def tooi_names(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every name a TOOI ministry had: ``{tooi, name, abbreviation, from, until, basis}``,
    oldest first per ministry. ``from`` and ``until`` are ``None`` where TOOI does not
    date them; ``basis`` is the decree of the event that ended the name."""
    ministries = {i["@id"]: i for i in items if _types(i) == {"Ministerie"}}
    versions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if {"HistorischeVersie", "Ministerie"} <= _types(item):
            of = _one(item, "specializationOf")
            if of:
                versions[of].append(item)
    ended = _decrees(items)
    names = []
    for uri, ministry in ministries.items():
        start = _day(_one(ministry, "begindatum"))
        for version in sorted(
            versions[uri], key=lambda v: _one(v, "einddatumHV") or ""
        ):
            until = _day(_one(version, "einddatumHV"))
            names.append(_name(uri, version, start, until, ended.get(version["@id"])))
            start = _shift(until, 1) if until else None
        names.append(
            _name(
                uri, ministry, start, _day(_one(ministry, "einddatum")), ended.get(uri)
            )
        )
    return names


def _name(
    uri: str,
    item: dict[str, Any],
    start: str | None,
    until: str | None,
    basis: str | None,
) -> dict[str, Any]:
    return {
        "tooi": _short_id(uri),
        "name": ministry_name(_one(item, "label")),
        "abbreviation": _one(item, "afkorting"),
        "from": start,
        "until": until,
        "basis": basis,
    }


def tooi_mergers(items: list[dict[str, Any]]) -> dict[str, str]:
    """TOOI id of a ministry that was merged -> the id of the ministry it went into."""
    merged = {}
    for event in items:
        if "Samenvoeging" in _types(event):
            for made in _values(event, "generated"):
                for gone in _values(event, "invalidated"):
                    merged[_short_id(gone)] = _short_id(made)
    return merged


def _name_on(names: list[dict[str, Any]], tooi: str, day: str) -> dict[str, Any] | None:
    return next(
        (
            n
            for n in names
            if n["tooi"] == tooi
            and (n["from"] is None or n["from"] <= day)
            and (n["until"] is None or day <= n["until"])
        ),
        None,
    )


def _key_for(name: dict[str, Any], by_name: dict[str, str], taken: set[str]) -> str:
    """The key of a name: the one the table has for it, else its abbreviation in lower
    case (``aenm`` of ``AenM``)."""
    known = by_name.get(_plain(name["name"]))
    if known:
        return known
    key = _plain(name["abbreviation"] or name["name"]).replace(" ", "") or "ministerie"
    while key in taken:
        key += "_"
    taken.add(key)
    by_name[_plain(name["name"])] = key
    return key


def tooi_periods(
    items: list[dict[str, Any]], by_name: dict[str, str], taken: set[str]
) -> dict[str, dict[str, Any]]:
    """Key -> ``{name, abbreviation, tooi, periods}`` of every name TOOI knows. A name that
    ends is succeeded by the next name of its ministry, or, when its ministry was merged,
    by the name the ministry it went into had on the next day."""
    names = tooi_names(items)
    mergers = tooi_mergers(items)
    keys = [_key_for(n, by_name, taken) for n in names]
    found: dict[str, dict[str, Any]] = {}
    for name, key in zip(names, keys, strict=True):
        successor = None
        if name["until"]:
            day = _shift(name["until"], 1)
            following = _name_on(names, mergers.get(name["tooi"], name["tooi"]), day)
            if following:
                successor = keys[names.index(following)]
        entry = found.setdefault(
            key,
            {
                "name": name["name"],
                "abbreviation": name["abbreviation"],
                "tooi": name["tooi"],
                "periods": [],
            },
        )
        entry["periods"].append(
            {
                "from": name["from"],
                "until": name["until"],
                "successor": successor,
                "basis": name["basis"],
                "source": SOURCE_TOOI,
            }
        )
    for entry in found.values():
        entry["periods"].sort(key=lambda p: p["from"] or "")
    return found


def page_spans(
    cabinets: Iterable[dict[str, Any]],
) -> dict[str, tuple[str, str | None, set[str]]]:
    """Ministry key -> ``(first start, last end, every start)`` of the posts under it on the
    pages; the last end ``None`` while a post under it is held."""
    spans: dict[str, tuple[str, str | None, set[str]]] = {}
    for cabinet in cabinets:
        for post in cabinet["posts"]:
            key = post.get("ministry")
            if not key:
                continue
            start, end = post["from_date"], post["to_date"]
            starts = {start}
            if key in spans:
                first, last, starts = spans[key]
                starts.add(start)
                start = min(first, start)
                end = None if last is None or end is None else max(last, end)
            spans[key] = (start, end, starts)
    return spans


def page_period(
    key: str,
    successor: str | None,
    spans: dict[str, tuple[str, str | None, set[str]]],
) -> dict[str, Any] | None:
    """The period the pages show for a name before TOOI: from its first post, until the
    day before a post under its successor begins on the day its last post ends (a
    handover the pages show); else the end stays unknown."""
    if key not in spans:
        return None
    first, last, _ = spans[key]
    handover = bool(last and successor in spans and last in spans[successor or ""][2])
    return {
        "from": first,
        "until": _shift(last, -1) if handover and last else None,
        "successor": successor,
        "basis": None,
        "source": SOURCE_RIJKSOVERHEID,
    }


def build_ministries(
    curated: dict[str, Any],
    tooi: list[dict[str, Any]],
    cabinets: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """``(table, dropped)``: the ministry table from the sources, and the curated keys no
    source names (so left out).

    *curated* is ``data/curated/ministries.json``: the keys in protocol order and the
    successions before TOOI; *tooi* the items of the TOOI value list; *cabinets* those of
    ``core.cabinet_sources``. A name TOOI knows gets its periods from TOOI; one it does not
    know, from the posts under it on the cabinet pages, with the curated successor
    (``successor_source`` ``curated``); one neither names is dropped. A TOOI name the curated
    list lacks comes at the end, keyed by its abbreviation."""
    order = curated["ministries"]
    successions = curated.get("successions") or {}
    by_name = {_plain(m["name"]): m["key"] for m in order}
    taken = {m["key"] for m in order}
    official = tooi_periods(tooi, by_name, taken)
    spans = page_spans(cabinets)
    table, dropped = [], []
    for entry in order:
        key = entry["key"]
        if key in official:
            table.append({"key": key, **official.pop(key)})
            continue
        period = page_period(key, successions.get(key), spans)
        if period is None:
            dropped.append(key)
            continue
        if period["successor"]:
            period["successor_source"] = SOURCE_CURATED
        table.append(
            {
                "key": key,
                "name": entry["name"],
                "abbreviation": None,
                "tooi": None,
                "periods": [period],
            }
        )
    table += [{"key": key, **entry} for key, entry in official.items()]
    return table, dropped
