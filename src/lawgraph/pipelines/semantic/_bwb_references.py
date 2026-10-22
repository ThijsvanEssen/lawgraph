"""Turn the structured references of a BWB article into linkable hits.

Pure functions — no store access. The BWB XML records every reference as an
``<extref>``/``<intref>`` element; ``core.bwb_xml`` stores them on the article
as ``props.references`` and this module turns them into edge candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.citations import (
    ARTICLE_NUMBERS_PATTERN,
    article_order,
    number_shape,
    parse_article_numbers,
)
from lawgraph.core.code_families import CODE_FAMILIES, family_of
from lawgraph.core.provenance import REASON_XML_REF
from lawgraph.core.qualifiers import Qualifier

from .base import EXACT_CONFIDENCE

# The article numbers a reference's text starts with: "artikel 230m lid 1", "Artikel 62
# leden 2 en 3 van Boek 4", "1116 tot en met 1118". A text that starts otherwise ("titel 3
# van Boek 6", "het eerste lid") names no article number to check the link against.
_TEXT_NUMBERS_RE = re.compile(
    rf"^\s*(?:(?:de|het)\s+)?(?:(?:artikel(?:en)?|art\.?)\s+)?"
    rf"(?P<nums>{ARTICLE_NUMBERS_PATTERN})(?![\w:]|\.\d)",
    re.IGNORECASE,
)
# A space between the thousands of a number: "artikel 1 064 van het Wetboek van Burgerlijke
# Rechtsvordering" names article 1064, not article 1.
_THOUSANDS_RE = re.compile(r"(?<=\d)[ \u00a0](?=\d{3}(?!\d))")
# "van Boek 4": the book of the code whose article the text names.
_OF_BOOK_RE = re.compile(r"\bvan\s+Boek\s+(?P<book>\d+[A-Z]?)\b", re.IGNORECASE)


@dataclass
class ArticleReferenceHit:
    """A reference from one BWB article to another, as recorded in the XML."""

    start: int
    end: int
    text: str
    bwb_id: str | None
    article_number: str
    confidence: float
    cross_law: bool = field(default=False)
    reason: str | None = None
    kind: str | None = None  # "intref" | "extref": how the XML wrote the link
    qualifier: Qualifier = field(default_factory=Qualifier)
    # ``(bwb_id, article_number)`` the link of the XML points at, when the text names
    # another article (``text_target``)
    linked: tuple[str, str] | None = None
    # the footnote of the article it stands in (its place in ``footnotes``): ``start`` and
    # ``end`` are offsets into that footnote, no span of the text
    footnote: int | None = None


def _books_of(law_id: str) -> dict[str, str]:
    """The books of the code (``CODE_FAMILIES``) that *law_id* is a book of."""
    code = family_of(law_id)
    return CODE_FAMILIES[code] if code else {}


def text_target(text: str, bwb_id: str, number: str) -> tuple[str, str]:
    """``(bwb_id, number)`` of the article a reference names, by its text where the text
    and the link of the XML differ.

    The link is written by hand beside the words and is sometimes wrong where the words are
    not: "artikel 230m" linked to article 230, "artikel 1133" to 113, "Artikel 62 leden 2 en
    3 van Boek 4" to article 178. A number the text names wins over the linked one unless
    the link is one of the numbers the text names (an enumeration or a range is one link
    per article), or the two are numbered in different ways (``6.1`` beside ``6:21``: the
    text names an article of another law). Where the link points into a book of a code, a
    book the text names ("van Boek 4", ``6:162``) wins over the linked book. A text that
    names no number leaves the link as it is. A number written with a space between its
    thousands ("artikel 1 064") is one number.
    """
    text = _THOUSANDS_RE.sub("", text or "")
    head = _TEXT_NUMBERS_RE.match(text)
    if not head:
        return bwb_id, number
    books = _books_of(bwb_id)
    law = bwb_id
    book = _OF_BOOK_RE.search(text, head.end())
    if book and books.get(book["book"].upper()):
        law = books[book["book"].upper()]
    numbers: list[str] = []
    for named in parse_article_numbers(head["nums"]):
        prefix, colon, rest = named.partition(":")
        if colon and books.get(prefix.upper()):
            law, named = books[prefix.upper()], rest
        numbers.append(named.lower())
    if law == bwb_id and (
        number.lower() in numbers or _in_range(head["nums"], numbers, number)
    ):
        return bwb_id, number
    if not numbers or _skeleton(numbers[0]) != _skeleton(number):
        # "6.1" beside a link to "6:21": another numbering, so another law than the
        # link's; which one the text does not say.
        return bwb_id, number
    return law, numbers[0]


def _in_range(written: str, numbers: list[str], number: str) -> bool:
    """Whether *number* lies in the range the text writes ("395a tot en met 397"): a range
    is linked to any article in it."""
    if len(numbers) != 2 or not re.search(r"\btot\s+en\s+met\b", written, re.I):
        return False
    return (
        article_order(numbers[0]) <= article_order(number) <= article_order(numbers[1])
    )


def _skeleton(number: str) -> str:
    """How an article number is built, letters left out: ``230`` and ``230m`` are ``9``,
    ``6:21`` is ``9:9``, ``6.1`` is ``9.9``."""
    return number_shape(number).replace("a", "")


def hits_from_references(
    references: list[dict[str, Any]], own_bwb_id: str, own_article_number: str | None
) -> list[ArticleReferenceHit]:
    """Hits for the structured references stored on an article (``props.references``).

    Those references come from the ``<extref>``/``<intref>`` elements of the BWB
    XML: the words of the text and a link beside them, so a reference is certain,
    confidence 1.0. Where the words name another article than the link, the words
    count (``text_target``) and ``linked`` keeps what the link said: the pipeline falls
    back on it when the graph has no article the words name ("artikel 98lid 1"). Entries without a
    regulation or article number have no target and are dropped, as is a reference to
    the article itself.
    """
    hits: list[ArticleReferenceHit] = []
    for ref in references:
        linked_id, linked_number = ref.get("bwb_id"), ref.get("article")
        if not linked_id or not linked_number:
            continue
        text = str(ref.get("text") or "")
        bwb_id, number = text_target(text, str(linked_id), str(linked_number))
        if bwb_id == own_bwb_id and number == own_article_number:
            continue
        changed = (bwb_id, number) != (linked_id, linked_number)
        hits.append(
            ArticleReferenceHit(
                start=int(ref.get("start") or 0),
                end=int(ref.get("end") or 0),
                text=text,
                bwb_id=bwb_id,
                article_number=number,
                confidence=EXACT_CONFIDENCE,
                cross_law=bwb_id != own_bwb_id,
                reason=REASON_XML_REF,
                kind=ref.get("kind"),
                qualifier=Qualifier.from_dict(ref),
                linked=(str(linked_id), str(linked_number)) if changed else None,
                footnote=footnote
                if isinstance(footnote := ref.get("footnote"), int)
                else None,
            )
        )
    return hits
