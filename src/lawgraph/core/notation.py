"""What a person types to find one thing: an identifier or a citation, taken apart.

Pure: a text and the law names known to the graph in, a ``Notation`` out. Whether the
thing exists is for the caller to ask. The article grammar is that of the citation
extractor (``core.citations``), so a citation that is understood in a judgment is
understood in a search box, with the same numbers (``6:162``, ``36e``, ``3.26``), the
same qualifiers (``lid 2``) and the same treatment of the books of the Burgerlijk Wetboek.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from lawgraph.core.citations import (
    ARTICLE_HEAD_RE,
    ARTICLE_NUMBER_PATTERN,
    LAW_CONNECTOR_RE,
    DutchCitationExtractor,
    name_key,
    parse_article_numbers,
)
from lawgraph.core.code_families import CODE_FAMILIES
from lawgraph.core.identifiers import is_bwb_id, is_ecli, parse_celex

NotationKind = Literal[
    "ecli",
    "bwb",
    "celex",
    "dossier",
    "document",
    "article",
    "commitment",
    "publication",
]
LawTier = Literal["code", "title", "prefix", "contains"]

# The number of a toezegging: "TZ202603-130".
_COMMITMENT_RE = re.compile(r"^TZ\d{6}-\d{1,5}$", re.IGNORECASE)

# A bare number is a dossier only when it has the length of one; behind "Kamerstuk" or
# "dossier" any number is.
_BARE_DOSSIER_DIGITS = 5
_MIN_NAME_PART = 3  # the shortest text that is looked for inside law names
_MIN_CONTAINED = 4
_LAW_LIMIT = 6

# "Kamerstuk 36327", "Kamerstukken II 2020/21, 36327, nr. 3", "kst-36327-3", "36 327",
# "36327-3", "29684-I", "29684-I-3", "35925 VII", and a paper of the Eerste Kamer by its
# letter: "Kamerstukken I 2025/26, 36799, A". The suffix (a budget chapter) is letters
# behind a hyphen; a number behind a hyphen is the paper (ondernummer), and so are letters
# behind a comma.
_KAMERSTUK_RE = re.compile(
    r"""^
    (?:(?P<keyword>kamerstuk(?:ken)?|kst[.-]?|dossier)\s*
       (?:I{1,2}\b\s*)?
       (?:\d{4}/(?:\d{4}|\d{2})\s*,?\s*)?
    )?
    (?P<number>\d{2}\s\d{3}(?!\d)|\d{1,6})
    (?:-(?P<suffix>[A-Z]{1,6})(?![A-Z0-9])|\s+(?P<spaced>[IVXLC]{1,5})(?![A-Z0-9]))?
    (?:\s*,?\s*nr\.?\s*(?P<nr>\d{1,4}|[A-Z]{1,2})|\s*-\s*(?P<seq>\d{1,4})
       |\s*,\s*(?P<letter>[A-Z]{1,2})(?![A-Z0-9]))?
    $""",
    re.IGNORECASE | re.VERBOSE,
)

# "Staatsblad 2026, 94", "Stb. 2026, 94": a publication in the Staatsblad, an instrument of
# its own (``stb_2026_94``, ``core.bwb_xml.publication_key``).
_STAATSBLAD_RE = re.compile(
    r"^(?:staatsblad|stb\.?)\s*(?P<year>\d{4})\s*,?\s*(?:nr\.?\s*)?(?P<number>\d{1,5})$",
    re.IGNORECASE,
)

# "Sr 287", "Grondwet 1", "Wetboek van Strafrecht art. 287": the law, then the number.
_LAW_THEN_NUMBER_RE = re.compile(
    rf"^(?P<law>.+?)\s+(?:(?:art\.?|artikel)\s+)?(?P<number>{ARTICLE_NUMBER_PATTERN})$",
    re.IGNORECASE,
)
# "boek 6 art 162", "boek 6, artikel 162 BW": a book of a code, then the article in it
_BOOK_THEN_ARTICLE_RE = re.compile(
    rf"^boek\s+(?P<book>\d{{1,2}}[a-z]?)\s*,?\s*(?:art\.?|artikel)\s+"
    rf"(?P<number>{ARTICLE_NUMBER_PATTERN})(?:\s+(?P<code>\D.*))?$",
    re.IGNORECASE,
)
# "6:162 BW", "287 Sr": a number, then the law, as lawyers write it in running text
_NUMBER_THEN_LAW_RE = re.compile(
    rf"^(?P<number>{ARTICLE_NUMBER_PATTERN})\s+(?P<law>\D.*)$", re.IGNORECASE
)


@dataclass(frozen=True)
class ArticleRef:
    """One cited article: *number* as the article is stored, in the law with *law_id*.

    *law_id* is a BWB id or a CELEX id, ``None`` when the citation names no law. In the
    Burgerlijk Wetboek every book is a regulation and its articles are stored without the
    book: ``6:162 BW`` is ``162`` of the regulation that is book 6.
    """

    law_id: str | None
    number: str


@dataclass(frozen=True)
class Notation:
    """A recognised notation.

    * ``ecli``, ``bwb``, ``celex``: *identifier* (upper case).
    * ``publication``: *identifier* of a Staatsblad publication (``stb-2026-94``).
    * ``dossier``: *dossier* number and its *suffix* (``29684``, ``I``), or ``None``.
    * ``document``: a dossier and the *sequence* (ondernummer) of one paper in it.
    * ``article``: *articles* (several for ``artikel 36e en 36f Sr``) and their *qualifier*
      (``derde lid``); with *choice* the articles are the ones a citation may mean
      (``art. 3 BW``: article 3 of every book of the code).
    """

    kind: NotationKind
    identifier: str | None = None
    dossier: str | None = None
    suffix: str | None = None
    sequence: str | None = None
    articles: tuple[ArticleRef, ...] = ()
    qualifier: str | None = None
    # The articles are alternatives, not cited together: a citation of a code that leaves
    # the book open (``art. 3 BW``: article 3 of which book?).
    choice: bool = False


@dataclass(frozen=True)
class LawMatch:
    """A law a text may name: by abbreviation, by full name, by the start or a part of one."""

    law_id: str
    tier: LawTier


def _dossier(text: str) -> Notation | None:
    match = _KAMERSTUK_RE.match(text)
    if not match:
        return None
    number = re.sub(r"\s", "", match["number"])
    keyword = match["keyword"]
    if not keyword and (len(number) != _BARE_DOSSIER_DIGITS or match["spaced"]):
        return None
    suffix = match["suffix"] or match["spaced"]
    sequence = match["nr"] or match["seq"] or match["letter"]
    return Notation(
        kind="document" if sequence else "dossier",
        dossier=number,
        suffix=suffix.upper() if suffix else None,
        sequence=sequence.upper() if sequence else None,
    )


class NotationParser:
    """Reads notations against the laws of the graph.

    *code_aliases* maps an abbreviation (``Sr``) to the BWB or CELEX id of its law; the
    books of a code (``BW1`` ... ``BW10``) let ``BW`` resolve through the book in the
    article number. *names* maps a lower-case law name to every id that carries it.
    """

    def __init__(
        self, code_aliases: Mapping[str, str], names: Mapping[str, Sequence[str]]
    ) -> None:
        self._codes = {
            code.strip().upper(): law_id
            for code, law_id in code_aliases.items()
            if code.strip().upper() not in CODE_FAMILIES
        }
        self._names: dict[str, list[str]] = {}
        for name, ids in names.items():
            known = self._names.setdefault(name_key(name), [])
            known.extend(i for i in ids if i not in known)
        # A name two laws share would cite whichever came first, so a citation cannot
        # use it; asking for the law by that name lists both (``law_matches``).
        self._extractor = DutchCitationExtractor(
            code_aliases=dict(code_aliases),
            name_aliases={n: ids[0] for n, ids in self._names.items() if len(ids) == 1},
        )

    def parse(self, query: str) -> Notation | None:
        """The notation *query* is, or ``None`` when it is words to search for."""
        text = " ".join(query.split())
        if not text:
            return None
        if is_ecli(text):
            return Notation(kind="ecli", identifier=text.upper())
        if is_bwb_id(text):
            return Notation(kind="bwb", identifier=text.upper())
        if parse_celex(text):
            return Notation(kind="celex", identifier=text.upper())
        if _COMMITMENT_RE.match(text):
            return Notation(kind="commitment", identifier=text.upper())
        if staatsblad := _STAATSBLAD_RE.match(text):
            number = str(int(staatsblad["number"]))
            return Notation(
                kind="publication", identifier=f"stb-{staatsblad['year']}-{number}"
            )
        return _dossier(text) or self._article(text)

    def law_matches(self, text: str) -> list[LawMatch]:
        """The laws *text* may name, best first: code, full name, start of a name, part of one.

        An abbreviation and a full name match whole (case-insensitive, without a leading
        "de" or "het"); shorter names come before longer ones within a tier.
        """
        key = name_key(text)
        bare = re.sub(r"^(?:de|het)\s+", "", key)
        found: dict[str, LawTier] = {}
        for candidate in dict.fromkeys(k for k in (key, bare) if k):
            law_id = self._codes.get(candidate.upper())
            if law_id:
                found.setdefault(law_id, "code")
            for law_id in self._names.get(candidate, []):
                found.setdefault(law_id, "title")
        found.update(self._partial_matches(key, set(found)))
        return [LawMatch(i, tier) for i, tier in found.items()][:_LAW_LIMIT]

    def _partial_matches(self, key: str, known: set[str]) -> dict[str, LawTier]:
        if len(key) < _MIN_NAME_PART:
            return {}
        prefixed: list[tuple[int, str]] = []
        contained: list[tuple[int, str]] = []
        for name, ids in self._names.items():
            if name.startswith(key):
                prefixed.extend((len(name), i) for i in ids if i not in known)
            elif len(key) >= _MIN_CONTAINED and key in name:
                contained.extend((len(name), i) for i in ids if i not in known)
        tiers: tuple[tuple[LawTier, list[tuple[int, str]]], ...] = (
            ("prefix", prefixed),
            ("contains", contained),
        )
        found: dict[str, LawTier] = {}
        for tier, hits in tiers:
            for _, law_id in sorted(hits):
                found.setdefault(law_id, tier)
        return found

    # ── articles ──────────────────────────────────────────────────────────────

    def _article(self, text: str) -> Notation | None:
        if book := _BOOK_THEN_ARTICLE_RE.match(text):
            return _of_book(book["book"], book["number"], book["code"])
        if ARTICLE_HEAD_RE.match(text):
            return self._cited(text)
        for pattern in (_LAW_THEN_NUMBER_RE, _NUMBER_THEN_LAW_RE):
            match = pattern.match(text)
            if match:
                cited = self._cited(f"artikel {match['number']} {match['law']}")
                if cited is not None:
                    return cited
        return None

    def _cited(self, text: str) -> Notation | None:
        """``artikel 6:162 BW`` and its like: the head, then the law that ends the text."""
        head = ARTICLE_HEAD_RE.match(text)
        if not head:
            return None
        qualifier = (head["qual"] or "").strip(", ") or None
        rest = text[head.end() :].strip(" ,.;:")
        numbers = [n.lower() for n in parse_article_numbers(head["nums"])]
        if not rest:
            return _without_law(numbers, qualifier)
        articles = self._articles_of(text, rest, numbers)
        if not articles:
            return _of_code(rest, numbers, qualifier)
        return Notation(kind="article", articles=articles, qualifier=qualifier)

    def _articles_of(
        self, text: str, rest: str, numbers: list[str]
    ) -> tuple[ArticleRef, ...]:
        """The articles a citation names in the law it ends with; none when that law is unknown."""
        named = rest[LAW_CONNECTOR_RE.match(rest).end() :].strip()  # type: ignore[union-attr]
        if is_bwb_id(named) or parse_celex(named):
            return tuple(ArticleRef(named.upper(), n) for n in numbers)
        cited = [
            hit
            for hit in self._extractor.extract(text)
            if not text[len(hit.raw_match or "") :].strip(" ,.;:")
        ]
        return tuple(
            ArticleRef(hit.bwb_id or hit.celex, (hit.article_number or "").lower())
            for hit in cited
        )


def _family(name: str | None) -> dict[str, str] | None:
    """The books of the code *name* names (``BW``, ``Burgerlijk Wetboek``); None for no code
    with books. Without a name, the one code with books there is."""
    if name is None:
        return next(iter(CODE_FAMILIES.values())) if len(CODE_FAMILIES) == 1 else None
    key = LAW_CONNECTOR_RE.sub("", name, count=1).strip(" .,;:").upper()
    for code, books in CODE_FAMILIES.items():
        if key in (code.upper(), *_FAMILY_NAMES.get(code.upper(), ())):
            return books
    return None


# The names a code with books goes by besides its abbreviation.
_FAMILY_NAMES = {"BW": ("BURGERLIJK WETBOEK",)}


def _of_code(rest: str, numbers: list[str], qualifier: str | None) -> Notation | None:
    """``art. 3 BW``: a code with books that the number does not name a book of: the
    article of that number in every book, as a choice. ``art. 6:162 BW`` names its book and
    is read by the extractor before this."""
    books = _family(rest)
    if books is None:
        return None
    articles = tuple(
        ArticleRef(law_id, n)
        for n in numbers
        if ":" not in n
        for law_id in books.values()
    )
    if not articles:
        return None
    return Notation(kind="article", articles=articles, qualifier=qualifier, choice=True)


def _without_law(numbers: list[str], qualifier: str | None) -> Notation:
    """``art. 6:162``, no law: the article of that number in any law, and where the part
    before the colon is a book of the code with books, article ``162`` of that book too."""
    books = _family(None) or {}
    articles: list[ArticleRef] = []
    for n in numbers:
        book, colon, own = n.partition(":")
        if colon and book.upper() in books:
            articles.append(ArticleRef(books[book.upper()], own))
        articles.append(ArticleRef(None, n))
    choice = len(articles) > len(numbers)
    return Notation(
        kind="article", articles=tuple(articles), qualifier=qualifier, choice=choice
    )


def _of_book(book: str, number: str, code: str | None) -> Notation | None:
    """``boek 6 art 162``: article 162 of book 6 of the code (the one code with books when
    the text names none)."""
    books = _family(code)
    law_id = (books or {}).get(book.upper())
    if law_id is None:
        return None
    return Notation(kind="article", articles=(ArticleRef(law_id, number.lower()),))


def native_article_number(bwb_id: str, number: str) -> str:
    """The number an article has in its own book of a code: ``162`` for ``6:162`` under
    BW Boek 6 (BWBR0005289). A number of another book, or of a law that is no book of a
    code (the Awb's ``8:69`` is its own), is left as it is."""
    for books in CODE_FAMILIES.values():
        for book, law_id in books.items():
            prefix = f"{book}:"
            if law_id.upper() == bwb_id.upper() and number.upper().startswith(prefix):
                return number[len(prefix) :]
    return number
