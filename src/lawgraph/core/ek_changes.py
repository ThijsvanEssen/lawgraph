"""The changes in the composition of the Eerste Kamer as its site tells them, read by pattern.

Two kinds of page say them, both in prose:

- ``/personele_mutaties`` lists, per term, the news items about the members: an item is a
  date, a headline (``Senator Van Gasteren uit BBB-fractie``) and a page of a few sentences;
- the page of a faction tells its own history: ``vanaf <day> vertegenwoordigd``, ``Van <day>
  tot <day> was de naam van de fractie X``, ``waren er twee fracties, een voor A en een voor
  B``.

Of each a ``Change`` is read: what it does to the seats of the factions (a member sworn in,
gone, from one faction to another; a faction renamed or two merged), the day it takes
effect, and the source's own words. A change is read from the text (``basis`` ``tekst``),
never typed: what no pattern reads is no change, and a text that speaks of the composition
but that no pattern reads is reported (``unread``)."""

from __future__ import annotations

import datetime as dt
import html as html_lib
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

MONTHS = {
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}
_MONTH = "|".join(MONTHS)
# "11 juli 2023", "5 juli" (the year of the item), "1 februari"
_DAY = rf"(\d{{1,2}}) ({_MONTH})(?: (\d{{4}}))?"
_ITEM = re.compile(
    r'<a href="(/nieuws/\d{8}/[^"]+)">.*?<div>\s*(.*?)\s*</div>\s*</a>\s*'
    r"<span>([^<]+)</span>",
    re.S,
)
_TERM = re.compile(r'href="(/personele_mutaties\?zittingid=[a-z0-9]+)"')
_TERM_TITLE = re.compile(
    r"Personele mutaties (huidige zittingsperiode|zittingsperiode \d{4}-\d{4})"
)
# Words of the composition: a text with one of them that no pattern reads is reported.
_COMPOSITION = re.compile(
    r"geïnstalleerd|beëdigd|verlaat|vertrek|stopt als|gestopt|ontslag|fractie|"
    r"afgesplitst|splitst|stapt", re.I
)  # fmt: skip

BASIS = "tekst"
# The list of changes of the current term; it links those of the terms before.
MUTATIONS_PATH = "/personele_mutaties"


def iso_day(text: str, year: int) -> str | None:
    """``11 juli 2023`` (or ``5 juli`` in *year*) as ISO; None for no such day."""
    found = re.search(_DAY, text)
    if not found:
        return None
    day, month, of_year = found.groups()
    try:
        return dt.date(int(of_year or year), MONTHS[month], int(day)).isoformat()
    except ValueError:
        return None


def plain(fragment: str) -> str:
    """The text of an HTML fragment, its whitespace folded."""
    without = re.sub(
        r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", fragment, flags=re.S
    )
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", without))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


@dataclass(frozen=True)
class Listed:
    """An item of ``/personele_mutaties``: its day, headline and page."""

    date: str
    headline: str
    path: str


@dataclass(frozen=True)
class TermPage:
    """A term of ``/personele_mutaties``: its title, its items, and the pages of the terms
    before it."""

    title: str
    items: list[Listed]
    terms: list[str]


def term_page(page: str) -> TermPage:
    """The items and the other terms of a page of ``/personele_mutaties``."""
    title = _TERM_TITLE.search(page)
    items = []
    for path, headline, day in _ITEM.findall(page):
        date = iso_day(plain(day), 0)
        if date:
            items.append(Listed(date=date, headline=plain(headline), path=path))
    return TermPage(
        title=title.group(0) if title else "",
        items=items,
        terms=sorted(set(_TERM.findall(page))),
    )


@dataclass(frozen=True)
class Article:
    """The page of an item: its headline, its day, its text and the members it links."""

    headline: str
    date: str
    text: str
    persons: list[str] = field(default_factory=list)


def article(page: str, date: str, headline: str) -> Article:
    """The text of an item's page: what stands between its date and ``Terug naar boven``."""
    start = page.find("Nieuwsoverzicht")
    end = page.find("Terug naar boven", start)
    body = page[start:end] if start >= 0 and end > start else page
    text = plain(body).removeprefix("Nieuwsoverzicht").strip()
    # the item's own date stands first: a day of the text is one after it
    text = re.sub(rf"^{_DAY}\s*", "", text)
    # the links to other items under it ("Lees ook: …") are not its text
    text = text.split("Lees ook:")[0].strip()
    return Article(
        headline=headline,
        date=date,
        text=text,
        persons=sorted(set(re.findall(r'href="(/persoon/[^"#?]+)"', body))),
    )


@dataclass(frozen=True)
class Change:
    """What a change does to the seats.

    ``kind``: ``beëdiging`` (a member sworn in: +1 for ``to``), ``vertrek`` (a member gone:
    -1 for ``source``), ``overstap`` (from ``source`` to ``to``), ``afsplitsing`` (from
    ``source`` to a faction of their own, ``to``), ``hernoeming`` (``source`` is called
    ``to`` from then on), ``samenvoeging`` (the factions of ``sources`` are one, ``to``).
    ``date`` the day it takes effect; ``words`` the source's headline or sentence; ``member``
    the name the text gives; ``succeeds`` of one sworn in, the member whose seat they take
    (their faction, when the text names none); ``by`` of one gone, the member sworn in in
    their place (whose faction is theirs, when the text names none)."""

    kind: str
    date: str
    words: str
    source: str | None = None
    to: str | None = None
    member: str | None = None
    sources: tuple[str, ...] = ()
    basis: str = BASIS
    succeeds: str | None = None
    by: str | None = None


def initials(name: str) -> str:
    """The initials of a faction's name, upper case: of its words and of the capitals
    inside one (``GroenLinks`` GL, ``ChristenUnie`` CU, ``Partij van de Arbeid`` PVDA)."""
    parts = re.findall(r"[A-Z][a-z]*|\b[a-z]+", re.sub(r"[^\w\s]", " ", name))
    return "".join(p[0] for p in parts).upper()


def faction_key(name: str) -> str:
    """The name of a faction as it is matched: ``BBB-fractie``, ``de BBB`` and ``BBB`` alike,
    without dots, in upper case."""
    name = re.sub(r"^(de|het)\s+", "", name.strip(), flags=re.I)
    name = re.sub(r"[-\s]?fractie$", "", name, flags=re.I)
    return name.replace(".", "").strip().upper()


# ── reading the changes of an item ─────────────────────────────────────────────

# A name as the texts write it: "Robert van Gasteren", "Marjolein Faber-van de Klashorst",
# "Annabel Nanninga", "Cees van de Sanden".
_NAME = (
    r"[A-Z][\w'’.-]+(?: (?:van|de|der|den|het|ten|ter|op|in|'t)| [A-Z][\w'’.-]+)*?"
    r"(?: [A-Z][\w'’.-]+)?"
)
# A faction as a text names it: "(VVD)", "( Fractie-Beukering )", "voor de VVD", "de BBB-fractie",
# "de fractie van D66", "de fractie van Forum Voor Democratie (FVD)".
_IN_BRACKETS = r"\(\s*([^()\d][^()]*?)\s*\)"  # not "(56)", an age
_NAMED_WITH = re.compile(rf"({_NAME}) {_IN_BRACKETS}")
# What a text says of a member that changes no seat: the chair of the Kamer or of a faction.
_ROLE = re.compile(r"\b(?:Voorzitter|Ondervoorzitter|fractievoorzitter)", re.I)
_SEAT = re.compile(
    r"geïnstalleerd|beëdigd|versterkt met|verlaat|vertrek|vertrokken|stopt als|gestopt|"
    r"beëindigt|ontslag als (?:lid|Eerste Kamerlid|senator)|afscheid|afgesplitst|splitst|"
    r"scheidt zich af|stapt|sluit zich|"
    r"overleden|verder als|verder onder", re.I
)  # fmt: skip


_TITLE = re.compile(
    r"^(?:(?:Het|De) )?(?:Eerste )?"
    r"(?:Kamerlid|Kamerleden|Kamer|[Ss]enator(?:en)?|Fractievoorzitter) "
)


def surname(name: str) -> str:
    """The surname a member goes by in the names of factions: "Robert van Gasteren" is "Van
    Gasteren", "Marjolein Faber-van de Klashorst" "Faber-van de Klashorst"; a name of one word
    (``Senator Kemperman``) is itself."""
    words = _TITLE.sub("", name.strip()).split()
    if len(words) < 2:
        return name.strip()
    if words[0] in ("Van", "De", "Der", "Den", "Ten", "Ter", "Het"):
        return " ".join(words)
    rest = " ".join(words[1:])
    return rest[:1].upper() + rest[1:]


def member_key(name: str | None) -> str:
    """Who a change is about, as texts name them differently ("Marjolein Faber-van de
    Klashorst", "Faber"): the last word of the name, in lower case."""
    return re.split(r"[\s-]", (name or "").strip())[-1].lower()


def _faction(text: str) -> str | None:
    """The faction a phrase names: ``(VVD)``, ``Fractie-Beukering``, ``BBB-fractie``."""
    text = re.sub(r"^(?:de |het )?fractie van (?:de |het )?", "", text.strip())
    brackets = re.search(_IN_BRACKETS, text)
    if brackets:
        return brackets.group(1).strip()
    return text or None


@dataclass
class Reading:
    """What was read of an item: its changes, and whether it speaks of the seats without a
    pattern reading it (``unread``)."""

    changes: list[Change] = field(default_factory=list)
    unread: bool = False
    temporary: bool = False


def _sentences(text: str) -> list[str]:
    # not after an initial: "de heer C.J. Kok"
    parts = re.split(r"(?<!\b[A-Z]\.)(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in parts if s.strip()]


def read(item: Article) -> Reading:
    """The changes an item's headline and text tell (``Change``)."""
    found = Reading()
    year = int(item.date[:4])
    text = f"{item.headline}. {item.text}"
    if re.search(r"tijdelijk", item.headline) or re.search(
        r"griffier", item.headline, re.I
    ):
        found.temporary = True
        return found
    sentences = _sentences(item.text)
    for sentence in sentences:
        found.changes += _installed(sentence, item, year)
        found.changes += _succeeds(sentence, item, year)
        found.changes += _gone(sentence, item, year)
        found.changes += _moved(sentence, item, year)
    found.changes += _regrouped(item, year, found.changes)
    found.changes += _headline(item, year, found.changes)
    kept = _temporaries(item, found.changes)
    found.temporary = len(kept) < len(found.changes)
    found.changes = _linked(_once(kept), item)
    if (
        not found.changes
        and not found.temporary
        and _SEAT.search(text)
        and not _only_role(text)
    ):
        found.unread = True
    return found


# A member sworn in for one on leave or ill, and that member: "Max Aardema vervangt tijdelijk
# de zieke senator Martin van Beek", "Senator Vink volgt Annelien Bredenoord op die tijdelijk
# ontslag heeft genomen", "Hij vervangt Mirjam Bikker , die met … verlof is".
_STAND_IN = re.compile(
    rf"(?:({_NAME}) )?(?:(?:vervangt|volgt) tijdelijk (?:de zieke senator )?({_NAME})|"
    rf"(?:volgt|vervangt) ({_NAME})(?: op)?,? die tijdelijk ontslag|"
    rf"vervangt ({_NAME}) ,? die [^.]*verlof|"
    rf"vervangt (?:de heer |mevrouw )?({_NAME}) gedurende (?:haar|zijn) \w*verlof)"
)


def _temporaries(item: Article, changes: list[Change]) -> list[Change]:
    """The changes without those of a member who stands in for one on leave or ill (no seat
    changes hands): their swearing in, and the leave of the one they stand in for."""
    standing, away = set(), set()
    sworn = [c.member for c in changes if c.kind == "beëdiging"]
    for m in _STAND_IN.finditer(item.text):
        who = m.group(1)
        if who in (None, "Hij", "Zij") and len(sworn) == 1:
            who = sworn[0]
        standing.add(member_key(who))
        away.add(member_key(m.group(2) or m.group(3) or m.group(4) or m.group(5)))
    return [
        c
        for c in changes
        if not (c.kind == "beëdiging" and member_key(c.member) in standing)
        and not (c.kind == "vertrek" and member_key(c.member) in away)
    ]


def _linked(changes: list[Change], item: Article) -> list[Change]:
    """Of one sworn in and one gone in the same item, each's faction from the other: the one
    gone ``by`` a member sworn in is of that member's faction; with one sworn in, every one
    gone that day or before is; one sworn in with no faction ``succeeds`` the one gone."""
    sworn = [c for c in changes if c.kind == "beëdiging"]
    of = {member_key(c.member): c.to for c in sworn if c.to}
    gone = [c for c in changes if c.kind == "vertrek" and c.date <= item.date]
    if len(sworn) == 1 and len(gone) == 1 and sworn[0].to is None:
        changes = [
            replace(c, succeeds=gone[0].member) if c is sworn[0] else c for c in changes
        ]
    one = sworn[0] if len(sworn) == 1 and sworn[0].to else None

    def faction(c: Change) -> str | None:
        if c.by and member_key(c.by) in of:
            return of[member_key(c.by)]
        if one and c.date <= item.date and c.member != one.member:
            return one.to
        return None

    return [
        replace(c, source=faction(c)) if c.kind == "vertrek" and c.source is None else c
        for c in changes
    ]


def _only_role(text: str) -> bool:
    """Whether a text that speaks of a member speaks only of a chair (no seat changes)."""
    return bool(_ROLE.search(text)) and not re.search(
        r"geïnstalleerd als lid|beëdigd als lid|afgesplitst|stapt over|verlaat de", text
    )


def _once(changes: list[Change]) -> list[Change]:
    """Each change once: a text tells a change in its headline and again in a sentence; of a
    member's departure, the one that names their faction."""
    named = {member_key(c.member) for c in changes if c.kind == "vertrek" and c.source}
    changes = [
        c
        for c in changes
        if not (c.kind == "vertrek" and not c.source and member_key(c.member) in named)
    ]
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    kept = []
    for change in changes:
        key = (change.kind, change.member, change.source, change.to)
        if key not in seen:
            seen.add(key)
            kept.append(change)
    return kept


_BEFORE = re.compile(rf"(?:sinds|van|tot(?: en met)?|vanaf) {_DAY}")


def _day_in(sentence: str, item: Article, year: int) -> str:
    """The day a change in *sentence* takes effect: a day it names, not one that dates
    something before it (``sinds 13 juni 2023``); else the day of the item."""
    return iso_day(_BEFORE.sub(" ", sentence), year) or item.date


_INSTALLED_LIST = re.compile(
    rf"geïnstalleerd: ({_NAME}) {_IN_BRACKETS}(?: en ({_NAME}) {_IN_BRACKETS})?"
)
_INSTALLED_FOR = re.compile(
    rf"(?:zijn|is) ({_NAME})(?: en ({_NAME}))? geïnstalleerd als lid van de Eerste Kamer"
    rf" voor (?:respectievelijk )?(?:de )?([\w-]+)(?: en (?:de )?([\w-]+))?"
)
_SWORN = re.compile(
    rf"({_NAME}) {_IN_BRACKETS} (?:is (?:\w+dag {_DAY} )?(?:eveneens )?)?beëdigd als"
    r" (?:lid|Eerste Kamerlid)"
)
# "is de heer J.A. Bruijn beëdigd en geïnstalleerd als lid van de Eerste Kamer voor de
# Volkspartij voor Vrijheid en Democratie (VVD)", "zijn Alexander Kops (PVV) en Eric Meijer
# (SP) beëdigd en geïnstalleerd als lid van de Eerste Kamer".
_SIR = r"(?:de heer |mevrouw )?"
_SWORN_AND_INSTALLED = re.compile(
    rf"(?:is|zijn) (?:de )?{_SIR}({_NAME})(?: {_IN_BRACKETS})?"
    rf"(?: en {_SIR}({_NAME})(?: {_IN_BRACKETS})?)?"
    r" beëdigd (?:en geïnstalleerd )?(?:als|tot) lid van de Eerste Kamer"
    r"(?: voor (?:de |het )?(.+?))?\s*\.?$"
)


# "heeft dinsdag senator Hugo Berkhout benoemd in de vacature die was ontstaan door het
# vertrek …": a stand-in who keeps the seat, in the faction they sit in.
_APPOINTED = re.compile(rf"senator ({_NAME}) benoemd in de vacature")
# "heeft de Eerste Kamer op 6 december 2016 senator Mohamed Sini (PvdA) beëdigd", "… Pia
# Lokin-Sassen (CDA) en Max Aardema (PVV) beëdigd als senator".
_HAS_SWORN = re.compile(
    rf"heeft (?:de Eerste Kamer )?(?:vandaag |op {_DAY} )?(?:senator )?({_NAME}) {_IN_BRACKETS}"
    rf"(?: en ({_NAME}) {_IN_BRACKETS})? beëdigd"
)
# "vijf nieuwe leden beëdigd: Peter Van Dijk , Martin van Beek , … (allen PVV) en Martine
# Baaij-Timmerman (50PLUS)".
_SWORN_LIST = re.compile(r"leden beëdigd: (.+?)\s*\.?$")
_LIST_GONE = re.compile(r"volgen (?:oud-senatoren |de senatoren )?(.+?) op\b")


def _named_list(text: str) -> list[tuple[str, str]]:
    """The members of a list and their factions: each name until the next ``(F)`` or
    ``(allen F)`` is of that faction."""
    found: list[tuple[str, str]] = []
    waiting: list[str] = []
    for part in re.split(r"\s*,\s*|\s+en\s+", text):
        named = re.match(
            rf"({_NAME})(?:\s*\((?:allen |beiden )?([^()]+)\))?\s*$", part.strip()
        )
        if not named:
            continue
        waiting.append(named.group(1))
        if named.group(2):
            found += [(n, named.group(2)) for n in waiting]
            waiting = []
    return found


def _sworn_named(m: re.Match[str]) -> list[tuple[str, str]]:
    """The members and factions of a ``_SWORN_AND_INSTALLED`` match: each its own brackets,
    else the faction the sentence ends on (its abbreviation in brackets, else its name)."""
    after = m.group(5) or ""
    common = _faction(after) if after else ""
    return [
        (name, faction or common or "")
        for name, faction in ((m.group(1), m.group(2)), (m.group(3), m.group(4)))
        if name
    ]


_INSTALLED_AS = re.compile(rf"werd ({_NAME}) als ([\w-]+)-senator geïnstalleerd")
_STRENGTHENED = re.compile(
    rf"De ([\w-]+)-fractie in de Eerste Kamer is .*? versterkt met ({_NAME})"
)


def _installed(sentence: str, item: Article, year: int) -> list[Change]:
    day = _day_in(sentence, item, year)
    made = []
    if m := _INSTALLED_LIST.search(sentence):
        made.append((m.group(1), m.group(2)))
        if m.group(3):
            made.append((m.group(3), m.group(4)))
    elif m := _INSTALLED_FOR.search(sentence):
        made.append((m.group(1), m.group(3)))
        if m.group(2):
            made.append((m.group(2), m.group(4) or m.group(3)))
    elif m := _HAS_SWORN.search(sentence):
        made = [
            (n, f) for n, f in ((m.group(4), m.group(5)), (m.group(6), m.group(7))) if n
        ]
    elif m := _SWORN.search(sentence):
        made.append((m.group(1), m.group(2)))
    elif m := _APPOINTED.search(sentence):
        made.append((m.group(1), ""))
        day = item.date  # the day it names is the vacancy's
    elif m := _STRENGTHENED.search(sentence):
        made.append((m.group(2), m.group(1)))
    elif m := _INSTALLED_AS.search(sentence):
        made.append((m.group(1), m.group(2)))
    elif m := _SWORN_AND_INSTALLED.search(sentence):
        made = _sworn_named(m)
    elif m := _SWORN_LIST.search(sentence):
        made = _named_list(m.group(1))
    return [
        Change(
            "beëdiging",
            day,
            item.headline,
            to=_faction(faction) if faction else None,
            member=surname(name),
        )
        for name, faction in made
    ]


_SUCCEEDS = re.compile(
    rf"(?:({_NAME}) )?volgt (?:de onlangs overleden senator )?({_NAME})(?: {_IN_BRACKETS})? op"
    rf"(?: en ({_NAME}) ({_NAME}) {_IN_BRACKETS})?"
)
# "Hij is de opvolger van de per 1 november 2009 afgetreden oud-Voorzitter … Yvonne
# Timmerman-Buck."
# "De heer Witteveen volgt hiermee PvdA-senator P.L. Meurs op, die op dezelfde dag afscheid
# nam", "Hij volgt de heer Witteveen op, die op 17 juli 2014 … om het leven is gekomen".
_FOLLOWS = re.compile(
    rf"(?:(?:Senator |senator )?({_NAME}) )?(?:volgt|vervangt) (?:hiermee )?"
    rf"(?:([\w-]+)-senator |partijgenoot |{_SIR})({_NAME})"
    r"(?: op|,? die de (?:Eerste )?Kamer (?:heeft verlaten|verlaat))"
)
_SUCCESSOR = re.compile(r"(?:is|wordt) de opvolger van (.+?)\s*\.?$")
_SUCCEED_BOTH = re.compile(
    rf"volgen ({_NAME}) {_IN_BRACKETS} en ({_NAME}) {_IN_BRACKETS} op"
)


def _succeeds(sentence: str, item: Article, year: int) -> list[Change]:
    """A member who succeeds another: the one gone (``vertrek`` on the day of the item, when
    no item of their own dates it; ``walk`` keeps the first)."""
    gone: list[tuple[str, str | None]] = []
    if m := _SUCCEED_BOTH.search(sentence):
        gone = [(m.group(1), m.group(2)), (m.group(3), m.group(4))]
    else:
        for m in _SUCCEEDS.finditer(sentence):
            gone.append((m.group(2), m.group(3)))
            if m.group(4):
                gone.append((m.group(5), m.group(6)))
    found = [
        Change(
            "vertrek", item.date, item.headline, source=faction, member=surname(name)
        )
        for name, faction in gone
    ]
    for m in _FOLLOWS.finditer(sentence):
        rest = sentence[m.end() :]
        died = re.search(rf"(?:op|per) {_DAY}", rest)
        day = (iso_day(died.group(0), year) if died else None) or item.date
        by = m.group(1) if m.group(1) not in (None, "Hij", "Zij") else None
        found.append(
            Change(
                "vertrek",
                day,
                item.headline,
                by=by,
                source=m.group(2),
                member=surname(m.group(3)),
            )
        )
    if m := _SUCCESSOR.search(sentence):
        clause = re.split(r"\s*,", m.group(1))[0]
        name = re.search(rf"({_NAME})\s*\.?$", clause)
        per = _PER.search(clause) or re.search(rf"op {_DAY}", clause)
        day = (iso_day(per.group(0), year) if per else None) or item.date
        if name:
            found.append(
                Change("vertrek", day, item.headline, member=surname(name.group(1)))
            )
    return found


_GONE = [
    re.compile(rf"({_NAME}) {_IN_BRACKETS} vertrekt (?:per )?(?=\d)"),
    re.compile(rf"({_NAME}) {_IN_BRACKETS} is per (?=\d).*? gestopt als lid"),
    re.compile(rf"({_NAME}) {_IN_BRACKETS} vertrekt bij de Kamer"),
    re.compile(
        rf"(?<![\w-])([\w]+)-senator ({_NAME}) vertrekt uit de (?:Senaat|Eerste Kamer)"
    ),
    re.compile(
        rf"([\w-]+)-senator ({_NAME}) nam op (?=\d).*? afscheid van de Eerste Kamer"
    ),
]


def _gone(sentence: str, item: Article, year: int) -> list[Change]:
    day = _day_in(sentence, item, year)
    if m := _GONE[3].search(sentence):
        return [
            Change(
                "vertrek",
                day,
                item.headline,
                source=m.group(1),
                member=surname(m.group(2)),
            )
        ]
    for pattern in _GONE[:3]:
        if m := pattern.search(sentence):
            return [
                Change(
                    "vertrek",
                    day,
                    item.headline,
                    source=m.group(2),
                    member=surname(m.group(1)),
                )
            ]
    if m := _GONE[4].search(sentence):
        return [
            Change(
                "vertrek",
                day,
                item.headline,
                source=m.group(1),
                member=surname(m.group(2)),
            )
        ]
    if m := re.search(r"beëindigt (?:zijn|haar) Kamerlidmaatschap per", sentence):
        name = re.search(rf"^({_NAME}) ", sentence)
        return [
            Change(
                "vertrek",
                day,
                item.headline,
                member=surname(name.group(1)) if name else None,
            )
        ]
    if m := _LIST_GONE.search(sentence):
        if len(named := _named_list(m.group(1))) > 1:
            rest = sentence[m.end() :]
            when = re.search(rf"op {_DAY}", rest)
            day = (iso_day(when.group(0), year) if when else None) or item.date
            return [
                Change("vertrek", day, item.headline, source=f, member=surname(n))
                for n, f in named
            ]
    if resigned := _resigned(sentence, item, year):
        return resigned
    if m := _TO_TK.search(sentence):
        return [
            Change("vertrek", day, item.headline, source=f, member=surname(n))
            for n, f in ((m.group(1), m.group(2)), (m.group(3), m.group(4)))
            if n
        ]
    if m := _FAREWELL.search(sentence):
        until = re.search(rf"tot en met {_DAY}", item.text)
        left = item.date
        if until:
            last = iso_day(until.group(0), year)
            if last:
                left = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
        return [
            Change(
                "vertrek",
                left,
                item.headline,
                source=m.group(2),
                member=surname(m.group(1)),
            )
        ]
    return []


# A member who gives up their seat, in the words of older items: "treedt terug per 15 mei",
# "zegt zijn lidmaatschap van de senaat per 9 juni op", "zijn Kamerlidmaatschap per 14
# september zal neerleggen", "vervalt hun Kamerlidmaatschap met ingang van vandaag".
_RESIGNS = re.compile(
    r"treedt terug per|treden terug per|zegt (?:zijn|haar) lidmaatschap .*? op\b|"
    r"(?:functie|lidmaatschap)[^.]*? neergelegd|"
    r"(?:Hun|Zijn|Haar) lidmaatschap van de Eerste Kamer is geëindigd|"
    r"verlaat de Eerste Kamer|vertrekt uit de Eerste Kamer|"
    r"(?:zijn|haar) (?:Kamer)?lidmaatschap .*?(?:neer ?leggen|neerlegt)|"
    r"vervalt (?:zijn|haar|hun) (?:Kamer)?lidmaatschap"
)
_PER = re.compile(rf"(?:per|met ingang van) {_DAY}")
_OF_FACTION = re.compile(r"(?:leden|lid) van de ([\w-]+?)-fractie")


def _resigned(sentence: str, item: Article, year: int) -> list[Change]:
    """The members *sentence* says give up their seat: those it names with their faction,
    else those the sentence before names (``vervalt hun Kamerlidmaatschap``), else the name
    it opens with, in the faction the item names (``Twee leden van de CDA-fractie``)."""
    if not _RESIGNS.search(sentence):
        return []
    per = _PER.search(sentence)
    day = (iso_day(per.group(0), year) if per else None) or item.date
    named = _NAMED_WITH.findall(sentence)
    if not named and re.search(r"\b(?:hun|zijn|haar)\b", sentence, re.I):
        before = item.text[: item.text.find(sentence)]
        last = _sentences(before)[-1] if before.strip() else ""
        named = _NAMED_WITH.findall(last)
        sir = rf"(?:de heer|mevrouw) ({_NAME})(?= en | geïnstalleerd| beëdigd|,)"
        if not named and (sirs := re.findall(sir, last)):
            voor = re.search(r" voor (?:de |het )?(.+?)\s*\.?$", last)
            named = [(n, _faction(voor.group(1)) or "" if voor else "") for n in sirs]
    if not named and (opens := re.match(rf"({_NAME}) (?:treedt|zegt)", sentence)):
        faction = _OF_FACTION.search(item.text)
        named = [(opens.group(1), faction.group(1) if faction else "")]
    return [
        Change("vertrek", day, item.headline, source=f or None, member=surname(n))
        for n, f in named
    ]


_TO_TK = re.compile(
    rf"De senatoren ({_NAME}) {_IN_BRACKETS}(?: en ({_NAME}) {_IN_BRACKETS})? worden .*?"
    r"geïnstalleerd als lid van de Tweede Kamer"
)
_FAREWELL = re.compile(rf"afscheid genomen van ({_NAME}) ,? senator namens de ([\w-]+)")

_LEAVES_FOR = re.compile(
    rf"(?:Senator|senator) ({_NAME}) verlaat de ([\w-]+)-fractie in de Eerste Kamer en"
    rf" (?:stapt over naar de (?:fractie van )?([\w-]+)|gaat verder als eenmansfractie)"
)
_LEFT = re.compile(
    rf"(?:Senator|senator) ({_NAME}) heeft de ([\w-]+)-fractie in de Eerste Kamer verlaten"
    rf" en gaat verder als eenmansfractie"
)
_SPLIT = re.compile(
    rf"heeft senator ({_NAME}) zich afgesplitst van de ([\w-]+)-fractie"
)
_SPLIT_NAME = re.compile(r"verder onder naam (Fractie-[\w' -]+?)\.")
_CROSSES = re.compile(
    rf"([\w-]+)-senator ({_NAME}) scheidt zich af van zijn fractie"
    r" en stapt over naar de ([\w-]+)-fractie"
)
_JOINS = re.compile(
    rf"(?:Senator|senator) ({_NAME}) ,? .*?sluit zich (?:per direct )?aan"
    r" bij de fractie van [^(]*\(([^)]+)\)"
)


# "Eerste Kamerlid Anne-Wil Duthler maakt geen deel meer uit van de VVD-fractie … en gaat
# alleen verder in de Fractie-Duthler".
_ALONE = re.compile(
    rf"({_NAME}) maakt geen deel meer uit van de ([\w-]+?)-fractie"
    r" .*?verder in de (Fractie-[\w' -]+?)\s*\.?$"
)


def _moved(sentence: str, item: Article, year: int) -> list[Change]:
    day = _day_in(sentence, item, year)
    if m := _ALONE.search(sentence):
        return [
            Change(
                "afsplitsing",
                item.date,
                item.headline,
                source=m.group(2),
                to=m.group(3),
                member=surname(m.group(1)),
            )
        ]
    if m := _LEAVES_FOR.search(sentence):
        member = surname(m.group(1))
        to = m.group(3) or f"Fractie-{member}"
        kind = "overstap" if m.group(3) else "afsplitsing"
        return [
            Change(kind, day, item.headline, source=m.group(2), to=to, member=member)
        ]
    if m := _LEFT.search(sentence):
        member = surname(m.group(1))
        return [
            Change(
                "afsplitsing",
                day,
                item.headline,
                source=m.group(2),
                to=f"Fractie-{member}",
                member=member,
            )
        ]
    if m := _SPLIT.search(sentence):
        member = surname(m.group(1))
        named = _SPLIT_NAME.search(item.text)
        to = named.group(1).strip() if named else f"Fractie-{member}"
        return [
            Change(
                "afsplitsing",
                day,
                item.headline,
                source=m.group(2),
                to=to,
                member=member,
            )
        ]
    if m := _CROSSES.search(sentence):
        return [
            Change(
                "overstap",
                day,
                item.headline,
                source=m.group(1),
                to=m.group(3),
                member=surname(m.group(2)),
            )
        ]
    if m := _JOINS.search(sentence):
        return [
            Change(
                "overstap",
                day,
                item.headline,
                to=m.group(2),
                member=surname(m.group(1)),
            )
        ]
    return []


# ── the history a faction page tells ───────────────────────────────────────────

_SINCE = re.compile(rf"(.+?) is vanaf ({_DAY}) vertegenwoordigd in de Eerste Kamer")
_NAMED = re.compile(rf"Van ({_DAY}) tot ({_DAY}) was de naam van de fractie (.+?) \.")
_TWO = re.compile(
    r"Voor die datum waren er twee fracties, een voor (.+?) en een voor (?:de )?(.+?) \."
)


def faction_history(page: str) -> list[Change]:
    """The merges and renames a faction's page tells of itself: ``Van 13 juni 2023 tot 9
    september 2026 was de naam van de fractie GroenLinks-PvdA`` (a rename on the second day)
    and ``Voor die datum waren er twee fracties, een voor GroenLinks en een voor de PvdA`` (a
    merge on the first)."""
    text = plain(page)
    since, named = _SINCE.search(text), _NAMED.search(text)
    if not since or not named:
        return []
    current = re.sub(r"\s*\([^)]*\)\s*$", "", since.group(1).split(". ")[-1]).strip()
    short = re.search(r"\(([^)]+)\)", since.group(1))
    first = iso_day(named.group(1), 0)
    renamed = iso_day(named.group(5), 0)
    old = named.group(9).strip()
    changes = []
    if two := _TWO.search(text):
        if first:
            changes.append(
                Change(
                    "samenvoeging",
                    first,
                    two.group(0),
                    to=old,
                    sources=(two.group(1).strip(), two.group(2).strip()),
                )
            )
    if renamed:
        changes.append(
            Change(
                "hernoeming",
                renamed,
                named.group(0),
                source=old,
                to=short.group(1) if short else current,
            )
        )
    return changes


# ── the seats of a term, day by day ────────────────────────────────────────────

SEATS = 75
# Within so many days of a term's first day, a member sworn in with no seat open was elected.
LATE_DAYS = 60
# Of the changes of one day: the factions merged and renamed first, then the members who go,
# then who change faction, then who come.
_ORDER = {"samenvoeging": 0, "hernoeming": 1, "vertrek": 2, "overstap": 3, "afsplitsing": 3,
          "beëdiging": 4}  # fmt: skip


@dataclass
class Stretch:
    """The seats of the factions from a day until the day before the next stretch."""

    from_date: str
    to_date: str | None
    seats: dict[str, int]
    events: list[Change] = field(default_factory=list)


@dataclass
class Walk:
    """The stretches of a term and what did not add up: ``mismatches`` (the changes whose
    faction is not known, a faction short of seats, more seats than the Kamer has);
    ``checked`` when there are none."""

    stretches: list[Stretch]
    mismatches: list[str]

    @property
    def checked(self) -> bool:
        return not self.mismatches


class _Seats:
    """The seats of the factions while a term is walked: per faction (by ``faction_key``) its
    name and seats, the faction each member was last seen in, the members gone."""

    def __init__(self, seats: dict[str, int], late: str = "") -> None:
        self.late = late
        self.names: dict[str, str] = {}
        self.count: dict[str, int] = {}
        self.member_of: dict[str, str] = {}
        self.gone: set[str] = set()
        self.vacant: dict[str, int] = {}
        self.mismatches: list[str] = []
        for name, n in seats.items():
            self._add(name, n)

    def _add(self, name: str, n: int) -> None:
        key = self._resolve(name)
        self.names.setdefault(key, name)
        self.count[key] = self.count.get(key, 0) + n

    def _resolve(self, name: str) -> str:
        """The key a faction's *name* counts under: its own, else that of a faction already
        counted whose name is its initials or whose initials it is (``GroenLinks`` and
        ``GL``, ``ChristenUnie`` and ``CU``)."""
        key = faction_key(name)
        if key in self.count:
            return key
        mine = initials(name)
        for other in self.count:
            if other == mine or initials(self.names[other]) == key:
                return other
        return key

    def add(self, name: str | None, n: int, change: Change) -> bool:
        if not name:
            self.mismatches.append(
                f"{change.date}: {change.kind} of {change.member}: no faction"
            )
            return False
        key = self._resolve(name)
        self._add(name, n)
        if self.count[key] < 0:
            self.mismatches.append(
                f"{change.date}: {self.names[key]} below 0 ({change.words})"
            )
        return True

    def apply(self, change: Change) -> None:
        member = member_key(change.member)
        if change.kind == "samenvoeging":
            total = sum(self.count.pop(faction_key(s), 0) for s in change.sources)
            self.add(change.to, total, change)
        elif change.kind == "hernoeming":
            key = faction_key(change.source or "")
            if key in self.count and change.to:
                self.names[faction_key(change.to)] = change.to
                self.count[faction_key(change.to)] = self.count.pop(key)
        elif change.kind == "vertrek":
            if member not in self.gone:
                self.gone.add(member)
                faction = change.source or self.member_of.get(member)
                if self.add(faction, -1, change):
                    key = self._resolve(faction or "")
                    self.vacant[key] = self.vacant.get(key, 0) + 1
        elif change.kind in ("overstap", "afsplitsing"):
            if self.add(change.source or self.member_of.get(member), -1, change):
                self.add(change.to, 1, change)
            self.member_of[member] = faction_key(change.to or "")
        elif change.kind == "beëdiging":
            self._sworn(member, change)
        if sum(self.count.values()) > SEATS:
            self.mismatches.append(
                f"{change.date}: more than {SEATS} seats ({change.words})"
            )

    def _sworn(self, member: str, change: Change) -> None:
        """A member sworn in fills a seat their faction left open; one sworn in within the
        term's first weeks with no seat open was elected and sworn in late (the Kiesraad's
        result counts them already)."""
        self.gone.discard(member)
        if not change.to:
            # the faction of the one they succeed, else their own (a stand-in kept on)
            faction = self.member_of.get(
                member_key(change.succeeds)
            ) or self.member_of.get(member)
            change = replace(change, to=self.names.get(faction or ""))
        key = self._resolve(change.to or "")
        if change.to and not self.vacant.get(key) and change.date <= self.late:
            self.member_of[member] = key
            return
        if self.add(change.to, 1, change):
            self.vacant[key] = self.vacant.get(key, 0) - 1
            self.member_of[member] = key

    def now(self) -> dict[str, int]:
        return {k: v for k, v in self.count.items() if v}


def walk(start: str, seats: dict[str, int], changes: list[Change], until: str) -> Walk:
    """The seats of a term from its first day (*start*, *seats* per faction by name) through
    *changes* to *until*. A member's faction is the one the change names, else the one the
    walk last saw them in; a member already gone is gone once."""
    late = dt.date.fromisoformat(start) + dt.timedelta(days=LATE_DAYS)
    state = _Seats(seats, late.isoformat())
    stretches = [Stretch(start, None, state.now())]
    kept = sorted(
        (c for c in changes if start <= c.date <= until),
        key=lambda c: (c.date, _ORDER.get(c.kind, 9)),
    )
    for change in kept:
        before = state.now()
        state.apply(change)
        current = state.now()
        if current == before:
            continue
        last = stretches[-1]
        if last.from_date == change.date:
            last.seats = current
            last.events.append(change)
        else:
            day_before = dt.date.fromisoformat(change.date) - dt.timedelta(days=1)
            last.to_date = day_before.isoformat()
            stretches.append(Stretch(change.date, None, current, [change]))
    for stretch in stretches:
        stretch.seats = {state.names[k]: v for k, v in stretch.seats.items() if v}
    return Walk(stretches, state.mismatches)


def start_seats(
    lists: dict[str, int], factions: dict[str, set[str]]
) -> tuple[dict[str, int], list[str]]:
    """The seats of a term's first day by faction name: each list of the Kiesraad's result
    (by name, its seats) to the faction one of whose names (``factions``: name to the names
    it is matched by, upper case: abbreviation, full name) is one of the list's
    (``kiesraad.list_names``); a list that matches none keeps its own short name and is
    reported."""
    from lawgraph.core.kiesraad import list_names

    seats: dict[str, int] = {}
    unmatched = []
    for name, n in lists.items():
        names = list_names(name)
        match = next((f for f, known in factions.items() if names & known), None)
        if match is None:
            short = re.search(r"\(([^)]+)\)\s*$", name)
            match = short.group(1) if short else name
            unmatched.append(name)
        seats[match] = seats.get(match, 0) + n
    return seats, unmatched


# A faction's name and its abbreviation, as a text writes them: "de Onafhankelijke
# Senaatsfractie (OSF)", "Forum voor Democratie (FVD)".
_SPELLED_OUT = re.compile(
    r"\b([A-Z][\w-]+(?: (?:voor|van|de|het|en|[A-Z][\w-]+))*? [A-Z][\w-]+) \(([A-Z][\w.-]{1,9})\)"
)


def spelled_out(text: str) -> list[str]:
    """Each faction a text names in full with its abbreviation, as a list name
    (``Onafhankelijke Senaatsfractie (OSF)``): ``known_factions`` matches it like a list's."""
    found = []
    for name, abbr in _SPELLED_OUT.findall(text):
        words = name.split()
        # "Senator Gerben Gerbrandy van de Onafhankelijke Senaatsfractie": from each capital
        found += [
            f"{' '.join(words[i:])} ({abbr})"
            for i, w in enumerate(words)
            if w[0].isupper()
        ]
    return found


def known_factions(
    today: dict[str, set[str]],
    lists: Iterable[str],
    changes: list[Change],
    spelled: Iterable[str] = (),
) -> dict[str, set[str]]:
    """Every faction by name and the names it is matched by (upper case): today's (*today*);
    each list of the Kiesraad's (*lists*) as the faction of today it is one of, else as a
    faction of its own by its short name; each with the names in full the texts give
    (*spelled*, ``spelled_out``); then each faction a change names that is none of those."""
    from lawgraph.core.kiesraad import list_names

    found = {name: set(known) for name, known in today.items()}
    for listed in lists:
        names = list_names(listed)
        match = next((f for f, known in found.items() if names & known), None)
        if match is None:
            short = re.search(r"\(([^)]+)\)\s*$", listed)
            match = short.group(1) if short else listed
        found[match] = found.get(match, set()) | names
    for listed in spelled:
        names = list_names(listed)
        match = next((f for f, known in found.items() if names & known), None)
        if match is not None:
            found[match] |= names
    _named_as_told(found, set(today), changes)
    every = {alias for known in found.values() for alias in known}
    for change in changes:
        for name in (change.source, change.to, *change.sources):
            if (
                name
                and name.upper() not in every
                and name.replace(".", "").upper() not in every
            ):
                found.setdefault(name, aliases(name))
    return found


def _named_as_told(
    found: dict[str, set[str]], keep: set[str], changes: list[Change]
) -> None:
    """Each faction not of today by the name the changes call it most (``PvdA``, not the
    Kiesraad's ``P.v.d.A.``)."""
    told = Counter(n for c in changes for n in (c.source, c.to, *c.sources) if n)
    for name in [n for n in found if n not in keep]:
        names = [n for n in told if n.upper() in found[name]]
        best = max(names, key=lambda n: told[n], default=name)
        if best != name and best not in found:
            found[best] = found.pop(name)


def canonical(changes: list[Change], factions: dict[str, set[str]]) -> list[Change]:
    """The changes with each faction by the name of the faction it is one of the names of
    (``factions``: name to its names, upper case): ``Partij voor de Vrijheid`` is ``PVV``."""
    by_alias = {alias: name for name, known in factions.items() for alias in known}

    def one(name: str | None) -> str | None:
        if not name:
            return name
        return by_alias.get(
            name.upper(), by_alias.get(name.replace(".", "").upper(), name)
        )

    return [
        replace(
            c,
            source=one(c.source),
            to=one(c.to),
            sources=tuple(one(n) or n for n in c.sources),
        )
        for c in changes
    ]


def aliases(abbreviation: str, path: str = "") -> set[str]:
    """The names a faction is matched by: its abbreviation, without dots, and the full name
    its page's path spells (``/fractie/forum_voor_democratie``)."""
    found = {abbreviation.upper(), abbreviation.replace(".", "").upper()}
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    if slug:
        found.add(slug.replace("_", " ").upper())
    return found


# ── the factions regrouped, as a whole item tells it ───────────────────────────

_FROM = (
    r"(?:de ([\w-]+?)-fractie|de fractie van ([A-Z][^.(,]*?)"
    r"(?= \(| in de| stappen| maar| met|\s*[.,]))"
)
_INTO = r"(Fractie-[A-Z][\w']*(?:[ -](?:van|de|der|den|[A-Z][\w']*))*)"
# "X en Y stappen uit de fractie van F … sluiten zich aan bij de Fractie-Z"
_BOTH_JOIN = re.compile(
    rf"({_NAME}) en ({_NAME}) stappen uit {_FROM}\s*\..*?sluiten zich aan bij de {_INTO}"
)
# "X maakt geen deel meer uit van de fractie van F … Hij gaat verder als Fractie-Z"
_ALONE_ON = re.compile(
    rf"({_NAME}) maakt geen deel meer uit van {_FROM}.{{0,200}}?verder (?:in|als) (?:de )?{_INTO}"
)
# "De vijf leden van de Fractie-Z zijn: A , B en C" (from "senatoren van de fractie van F")
_MEMBERS_ARE = re.compile(rf"De \w+ leden van de {_INTO} zijn: (.+?)\s*\.")
_OUT_OF = re.compile(rf"senatoren van {_FROM}")
# "Van Wely sluit zich aan bij de Fractie-Z", "Hij heeft zich … aangesloten bij de Fractie-Z"
_JOINS_GROUP = re.compile(
    rf"({_NAME}) (?:sluit zich aan bij|heeft zich [^.]*?aangesloten bij) de {_INTO}"
)
_LEFT_GROUP = re.compile(rf"(?:uit|lid meer van) {_FROM}")
# "X van F en zijn fractiegenoot Y zijn uit de F-fractie gestapt … onder de naam Fractie-Z"
_PAIR_SPLIT = re.compile(
    rf"({_NAME}) van [^.]*? en zijn fractiegenoot ({_NAME}) zijn uit {_FROM} gestapt"
    rf".*?onder de naam {_INTO}"
)
# "Fractie-Nanninga , tot voor kort de Fractie-Van Pareren geheten"
_RENAMED = re.compile(rf"{_INTO} ,? tot voor kort de {_INTO} geheten")
# "afscheid genomen van de senatoren A (F), B (F) en C (F). Zij worden … Tweede Kamer"
_TO_TK_LIST = re.compile(
    r"afscheid genomen van de senatoren (.+?)\s*\. Zij [^.]*Tweede Kamer"
)
# "De VVD-senatoren X en Y verlaten de Eerste Kamer"
_PAIR_GONE = re.compile(
    rf"De ([\w-]+)-senatoren ({_NAME}) en ({_NAME}) verlaten de Eerste Kamer"
)


def _regrouped(item: Article, year: int, read: list[Change]) -> list[Change]:
    """What a whole item tells of factions regrouped and members gone together, across its
    sentences: two who leave a faction for another, a split of many, a rename."""
    text, head = item.text, item.headline
    since = re.search(rf"met ingang van (?:\w+dag )?{_DAY}", text)
    day = (iso_day(since.group(0), year) if since else None) or item.date
    if m := _BOTH_JOIN.search(text):
        f = m.group(3) or m.group(4)
        return [
            Change("overstap", day, head, source=f, to=m.group(5), member=surname(n))
            for n in (m.group(1), m.group(2))
        ]
    if m := _PAIR_SPLIT.search(text):
        f = m.group(3) or m.group(4)
        return [
            Change("afsplitsing", day, head, source=f, to=m.group(5), member=surname(n))
            for n in (m.group(1), m.group(2))
        ]
    if (m := _MEMBERS_ARE.search(text)) and (out := _OUT_OF.search(text)):
        f = out.group(1) or out.group(2)
        return [
            Change("afsplitsing", day, head, source=f, to=m.group(1), member=surname(n))
            for n, _ in _named_list(m.group(2) + " (x)")
        ]
    if any(c.kind in ("overstap", "afsplitsing") for c in read):
        return []
    if m := _ALONE_ON.search(text):
        return [
            Change(
                "afsplitsing",
                day,
                head,
                source=m.group(2) or m.group(3),
                to=m.group(4),
                member=surname(m.group(1)),
            )
        ]
    if (m := _JOINS_GROUP.search(text)) and (left := _LEFT_GROUP.search(text)):
        member = m.group(1)
        if member.split()[-1] in ("Hij", "Zij"):
            member = _subject(text)
        return (
            [
                Change(
                    "overstap",
                    day,
                    head,
                    source=left.group(1) or left.group(2),
                    to=m.group(2),
                    member=surname(member),
                )
            ]
            if member
            else []
        )
    if m := _RENAMED.search(text):
        return [Change("hernoeming", day, head, source=m.group(2), to=m.group(1))]
    if m := _TO_TK_LIST.search(text):
        return [
            Change("vertrek", item.date, head, source=f, member=surname(n))
            for n, f in _named_list(m.group(1))
        ]
    if m := _PAIR_GONE.search(text):
        return [
            Change("vertrek", item.date, head, source=m.group(1), member=surname(n))
            for n in (m.group(2), m.group(3))
        ]
    return []


def _subject(text: str) -> str:
    """The member an item opens with (``Senator Lennart van der Linden is …``)."""
    m = re.match(
        rf"(?:Senator |senator |Eerste Kamerlid )?({_NAME}) (?:is|heeft|wordt|maakt)\b",
        text,
    )
    return m.group(1) if m else ""


# ── the headline, where the text says no more ──────────────────────────────────

_H_GONE = re.compile(
    rf"^(?:Eerste Kamerlid |Senator |senator )?({_NAME}) {_IN_BRACKETS}"
    r" (?:verlaat|vertrekt uit|vertrokken uit) (?:de )?(?:Eerste )?Kamer"
)
_H_GONE_ROLE = re.compile(
    rf"^([\w-]+?)-(?:fractievoorzitter|senator) ({_NAME})"
    r" (?:verlaat|vertrekt uit) (?:de )?(?:Eerste )?Kamer"
)
_H_DIED = re.compile(
    rf"^(?:Eerste Kamerlid |Senator |senator )?({_NAME}) {_IN_BRACKETS} overleden"
)
_H_SWORN = re.compile(
    rf"^(?:Eerste Kamerlid |Senator |senator )?({_NAME}) {_IN_BRACKETS}"
    r" (?:is )?(?:beëdigd|geïnstalleerd)"
)
_H_SWORN_LIST = re.compile(
    r"^(?:Eerste Kamerleden |Senatoren )?(.+?) (?:beëdigd|geïnstalleerd)"
    r" als (?:Eerste Kamerlid|lid)"
)
_H_SWORN_NAMED = re.compile(rf"^Beëdiging Eerste Kamerlid ({_NAME})$")
_FOR_FACTION = re.compile(
    r"(?:voor de|namens de|lid van de) (?!Eerste )([\w-]+?)(?:-fractie)?[ ,.]"
)


def _headline(item: Article, year: int, read: list[Change]) -> list[Change]:
    """What the headline tells when the text's sentences told nothing of that member: older
    items put the member and faction there and little else (``Jacob Kohnstamm (D66)
    verlaat de Eerste Kamer``)."""
    told = {member_key(c.member) for c in read}
    head = item.headline
    opening = _sentences(item.text)
    day = _day_in(opening[0], item, year) if opening else item.date
    if m := _H_GONE.search(head) or _H_DIED.search(head):
        if member_key(m.group(1)) not in told:
            return [
                Change(
                    "vertrek", day, head, source=m.group(2), member=surname(m.group(1))
                )
            ]
    if m := _H_GONE_ROLE.search(head):
        if member_key(m.group(2)) not in told:
            return [
                Change(
                    "vertrek", day, head, source=m.group(1), member=surname(m.group(2))
                )
            ]
    sworn = [c for c in read if c.kind == "beëdiging"]
    if not sworn and (m := _H_SWORN_LIST.search(head)) and " en " in m.group(1):
        return [
            Change("beëdiging", item.date, head, to=f, member=surname(n))
            for n, f in _named_list(m.group(1))
        ]
    if m := _H_SWORN.search(head):
        if member_key(m.group(1)) not in told:
            return [
                Change(
                    "beëdiging",
                    item.date,
                    head,
                    to=m.group(2),
                    member=surname(m.group(1)),
                )
            ]
    if m := _H_SWORN_NAMED.search(head):
        name = m.group(1)
        if member_key(name) not in told:
            near = re.search(rf"{re.escape(surname(name))}\s*{_IN_BRACKETS}", item.text)
            faction = near.group(1) if near else None
            if faction is None and (f := _FOR_FACTION.search(item.text)):
                faction = f.group(1)
            return [
                Change("beëdiging", item.date, head, to=faction, member=surname(name))
            ]
    if re.search(
        r"senatoren (?:beëdigd|geïnstalleerd)|Kamerleden (?:beëdigd|geïnstalleerd)",
        head,
    ):
        first = next(
            (
                x
                for x in _sentences(item.text)
                if re.search(r"beëdigd|geïnstalleerd", x)
            ),
            "",
        )
        return [
            Change("beëdiging", item.date, head, to=f, member=surname(n))
            for n, f in _NAMED_WITH.findall(first)
            if member_key(n) not in told
        ]
    if re.search(r"^Senatoren .+ vertrekken uit", head):
        return [
            Change("vertrek", day, head, source=f, member=surname(n))
            for n, f in _NAMED_WITH.findall(item.text[:600])
            if member_key(n) not in told
        ]
    return []
