"""BWB WTI (wetstechnische informatie): the official abbreviations of a regulation, and the
legal areas and government themes it is filed under.

A WTI file opens with one ``<algemene-informatie>`` element; the amendment log and the
related regulations that follow make the file large (27 MB for the Wetboek van Strafrecht).
Only that first element is kept. Its ``<afkortingen>`` list is sorted alphabetically by the
source, so the position of an abbreviation says nothing about its importance. Its
``<rechtsgebieden>`` (a ``hoofdgebied`` with a ``specifiekgebied``) and ``<overheidsdomeinen>``
are concepts of the TOOI thesauri ``scw_bwb_rechtsgebieden`` and ``scw_bwb_themas``, by their
label.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from lawgraph.core.code_families import CODE_FAMILIES
from lawgraph.core.xml import collapse_ws, first_named, iter_named

GENERAL_INFO_START = "<algemene-informatie"
GENERAL_INFO_END = "</algemene-informatie>"


def extract_general_info(wti_head: str) -> str | None:
    """The ``<algemene-informatie>`` element, verbatim, from the start of a WTI file.

    *wti_head* may stop anywhere after the closing tag. ``None`` when the element is
    missing or not yet complete.
    """
    start = wti_head.find(GENERAL_INFO_START)
    end = wti_head.find(GENERAL_INFO_END, start)
    if start < 0 or end < 0:
        return None
    return wti_head[start : end + len(GENERAL_INFO_END)]


def _text(element: ET.Element, name: str) -> str | None:
    child = first_named(element, name)
    return (collapse_ws(child.text) or None) if child is not None else None


def parse_subjects(general_info_xml: str) -> tuple[list[dict[str, Any]], list[str]]:
    """``(legal_areas, policy_domains)`` of a regulation, each once, in source order: the
    legal areas as ``{main, specific}`` (``specific`` None when the source names none), the
    government themes as their labels. Raises ``ET.ParseError`` on broken XML."""
    root = ET.fromstring(general_info_xml)
    areas: list[dict[str, Any]] = []
    for element in iter_named(root, "rechtsgebied"):
        area = {
            "main": _text(element, "hoofdgebied"),
            "specific": _text(element, "specifiekgebied"),
        }
        if area["main"] and area not in areas:
            areas.append(area)
    domains: list[str] = []
    for element in iter_named(root, "overheidsdomein"):
        domain = collapse_ws(element.text)
        if domain and domain not in domains:
            domains.append(domain)
    return areas, domains


def slugify(text: str) -> str:
    """``staats-en-bestuursrecht`` for "Staats- en bestuursrecht": lower case ASCII words
    joined by ``-``."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def assign_slugs(concepts: Sequence[tuple[str, str, str | None]]) -> dict[str, str]:
    """``key -> slug`` of the *concepts* ``(key, label, broader key)`` of one list, each
    slug once in the list. A slug is that of the label; a narrower concept whose slug is
    taken gets the slug of its broader concept in front (``bestuursrecht-algemeen``), and
    one still taken a number. Top concepts first, then by key, so the same list gives the
    same slugs."""
    ordered = sorted(concepts, key=lambda c: (c[2] is not None, c[0]))
    slugs: dict[str, str] = {}
    taken: set[str] = set()
    for key, label, broader in ordered:
        slug = slugify(label) or "concept"
        if slug in taken and broader in slugs:
            slug = f"{slugs[broader]}-{slug}"
        base, n = slug, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        slugs[key] = slug
        taken.add(slug)
    return slugs


Concepts = dict[str, dict[str, Any]]  # label casefolded -> {id, uri, slug}


def thesaurus_concepts(items: Sequence[Mapping[str, Any]]) -> Concepts:
    """The concepts of a TOOI thesaurus (its JSON-LD items) by label, without regard to
    case: ``{id, uri, slug}``, ``id`` the last part of the URI (``c_e49bce03``)."""
    found: dict[str, tuple[str, str | None]] = {}  # uri -> (label, broader uri)
    for item in items:
        labels = item.get(SKOS_PREF_LABEL) or []
        label = (
            labels[0].get("@value") if labels and isinstance(labels[0], dict) else None
        )
        if label and item.get("@id"):
            broader = item.get(SKOS_BROADER) or []
            parent = (
                broader[0].get("@id")
                if broader and isinstance(broader[0], dict)
                else None
            )
            found.setdefault(str(item["@id"]), (str(label), parent))
    slugs = assign_slugs(
        [(uri, label, parent) for uri, (label, parent) in found.items()]
    )
    concepts: Concepts = {}
    for uri, (label, _) in found.items():
        concepts.setdefault(
            label.casefold(),
            {"id": uri.rstrip("/").rsplit("/", 1)[-1], "uri": uri, "slug": slugs[uri]},
        )
    return concepts


def label_concepts(pairs: Iterable[tuple[str, str | None]]) -> Concepts:
    """Concepts from the labels alone, for when the thesaurus was not retrieved: the
    ``(label, broader label)`` pairs the WTI records give, without id or URI."""
    found: dict[str, tuple[str, str | None]] = {}
    for label, broader in pairs:
        found.setdefault(
            label.casefold(), (label, broader.casefold() if broader else None)
        )
    slugs = assign_slugs(
        [(key, label, parent) for key, (label, parent) in found.items()]
    )
    return {key: {"id": None, "uri": None, "slug": slugs[key]} for key in found}


def with_concepts(
    areas: Sequence[Mapping[str, Any]],
    domains: Sequence[str],
    legal_areas: Concepts,
    themes: Concepts,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The legal areas and themes of a regulation with the id, URI and slug of their
    concept, found by label without regard to case; None for a label the list lacks."""

    def concept(index: Concepts, label: Any, field: str) -> Any:
        found = index.get(str(label).casefold()) if label else None
        return found.get(field) if found else None

    return (
        [
            {
                "main": area["main"],
                "main_id": concept(legal_areas, area["main"], "id"),
                "main_uri": concept(legal_areas, area["main"], "uri"),
                "main_slug": concept(legal_areas, area["main"], "slug"),
                "specific": area.get("specific"),
                "specific_id": concept(legal_areas, area.get("specific"), "id"),
                "specific_uri": concept(legal_areas, area.get("specific"), "uri"),
                "specific_slug": concept(legal_areas, area.get("specific"), "slug"),
            }
            for area in areas
        ],
        [
            {
                "label": domain,
                "id": concept(themes, domain, "id"),
                "uri": concept(themes, domain, "uri"),
                "slug": concept(themes, domain, "slug"),
            }
            for domain in domains
        ],
    )


def parse_abbreviations(general_info_xml: str) -> list[str]:
    """The ``<afkorting>`` values in source order, without case-insensitive repeats.

    The source lists ``GW`` and ``Gw`` as two abbreviations; citations are matched without
    regard to case, so one spelling is kept: the form a citation writes, a capital and then
    lower case (``Gw``, ``_citation_form``), else the first. The source sorts alphabetically,
    capitals first, so its first spelling says nothing. Raises ``ET.ParseError`` on broken
    XML.
    """
    root = ET.fromstring(general_info_xml)
    kept: dict[str, str] = {}  # upper case -> the spelling kept, in source order
    for element in iter_named(root, "afkorting"):
        value = collapse_ws(element.text)
        if not value:
            continue
        before = kept.setdefault(value.upper(), value)
        if _citation_form(value) and not _citation_form(before):
            kept[value.upper()] = value
    return list(kept.values())


def _citation_form(abbreviation: str) -> bool:
    """Written as a citation writes it: a capital first, lower case in it (``Gw``, ``WvS``;
    not ``GW`` or ``bw``)."""
    return abbreviation[:1].isupper() and any(c.islower() for c in abbreviation)


def choose_short_titles(
    abbreviations_by_id: Mapping[str, Sequence[str]],
) -> dict[str, str | None]:
    """Pick the one abbreviation per regulation that becomes its ``short_title``.

    A short title has to lead back to one regulation, so an abbreviation that several
    regulations claim never wins, and neither does a code whose books are regulations of
    their own (``CODE_FAMILIES``: every book of the Burgerlijk Wetboek lists ``BW``, also
    when only one book is loaded). Of the remaining ones the shortest wins (``Sr`` over
    ``WvS`` and ``WvSr``, ``WVW`` over ``WVW 1994``, ``BW1`` over ``BW Boek 1``); of equal
    lengths the citation form (``Gw`` over ``GW``, ``_citation_form``), then the source
    order.
    A regulation left with nothing gets ``None``. Comparison ignores case.
    """
    claims = Counter(
        claimed
        for abbreviations in abbreviations_by_id.values()
        for claimed in {abbreviation.upper() for abbreviation in abbreviations}
    )
    chosen: dict[str, str | None] = {}
    for regulation_id, abbreviations in abbreviations_by_id.items():
        own = [
            a
            for a in abbreviations
            if claims[a.upper()] == 1 and a.upper() not in CODE_FAMILIES
        ]
        chosen[regulation_id] = (
            min(own, key=lambda a: (len(a), not _citation_form(a))) if own else None
        )
    return chosen


def _book_aliases(family: str, book: str) -> list[str]:
    """The ways a book of a code is cited: ``Boek 6 BW``, ``6 BW``, ``BW 6``, ``BW6``,
    ``BW Boek 6`` and the code itself (``BW``)."""
    return [
        f"Boek {book} {family}",
        f"{book} {family}",
        f"{family} {book}",
        f"{family}{book}",
        f"{family} Boek {book}",
        family,
    ]


def instrument_aliases(
    abbreviations_by_id: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    """Every name a regulation is cited by, for the search: its WTI abbreviations and, for a
    book of a code (``CODE_FAMILIES``), the usual forms of book and code.

    Unlike a short title an alias may be shared: ``BW`` is an alias of every book. A book
    gets the forms of its code also when no WTI record was stored for it. Repeats that
    differ in case only are dropped; the order is the source order, then the book forms.
    """
    books = {
        regulation_id: _book_aliases(family, book)
        for family, known in CODE_FAMILIES.items()
        for book, regulation_id in known.items()
    }
    aliases: dict[str, list[str]] = {}
    for regulation_id in sorted({*abbreviations_by_id, *books}):
        seen: set[str] = set()
        names: list[str] = []
        for name in (
            *abbreviations_by_id.get(regulation_id, ()),
            *books.get(regulation_id, ()),
        ):
            if name.upper() not in seen:
                seen.add(name.upper())
                names.append(name)
        aliases[regulation_id] = names
    return aliases


SKOS_PREF_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
