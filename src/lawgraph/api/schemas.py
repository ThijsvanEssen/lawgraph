"""DTO definitions for the FastAPI layer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

_DROP_PROPS_KEYS = ("raw_xml",)


def _build_node_payload(doc: dict[str, Any], *, drop_props_keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    props: dict[str, Any] = {}
    raw_props = doc.get("props")
    if isinstance(raw_props, dict):
        props = raw_props
    sanitized = {
        key: value
        for key, value in props.items()
        if key not in (drop_props_keys or ())
    }
    return {
        "id": doc["_id"],
        "key": doc["_key"],
        "collection": doc["_id"].split("/", 1)[0] if "/" in doc["_id"] else doc["_id"],
        "type": doc.get("type", ""),
        "display_name": props.get("display_name"),
        "labels": list(doc.get("labels") or []),
        "props": sanitized or None,
    }


class BaseNodeDTO(BaseModel):
    """Common node representation used by multiple responses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> BaseNodeDTO:
        payload = _build_node_payload(doc, drop_props_keys=drop_props_keys)
        return cls(**payload)


class InstrumentDTO(BaseNodeDTO):
    """Instrument view model used by article and relation responses."""

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> InstrumentDTO:
        base = BaseNodeDTO.from_document(doc, drop_props_keys=drop_props_keys)
        return cls(**base.model_dump())


class ArticleDTO(BaseNodeDTO):
    """Dedicated article view model that exposes identifiers."""

    bwb_id: str | None
    article_number: str | None

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> ArticleDTO:
        base = BaseNodeDTO.from_document(doc, drop_props_keys=drop_props_keys)
        props = base.props or {}
        return cls(
            **base.model_dump(),
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
        )


class JudgmentDTO(BaseNodeDTO):
    """Rich judgment DTO that hides raw XML but exposes metadata."""

    ecli: str | None
    summary: str | None

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> JudgmentDTO:
        base = BaseNodeDTO.from_document(doc, drop_props_keys=drop_props_keys)
        props = doc.get("props") or {}
        return cls(
            **base.model_dump(),
            ecli=props.get("ecli"),
            summary=props.get("summary") or props.get("strafrecht_profile"),
        )


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
    article_number: str | None
    instrument: InstrumentDTO | None

    @classmethod
    def from_documents(
        cls,
        article_doc: dict[str, Any],
        instrument_doc: dict[str, Any] | None,
    ) -> ArticleRelationDTO:
        props = article_doc.get("props") or {}
        instrument = InstrumentDTO.from_document(
            instrument_doc) if instrument_doc else None
        return cls(
            id=article_doc["_id"],
            key=article_doc["_key"],
            display_name=props.get("display_name"),
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
            instrument=instrument,
        )


class ArticleDetailResponse(BaseModel):
    """Response model for article detail endpoint."""

    article: ArticleDTO
    instrument: InstrumentDTO | None
    judgments: list[JudgmentSummaryDTO]
    metadata: dict[str, Any] | None


class JudgmentDetailResponse(BaseModel):
    """Response model for judgment detail endpoint."""

    judgment: JudgmentDTO
    articles: list[ArticleRelationDTO]
    metadata: dict[str, Any] | None


class NeighborDTO(BaseModel):
    """Neighbor view used by the generic node explorer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None
    relation: str | None
    direction: Literal["outbound", "inbound"]
    confidence: float | None

    @classmethod
    def from_entry(
        cls,
        doc: dict[str, Any],
        relation: str | None,
        direction: Literal["outbound", "inbound"],
        confidence: float | None,
    ) -> NeighborDTO:
        payload = _build_node_payload(doc)
        return cls(**payload, relation=relation, direction=direction, confidence=confidence)


class NodeNeighborsDTO(BaseModel):
    strict: list[NeighborDTO]
    semantic: list[NeighborDTO]


class NodeGraphResponse(BaseModel):
    node: BaseNodeDTO
    neighbors: NodeNeighborsDTO
