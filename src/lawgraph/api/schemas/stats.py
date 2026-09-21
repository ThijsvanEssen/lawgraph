"""Stats endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EdgeStatsDTO(BaseModel):
    """Edge counts: total and per relation type."""

    model_config = ConfigDict(extra="forbid")

    total: int
    by_relation: dict[str, int]


class InstrumentStatsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_kind: dict[str, int] = {}
    by_jurisdiction: dict[str, int] = {}


class StatsResponse(BaseModel):
    """Database statistics: document counts per collection and edge counts."""

    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, int]
    edges: EdgeStatsDTO
    by_source: dict[str, dict[str, int]] = {}
    instruments: InstrumentStatsDTO = InstrumentStatsDTO()
