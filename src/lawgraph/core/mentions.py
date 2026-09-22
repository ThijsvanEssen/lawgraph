"""Where a judgment cites an article — pure, no I/O.

A judgment cites an article in its paragraphs, often more than once: "artikel 6:162 BW"
in the ratio, "art. 6:162, tweede lid, BW" a paragraph later. :func:`find_mentions` reads
every citation of every paragraph and answers, per article, the places that cite it: a
:class:`Mention` says which paragraph, where in its text, which lid or onderdeel it names
and how sure the detection is. The semantic pipeline stores them on the ``REFERS_TO`` edge
(one edge per judgment and article), and the API serves them back as the citation spans of a
paragraph and as the passages that cite an article.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.citations import CitationHit, hit_reason, make_snippet
from lawgraph.core.qualifiers import Qualifier, parse_qualifier

# The most mentions an edge keeps. A judgment that cites one article hundreds of times
# (a ruling on a single provision) keeps the first ones; ``mention_count`` is the whole number.
MAX_MENTIONS_PER_EDGE = 100

# Between two paragraphs of the text the detector reads: it is read as one text, so that
# "die wet" and "(hierna: de Awb)" reach across paragraphs as they do in the judgment.
# A citation that runs over the break is no citation of either paragraph and is left out.
_BREAK = "\n\n"


@dataclass(frozen=True)
class Mention:
    """One place in a judgment that cites an article."""

    paragraph_id: str
    paragraph_number: str | None
    start: int  # offsets into the text of that paragraph: text[start:end] is raw_match
    end: int
    raw_match: str
    qualifier: str | None  # as written: "derde lid"
    parts: Qualifier  # what the qualifier names: leden, onderdelen, aanhef
    snippet: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """The mention as stored in ``meta.mentions`` of the edge."""
        stored: dict[str, Any] = {
            "paragraph_id": self.paragraph_id,
            "start": self.start,
            "end": self.end,
            "raw_match": self.raw_match,
            **self.parts.to_dict(),
            "snippet": self.snippet,
            "confidence": self.confidence,
        }
        if self.paragraph_number:
            stored["paragraph_number"] = self.paragraph_number
        if self.qualifier:
            stored["qualifier"] = self.qualifier
        return stored

    @classmethod
    def from_dict(cls, stored: Any) -> Mention | None:
        """Read :meth:`to_dict` back; ``None`` for anything that is not a mention."""
        if not isinstance(stored, Mapping):
            return None
        start, end, confidence = (
            stored.get("start"),
            stored.get("end"),
            stored.get("confidence"),
        )
        paragraph_id = stored.get("paragraph_id")
        if not (
            isinstance(paragraph_id, str)
            and isinstance(start, int)
            and isinstance(end, int)
            and isinstance(confidence, (int, float))
        ):
            return None
        return cls(
            paragraph_id=paragraph_id,
            paragraph_number=_text(stored.get("paragraph_number")),
            start=start,
            end=end,
            raw_match=str(stored.get("raw_match") or ""),
            qualifier=_text(stored.get("qualifier")),
            parts=Qualifier.from_dict(stored),
            snippet=str(stored.get("snippet") or ""),
            confidence=float(confidence),
        )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass
class ArticleMentions:
    """Everything one judgment says about one article."""

    bwb_id: str | None
    celex: str | None
    article_number: str | None
    reason: str
    # the first MAX_MENTIONS_PER_EDGE of them
    mentions: list[Mention] = field(default_factory=list)
    count: int = 0  # all of them
    confidence: float = 0.0  # the strongest

    def add(self, mention: Mention) -> None:
        self.count += 1
        self.confidence = max(self.confidence, mention.confidence)
        if len(self.mentions) < MAX_MENTIONS_PER_EDGE:
            self.mentions.append(mention)

    def meta(self) -> dict[str, Any]:
        """The evidence on the edge."""
        return {
            "reason": self.reason,
            "mention_count": self.count,
            "mentions": [mention.to_dict() for mention in self.mentions],
        }


def find_mentions(
    paragraphs: Sequence[Mapping[str, Any]],
    detect: Callable[[str], Iterable[CitationHit]],
) -> dict[tuple[str | None, str | None, str | None], ArticleMentions]:
    """The articles a judgment cites, each with the places that cite it.

    *paragraphs* are the ``{id, number, text}`` of ``core.judgments.extract_sections``;
    *detect* reads a text and returns a hit for every citation, with its ``start`` and
    ``end`` (``detect_in_text(..., every_occurrence=True)``). The keys are
    ``(bwb_id, celex, article_number)``, in the order of first citation.
    """
    texts = [str(paragraph.get("text") or "") for paragraph in paragraphs]
    starts: list[int] = []
    position = 0
    for text in texts:
        starts.append(position)
        position += len(text) + len(_BREAK)

    found: dict[tuple[str | None, str | None, str | None], ArticleMentions] = {}
    for hit in detect(_BREAK.join(texts)):
        if hit.start is None or hit.end is None:
            continue
        index = bisect_right(starts, hit.start) - 1
        start, end = hit.start - starts[index], hit.end - starts[index]
        text = texts[index]
        if start >= len(text) or end > len(text):  # in the break, or over it
            continue
        paragraph = paragraphs[index]
        key = (hit.bwb_id, hit.celex, hit.article_number)
        target = found.get(key)
        if target is None:
            target = found[key] = ArticleMentions(
                bwb_id=hit.bwb_id,
                celex=hit.celex,
                article_number=hit.article_number,
                reason=hit_reason(hit),
            )
        target.add(
            Mention(
                paragraph_id=str(paragraph["id"]),
                paragraph_number=_text(paragraph.get("number")),
                start=start,
                end=end,
                raw_match=text[start:end],
                qualifier=hit.qualifier,
                parts=parse_qualifier(hit.qualifier),
                snippet=make_snippet(text, (start, end)),
                confidence=hit.confidence,
            )
        )
    return found
