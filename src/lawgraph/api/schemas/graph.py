"""Graph-view endpoints: global, instrument-layer and judgment-layer graphs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class InstrumentLayerInstrumentDTO(BaseModel):
    """Instrument node in the instrument-layer graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    display_name: str | None = None
    citation_title: str | None = None
    title: str | None = None
    shorthand: str | None = None
    jurisdiction: str | None = None
    stub: bool = False
    citation_count: int = 0

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        stats: dict[str, Any] | None = None,
    ) -> InstrumentLayerInstrumentDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            display_name=(
                props.get("display_name")
                or props.get("citation_title")
                or props.get("title")
            ),
            citation_title=props.get("citation_title"),
            title=props.get("title"),
            shorthand=props.get("short_title") or props.get("shorthand"),
            jurisdiction=props.get("jurisdiction"),
            stub=bool(props.get("stub", False)),
            citation_count=int((stats or {}).get("citation_count", 0)),
        )


class JudgmentGraphNodeDTO(BaseModel):
    """Judgment node in the judgment-layer or global graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None = None
    shorthand: str | None = None
    ecli: str | None = None
    stub: bool = False

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> JudgmentGraphNodeDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name") or props.get("ecli"),
            shorthand=props.get("shorthand"),
            ecli=props.get("ecli"),
            stub=bool(props.get("stub", False)),
        )


class ArticleGraphNodeDTO(BaseModel):
    """Article node for the global graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    article_number: str | None = None
    display_name: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ArticleGraphNodeDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
            display_name=props.get("display_name"),
        )


class GraphEdgeDTO(BaseModel):
    """Graph edge with optional text annotation (for global/article-level graphs)."""

    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    relation_type: str
    start: int | None = None
    end: int | None = None
    text: str | None = None
    confidence: float | None = None
    semantic_type: str | None = None
    explanation: str | None = None


class InstrumentEdgeDTO(BaseModel):
    """Aggregated instrument-layer edge with weight."""

    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    relation_type: str
    weight: float | None = None
    confidence: float | None = None


class InstrumentLayerGraphResponse(BaseModel):
    """Response for GET /api/graph/instruments."""

    model_config = ConfigDict(extra="forbid")

    instruments: list[InstrumentLayerInstrumentDTO]
    edges: list[InstrumentEdgeDTO]
    metadata: dict[str, Any] | None = None


class GlobalGraphResponse(BaseModel):
    """Response for GET /api/graph/global."""

    model_config = ConfigDict(extra="forbid")

    instruments: list[InstrumentLayerInstrumentDTO]
    articles: list[ArticleGraphNodeDTO]
    judgments: list[JudgmentGraphNodeDTO]
    edges: list[GraphEdgeDTO]
    metadata: dict[str, Any] | None = None


class JudgmentLayerGraphResponse(BaseModel):
    """Response for GET /api/graph/judgments."""

    model_config = ConfigDict(extra="forbid")

    judgments: list[JudgmentGraphNodeDTO]
    instruments: list[InstrumentLayerInstrumentDTO]
    edges: list[InstrumentEdgeDTO]
    metadata: dict[str, Any] | None = None
