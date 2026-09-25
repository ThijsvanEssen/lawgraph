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

import re
import unicodedata
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Ministry:
    key: str
    name: str
    successor: str | None = None  # the key of the ministry that took over its work
    until: str | None = None  # the last day it had this name, for a former ministry


# The ministries in protocol order (the order of the Rijksoverheid), each followed by the
# ministries it succeeded; a former ministry takes the place of its successor.
MINISTRIES: tuple[Ministry, ...] = (
    Ministry("az", "Algemene Zaken"),
    Ministry("aok", "Algemene Oorlogvoering van het Koninkrijk", "az"),
    Ministry("bz", "Buitenlandse Zaken"),
    Ministry("jenv", "Justitie en Veiligheid"),
    Ministry("venj", "Veiligheid en Justitie", "jenv", "2017-10-25"),
    Ministry("justitie", "Justitie", "venj", "2010-10-13"),
    Ministry("bzk", "Binnenlandse Zaken en Koninkrijksrelaties"),
    Ministry("biza", "Binnenlandse Zaken", "bzk", "1998-08-02"),
    Ministry(
        "bzbpbo",
        "Binnenlandse Zaken, Bezitsvorming en Publiekrechtelijke Bedrijfsorganisatie",
        "biza",
    ),
    Ministry("ocw", "Onderwijs, Cultuur en Wetenschap"),
    Ministry("ow", "Onderwijs en Wetenschappen", "ocw", "1994-08-21"),
    Ministry("okw", "Onderwijs, Kunsten en Wetenschappen", "ow", "1965-04-13"),
    Ministry("fin", "Financiën"),
    Ministry("def", "Defensie"),
    Ministry("oorlog", "Oorlog", "def"),
    Ministry("marine", "Marine", "def"),
    Ministry("ienw", "Infrastructuur en Waterstaat"),
    Ministry("ienm", "Infrastructuur en Milieu", "ienw", "2017-10-25"),
    Ministry("venw", "Verkeer en Waterstaat", "ienm", "2010-10-13"),
    Ministry("vene", "Verkeer en Energie", "venw", "1946-07-02"),
    Ministry("owen", "Openbare Werken en Wederopbouw", "venw", "1947-01-01"),
    Ministry("opw", "Openbare Werken", "venw"),
    Ministry("ez", "Economische Zaken"),
    Ministry("ezk", "Economische Zaken en Klimaat", "ez", "2024-07-01"),
    Ministry("eli", "Economische Zaken, Landbouw en Innovatie", "ez", "2012-11-04"),
    Ministry("hn", "Handel en Nijverheid", "ez"),
    Ministry("ahn", "Arbeid, Handel en Nijverheid", "hn"),
    Ministry("kgg", "Klimaat en Groene Groei"),
    Ministry("lvvn", "Landbouw, Visserij, Voedselzekerheid en Natuur"),
    Ministry("lnv", "Landbouw, Natuur en Voedselkwaliteit", "lvvn", "2024-07-01"),
    Ministry("lnbv", "Landbouw, Natuurbeheer en Visserij", "lnv", "2003-05-26"),
    Ministry("lenv", "Landbouw en Visserij", "lnbv", "1989-11-06"),
    Ministry("lvv", "Landbouw, Visserij en Voedselvoorziening", "lenv"),
    Ministry("szw", "Sociale Zaken en Werkgelegenheid"),
    Ministry("sz", "Sociale Zaken", "szw", "1981-09-10"),
    Ministry("szv", "Sociale Zaken en Volksgezondheid", "sz"),
    Ministry("arbeid", "Arbeid", "sz"),
    Ministry("vws", "Volksgezondheid, Welzijn en Sport"),
    Ministry("wvc", "Welzijn, Volksgezondheid en Cultuur", "vws", "1994-08-21"),
    Ministry("vm", "Volksgezondheid en Milieuhygiëne", "wvc", "1982-11-03"),
    Ministry("crm", "Cultuur, Recreatie en Maatschappelijk Werk", "wvc", "1982-11-03"),
    Ministry("mw", "Maatschappelijk Werk", "crm"),
    Ministry("vro", "Volkshuisvesting en Ruimtelijke Ordening"),
    Ministry("vb", "Volkshuisvesting en Bouwnijverheid", "vro"),
    Ministry("wv", "Wederopbouw en Volkshuisvesting", "vb"),
    Ministry(
        "vrom",
        "Volkshuisvesting, Ruimtelijke Ordening en Milieubeheer",
        "ienm",
        "2010-10-13",
    ),
    Ministry("aenm", "Asiel en Migratie"),
    # Ministries without a successor of their name.
    Ministry("scheepvaart", "Scheepvaart"),
    Ministry("ogd", "Overzeese Gebiedsdelen"),
    Ministry("uor", "Uniezaken en Overzeese Rijksdelen"),
    Ministry("or", "Overzeese Rijksdelen"),
    Ministry("zo", "Zaken Overzee"),
)
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
    # the abbreviations the sources use for a ministry
    **{
        _plain(short): key
        for short, key in (
            ("AZ", "az"),
            ("BZ", "bz"),
            ("JenV", "jenv"),
            ("BZK", "bzk"),
            ("OCW", "ocw"),
            ("OCenW", "ocw"),
            ("IenW", "ienw"),
            ("IenM", "ienm"),
            ("VenW", "venw"),
            ("EZ", "ez"),
            ("EZK", "ezk"),
            ("LNV", "lnv"),
            ("SZW", "szw"),
            ("VWS", "vws"),
            ("WVC", "wvc"),
            ("VROM", "vrom"),
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


def current_on(key: str | None, on: str | None) -> str | None:
    """*key*, or the ministry that succeeded it when it no longer had its name *on* that
    day: a later source that writes ``Binnenlandse Zaken`` means Binnenlandse Zaken en
    Koninkrijksrelaties."""
    seen: set[str] = set()
    while key in MINISTRY_BY_KEY and on and key not in seen:
        seen.add(key)
        ministry = MINISTRY_BY_KEY[key]
        if not ministry.until or on <= ministry.until or not ministry.successor:
            break
        key = ministry.successor
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
