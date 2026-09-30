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
    number_shape,
    parse_article_numbers,
)
from lawgraph.core.code_families import CODE_FAMILIES
from lawgraph.core.qualifiers import Qualifier

REASON_XML_REF = "bwb_xml_ref"

# The article numbers a reference's text starts with: "artikel 230m lid 1", "Artikel 62
# leden 2 en 3 van Boek 4", "1116 tot en met 1118". A text that starts otherwise ("titel 3
# van Boek 6", "het eerste lid") names no article number to check the link against.
_TEXT_NUMBERS_RE = re.compile(
    rf"^\s*(?:(?:de|het)\s+)?(?:(?:artikel(?:en)?|art\.?)\s+)?"
    rf"(?P<nums>{ARTICLE_NUMBERS_PATTERN})(?![\w:]|\.\d)",
    re.IGNORECASE,
)
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


def _books_of(law_id: str) -> dict[str, str]:
    """The books of the code (``CODE_FAMILIES``) that *law_id* is a book of."""
    for books in CODE_FAMILIES.values():
        if law_id in books.values():
            return books
    return {}


def text_target(
    text: str, bwb_id: str, number: str, own_bwb_id: str
) -> tuple[str, str]:
    """``(bwb_id, number)`` of the article a reference names, by its text where the text
    and the link of the XML differ.

    The link is written by hand beside the words and is sometimes wrong where the words are
    not: "artikel 230m" linked to article 230, "artikel 1133" to 113, "Artikel 62 leden 2 en
    3 van Boek 4" to article 178. A number the text names wins over the linked one unless
    the link is one of the numbers the text names (an enumeration or a range is one link
    per article), or the two are numbered in different ways (``6.1`` beside ``6:21``: the
    text names an article of another law). Where the link points into a book of a code, a
    book the text names ("van Boek 4", ``6:162``) wins over the linked book. A text that
    names no number leaves the link as it is.
    """
    head = _TEXT_NUMBERS_RE.match(text or "")
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


def _order(number: str) -> tuple[tuple[int, str], ...]:
    """An article number as it sorts: ``5:10a`` after ``5:10`` and before ``5:11``."""
    return tuple(
        (int(digits), letters)
        for digits, letters in re.findall(r"(\d+)([a-z]*)", number.lower())
    )


def _in_range(written: str, numbers: list[str], number: str) -> bool:
    """Whether *number* lies in the range the text writes ("395a tot en met 397"): a range
    is linked to any article in it."""
    if len(numbers) != 2 or not re.search(r"\btot\s+en\s+met\b", written, re.I):
        return False
    return _order(numbers[0]) <= _order(number) <= _order(numbers[1])


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
        bwb_id, number = text_target(
            text, str(linked_id), str(linked_number), own_bwb_id
        )
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
                confidence=1.0,
                cross_law=bwb_id != own_bwb_id,
                reason=REASON_XML_REF,
                kind=ref.get("kind"),
                qualifier=Qualifier.from_dict(ref),
                linked=(str(linked_id), str(linked_number)) if changed else None,
            )
        )
    return hits
