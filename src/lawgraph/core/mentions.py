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
from typing import Any, Literal

from lawgraph.core.citations import (
    CitationHit,
    hit_reason,
    snippet_bounds,
)
from lawgraph.core.qualifiers import Qualifier, parse_qualifier

# The most mentions an edge keeps. A judgment that cites one article hundreds of times
# (a ruling on a single provision) keeps the first ones; ``mention_count`` is the whole number.
MAX_MENTIONS_PER_EDGE = 100

# (bwb_id, celex, article_number, unknown_law): one article a judgment cites.
MentionKey = tuple[str | None, str | None, str | None, str | None]

# What names an article a judgment cites (``origin`` of the edge): its text, its metadata.
CitationOrigin = Literal["text", "metadata"]

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
    # where ``snippet`` stands in that text: ``snippet[start - snippet_start:end -
    # snippet_start]`` is ``raw_match``; None for a mention stored without it
    snippet_start: int | None
    confidence: float
    # the label of the footnote that cites it, the referring paragraph its paragraph: start
    # and end are then offsets into the text of the footnote
    footnote: str | None = None

    def to_dict(self, *, parts: bool = True) -> dict[str, Any]:
        """The mention as stored in ``meta.mentions`` of the edge; without the lid and
        onderdeel (*parts*) for a citation of what has none, a judgment."""
        stored: dict[str, Any] = {
            "paragraph_id": self.paragraph_id,
            "start": self.start,
            "end": self.end,
            "raw_match": self.raw_match,
            **(self.parts.to_dict() if parts else {}),
            "snippet": self.snippet,
            "confidence": self.confidence,
        }
        if self.snippet_start is not None:
            stored["snippet_start"] = self.snippet_start
        if self.paragraph_number:
            stored["paragraph_number"] = self.paragraph_number
        if self.qualifier:
            stored["qualifier"] = self.qualifier
        if self.footnote:
            stored["footnote"] = self.footnote
        return stored

    def in_snippet(self, text: str) -> tuple[int, int] | None:
        """Where ``raw_match`` stands in ``snippet``: ``snippet[start:end]``, from *text*,
        the paragraph or footnote the mention was read in (``mention_texts``). None when
        *text* no longer holds the mention or its snippet (normalized again since)."""
        if text[self.start : self.end] != self.raw_match:
            return None
        begin, finish = snippet_bounds(text, (self.start, self.end))
        if text[begin:finish] != self.snippet:
            return None
        return self.start - begin, self.end - begin

    def passage(self) -> dict[str, Any] | None:
        """The mention as a passage to show without the text of the judgment: its paragraph
        (``paragraph_id``, ``paragraph_number``, ``footnote``), ``snippet``, the citation as
        written (``text``) and where it stands in the snippet (``start``, ``end``:
        ``snippet[start:end]`` is ``text``). None for a mention stored without
        ``snippet_start``, or whose snippet does not hold it there."""
        if self.snippet_start is None:
            return None
        start, end = self.start - self.snippet_start, self.end - self.snippet_start
        if start < 0 or self.snippet[start:end] != self.raw_match:
            return None
        return {
            "paragraph_id": self.paragraph_id,
            "paragraph_number": self.paragraph_number,
            "footnote": self.footnote,
            "snippet": self.snippet,
            "text": self.raw_match,
            "start": start,
            "end": end,
        }

    @classmethod
    def read(
        cls,
        paragraph: Mapping[str, Any],
        text: str,
        span: tuple[int, int],
        *,
        confidence: float,
        qualifier: str | None = None,
    ) -> Mention:
        """The mention ``text[span[0]:span[1]]`` of *paragraph* (``{id, number}``, a
        footnote with its ``footnote`` label, as :func:`find_mentions` reads them), *text*
        its text, with its snippet cut by ``core.citations.snippet_bounds``."""
        start, end = span
        begin, finish = snippet_bounds(text, span)
        return cls(
            paragraph_id=str(paragraph["id"]),
            paragraph_number=_text(paragraph.get("number")),
            start=start,
            end=end,
            raw_match=text[start:end],
            qualifier=qualifier,
            parts=parse_qualifier(qualifier),
            snippet=text[begin:finish],
            snippet_start=begin,
            confidence=confidence,
            footnote=_text(paragraph.get("footnote")),
        )

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
        paragraph_id, snippet_start = (
            stored.get("paragraph_id"),
            stored.get("snippet_start"),
        )
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
            snippet_start=snippet_start if isinstance(snippet_start, int) else None,
            confidence=float(confidence),
            footnote=_text(stored.get("footnote")),
        )


def footnote_paragraphs(
    paragraphs: Sequence[Mapping[str, Any]], footnotes: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The footnotes of a judgment (``core.judgment_paragraphs.judgment_text``) as paragraphs for
    :func:`find_mentions`: a citation in a footnote counts for the paragraph that refers
    to it (its id and number; ``referring``, null when none does), with the footnote's
    label (its place among them when it has none); one nothing refers to is a paragraph
    ``fn-<label>`` of its own."""
    numbers = {str(p.get("id")): p.get("number") for p in paragraphs}
    found: list[dict[str, Any]] = []
    for note in footnotes:
        label = _text(note.get("label")) or str(len(found) + 1)
        referring = _text(note.get("paragraph_id"))
        found.append(
            {
                "id": referring or f"fn-{label}",
                "number": numbers.get(referring) if referring else None,
                "text": str(note.get("text") or ""),
                "footnote": label,
                "referring": referring,
            }
        )
    return found


def mention_texts(
    paragraphs: Sequence[Mapping[str, Any]], footnotes: Sequence[Mapping[str, Any]]
) -> dict[tuple[str, str | None], str]:
    """The texts the mentions of a judgment are offsets into, by ``(paragraph_id,
    footnote)``: a paragraph's own text under ``None``, a footnote's under its label."""
    return {
        (str(p.get("id")), _text(p.get("footnote"))): str(p.get("text") or "")
        for p in [*paragraphs, *footnote_paragraphs(paragraphs, footnotes)]
    }


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass
class ArticleMentions:
    """Everything one judgment says about one article.

    The article of a law that is not in the graph has no id: *unknown_law* is the law as the
    judgment writes it (``Rv``).
    """

    bwb_id: str | None
    celex: str | None
    article_number: str | None
    reason: str
    # the first MAX_MENTIONS_PER_EDGE of them
    mentions: list[Mention] = field(default_factory=list)
    count: int = 0  # all of them
    confidence: float = 0.0  # the strongest
    unknown_law: str | None = None

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

    def unresolved(self) -> dict[str, Any]:
        """A citation of a law that is not in the graph, as the judgment keeps it
        (``props.unresolved_citations``): the law and article as written, and the first
        mention's text and qualifier."""
        first = self.mentions[0]
        stored: dict[str, Any] = {
            "law": self.unknown_law,
            "article_number": self.article_number,
            "raw_match": first.raw_match,
            **first.parts.to_dict(),
            "paragraph_ids": list(dict.fromkeys(m.paragraph_id for m in self.mentions)),
            "mention_count": self.count,
        }
        if first.qualifier:
            stored["qualifier"] = first.qualifier
        return stored


def find_mentions(
    paragraphs: Sequence[Mapping[str, Any]],
    detect: Callable[[str], Iterable[CitationHit]],
) -> dict[MentionKey, ArticleMentions]:
    """The articles a judgment cites, each with the places that cite it.

    *paragraphs* are the ``{id, number, text}`` of ``core.judgment_paragraphs.judgment_text``, and
    a footnote as one with its ``footnote`` label (``footnote_paragraphs``);
    *detect* reads a text and returns a hit for every citation, with its ``start`` and
    ``end`` (``detect_in_text(..., every_occurrence=True)``). The keys are
    ``(bwb_id, celex, article_number, unknown_law)``, in the order of first citation.
    """
    texts = [str(paragraph.get("text") or "") for paragraph in paragraphs]
    starts: list[int] = []
    position = 0
    for text in texts:
        starts.append(position)
        position += len(text) + len(_BREAK)

    found: dict[MentionKey, ArticleMentions] = {}
    for hit in detect(_BREAK.join(texts)):
        if hit.start is None or hit.end is None:
            continue
        index = bisect_right(starts, hit.start) - 1
        start, end = hit.start - starts[index], hit.end - starts[index]
        text = texts[index]
        if start >= len(text) or end > len(text):  # in the break, or over it
            continue
        key = (hit.bwb_id, hit.celex, hit.article_number, hit.unknown_law)
        target = found.get(key)
        if target is None:
            target = found[key] = ArticleMentions(
                bwb_id=hit.bwb_id,
                celex=hit.celex,
                article_number=hit.article_number,
                reason=hit_reason(hit),
                unknown_law=hit.unknown_law,
            )
        target.add(
            Mention.read(
                paragraphs[index],
                text,
                (start, end),
                confidence=hit.confidence,
                qualifier=hit.qualifier,
            )
        )
    return found
