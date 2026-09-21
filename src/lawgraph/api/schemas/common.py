"""Building blocks shared by several API domains: instrument / article / judgment
summaries, citation spans, article relations and community votes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.core.models import make_node_key


class InstrumentSummaryDTO(BaseModel):
    """Short representation of an instrument."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    article_count: int = 0
    judgment_count: int = 0
    inbound_citation_count: int = 0
    outbound_citation_count: int = 0

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        stats: Any = None,
    ) -> InstrumentSummaryDTO:
        """Build from an ArangoDB document and an optional InstrumentStats dataclass."""
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name"),
            article_count=int(getattr(stats, "article_count", 0) or 0),
            judgment_count=int(getattr(stats, "judgment_count", 0) or 0),
            inbound_citation_count=int(
                getattr(stats, "inbound_citation_count", 0) or 0
            ),
            outbound_citation_count=int(
                getattr(stats, "outbound_citation_count", 0) or 0
            ),
        )


class ArticleCitationTarget(BaseModel):
    """Minimal metadata describing the referenced article."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    bwb_id: str | None
    article_number: str | None
    display_name: str | None


class ArticleCitationSpan(BaseModel):
    """Character span for an internal citation inside the source article."""

    model_config = ConfigDict(extra="forbid")

    start: int | None
    end: int | None
    text: str | None
    target: ArticleCitationTarget
    kind: str = "article"
    confidence: float | None = None


class JudgmentSummaryDTO(BaseModel):
    """Lightweight judgment summary for listing matches."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    ecli: str | None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> JudgmentSummaryDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name"),
            ecli=props.get("ecli"),
        )


class ArticleRelationDTO(BaseModel):
    """Article reference plus optional parent instrument used in judgment responses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    bwb_id: str | None
    celex: str | None = None
    article_number: str | None
    instrument: InstrumentSummaryDTO | None

    @classmethod
    def from_documents(
        cls,
        article_doc: dict[str, Any],
        instrument_doc: dict[str, Any] | None,
    ) -> ArticleRelationDTO:
        props = article_doc.get("props") or {}
        instrument = (
            InstrumentSummaryDTO.from_document(instrument_doc)
            if instrument_doc
            else None
        )
        return cls(
            id=article_doc["_id"],
            key=article_doc["_key"],
            display_name=props.get("display_name"),
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            article_number=props.get("article_number"),
            instrument=instrument,
        )


class CommunityVotes(BaseModel):
    """Community vote counters on a semantic relationship."""

    model_config = ConfigDict(extra="forbid")

    upvotes: int = 0
    downvotes: int = 0


class DossierRefDTO(BaseModel):
    """Reference to a Kamerstukdossier by number; ``title`` is null when unknown."""

    model_config = ConfigDict(extra="forbid")

    number: str
    key: str
    title: str | None = None

    @classmethod
    def from_number(
        cls, number: Any, titles: dict[str, str | None] | None = None
    ) -> DossierRefDTO:
        """Build from a dossier number and an optional ``key -> title`` lookup."""
        text = str(number)
        key = make_node_key(text)
        return cls(number=text, key=key, title=(titles or {}).get(key))


class PublicationDTO(BaseModel):
    """An amending publication (Staatsblad, Tractatenblad, ...) as recorded on a version."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    kind: str | None = None
    year: int | None = None
    number: str | None = None
    signed: str | None = None
    published: str | None = None
    dossiers: list[DossierRefDTO] = Field(default_factory=list)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        titles: dict[str, str | None] | None = None,
    ) -> PublicationDTO | None:
        """Build from a ``Publication.to_dict()`` prop; None when there is none."""
        if not isinstance(data, dict) or not data:
            return None
        year = data.get("year")
        number = data.get("number")
        return cls(
            id=data.get("id"),
            kind=data.get("kind"),
            year=year if isinstance(year, int) else None,
            number=str(number) if number is not None else None,
            signed=data.get("signed"),
            published=data.get("published"),
            dossiers=[
                DossierRefDTO.from_number(n, titles)
                for n in (data.get("dossiers") or [])
                if n is not None and str(n).strip()
            ],
        )
