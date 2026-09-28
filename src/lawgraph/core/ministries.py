"""The ministries of the Netherlands, and the post and ministry a government function names.

A function is written in many ways: ``Nederlands minister van Financiën``, ``minister van
Financiën``, ``Minister van Economische Zaken en Klimaat``, ``Staatssecretaris van Justitie
en Veiligheid - Rechtsbescherming en Gevangeniswezen``. ``classify_function`` reads from
any of them what the post is (``POSTS``) and under which ministry it falls (``MINISTRIES``).

A ministry that no longer exists under its name (``Verkeer en Waterstaat``, ``VROM``,
``Justitie``) has a key of its own and names its ``successor``. A minister without
portfolio ("minister voor …") and a state secretary belong to the ministry their post is
placed under: the Minister voor Klimaat en Energie to Economische Zaken en Klimaat, the
Minister voor Basis- en Voortgezet Onderwijs to Onderwijs, Cultuur en Wetenschap. Which
ministry that is follows from the words of the portfolio (``_PORTFOLIO_RULES``), since the
sources name only the portfolio.
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
Source = Literal["tooi", "rijksoverheid", "hand"]


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
    successor_source: Source | None = None  # hand, for a succession no source gives


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
# "beheer", the Landbouw ministries without commas).
_NAMES: dict[str, str] = {
    **{_plain(m.name): m.key for m in MINISTRIES},
    _plain("Volkshuisvesting, Ruimtelijke Ordening en Milieu"): "vrom",
    _plain("Landbouw Visserij Voedselzekerheid en Natuur"): "lvvn",
    _plain("Algemene Oorlogvoering"): "aok",
    _plain("Algemene Oorlogsvoering"): "aok",
    _plain("Onderwijs, Cultuur en Wetenschappen"): "ocw",
    # the abbreviations TOOI gives, and those the sources use beside them
    **{_plain(m.abbreviation): m.key for m in MINISTRIES if m.abbreviation},
    **{
        _plain(short): key
        for short, key in (
            ("OCenW", "ocw"),
            ("VenW", "venw"),
            ("WVC", "wvc"),
        )
    },
}


def ministry_named(text: str | None) -> str | None:
    """The key of the ministry whose name *text* is, exactly; ``None`` for a portfolio."""
    return _NAMES.get(_plain(text))


# A portfolio that is no ministry of its own: the ministry its post is placed under, by the
# words it contains. The first rule that matches wins, so a narrower rule comes first.
_PORTFOLIO_RULES: tuple[tuple[str, str], ...] = (
    (r"\bwonen wijken\b", "vrom"),
    (r"\bklimaat en energie\b|\bmijnbouw\b", "ezk"),
    (r"\bdigitale economie\b", "ez"),
    (r"\bontwikkeling|\bbuitenlandse handel\b|\beuropese zaken\b", "bz"),
    (r"\basiel\b|\bmigratie\b", "aenm"),
    (
        r"\bvreemdelingen|\bjeugdbescherming\b|\breclassering\b|\brechtsbescherming\b"
        r"|\bgevangeniswezen\b|\bjustitie\b|\bveiligheid\b",
        "jenv",
    ),
    (r"\btoeslagen\b|\bdouane\b|\bfiscaliteit\b|\bbelastingdienst\b", "fin"),
    (
        r"\bkoninkrijk|\bantilliaanse\b|\bbestuurlijke vernieuwing\b|\brijksdienst\b"
        r"|\bdigitalisering\b|\bslagvaardige overheid\b|\binlichtingen\b"
        r"|\bgrote steden\b|\bwonen\b|\bvolkshuisvesting\b|\bherstel groningen\b"
        r"|\bbinnenlandse zaken\b",
        "bzk",
    ),
    (
        r"\bonderwijs\b|\bwetenschap|\bmedia\b|\bemancipatie\b|\bcultuur\b",
        "ocw",
    ),
    (r"\bjeugd\b|\bgezin\b|\bzorg\b|\bsport\b|\bvolksgezondheid\b", "vws"),
    (r"\bwerk\b|\bparticipatie\b|\bpensioen|\bsociale zaken\b", "szw"),
    (r"\bnatuur\b|\bstikstof\b|\blandbouw\b|\bvisserij\b", "lvvn"),
    (r"\bmilieu\b|\bwaterstaat\b|\binfrastructuur\b", "ienw"),
    (r"\bdefensie\b", "def"),
    (r"\bfinancien\b", "fin"),
    (r"\beconomische zaken\b|\bklimaat\b", "ezk"),
)

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


def ministry_of(
    portfolio: str | None, *, on: str | None = None, named: bool = True
) -> str | None:
    """The key of the ministry a portfolio (``Economische Zaken en Klimaat``, ``Klimaat en
    Energie``, ``Justitie en Veiligheid - Rechtsbescherming``) falls under on the day
    *on*, or ``None``. With *named* false, the portfolio is never a ministry itself: the
    portfolio of a minister without portfolio ("minister voor Volkshuisvesting") is placed
    under a ministry, even when a ministry had that name at another time."""
    plain = _plain(_head(portfolio))
    if not plain:
        return None
    if named and plain in _NAMES:
        return current_on(_NAMES[plain], on)
    for pattern, key in _PORTFOLIO_RULES:
        if re.search(pattern, plain):
            return current_on(key, on)
    return None


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
            named = post != POST_MINISTER_WITHOUT_PORTFOLIO
            return post, ministry_of(portfolio, on=on, named=named)
    return None, None
