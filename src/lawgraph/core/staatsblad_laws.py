"""A law the Staatsblad published and the BWB does not hold (yet), read from the XML of its
publication (pure, no I/O): the Wetboek van Strafvordering of Stb. 2026, 56.

The XML of a Staatsblad law (the OP schema of officielebekendmakingen.nl) has the elements of
a BWB toestand: ``boek``, ``hoofdstuk``, ``titeldeel``, ``afdeling``, ``paragraaf``,
``artikel`` with ``kop``, ``lid``, ``al`` and ``lijst``. What it lacks are the ids of the BWB
(``stam-id``, ``versie-id``) and the links (``intref``): an article is known by its law and
its number, and a reference inside the law is read from its text (``own_references``).

* A publication **enacts a new law** when its wettekst holds an article of its own (not one
  of a ``wijzig-artikel``) numbered with a figure (``1``, ``2.8.6``). The articles of a law
  that only changes others are numbered with Roman numerals (``ARTIKEL I``, ``IV``), as the
  Aanwijzingen voor de regelgeving have them: such a publication enacts nothing.
* A later publication of the Staatsblad gives a division of such a law a **whole new text**
  when a ``wijzig-artikel`` says "<divisions> van het <law> komt te luiden:" and holds one
  ``wijzig-divisie``: Stb. 2026, 57 gives Boek 1, Hoofdstuk 10, and the Boeken 7 and 8 of
  the Wetboek van Strafvordering of Stb. 2026, 56, which left them "[Gereserveerd]". The
  law is read with that text in place (``law_articles``), each article with the publication
  it comes from (``bron``). A change of single words is not applied: the text stays that of
  the publications, as enacted. A ``wijzig-artikel`` of the law itself (one that changes
  another law) is an article of its instruction alone.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from typing import Any

from lawgraph.config.constants import SOURCE_STAATSBLAD
from lawgraph.core.bwb_xml import (
    DIVISIONS,
    ArticleXml,
    Crumb,
    article_display_name,
    article_heads,
    article_number,
)
from lawgraph.core.citations import (
    ARTICLE_HEAD_RE,
    ARTICLE_NUMBER_PATTERN,
    name_key,
)
from lawgraph.core.publications import koop_citation, parse_koop_id
from lawgraph.core.qualifiers import parse_qualifier
from lawgraph.core.xml import (
    child_named,
    children_named,
    collapse_ws,
    find_descendant,
    local_name,
    text_of,
)

# The status of a law read from the Staatsblad: its text as the Staatsblad published it,
# not in force while the BWB holds no regulation of it.
STATUS_ENACTED = "vastgesteld"
# The kind of such a law: the type the Staatsblad gives it (``DC.type`` ``Wet``).
KIND_LAW = "wet"

_ROMAN = re.compile(r"^[IVXLCDM]+[A-Z]?$")
_CITED_AS = re.compile(
    r"(?:wet|wetboek|besluit) wordt aangehaald als:?\s*(?P<title>.+?)\.?\s*$",
    re.IGNORECASE,
)
_REPLACED = re.compile(
    r"^(?P<divisions>.+?),?\s+van\s+(?:het|de)\s+(?P<law>.+?)\s+komt\s+te\s+luiden:?$",
    re.IGNORECASE,
)
# The word of a division as a ``wat`` names it, and its element.
_DIVISION_WORDS = {
    "boek": "boek",
    "deel": "deel",
    "hoofdstuk": "hoofdstuk",
    "titel": "titeldeel",
    "titeldeel": "titeldeel",
    "afdeling": "afdeling",
    "paragraaf": "paragraaf",
}


@dataclass(frozen=True)
class Replacement:
    """A division of a law given a whole new text: the law by its name (``name_key``), the
    division by its path of ``(element, number)`` (``(("boek", "1"), ("hoofdstuk",
    "10"))``) and the ``wijzig-divisie`` that is its text."""

    law: str
    path: tuple[tuple[str, str], ...]
    division: ET.Element


@dataclass(frozen=True)
class LawPublication:
    """A publication of the Staatsblad that is a law (``DC.type`` ``Wet``)."""

    official_id: str  # stb-2026-56
    intitule: str
    citation_title: str | None
    date_signed: str | None
    date_published: str | None
    dossiers: tuple[str, ...]
    wettekst: ET.Element
    replacements: tuple[Replacement, ...]

    @property
    def year_number(self) -> tuple[int, int]:
        parsed = parse_koop_id(self.official_id)
        if parsed is None or not parsed[2].isdigit():
            return (0, 0)
        return parsed[1], int(parsed[2])

    @property
    def enacts_a_law(self) -> bool:
        """Its wettekst holds an article of its own numbered with a figure."""
        return any(
            (number := article_number(article)) and number[0].isdigit()
            for article in _own_articles(self.wettekst)
        )


def _own_articles(element: ET.Element) -> Iterator[ET.Element]:
    """The articles under *element*, not those of a ``wijzig-artikel``."""
    for child in element:
        name = local_name(child.tag)
        if name == "artikel":
            yield child
        elif name != "wijzig-artikel":
            yield from _own_articles(child)


def _iso(element: ET.Element | None) -> str | None:
    value = (element.get("isodatum") or "").strip() if element is not None else ""
    return value or None


def _citation_title(wettekst: ET.Element) -> str | None:
    """The title its own article says the law is cited by ("Deze wet wordt aangehaald als:
    Wetboek van Strafvordering.")."""
    for article in _own_articles(wettekst):
        for al in article.iter("al"):
            match = _CITED_AS.search(collapse_ws(text_of(al)))
            if match:
                return match["title"].strip()
    return None


def _division_path(divisions: str) -> tuple[tuple[str, str], ...] | None:
    """``(("boek", "1"), ("hoofdstuk", "10"))`` of "Boek 1, Hoofdstuk 10"; None when a word
    names no division."""
    path: list[tuple[str, str]] = []
    for part in divisions.split(","):
        words = part.split()
        if len(words) != 2 or words[0].lower() not in _DIVISION_WORDS:
            return None
        path.append((_DIVISION_WORDS[words[0].lower()], words[1]))
    return tuple(path) or None


def _replacements(wettekst: ET.Element) -> Iterator[Replacement]:
    for change in children_named(wettekst, "wijzig-artikel"):
        match = _REPLACED.match(collapse_ws(text_of(child_named(change, "wat"))))
        divisions = children_named(child_named(change, "wijziging"), "wijzig-divisie")
        if not match or len(divisions) != 1:
            continue
        path = _division_path(match["divisions"])
        if path is not None:
            yield Replacement(name_key(match["law"]), path, divisions[0])


def read_publication(official_id: str, xml: str) -> LawPublication | None:
    """The law publication *official_id* (``stb-2026-56``) of its XML; None for XML
    without a wettekst."""
    root = ET.fromstring(xml)
    wettekst = find_descendant(root, "wettekst")
    if wettekst is None:
        return None
    closing = find_descendant(root, "wetsluiting")
    given = find_descendant(closing, "gegeven") if closing is not None else None
    issued = find_descendant(closing, "uitgifte") if closing is not None else None
    dossiers = (
        tuple(
            dict.fromkeys(
                ref.get("dossier", "").strip()
                for ref in closing.iter("dossierref")
                if ref.get("dossier", "").strip()
            )
        )
        if closing is not None
        else ()
    )
    return LawPublication(
        official_id=official_id.lower(),
        intitule=collapse_ws(text_of(find_descendant(root, "intitule"))),
        citation_title=_citation_title(wettekst),
        date_signed=_iso(
            find_descendant(given, "datum") if given is not None else None
        ),
        date_published=_iso(
            find_descendant(issued, "datum") if issued is not None else None
        ),
        dossiers=dossiers,
        wettekst=wettekst,
        replacements=tuple(_replacements(wettekst)),
    )


# ── the law with its replaced divisions ──────────────────────────────────────


def _nr(element: ET.Element) -> str:
    return collapse_ws(text_of(child_named(child_named(element, "kop"), "nr")))


def _find(
    element: ET.Element, kind: str, number: str
) -> tuple[ET.Element, ET.Element] | None:
    """``(parent, division)`` of the first division *kind* numbered *number* under
    *element*, depth first."""
    for child in element:
        if local_name(child.tag) == kind and _nr(child) == number:
            return element, child
        found = _find(child, kind, number)
        if found is not None:
            return found
    return None


def _as_division(element: ET.Element, source: str) -> ET.Element:
    """A copy of a ``wijzig-divisie`` as the division it is (its ``soort``), the ones in it
    too, each of its articles with *source* as its ``bron``."""
    division = copy.deepcopy(element)
    for node in division.iter():
        if local_name(node.tag) == "wijzig-divisie":
            soort = (node.get("soort") or "").strip().lower()
            node.tag = soort if soort in DIVISIONS else "divisie"
        elif local_name(node.tag) == "artikel":
            node.set("bron", source)
    return division


@dataclass(frozen=True)
class LawText:
    """The articles of a law in their order, and the replacements of other publications
    it holds (``official_id`` and path of each) and those it does not (no such division)."""

    articles: tuple[ArticleXml, ...]
    applied: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    not_found: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def law_text(law: LawPublication, others: Iterable[LawPublication]) -> LawText:
    """The articles of *law* with the divisions *others* give a whole new text in place, in
    the order of their publication; each article with the publication it comes from as its
    ``source`` (``stb-2026-57``) and its divisions labelled as a law prints them."""
    wettekst = copy.deepcopy(law.wettekst)
    title = name_key(law.citation_title or "")
    applied: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    not_found: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for other in sorted(others, key=lambda p: p.year_number):
        for change in other.replacements:
            if not title or change.law != title:
                continue
            place: tuple[ET.Element, ET.Element] | None = (wettekst, wettekst)
            for kind, number in change.path:
                place = _find(place[1], kind, number) if place else None
            if place is None:
                not_found.append((other.official_id, change.path))
                continue
            parent, old = place
            index = list(parent).index(old)
            parent.remove(old)
            parent.insert(index, _as_division(change.division, other.official_id))
            applied.append((other.official_id, change.path))
    _instructions(wettekst)
    for article in wettekst.iter("artikel"):
        article.set("bron", article.get("bron") or law.official_id)
    # "1." in the Staatsblad, "1" in the BWB, whose text puts the full stop after it
    for lidnr in wettekst.iter("lidnr"):
        lidnr.text = (lidnr.text or "").strip().rstrip(".")
    articles = tuple(
        replace(head.article, breadcrumb=tuple(_printed(c) for c in head.breadcrumb))
        for head in article_heads(wettekst)
    )
    return LawText(articles, tuple(applied), tuple(not_found))


def _instructions(wettekst: ET.Element) -> None:
    """Make each ``wijzig-artikel`` of a law (one that changes another law) an article of
    its instruction alone ("Het Wetboek van Strafrecht wordt als volgt gewijzigd:"): the
    changes it makes are text of the other law, not of this one."""
    for change in list(wettekst.iter("wijzig-artikel")):
        change.tag = "artikel"
        for child in list(change):
            if local_name(child.tag) == "wijziging":
                change.remove(child)
            elif local_name(child.tag) == "wat":
                child.tag = "al"


def _printed(crumb: Crumb) -> Crumb:
    """A division as a law prints it: "Boek 1", "Strafvordering in het algemeen"; the
    Staatsblad sets the word of a division and its title in capitals."""
    label = crumb.label
    if label:
        word, _, rest = label.partition(" ")
        label = f"{word.capitalize()} {rest}".strip() if word.isupper() else label
    title = crumb.title
    if title and title.isupper():
        title = title[0] + title[1:].lower()
    return replace(crumb, label=label, title=title)


# ── props ────────────────────────────────────────────────────────────────────


def law_name(law: LawPublication) -> str:
    """The name of the law: its citation title, else its intitule."""
    return law.citation_title or law.intitule


def law_display_name(law: LawPublication) -> str:
    """``Wetboek van Strafvordering (Stb. 2026, 56)``: its name and the publication that
    enacted it, which tells it from the law of the BWB of the same name."""
    cited = koop_citation(law.official_id)
    return f"{law_name(law)} ({cited})" if cited else law_name(law)


def law_props(law: LawPublication, dossiers: list[str]) -> dict[str, Any]:
    """The props of the instrument of *law*; *dossiers* those of every publication its
    text comes from."""
    return {
        "source": SOURCE_STAATSBLAD,
        "official_id": law.official_id,
        "enacted_publication": law.official_id,
        "kind": KIND_LAW,
        "jurisdiction": "nl",
        "title": law_name(law),
        "official_title": law.intitule or None,
        "citation_title": law.citation_title,
        "display_name": law_display_name(law),
        "date_signed": law.date_signed,
        "date_published": law.date_published,
        "dossier_numbers": dossiers,
        "status": STATUS_ENACTED,
        "in_force": False,
    }


def article_props(
    article: ArticleXml, law: LawPublication, position: int
) -> dict[str, Any]:
    """The props of an article of *law*; *position* its place in the law."""
    props = {
        "source": SOURCE_STAATSBLAD,
        "official_id": law.official_id,
        "article_number": article.number,
        "label": article.label,
        "heading": article.heading,
        "position": position,
        "text": article.text,
        "instrument_citation_title": law.citation_title,
        "display_name": article_display_name(article.label, law_display_name(law)),
        "source_publication": koop_citation(article.source or ""),
        # always written: an upsert merges props, so a stale true must be overwritten
        "repealed": False,
        "parts": [part.to_dict() for part in article.parts],
        "tables": [table.to_dict() for table in article.tables] or None,
        "breadcrumb": [crumb.to_dict() for crumb in article.breadcrumb] or None,
    }
    return {k: v for k, v in props.items() if v is not None}


# ── the law a paper of its dossier cites ─────────────────────────────────────


@dataclass(frozen=True)
class DossierLaw:
    """A law of the Staatsblad as the papers of its dossiers cite it: its publication and
    the numbers of its articles."""

    official_id: str
    numbers: frozenset[str]


class DossierLaws:
    """Which law a paper means when it cites a law by a name a law of the Staatsblad shares
    (the Wetboek van Strafvordering of the BWB and the new one of Stb. 2026, 56): a paper of
    a dossier of that law (``dossier_numbers`` of the law: those of the publications its
    text comes from) means it. The source says it: the bill of the dossier made it."""

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self._laws: dict[tuple[str, str], DossierLaw] = {}
        for row in rows:
            law = DossierLaw(
                str(row["official_id"]),
                frozenset(str(n) for n in row.get("numbers") or []),
            )
            for dossier in row.get("dossier_numbers") or []:
                for bwb_id in row.get("named") or []:
                    self._laws.setdefault((str(dossier), str(bwb_id).upper()), law)

    def __bool__(self) -> bool:
        return bool(self._laws)

    def of(self, dossiers: object, bwb_id: str | None) -> DossierLaw | None:
        """The law of the Staatsblad a paper of *dossiers* means by the law *bwb_id*."""
        if not bwb_id or not isinstance(dossiers, list):
            return None
        for dossier in dossiers:
            law = self._laws.get((str(dossier), bwb_id.upper()))
            if law is not None:
                return law
        return None


# ── references inside the law ────────────────────────────────────────────────

_NUMBER = re.compile(ARTICLE_NUMBER_PATTERN)
# After the numbers of a reference: another law ("van het Wetboek van Strafrecht", "van de
# Wet op de rechterlijke organisatie", "van Boek 1 van het Burgerlijk Wetboek", "van die
# wet", "Sr"), not this one ("van deze wet", "van dit wetboek", or nothing).
_OTHER_LAW = re.compile(
    r"\s*,?\s*(?:(?:van|in|uit|krachtens|ingevolge)\s+"
    r"(?:(?:de|het)\s+(?!(?:deze|dit|die|dat)\b)\S|(?:die|dat|dezelfde)\s|Boek\s)"
    r"|[A-Z][A-Za-z]*\b)"
)
_THIS_LAW = re.compile(
    r"\s*,?\s*(?:van|in|uit|krachtens|ingevolge)\s+(?:deze|dit)\s+(?:wet|wetboek)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OwnReference:
    """A reference in an article to an article of its own law: the number and where it
    stands in the text, with the parts it names of a single article."""

    number: str
    start: int
    end: int
    text: str
    qualifier: str = ""

    def meta(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "reference_kind": "intref",
            **parse_qualifier(self.qualifier).to_dict(),
        }


def own_references(text: str) -> list[OwnReference]:
    """The references of *text* to articles of its own law: "artikel 2.8.16", "de
    artikelen 1.1.1 en 1.1.2" and "artikel 3 van deze wet", not "artikel 76 van de Wet op
    de rechterlijke organisatie" or "artikel 41 Sr"."""
    found: list[OwnReference] = []
    for head in ARTICLE_HEAD_RE.finditer(text):
        rest = text[head.end() :]
        if not _THIS_LAW.match(rest) and _OTHER_LAW.match(rest):
            continue
        numbers = list(_NUMBER.finditer(head["nums"]))
        qualifier = head["qual"].strip(" ,") if len(numbers) == 1 else ""
        for number in numbers:
            start = head.start("nums") + number.start()
            end = head.start("nums") + number.end()
            found.append(
                OwnReference(number[0], start, end, text[start:end], qualifier)
            )
    return found
