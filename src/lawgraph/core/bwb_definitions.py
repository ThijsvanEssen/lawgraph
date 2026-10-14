"""The definitions a regulation gives itself (its begripsbepalingen), read from the BWB XML.

Pure: no I/O. The BWB marks no definition as such; a definition article has a structure all
the same, in two forms:

* an ``<al>`` that announces them ("In dit besluit en de daarop berustende bepalingen wordt
  verstaan onder:"), then a ``<lijst>`` of ``<li>``: each its ``<li.nr>`` ("a."), its JCI
  (``o=a``) and an ``<al>`` "term: definition;" — the term is often ``<nadruk>`` ("wet:");
* after the announcement, ``<al>`` after ``<al>`` that begins with ``<nadruk>term:</nadruk>``
  and goes on with the definition, or with a ``<lijst>`` of its meanings (the Wft).

A sentence that defines one term ("In deze wet wordt verstaan onder werkgever: …") is the
third form. The announcement says where the definitions hold (``scope``): the whole
regulation, or a chapter, section or article of it (``path``: its ``bwb-ng-variabel-deel``);
and whether they hold in the regulations issued under it too (``reach``: ``own_and_based``
for "In deze wet en de daarop berustende bepalingen", else ``own``). A regulation issued
under a law (its ``BASED_ON``) uses the definitions of that law that reach it
(``inherited``): of the part of the law its basis articles stand in, its own definition of
the same term first.
A definition whose text links to a regulation (``<extref bwb-id>``: "wet: de
Zorgverzekeringswet") names it (``refers_to``). An onderdeel without a term before a colon
is left out: nothing is guessed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

from lawgraph.core.bwb_xml import article_key, article_number, leading_term
from lawgraph.core.xml import (
    child_named,
    children_named,
    collapse_ws,
    local_name,
    words_of,
)

# "… wordt (in deze wet …) verstaan onder:", the last words of an announcement.
_ANNOUNCES = re.compile(r"\bverstaan\s+onder\s*:\s*$", re.IGNORECASE)
# "In deze wet …", "In dit hoofdstuk …", "Voor de toepassing van deze afdeling …": the part
# of the regulation the definitions hold in.
_SCOPE = re.compile(
    r"\b(?:deze|dit)\s+(wet|besluit|regeling|verordening|hoofdstuk|afdeling|paragraaf|"
    r"titel|titeldeel|artikel|bijlage|boek|deel|onderdeel)\b",
    re.IGNORECASE,
)
# "… en de daarop berustende bepalingen", "… en de op deze wet berustende bepalingen": the
# definitions hold in the regulations issued under the part too.
_BASED = re.compile(
    r"\ben\s+de\s+(?:daarop|op\s+(?:deze|dit)\s+\w+)\s+(?:be)?rustende\b",
    re.IGNORECASE,
)
OWN = "own"
OWN_AND_BASED = "own_and_based"
# "In deze wet wordt verstaan onder werkgever: de …": one term, defined in one sentence.
_ONE = re.compile(
    r"^(?:in|voor de toepassing van)\b.{0,200}?\bwordt\b.{0,120}?\bverstaan\s+onder\s+"
    r"(?P<term>[^:;]{1,80}?)\s*:\s+(?P<text>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "term: definition", the term at most a few words.
_TERM = re.compile(r"^(?P<term>[^:;]{1,80}?)\s*:\s+(?P<text>.+)$", re.DOTALL)
# The parts of a ``bwb-ng-variabel-deel`` a scope can be: "/Hoofdstuk1/Artikel1" holds the
# chapter "/Hoofdstuk1".
_PART = {
    "hoofdstuk": "Hoofdstuk",
    "afdeling": "Afdeling",
    "paragraaf": "Paragraaf",
    "titel": "Titeldeel",
    "titeldeel": "Titeldeel",
    "boek": "Boek",
    "deel": "Deel",
}
_WHOLE = {"wet", "besluit", "regeling", "verordening"}


def definitions(bwb_id: str, xml: str) -> list[dict[str, Any]]:
    """Every definition the toestand *xml* of *bwb_id* gives, in the order of the text:
    ``{term, text, article_key, article_number, place, jci, scope: {kind, path},
    refers_to}``."""
    root = ET.fromstring(xml)
    found: list[dict[str, Any]] = []
    for article in root.iter():
        if local_name(article.tag) != "artikel":
            continue
        number = article_number(article)
        key = article_key(bwb_id, number, article.get("stam-id"))
        if key is None:
            continue
        path = article.get("bwb-ng-variabel-deel") or ""
        found += [
            {"article_key": key, "article_number": number, **definition}
            for definition in _of_article(article, path)
        ]
    return found


def _of_article(article: ET.Element, path: str) -> Iterator[dict[str, Any]]:
    for parent in article.iter():
        kids = list(parent)
        for index, child in enumerate(kids):
            if local_name(child.tag) != "al":
                continue
            sentence = words_of(child)
            if _ANNOUNCES.search(sentence):
                scope = _scope(sentence, path)
                yield from _after_announcement(kids[index + 1 :], scope)
                continue
            one = _ONE.match(sentence)
            if one:
                yield _definition(
                    one["term"], one["text"], child, _scope(sentence, path)
                )


def _after_announcement(
    following: list[ET.Element], scope: dict[str, str]
) -> list[dict[str, Any]]:
    """The definitions that follow an announcement: a ``<lijst>`` of "term: text", or
    ``<al>`` after ``<al>`` that begins with a term in ``<nadruk>`` (its meanings in the
    ``<lijst>`` after it when the ``<al>`` holds only the term). An ``<al>`` without a term
    between them goes on with the definition before it ("waarbij …", "met dien verstande
    dat …")."""
    if following and local_name(following[0].tag) == "lijst":
        return list(_of_list(following[0], scope))
    found: list[dict[str, Any]] = []
    for index, element in enumerate(following):
        if local_name(element.tag) != "al":
            continue
        term = leading_term(element)
        if term is None:
            more = words_of(element)
            if found and more:
                found[-1]["text"] = f"{found[-1]['text']} {more}".rstrip(" ;")
            continue
        whole = words_of(element)
        rest = whole.split(":", 1)[1].strip() if ":" in whole else ""
        if not rest and index + 1 < len(following):
            nxt = following[index + 1]
            if local_name(nxt.tag) == "lijst":
                rest = words_of(nxt)
        if rest:
            found.append(_definition(term, rest, element, scope))
    return found


def _place(item: ET.Element, marked: bool) -> str | None:
    """The number of an onderdeel ("a", "1°"): none in a list the BWB calls unmarked
    (``type="ongemarkeerd"``), and none whose ``<li.nr>`` holds no letter or digit, a dash
    or a bullet ("–", "−", "•") of a list the BWB calls explicit all the same: a mark
    without a number is no place to cite."""
    number = child_named(item, "li.nr")
    if not marked or number is None:
        return None
    place = words_of(number).rstrip(".")
    return place if any(char.isalnum() for char in place) else None


def _of_list(lijst: ET.Element, scope: dict[str, str]) -> Iterator[dict[str, Any]]:
    """The definitions of a ``<lijst>``, each with the number of its onderdeel
    (``_place``)."""
    marked = lijst.get("type") != "ongemarkeerd"
    for item in children_named(lijst, "li"):
        al = child_named(item, "al")
        if al is None:
            continue
        match = _TERM.match(words_of(al))
        if match is None:
            continue
        jci = next(
            (e.get("verwijzing") for e in item.iter() if local_name(e.tag) == "jci"),
            None,
        )
        yield {
            **_definition(match["term"], match["text"], al, scope),
            "place": _place(item, marked),
            "jci": jci,
        }


def _definition(
    term: str, text: str, element: ET.Element, scope: dict[str, str]
) -> dict[str, Any]:
    return {
        "term": collapse_ws(term),
        "text": text.strip().rstrip(";").strip(),
        "place": None,
        "jci": None,
        "scope": scope,
        "refers_to": _regulation_named(text, element),
    }


def _regulation_named(text: str, element: ET.Element) -> str | None:
    """The BWB id of the regulation a definition is ("wet: de <extref>Zorgverzekeringswet
    </extref>"): a link to a whole regulation that is all the definition says, but for an
    article. None when the definition only cites one ("… als bedoeld in artikel 11 van de
    wet")."""
    for link in element.iter():
        if local_name(link.tag) != "extref" or "artikel=" in (link.get("doc") or ""):
            continue
        rest = text.replace(words_of(link), "").strip(" ;,.")
        if rest.lower() in {"", "de", "het"}:
            return link.get("bwb-id")
    return None


def _scope(sentence: str, article_path: str) -> dict[str, str]:
    """Where an announcement's definitions hold: ``kind`` (``wet``, ``hoofdstuk``, …),
    ``path``, the ``bwb-ng-variabel-deel`` of that part ("" for the whole regulation, the
    article's own for ``artikel``), and ``reach``: ``own_and_based`` where the words before
    "verstaan" add "en de daarop berustende bepalingen", else ``own``."""
    head = re.split(r"\bverstaan\b", sentence, maxsplit=1, flags=re.IGNORECASE)[0]
    reach = OWN_AND_BASED if _BASED.search(head) else OWN
    return {**_part(head, article_path), "reach": reach}


def _part(head: str, article_path: str) -> dict[str, str]:
    match = _SCOPE.search(head)
    kind = match.group(1).lower() if match else "wet"
    if kind in _WHOLE:
        return {"kind": kind, "path": ""}
    if kind == "artikel":
        return {"kind": kind, "path": article_path}
    part = _PART.get(kind)
    if part is None:
        return {"kind": kind, "path": article_path}
    segments = article_path.split("/")
    for depth in range(len(segments) - 1, 0, -1):
        if segments[depth].startswith(part):
            return {"kind": kind, "path": "/".join(segments[: depth + 1])}
    return {"kind": kind, "path": article_path}


def applies(definition: dict[str, Any], article_path: str) -> bool:
    """Whether *definition* holds in the article at *article_path*."""
    path = (definition.get("scope") or {}).get("path") or ""
    return not path or article_path == path or article_path.startswith(path + "/")


def reaches(definition: dict[str, Any], basis_paths: list[str]) -> bool:
    """Whether *definition* holds in a regulation issued under the articles at
    *basis_paths* of its own: it reaches the regulations based on it, and one of those
    articles stands in its part."""
    reach = (definition.get("scope") or {}).get("reach")
    return reach == OWN_AND_BASED and any(applies(definition, p) for p in basis_paths)


def inherited(bases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The definitions a regulation takes from the regulations it is issued under: *bases*
    ``{level, paths, definitions, given_by}``, level 1 the regulations its preamble names
    (``BASED_ON``), level 2 theirs. Of each, those that reach it (``reaches``), each with
    ``given_by`` (the regulation that gives it); of one term in one regulation the narrower
    scope, as in the regulation itself. Of one term the nearest level; two of one level
    that say different things leave the term out (two laws that each define "Onze
    Minister"): nothing is guessed."""
    chosen: dict[str, tuple[int, dict[str, Any] | None]] = {}
    for base in sorted(bases, key=lambda b: b["level"]):
        for term, entry in _narrowest(base).items():
            seen = chosen.get(term)
            if seen is None:
                chosen[term] = (base["level"], entry)
            elif seen[0] == base["level"] and (
                seen[1] is None or seen[1]["text"] != entry["text"]
            ):
                chosen[term] = (base["level"], None)
    return [entry for _, entry in chosen.values() if entry is not None]


def _narrowest(base: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The definitions of *base* that reach the regulation issued under it, one per term:
    the one of the narrowest part."""
    found: dict[str, dict[str, Any]] = {}
    for definition in base["definitions"]:
        if not reaches(definition, base["paths"]):
            continue
        term = definition["term"].lower()
        path = definition["scope"].get("path") or ""
        seen = found.get(term)
        if seen is None or len(path) > len(seen["scope"].get("path") or ""):
            found[term] = {**definition, "given_by": base["given_by"]}
    return found


def definition_ref(definition: dict[str, Any]) -> str:
    """How a span names its definition: the article, the letter of the onderdeel and the
    term (``bwbr0018492_1:a:wet``), the article and the term where there is no letter. The
    term keeps two definitions of one article apart where their letters do not."""
    place = definition.get("place")
    return ":".join(
        [definition["article_key"], *([place] if place else []), definition["term"]]
    )


class TermMatcher:
    """The defined terms of one regulation, found in a text in one pass: one alternation of
    every term, the longest first, as a whole word, whatever its case. Its own definitions
    (*found*) and those it takes from the regulations it is issued under (*taken*,
    ``inherited``): its own where one holds."""

    def __init__(
        self, found: list[dict[str, Any]], taken: list[dict[str, Any]] | None = None
    ) -> None:
        self._by_term: dict[str, list[dict[str, Any]]] = {}
        for definition in found:
            self._by_term.setdefault(definition["term"].lower(), []).append(definition)
        self._taken = {d["term"].lower(): d for d in taken or []}
        terms = sorted(self._by_term.keys() | self._taken.keys(), key=len, reverse=True)
        self._pattern = (
            re.compile(
                r"(?<!\w)(?:" + "|".join(re.escape(t) for t in terms) + r")(?!\w)",
                re.IGNORECASE,
            )
            if terms
            else None
        )

    def find(
        self, text: str, article_path: str
    ) -> list[tuple[int, int, dict[str, Any]]]:
        """``(start, end, definition)`` of every term of *text* whose definition holds in
        the article at *article_path*: of two of the same term, the narrower scope; one
        taken where none of its own holds."""
        if self._pattern is None:
            return []
        found = []
        for match in self._pattern.finditer(text):
            term = match.group(0).lower()
            holding = [
                d for d in self._by_term.get(term, []) if applies(d, article_path)
            ]
            if holding:
                narrowest = max(
                    holding, key=lambda d: len(d["scope"].get("path") or "")
                )
                found.append((match.start(), match.end(), narrowest))
            elif term in self._taken:
                found.append((match.start(), match.end(), self._taken[term]))
        return found
