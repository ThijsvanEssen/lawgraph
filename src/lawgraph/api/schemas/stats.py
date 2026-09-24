"""Stats endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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

    nodes: dict[str, int] = Field(
        ..., description="Documents per collection, without stubs."
    )
    stubs: dict[str, int] = Field(
        default_factory=dict,
        description="Per collection that has them (instruments, articles, judgments): the "
        "nodes known only because something refers to them, without a text of their own.",
    )
    edges: EdgeStatsDTO
    by_source: dict[str, dict[str, int]] = {}
    instruments: InstrumentStatsDTO = InstrumentStatsDTO()


class CoverageCourtDTO(BaseModel):
    """The judgments of one court in the graph."""

    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(None, description="`rechtspraak` or `echr`.")
    tier: str | None = Field(
        None,
        description="`hoge_raad`, `parket` (the conclusions of the Parket bij de Hoge Raad), "
        "`raad_van_state`, `centrale_raad_van_beroep`, `gerechtshof`, `rechtbank`, … one per "
        "college (``core.judgments.TIERS``).",
    )
    court_code: str | None = Field(None, description="The court in the ECLI: `GHAMS`.")
    court: str | None = Field(None, description="Its name: Gerechtshof Amsterdam.")
    count: int
    first_date: str | None = Field(None, description="Date of its oldest judgment.")
    last_date: str | None = Field(None, description="Date of its newest judgment.")


class CoverageTierDTO(BaseModel):
    """The judgments of one court tier in the graph."""

    model_config = ConfigDict(extra="forbid")

    tier: str | None = None
    count: int
    first_date: str | None = None
    last_date: str | None = None


class JudgmentCoverageResponse(BaseModel):
    """Which judgments the graph holds: a count of case law is a count of this selection.

    ``total`` counts the judgments whose text is loaded; ``stubs`` the judgments known only
    because a loaded text cites them (they cite nothing themselves).
    """

    model_config = ConfigDict(extra="forbid")

    total: int
    first_date: str | None = None
    last_date: str | None = None
    stubs: int = Field(..., description="Cited judgments whose text is not loaded.")
    tiers: list[CoverageTierDTO] = Field(
        ...,
        description="Per tier: the highest courts first, the parket, the courts of first "
        "instance and appeal, the other colleges, the EHRM last.",
    )
    courts: list[CoverageCourtDTO] = Field(..., description="Per court, most first.")
