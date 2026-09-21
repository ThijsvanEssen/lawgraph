"""Turn the structured references of a BWB article into linkable hits.

Pure functions — no store access. The BWB XML records every reference as an
``<extref>``/``<intref>`` element; ``core.bwb_xml`` stores them on the article
as ``props.references`` and this module turns them into edge candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REASON_XML_REF = "bwb_xml_ref"


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


def hits_from_references(
    references: list[dict[str, Any]], own_bwb_id: str, own_article_number: str | None
) -> list[ArticleReferenceHit]:
    """Hits for the structured references stored on an article (``props.references``).

    Those references come from the ``<extref>``/``<intref>`` elements of the BWB
    XML, so they are exact: confidence 1.0. Entries without a regulation or
    article number have no target and are dropped, as is a reference to the
    article itself.
    """
    hits: list[ArticleReferenceHit] = []
    for ref in references:
        bwb_id, number = ref.get("bwb_id"), ref.get("article")
        if not bwb_id or not number:
            continue
        if bwb_id == own_bwb_id and number == own_article_number:
            continue
        hits.append(
            ArticleReferenceHit(
                start=int(ref.get("start") or 0),
                end=int(ref.get("end") or 0),
                text=str(ref.get("text") or ""),
                bwb_id=str(bwb_id),
                article_number=str(number),
                confidence=1.0,
                cross_law=bwb_id != own_bwb_id,
                reason=REASON_XML_REF,
            )
        )
    return hits
