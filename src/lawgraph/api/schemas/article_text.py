"""The narrow form of an article: its heading, its text as blocks per lid and onderdeel with
the links in them, and the articles before and after it (``GET /api/articles/.../text``,
``/api/articles/batch``)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.articles import headings_from_props, parts_from_props
from lawgraph.api.schemas.common import (
    ARTICLE_ADDRESS,
    OFFICIAL_ID,
    PathSource,
    QualifierFields,
    StrictModel,
    WithPath,
    address_of,
)
from lawgraph.api.schemas.validity import VALIDITY, ValidityDTO
from lawgraph.core.article_blocks import Block, article_blocks
from lawgraph.core.models import node_id, parse_node_id
from lawgraph.core.names import article_cite
from lawgraph.core.qualifiers import Qualifier
from lawgraph.core.reference_targets import reference_target
from lawgraph.db.queries.article_text import ArticleTextData

# The most articles one ``/batch`` asks for.
BATCH_MAX = 20


class ArticleTextLawDTO(WithPath):
    """The law an article stands in."""

    path_source = PathSource("instruments")

    id: str
    key: str
    bwb_id: str | None
    celex: str | None
    official_id: str | None = Field(description=OFFICIAL_ID)
    title: str | None
    citation_title: str | None
    abbreviation: str | None = Field(
        description="The abbreviation it is cited by (`Cbw`), as `abbreviation` of the "
        "instrument."
    )

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ArticleTextLawDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["id"],
            key=doc["key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            official_id=props.get("official_id"),
            title=props.get("title"),
            citation_title=props.get("citation_title"),
            abbreviation=props.get("abbreviation"),
        )


class ArticleNeighborDTO(WithPath):
    """The article before or after one in the list of the articles of its law."""

    path_source = PathSource("articles")

    id: str
    key: str
    bwb_id: str | None
    celex: str | None
    official_id: str | None
    article_number: str | None
    label: str | None = Field(description="`Artikel 67`.")
    address: str = Field(description=ARTICLE_ADDRESS)

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ArticleNeighborDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["id"],
            key=doc["key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            official_id=props.get("official_id"),
            article_number=props.get("article_number"),
            label=props.get("label"),
            address=address_of(doc),
        )


class ArticleTextLinkTargetDTO(WithPath):
    """What a link opens: an article, a judgment, a law, an annex or an EU act."""

    id: str
    key: str
    collection: str
    bwb_id: str | None
    celex: str | None
    official_id: str | None
    article_number: str | None


class ArticleTextLinkDTO(QualifierFields):
    """A reference in a block whose target the data holds, with the place it names."""

    start: int = Field(description="Offset of `text` in the `text` of the block.")
    end: int
    text: str
    target: ArticleTextLinkTargetDTO


class ArticleTextBlockDTO(StrictModel):
    """A lid, an onderdeel, an aanhef or a paragraph of the text, in text order."""

    anchor: str | None = Field(
        description="The id of its part (`lid-1`, `lid-2-aanhef`, `lid-2-onder-b`), the "
        "anchor of the place; null outside every part (an article without leden). It "
        "repeats where its part goes on after a part inside it (a line after a list)."
    )
    kind: str = Field(
        description="`lid`, `onderdeel`, `aanhef` or `tekst` (the kind of its part, "
        "`tekst` outside every part), or `kop` (a heading on a line of its own)."
    )
    number: str | None = Field(description="Its number as printed: `2`, `a`, `1°`.")
    marker: str | None = Field(
        description="What is printed before it: `2.`, `a.`; null for none."
    )
    within: list[str] = Field(
        description="The anchors of the parts it stands in, the outermost first: `lid-2` "
        "of `lid-2-onder-a`. A lid with an aanhef has no block of its own: its aanhef and "
        "onderdelen name it here."
    )
    text: str = Field(description="Its text, a paragraph a line.")
    links: list[ArticleTextLinkDTO]


class ArticleTextDTO(WithPath):
    """An article to read beside something else: its heading, its text in blocks, and the
    articles before and after it."""

    path_source = PathSource("articles")

    id: str
    key: str
    bwb_id: str | None
    celex: str | None
    official_id: str | None = Field(description=OFFICIAL_ID)
    article_number: str | None
    address: str = Field(description=ARTICLE_ADDRESS)
    label: str | None = Field(description="`Artikel 68`.")
    heading: str | None = Field(
        description="The title of its kop: `(toezichthouders)`."
    )
    display_name: str | None = Field(description="How it is cited: `Art. 68 Cbw`.")
    repealed: bool
    validity: ValidityDTO | None = Field(description=VALIDITY)
    law: ArticleTextLawDTO | None
    blocks: list[ArticleTextBlockDTO]
    previous: ArticleNeighborDTO | None = Field(
        description="The article before it in its law, as `/api/instruments/{bwb_id}/"
        "articles` lists them; null for the first, and for one not in that list."
    )
    next: ArticleNeighborDTO | None = Field(
        description="The article after it; null for the last."
    )

    @classmethod
    def build(
        cls,
        data: ArticleTextData,
        present: set[tuple[str, str]],
        validity: ValidityDTO | None,
    ) -> ArticleTextDTO:
        doc = data.article
        props = doc.get("props") or {}
        return cls(
            id=doc["id"],
            key=doc["key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            official_id=props.get("official_id"),
            article_number=props.get("article_number"),
            address=address_of(doc),
            label=props.get("label"),
            heading=props.get("heading"),
            display_name=article_cite(props) or None,
            repealed=bool(props.get("repealed")),
            validity=validity,
            law=ArticleTextLawDTO.from_document(data.instrument)
            if data.instrument
            else None,
            blocks=text_blocks(props, _links(data, present)),
            previous=ArticleNeighborDTO.from_document(data.previous)
            if data.previous
            else None,
            next=ArticleNeighborDTO.from_document(data.next) if data.next else None,
        )


class ArticleTextBatchItem(StrictModel):
    """One article a batch asks for, in the order it asks."""

    ref: str = Field(description="As asked: `BWBR0052875/19`.")
    article: ArticleTextDTO | None = Field(
        description="Null when the data does not hold it."
    )


class ArticleTextBatchResponse(StrictModel):
    items: list[ArticleTextBatchItem]
    not_in_data: list[str] = Field(
        description="The `ref`s of the items the data does not hold, in their order."
    )


# A link before it is cut to its block: its span in the text of the article.
_Link = tuple[int, int, str, ArticleTextLinkTargetDTO, Qualifier]


def _citation_link(entry: Any) -> _Link | None:
    """The link of a citation (``ArticleCitationEntry``) with a span."""
    if entry.start is None or entry.end is None or entry.end <= entry.start:
        return None
    target = entry.target
    props = target.get("props") or {}
    collection, _ = parse_node_id(target["id"])
    return (
        entry.start,
        entry.end,
        entry.text or "",
        ArticleTextLinkTargetDTO(
            id=target["id"],
            key=target["key"],
            collection=collection,
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            official_id=props.get("official_id"),
            article_number=props.get("article_number"),
            path_props=props,
        ),
        entry.qualifier,
    )


def _reference_link(ref: Any, present: set[tuple[str, str]]) -> _Link | None:
    """The link of a reference of the XML of the text whose target the data holds."""
    if not isinstance(ref, dict) or ref.get("footnote") is not None:
        return None
    target = reference_target(ref)
    start, end = ref.get("start"), ref.get("end")
    if target is None or target not in present:
        return None
    if not (isinstance(start, int) and isinstance(end, int) and start < end):
        return None
    collection, key = target
    return (
        start,
        end,
        str(ref.get("text") or ""),
        ArticleTextLinkTargetDTO(
            id=node_id(collection, key),
            key=key,
            collection=collection,
            bwb_id=ref.get("bwb_id"),
            celex=ref.get("celex"),
            official_id=None,
            article_number=ref.get("article"),
        ),
        Qualifier.from_dict(ref),
    )


def _links(data: ArticleTextData, present: set[tuple[str, str]]) -> list[_Link]:
    """The links of the text in text order: its citations, and each reference of its XML
    that overlaps none of them (as the explorer's ``referenceSpans`` joins them)."""
    links = [link for e in data.citations if (link := _citation_link(e))]
    taken = list(links)
    stored = (data.article.get("props") or {}).get("references")
    for ref in stored if isinstance(stored, list) else []:
        link = _reference_link(ref, present)
        if link and not any(link[0] < t[1] and link[1] > t[0] for t in taken):
            links.append(link)
            taken.append(link)
    return sorted(links, key=lambda link: (link[0], link[1]))


def _block_dto(text: str, block: Block, links: list[_Link]) -> ArticleTextBlockDTO:
    """The block *block* of *text* with the *links* that start in it, cut to it."""
    return ArticleTextBlockDTO(
        anchor=block.anchor,
        kind=block.kind,
        number=block.number,
        marker=block.marker,
        within=list(block.within),
        text=text[block.start : block.end],
        links=[
            ArticleTextLinkDTO(
                start=start - block.start,
                end=min(end, block.end) - block.start,
                text=text[start : min(end, block.end)] or label,
                target=target,
                **qualifier.to_dict(),
            )
            for start, end, label, target, qualifier in links
            if block.start <= start < block.end
        ],
    )


def text_blocks(props: dict[str, Any], links: list[_Link]) -> list[ArticleTextBlockDTO]:
    """The blocks of the text of an article of *props*, each with its *links*."""
    text = props.get("text")
    if not isinstance(text, str):
        return []
    blocks = article_blocks(text, parts_from_props(props), headings_from_props(props))
    return [_block_dto(text, block, links) for block in blocks]
