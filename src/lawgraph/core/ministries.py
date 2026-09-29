"""The ministries of the Netherlands, and the post and ministry a government function names.

A function is written in many ways: ``Nederlands minister van Financiën``, ``minister van
Financiën``, ``Minister van Economische Zaken en Klimaat``, ``Staatssecretaris van Justitie
en Veiligheid - Rechtsbescherming en Gevangeniswezen``. ``classify_function`` reads from
any of them what the post is (``POSTS``) and under which ministry it falls (``MINISTRIES``).

A ministry that no longer exists under its name (``Verkeer en Waterstaat``, ``VROM``,
``Justitie``) has a key of its own and names its ``successor``. A function names a ministry
only when it names one: ``Staatssecretaris van Financiën``. A minister without portfolio
("minister voor Klimaat en Energie") and a state secretary with a portfolio of their own
("Staatssecretaris Herstel en Toeslagen") name none; under which ministry their post falls an
official source has to say (``normalize rijksoverheid``: the Tweede Kamer and the
Staatscourant), not the words of the portfolio.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

POST_PRIME_MINISTER = "minister-president"
POST_DEPUTY_PRIME_MINISTER = "viceminister-president"
POST_MINISTER = "minister"
POST_MINISTER_WITHOUT_PORTFOLIO = "minister_zonder_portefeuille"
POST_STATE_SECRETARY = "staatssecretaris"

# In the order a cabinet lists them: the prime minister first, a state secretary last.
POSTS: tuple[str, ...] = (
    POST_PRIME_MINISTER,
    POST_DEPUTY_PRIME_MINISTER,
    POST_MINISTER,
    POST_MINISTER_WITHOUT_PORTFOLIO,
    POST_STATE_SECRETARY,
)


# Where a fact of the ministry table comes from (``core.ministry_sources``).
Source = Literal["tooi", "rijksoverheid", "curated"]


@dataclass(frozen=True)
class Period:
    """A stretch in which a ministry had its name (``data/ministries.json``)."""

    from_date: str | None  # None where no source dates the start
    until: (
        str | None
    )  # the last day; None while it has the name, or where no source says
    successor: str | None  # the key of the name that followed
    basis: str | None  # the decree the end rests on (a TOOI event)
    source: Source
    successor_source: Source | None = None  # curated, for a succession no source gives


@dataclass(frozen=True)
class Ministry:
    key: str
    name: str
    abbreviation: str | None = None
    tooi: str | None = None  # the TOOI code of the organisation: mnre1045
    periods: tuple[Period, ...] = ()

    @property
    def until(self) -> str | None:
        """The last day it had this name; ``None`` while it has it."""
        return self.periods[-1].until if self.periods else None

    @property
    def successor(self) -> str | None:
        """The key of the name that followed its last period."""
        return self.periods[-1].successor if self.periods else None


DATA = Path(__file__).resolve().parents[1] / "data" / "ministries.json"
CURATED = Path(__file__).resolve().parents[1] / "data" / "curated" / "ministries.json"


def load_ministries(path: Path = DATA) -> tuple[Ministry, ...]:
    """The ministries of ``data/ministries.json``, in protocol order."""
    entries = json.loads(path.read_text(encoding="utf-8"))["ministries"]
    return tuple(
        Ministry(
            key=m["key"],
            name=m["name"],
            abbreviation=m.get("abbreviation"),
            tooi=m.get("tooi"),
            periods=tuple(
                Period(
                    from_date=p.get("from"),
                    until=p.get("until"),
                    successor=p.get("successor"),
                    basis=p.get("basis"),
                    source=p["source"],
                    successor_source=p.get("successor_source"),
                )
                for p in m["periods"]
            ),
        )
        for m in entries
    )


# The ministries in protocol order (the order of the Rijksoverheid), each followed by the
# names it succeeded; a former name takes the place of its successor.
MINISTRIES: tuple[Ministry, ...] = load_ministries()
MINISTRY_BY_KEY: dict[str, Ministry] = {m.key: m for m in MINISTRIES}


def _plain(text: str | None) -> str:
    """*text* lower case, without accents, punctuation and doubled spaces."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def protocol_rank(key: str | None) -> int:
    """The place of a ministry in protocol order (a former ministry right after its
    successor); after every ministry for none."""
    return _RANK.get(key or "", len(MINISTRIES))


_RANK = {m.key: i for i, m in enumerate(MINISTRIES)}


# The name of every ministry, and the other ways the sources write one ("VROM" without
# "beheer", the Landbouw ministries without commas; ``data/curated/ministries.json``).
_NAMES: dict[str, str] = {
    **{_plain(m.name): m.key for m in MINISTRIES},
    # the abbreviations TOOI gives
    **{_plain(m.abbreviation): m.key for m in MINISTRIES if m.abbreviation},
    # the other ways the sources write a name (curated)
    **{
        _plain(alias): key
        for alias, key in json.loads(CURATED.read_text(encoding="utf-8"))[
            "aliases"
        ].items()
    },
}


def ministry_named(text: str | None) -> str | None:
    """The key of the ministry whose name *text* is, exactly; ``None`` for a portfolio."""
    return _NAMES.get(_plain(text))


_PREFIXES = re.compile(r"^(?:nederlandse?|de)\s+")
_OF_THE_NETHERLANDS = re.compile(r"\s+van nederland$")


def _head(text: str | None) -> str:
    """*text* before a dash: ``Justitie en Veiligheid - Rechtsbescherming`` names the
    ministry before it and the portfolio within it after it."""
    return re.split(r"\s+[-–]\s+", text or "", maxsplit=1)[0]


def _holds(period: Period, day: str) -> bool:
    return (period.from_date is None or period.from_date <= day) and (
        period.until is None or day <= period.until
    )


def current_on(key: str | None, on: str | None) -> str | None:
    """*key*, or the name that followed it when it no longer had its name *on* that day: a
    later source that writes ``Binnenlandse Zaken`` means Binnenlandse Zaken en
    Koninkrijksrelaties. A day in one of its periods, or before the first, keeps the name
    as written; after a period, its successor (and so on)."""
    seen: set[str] = set()
    while key in MINISTRY_BY_KEY and on and key not in seen:
        seen.add(key)
        periods = MINISTRY_BY_KEY[key].periods
        if any(_holds(p, on) for p in periods):
            break
        ended = [p for p in periods if p.until and p.until < on]
        if not ended:
            break
        following = max(ended, key=lambda p: p.until or "").successor
        if not following:
            break
        key = following
    return key


def ministry_of(text: str | None, *, on: str | None = None) -> str | None:
    """The key of the ministry *text* names (``Economische Zaken en Klimaat``, ``Justitie en
    Veiligheid - Rechtsbescherming``: the part before the dash), as it was named on the day
    *on*; ``None`` for a portfolio that names no ministry (``Klimaat en Energie``): which
    ministry that falls under an official source has to say (``normalize rijksoverheid``)."""
    plain = _plain(_head(text))
    return current_on(_NAMES[plain], on) if plain in _NAMES else None


def classify_function(
    function: str | None, *, on: str | None = None
) -> tuple[str | None, str | None]:
    """``(post, ministry)`` of a function as a source writes it on the day *on*; ``None``
    for what it does not say. The minister-president heads Algemene Zaken; a
    viceminister-president is also a minister, whose ministry that post does not name."""
    plain = _OF_THE_NETHERLANDS.sub("", _PREFIXES.sub("", _plain(_head(function))))
    if plain.startswith(("viceminister president", "vice minister president")):
        return POST_DEPUTY_PRIME_MINISTER, None
    if plain.startswith("minister president"):
        return POST_PRIME_MINISTER, "az"
    if plain.startswith("minister zonder portefeuille"):
        return POST_MINISTER_WITHOUT_PORTFOLIO, None
    for prefix, post in (
        ("staatssecretaris", POST_STATE_SECRETARY),
        ("minister voor", POST_MINISTER_WITHOUT_PORTFOLIO),
        ("minister", POST_MINISTER),
    ):
        if plain.startswith(prefix):
            portfolio = re.sub(
                r"^(?:van|voor)\b", "", plain.removeprefix(prefix).strip()
            )
            if post == POST_MINISTER_WITHOUT_PORTFOLIO:
                return post, None
            return post, ministry_of(portfolio, on=on)
    return None, None
