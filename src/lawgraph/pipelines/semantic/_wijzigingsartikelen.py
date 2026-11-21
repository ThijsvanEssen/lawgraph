"""The wijzigingsartikelen of a bill (``ARTIKEL I``, ``ARTIKEL II`` …, its roman ``article``
sections) and the law each changes: the one it names first."""

from __future__ import annotations

import itertools
from collections.abc import Collection, Iterable, Iterator, Mapping
from typing import Any

from lawgraph.core.citations import CitationHit, strip_xml
from lawgraph.core.document_xml import KIND_ARTICLE, SCHEME_ROMAN

from .tk import NamedActs


def wijzigingsartikelen(text: str, sections: Iterable[Mapping[str, Any]]) -> list[str]:
    """The text of each wijzigingsartikel, from its heading to the next one (a heading
    ``ARTIKEL I, onderdeel B`` right after ``ARTIKEL I`` is still that article); none
    without any."""
    heads = [
        (section["number"], section["char_start"])
        for section in sections
        if section["kind"] == KIND_ARTICLE and section["number_scheme"] == SCHEME_ROMAN
    ]
    starts = [
        start
        for index, (number, start) in enumerate(heads)
        if index == 0 or heads[index - 1][0] != number
    ]
    bounds = [*starts, len(text)] if starts else []
    return [strip_xml(text[start:end]) for start, end in itertools.pairwise(bounds)]


def laws_of_wijzigingsartikelen(
    text: str, sections: Iterable[Mapping[str, Any]], named_acts: NamedActs
) -> list[str]:
    """The BWB ids of the laws a document's wijzigingsartikelen change, in order: of each
    the law it names first; none without wijzigingsartikelen."""
    firsts = (
        first_law(part, named_acts) for part in wijzigingsartikelen(text, sections)
    )
    return list(dict.fromkeys(filter(None, firsts)))


def first_law(part: str, named_acts: NamedActs) -> str | None:
    """The BWB id of the law *part* names first; None when it names none."""
    return next(_laws_named(part, named_acts), None)


def first_law_of(part: str, laws: Collection[str], named_acts: NamedActs) -> str | None:
    """Of *laws*, the one *part* names first; None when it names none of them."""
    return next((law for law in _laws_named(part, named_acts) if law in laws), None)


def _laws_named(part: str, named_acts: NamedActs) -> Iterator[str]:
    """The BWB ids of the laws *part* names, first named first."""
    named: list[CitationHit] = []
    named_acts.collect_hits(part, named.append)
    for hit in sorted(named, key=lambda hit: hit.start or 0):
        if hit.bwb_id:
            yield hit.bwb_id
