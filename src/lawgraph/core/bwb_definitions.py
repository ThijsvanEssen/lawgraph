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
regulation, or a chapter, section or article of it (``path``: its ``bwb-ng-variabel-deel``).
A definition whose text links to a regulation (``<extref bwb-id>``: "wet: de
Zorgverzekeringswet") names it (``refers_to``). An onderdeel without a term before a colon
is left out: nothing is guessed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

from lawgraph.core.bwb_xml import article_key, article_number
from lawgraph.core.xml import local_name

# "… wordt (in deze wet …) verstaan onder:", the last words of an announcement.
_ANNOUNCES = re.compile(r"\bverstaan\s+onder\s*:\s*$", re.IGNORECASE)
# "In deze wet …", "In dit hoofdstuk …", "Voor de toepassing van deze afdeling …": the part
# of the regulation the definitions hold in.
_SCOPE = re.compile(
    r"\b(?:deze|dit)\s+(wet|besluit|regeling|verordening|hoofdstuk|afdeling|paragraaf|"
    r"titel|titeldeel|artikel|bijlage|boek|deel|onderdeel)\b",
    re.IGNORECASE,
)
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


def _text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if local_name(child.tag) == name]


def _first(element: ET.Element, name: str) -> ET.Element | None:
    return next(iter(_children(element, name)), None)


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
            sentence = _text(child)
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
        term = _leading_term(element)
        if term is None:
            more = _text(element)
            if found and more:
                found[-1]["text"] = f"{found[-1]['text']} {more}".rstrip(" ;")
            continue
        whole = _text(element)
        rest = whole.split(":", 1)[1].strip() if ":" in whole else ""
        if not rest and index + 1 < len(following):
            nxt = following[index + 1]
            if local_name(nxt.tag) == "lijst":
                rest = _text(nxt)
        if rest:
            found.append(_definition(term, rest, element, scope))
    return found


def _of_list(lijst: ET.Element, scope: dict[str, str]) -> Iterator[dict[str, Any]]:
    for item in _children(lijst, "li"):
        al = _first(item, "al")
        if al is None:
            continue
        match = _TERM.match(_text(al))
        if match is None:
            continue
        number = _first(item, "li.nr")
        jci = next(
            (e.get("verwijzing") for e in item.iter() if local_name(e.tag) == "jci"),
            None,
        )
        yield {
            **_definition(match["term"], match["text"], al, scope),
            "place": _text(number).rstrip(".") if number is not None else None,
            "jci": jci,
        }


def _leading_term(al: ET.Element) -> str | None:
    """The term an ``<al>`` begins with in ``<nadruk>``, without its colon: inside it
    ("<nadruk>aanbieden:</nadruk>") or right after it ("<nadruk>bieder</nadruk>: een …")."""
    first = next(iter(al), None)
    if first is None or local_name(first.tag) != "nadruk" or (al.text or "").strip():
        return None
    term = _text(first)
    if term.endswith(":"):
        term = term[:-1]
    elif not (first.tail or "").lstrip().startswith(":"):
        return None
    return term.strip() or None


def _definition(
    term: str, text: str, element: ET.Element, scope: dict[str, str]
) -> dict[str, Any]:
    return {
        "term": " ".join(term.split()),
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
        rest = text.replace(_text(link), "").strip(" ;,.")
        if rest.lower() in {"", "de", "het"}:
            return link.get("bwb-id")
    return None


def _scope(sentence: str, article_path: str) -> dict[str, str]:
    """Where an announcement's definitions hold: ``kind`` (``wet``, ``hoofdstuk``, …) and
    ``path``, the ``bwb-ng-variabel-deel`` of that part ("" for the whole regulation, the
    article's own for ``artikel``)."""
    match = _SCOPE.search(sentence)
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
