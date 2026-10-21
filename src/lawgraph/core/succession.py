"""Old law to new law: where an official source places each article of the old law in the new
law of a recodification, checked against the text of both.

A reader of a source gives rows: a part of an old article and its place as the source writes
it (``core.transposition_tables`` for a table in a PDF, ``core.transposition_xml`` for one in
the XML of a Kamerstuk, ``core.concordance_html`` for the concordance table of an EU act).
``place`` keeps a row whose place is an article the new law holds, with every lid it names,
from an article the old law holds: those become one ``TRANSPOSED_TO`` per pair of articles,
with the parts in its ``meta.parts``. A place may name another law ("afdeling 3.5 Awb",
"16.52 Omgevingswet"): then it is an article of that law (``Place.law``; the caller gives the
articles of each such law). A row may name a run of articles ("5.8 t/m 5.14"): it stands for
every article of the law from the first to the last, in the order of the law; a run of old
articles placed in a run of new ones as long ("Artikelen 1 tot en met 7" in "Artikelen 1 tot
en met 7") pairs them one by one. An old place that is a division of the old law ("§ 1.2",
"titel 10.5") stands for each article of it (the part keeps the division as ``via``). A part
keeps the place as the source writes it (``to``), read: the number of the article of its pair
(``article``) and the leden it names (``leden``).

What the source answers instead of a place is an outcome (``outcome``): the part lapses
(``vervallen``), is not taken over (``niet_overgenomen``: "niet overgenomen", "keert niet
terug", "–"), stays in a law (``blijft_in:<law as written>``: "Blijft in Wm"; a place in
the old law itself, "12 en 47b WEC" in a table of the WEC) or goes to another law it names
without an article of it (``naar:<law as written>``: "naar de Gratiewet (via de
invoeringswet)", "Wordt later ingevoegd in de Omgevingswet"). Such a part is no gap. A
besluit the source names by no name ("Besluit B2") is no law: a gap.

Nothing is filled in or corrected: a row that does not hold, and an article of the old law in
force for which no row of any source gives an article or an outcome, is a ``Gap``, with what
the source writes there. A division of the new law as a place ("afdeling 15.2", "B6H3": Boek
6, Hoofdstuk 3) is read and checked against the divisions the articles of the new law stand in
(``LawArticle.divisions``), but places nothing: the graph has no node of a division to point
at. A number of the source is that of a law in any case and without its spaces (``509ibis``
is ``509i bis``, ``9 bis`` is ``9bis``): the law's number is the one read.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal, NotRequired, TypedDict

from lawgraph.core.xml import collapse_ws

GapKind = Literal[
    # a row
    "unreadable",  # its place reads as no article and as no place that is none
    "no_old_article",  # the old law has no article (or division) of its number
    "no_new_article",  # the new law has no article of the number it names
    "no_lid",  # that article has no lid it names
    "no_law",  # it names another law the graph does not hold
    # an article of the old law in force that no row places in the new law
    "no_row",  # the source has no row for it (only of an old law that goes)
    "no_article",  # the source places it in no article ("Besluit B2")
    "in_division",  # it places it in divisions of the new law only
    "no_division",  # it places it in divisions only, one the new law does not have
    "not_placed",  # each of its places in an article is a gap above
]
ROW_GAPS: tuple[GapKind, ...] = (
    "unreadable",
    "no_old_article",
    "no_new_article",
    "no_lid",
    "no_law",
)

# What the source answers instead of a place, and the mark of a part that is a gap.
LAPSES = "vervallen"
NOT_TAKEN_OVER = "niet_overgenomen"
STAYS_IN = "blijft_in"
MOVES_TO = "naar"
GAP = "gat"

_LAPSES = re.compile(
    r"^(?:komt\s+te\s+)?verval+(?:en|t)\b\.?(?:\s*\([^()\d]*\))?\.?$", re.IGNORECASE
)
_NOT_TAKEN_OVER = re.compile(
    r"^(?:[-–—−_]+"
    r"|niet\s+overgenomen\.?"
    r"|(?:keert|komt)\s+niet\s+terug\.?"
    r"|.*\bwordt\s+niet\s+overgebracht\b.*)$",
    re.IGNORECASE,
)
_STAYS_IN = re.compile(
    r"^blijft\s+(?:bestaan\s+)?in\s+(?:de\s+|het\s+)?"
    r"(?P<law>[^\W\d][^\d,;.()]*?)\s*(?:[\d,;.(].*)?$",
    re.IGNORECASE,
)
# "naar de Gratiewet (via de invoeringswet)", "Wordt later ingevoegd in de Omgevingswet": a
# law by its name (a capital), a note between brackets after it.
_MOVES_TO = re.compile(
    r"^(?:naar|wordt\s+(?:later\s+)?ingevoegd\s+in)\s+(?:de\s+|het\s+)?"
    r"(?P<law>[^\W\d][^\d,;.()]*?)\s*(?:\([^()]*\))?\.?$",
    re.IGNORECASE,
)

# A division as a source names it: "afdeling 15.2", "§ 1.2", "titel 10.5A", "Hfdst. IV",
# "Boek 8"; in the PDF of the new Sv "B6H3" (Boek 6, Hoofdstuk 3), "B6T1.5" (Boek 6,
# Titel 1.5), "B6H4 Afdeling 4.1.3".
_DIVISION_WORDS = {
    "boek": "boek",
    "deel": "deel",
    "hoofdstuk": "hoofdstuk",
    "hoofdstukken": "hoofdstuk",
    "hfdst": "hoofdstuk",
    "hst": "hoofdstuk",
    "titel": "titel",
    "titeldeel": "titel",
    "afdeling": "afdeling",
    "afdelingen": "afdeling",
    "paragraaf": "paragraaf",
    "paragrafen": "paragraaf",
    "§": "paragraaf",
}
_DIVISION_NUMBER = r"[0-9IVXLC]+[a-zA-Z]?(?:\.[0-9]+[a-zA-Z]?)*"
_DIVISION = re.compile(
    rf"(?P<word>{'|'.join(sorted(_DIVISION_WORDS, key=len, reverse=True))})\.?\s*"
    rf"(?P<number>{_DIVISION_NUMBER})(?![\w.])",
    re.IGNORECASE,
)
_COMPACT = re.compile(r"B(?P<book>\d+)(?:(?P<kind>[HT])(?P<number>\d+(?:\.\d+)*))?")
_DIVISION_LEAD = re.compile(
    r"^(?:algemene\s+regeling|algemeen|gere?se?r?veerd)\s*\(?|\)$", re.IGNORECASE
)
_DIVISION_JOIN = re.compile(r"\s*(?:,|\ben\b)\s*")


@dataclass(frozen=True)
class Place:
    """A place in the new law a source gives: an article with the leden it names, or none."""

    text: str  # as the source writes it: "2.8.6, 1"
    article: str | None  # "2.8.6"; None for a place that is no article
    leden: tuple[str, ...]
    general: bool = False  # "algemene regeling 2.1.10": the general rule that covers it
    readable: bool = True
    through: str | None = (
        None  # the last article of a run "5.8 t/m 5.14"; no leden then
    )
    law: str | None = None  # another law it names, as written: "Awb"; None: the new law


@dataclass(frozen=True)
class SourceRow:
    """A place the source gives a part of an article of the old law."""

    old_article: str  # "126ffa"; or a division of the old law: "§ 1.2"
    part: str  # "2 a"; empty for the whole article
    place: Place
    where: str  # where in the source: "p. 94"
    source: str = ""  # the identifier of the source: "blg-1081574"
    old_through: str | None = None  # the last article of a run of old articles
    via: str = ""  # the division of the old law the row names, as written: "§ 1.2"


@dataclass(frozen=True)
class LawArticle:
    """An article of a law as the graph holds it."""

    id: str
    number: str
    leden: frozenset[str] = frozenset()
    repealed: bool = False
    # the divisions it stands in, outermost first, each as ``division_label`` reads it
    divisions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Gap:
    """A row that does not hold, or an article of the old law without a place."""

    kind: GapKind
    old_article: str
    part: str = ""
    text: str = ""  # the place as the source writes it; the places of an article
    where: str = ""
    source: str = ""


# A part of the old article and its place: as the source writes it (``to``) and read; of a
# division of the old law, that division (``via``).
PlacedPart = TypedDict(
    "PlacedPart",
    {
        "from": str,
        "to": str,
        "article": str,
        "leden": list[str],
        "via": NotRequired[str],
    },
)
# A part of the old article the source places in no article: what it writes (``to``) and
# its outcome, ``gat`` for a part that does not hold.
UnplacedPart = TypedDict(
    "UnplacedPart", {"from": str, "to": str, "outcome": str, "via": NotRequired[str]}
)


@dataclass
class Unplaced:
    """The parts of an old article the source places in no article of the new law, the
    sources that say so, and the outcome of the whole: ``gat`` for an article that is a
    gap, else the one outcome its parts share (None when they differ). Of an article that
    is no gap, only the parts with an outcome."""

    parts: list[UnplacedPart] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    outcome: str | None = None


@dataclass
class Placed:
    """The pairs of articles with their parts and the sources that give them, the parts of
    the old articles the source places in no article (by the id of the old article), the
    gaps, and the numbers of the old articles a row names."""

    pairs: dict[tuple[str, str], list[PlacedPart]] = field(default_factory=dict)
    sources: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    unplaced: dict[str, Unplaced] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    named: set[str] = field(default_factory=set)


def outcome(text: str) -> str | None:
    """The outcome a place that is no article says: ``vervallen``, ``niet_overgenomen``,
    ``blijft_in:<law>``, ``naar:<law>``; None for any other place."""
    text = collapse_ws(text)
    if _LAPSES.match(text):
        return LAPSES
    if _NOT_TAKEN_OVER.match(text):
        return NOT_TAKEN_OVER
    if match := _STAYS_IN.match(text):
        return f"{STAYS_IN}:{match['law'].strip()}"
    if (match := _MOVES_TO.match(text)) and match["law"][:1].isupper():
        return f"{MOVES_TO}:{match['law'].strip()}"
    return None


def division_label(text: str) -> str | None:
    """The label of a division as ``LawArticle.divisions`` holds it: ``§ 1.2`` and
    ``Paragraaf 1.2`` are ``paragraaf 1.2``, ``Titel 10.5A`` is ``titel 10.5a``; None for a
    text that names no one division."""
    match = _DIVISION.fullmatch(collapse_ws(text))
    if match is None:
        return None
    return f"{_DIVISION_WORDS[match['word'].lower()]} {match['number'].lower()}"


def divisions(text: str) -> list[tuple[str, ...]] | None:
    """The divisions a place names, each the path of labels down to it (``B6H3`` is
    ``("boek 6", "hoofdstuk 3")``; ``afdelingen 16.3 en 23.1`` two paths of one label); None
    for a place that is not only divisions."""
    text = _DIVISION_LEAD.sub("", collapse_ws(text)).strip()
    if not text:
        return None
    found: list[tuple[str, ...]] = []
    word = ""
    for item in _DIVISION_JOIN.split(text):
        path = _division_path(item, word)
        if path is None:
            return None
        word = path[-1].split()[0]
        found.append(path)
    return found


def _division_path(item: str, word: str) -> tuple[str, ...] | None:
    """The path of one item of a list of divisions; a bare number is one of the *word*
    before it ("hoofdstuk 13 en 15")."""
    path: list[str] = []
    rest = item
    if compact := _COMPACT.match(rest):
        path.append(f"boek {compact['book']}")
        if compact["kind"]:
            kind = "hoofdstuk" if compact["kind"] == "H" else "titel"
            path.append(f"{kind} {compact['number']}")
        rest = rest[compact.end() :].strip()
    while rest:
        match = _DIVISION.match(rest)
        if match is None:
            if path or not word or not re.fullmatch(_DIVISION_NUMBER, rest):
                return None
            return (f"{word} {rest.lower()}",)
        label = division_label(match[0])
        assert label is not None
        path.append(label)
        rest = rest[match.end() :].strip()
    return tuple(path) or None


def in_division(article: LawArticle, path: tuple[str, ...]) -> bool:
    """Whether *article* stands in the division of *path*: each of its labels among the
    divisions of the article, in their order."""
    labels = iter(article.divisions)
    return all(label in labels for label in path)


def place(
    rows: Iterable[SourceRow],
    old: dict[str, LawArticle],
    new: dict[str, LawArticle],
    *,
    replaced: bool = True,
    laws: Mapping[str, dict[str, LawArticle] | None] | None = None,
) -> Placed:
    """Check *rows* against the articles of the *old* and the *new* law (by number, in the
    order of the law), and of the other *laws* a place names (by the name as written; None:
    the graph does not hold it). An article of the old law no row names is a gap when the
    old law goes (*replaced*), not when it stays: then the source names only what moves."""
    check = _Check(old, new, laws or {})
    for row in rows:
        each = check.each_article(row)
        if isinstance(each, list):
            check.rows += each
        else:
            check.placed.gaps.append(_gap(each, row))
    for row in check.rows:
        check.read(row)
    check.articles_without_place(replaced)
    return check.placed


class _Check:
    """The rows of a source checked one by one, into ``placed``."""

    def __init__(
        self,
        old: dict[str, LawArticle],
        new: dict[str, LawArticle],
        laws: Mapping[str, dict[str, LawArticle] | None],
    ) -> None:
        self.old, self.new, self.laws = old, new, laws
        self.placed = Placed()
        self.rows: list[SourceRow] = []  # each a row of one old article
        self._numbers: dict[int, dict[str, str]] = {}
        self._own: dict[str, list[SourceRow]] = {}  # the rows of each old article
        # per row placed in divisions: whether the law has them
        self._divisions: dict[int, bool] = {}
        self._unplaced: dict[str, list[tuple[SourceRow, str]]] = {}

    def numbers(self, law: dict[str, LawArticle]) -> dict[str, str]:
        """The numbers of *law* by their folded form (``_folded``), the first kept."""
        if id(law) not in self._numbers:
            numbers: dict[str, str] = {}
            for number in law:
                numbers.setdefault(_folded(number), number)
            self._numbers[id(law)] = numbers
        return self._numbers[id(law)]

    def target(self, place_: Place) -> dict[str, LawArticle] | None:
        """The articles of the law of *place_*: the new law, or the other law it names."""
        return self.new if place_.law is None else self.laws.get(place_.law)

    def each_article(self, row: SourceRow) -> list[SourceRow] | GapKind:
        """*row* once per article of its runs (two runs as long one by one), its numbers as
        the laws write them; a division of the old law once per article of it. The gap of
        a run whose ends a law lacks."""
        target = self.target(row.place) or {}  # a law not found: a gap of the row
        row = _as_in_laws(row, self.numbers(self.old), self.numbers(target))
        olds = _run(self.old, row.old_article, row.old_through)
        if row.old_through is None and row.old_article not in self.old:
            if division := self._division_articles(row.old_article):
                olds, row = division, replace(row, via=row.old_article)
        if olds is None:
            return "no_old_article"
        place_ = row.place
        if place_.through is None or place_.article is None:
            news: list[str | None] = [place_.article]
        else:
            run = _run(target, place_.article, place_.through)
            if run is None:
                return "no_new_article"
            news = list(run)
        pairs = (
            list(zip(olds, news, strict=True))
            if len(olds) == len(news) > 1
            else [(number, article) for number in olds for article in news]
        )
        return [
            replace(
                row,
                old_article=number,
                old_through=None,
                place=replace(place_, article=article, through=None),
            )
            for number, article in pairs
        ]

    def _division_articles(self, text: str) -> list[str] | None:
        """The numbers of the articles of the old law in the divisions *text* names, in its
        order: also those repealed since, as a table names the articles of its day."""
        paths = divisions(text)
        if not paths:
            return None
        found = [
            number
            for number, article in self.old.items()
            if any(in_division(article, p) for p in paths)
        ]
        return found or None

    def read(self, row: SourceRow) -> None:
        """Check one row of one old article."""
        if row.old_article not in self.old:
            self.placed.gaps.append(_gap("no_old_article", row))
            return
        self.placed.named.add(row.old_article)
        self._own.setdefault(row.old_article, []).append(row)
        place_ = row.place
        said = outcome(place_.text) if place_.article is None else None
        if place_.law and self.target(place_) is self.old:  # "12 en 47b WEC" of the WEC
            said = f"{STAYS_IN}:{place_.law}"
        if said is None:
            gap = self._row_gap(row)
            if gap is None and place_.article is not None:
                self._pair(row)
                return
            if gap is not None and (found := _gap(gap, row)) not in self.placed.gaps:
                self.placed.gaps.append(found)  # of a division of the old law once
        self._unplaced.setdefault(row.old_article, []).append((row, said or GAP))

    def _row_gap(self, row: SourceRow) -> GapKind | None:
        place_ = row.place
        if not place_.readable:
            return "unreadable"
        target = self.target(place_)
        if target is None:
            return "no_law"
        if place_.article is None:
            if paths := divisions(_without_law(place_)):
                self._divisions[id(row)] = all(
                    any(in_division(a, p) for a in target.values()) for p in paths
                )
            return None
        article = target.get(place_.article)
        if article is None:
            return "no_new_article"
        if not set(place_.leden) <= article.leden:
            return "no_lid"
        return None

    def _pair(self, row: SourceRow) -> None:
        assert row.place.article is not None
        target = self.target(row.place) or {}
        pair = (self.old[row.old_article].id, target[row.place.article].id)
        parts = self.placed.pairs.setdefault(pair, [])
        part: PlacedPart = {
            "from": row.part,
            "to": row.place.text,
            "article": row.place.article,
            "leden": list(row.place.leden),
        }
        if row.via:
            part["via"] = row.via
        if part not in parts:
            parts.append(part)
        sources = self.placed.sources.setdefault(pair, [])
        if row.source not in sources:
            sources.append(row.source)

    def articles_without_place(self, replaced: bool) -> None:
        """The gaps of the articles of the old law in force that no row places in an
        article, in the order of the law; and what the source says of the parts of each old
        article it places in no article."""
        placed = {old for old, _ in self.placed.pairs}
        gaps: set[str] = set()
        for number, article in self.old.items():
            if article.repealed or article.id in placed:
                continue
            gap = self._article_gap(number, self._own.get(number, []))
            if gap is not None and (replaced or gap.kind != "no_row"):
                self.placed.gaps.append(gap)
                gaps.add(number)
        for number, said in self._unplaced.items():
            unplaced = _unplaced(said, gap=number in gaps)
            if unplaced.parts:
                self.placed.unplaced[self.old[number].id] = unplaced

    def _answered(self, row: SourceRow) -> bool:
        """Whether the source answers for the part of *row* with an outcome."""
        return any(
            r is row and o != GAP for r, o in self._unplaced.get(row.old_article, [])
        )

    def _article_gap(self, number: str, rows: list[SourceRow]) -> Gap | None:
        if not rows:
            return Gap("no_row", number)
        open_ = [r for r in rows if not self._answered(r)]
        if not open_:
            return None  # the source answers for each part
        texts = "; ".join(dict.fromkeys(r.place.text for r in open_))
        kind: GapKind = "not_placed"
        if all(id(r) in self._divisions for r in open_):
            has = all(self._divisions[id(r)] for r in open_)
            kind = "in_division" if has else "no_division"
        elif all(r.place.article is None and r.place.readable for r in open_):
            kind = "no_article"
        return Gap(kind, number, "", texts, open_[0].where, open_[0].source)


def _unplaced(said: list[tuple[SourceRow, str]], *, gap: bool) -> Unplaced:
    """What the source says of the parts of one old article it places in no article: each
    outcome, and of an article that is a gap each part that does not hold (``gat``)."""
    unplaced = Unplaced()
    for row, outcome_ in said:
        if outcome_ == GAP and not gap:
            continue
        part: UnplacedPart = {
            "from": row.part,
            "to": row.place.text,
            "outcome": outcome_,
        }
        if row.via:
            part["via"] = row.via
        if part not in unplaced.parts:
            unplaced.parts.append(part)
        if row.source not in unplaced.sources:
            unplaced.sources.append(row.source)
    outcomes = {part["outcome"] for part in unplaced.parts}
    unplaced.outcome = GAP if gap else (outcomes.pop() if len(outcomes) == 1 else None)
    return unplaced


def _without_law(place_: Place) -> str:
    """The text of *place_* without the other law it names at its end, and its note."""
    text = collapse_ws(place_.text)
    if place_.law and (at := text.rfind(place_.law)) > 0:
        return text[:at].rstrip(" ,(")
    return text


def _folded(number: str) -> str:
    return "".join(number.lower().split())


def _as_in_laws(
    row: SourceRow, olds: dict[str, str], news: dict[str, str]
) -> SourceRow:
    """*row* with each number it names as the law writes it (*olds*, *news*: numbers by
    their folded form)."""

    def own(numbers: dict[str, str], number: str | None) -> str | None:
        return number and numbers.get(_folded(number), number)

    return replace(
        row,
        old_article=own(olds, row.old_article) or row.old_article,
        old_through=own(olds, row.old_through),
        place=replace(
            row.place,
            article=own(news, row.place.article),
            through=own(news, row.place.through),
        ),
    )


def _gap(kind: GapKind, row: SourceRow) -> Gap:
    """The gap of *row*, of the old article or division as the source names it."""
    old = row.via or (
        f"{row.old_article} t/m {row.old_through}"
        if row.old_through
        else row.old_article
    )
    return Gap(kind, old, row.part, row.place.text, row.where, row.source)


def _run(law: dict[str, LawArticle], first: str, last: str | None) -> list[str] | None:
    """The numbers of the articles of *law* from *first* through *last* in its order; just
    *first* without a *last*, also when the law lacks it (a row gap then); None for a run
    whose ends the law lacks or that runs backwards."""
    if last is None:
        return [first]
    numbers = list(law)
    if first not in law or last not in law:
        return None
    start, end = numbers.index(first), numbers.index(last)
    return numbers[start : end + 1] if start <= end else None
