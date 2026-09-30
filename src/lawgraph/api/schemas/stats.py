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


class DataAsOfDTO(BaseModel):
    """How current the graph is for one source."""

    model_config = ConfigDict(extra="forbid")

    retrieved_at: str | None = Field(
        None, description="When its newest raw record was fetched (UTC, ISO 8601)."
    )
    newest: str | None = Field(
        None,
        description="The date of its newest dated record, on or before today: a paper of "
        "the Kamer, a judgment, a publication, a version of a law coming into force. Null "
        "for a source without dated records.",
    )


class StatsResponse(BaseModel):
    """Database statistics: document counts per collection and edge counts."""

    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, int] = Field(
        ...,
        description="Documents per collection, without stubs; `judgments` without the "
        "`replaced` publications, the `total` of `/api/judgments`.",
    )
    stubs: dict[str, int] = Field(
        default_factory=dict,
        description="Per collection that has them (instruments, articles, judgments): the "
        "nodes known only because something refers to them, without a text of their own.",
    )
    replaced: dict[str, int] = Field(
        default_factory=dict,
        description="Per collection that has them (judgments): the publications of a "
        "decision that another loaded publication replaces (`SAME_AS`, the Rechtspraak "
        "published many old arresten again under a new ECLI). `nodes` counts the decision "
        "once, by the one kept, as `/api/judgments` does.",
    )
    edges: EdgeStatsDTO
    by_source: dict[str, dict[str, int]] = {}
    instruments: InstrumentStatsDTO = InstrumentStatsDTO()
    data_as_of: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="Per source (`tk`, `eerstekamer`, `rechtspraak`, `staatsblad`, "
        "`staatscourant`, `bwb`, `eurlex`, …): how current the graph is.",
    )


class CoverageCourtDTO(BaseModel):
    """The judgments of one court in the graph."""

    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(None, description="`rechtspraak` or `echr`.")
    tier: str | None = Field(
        None,
        description="The Type of the court in the Instanties value list: `hoge_raad`, "
        "`parket` (the conclusions of the Parket bij de Hoge Raad), `raad_van_state`, "
        "`gerechtshof`, `rechtbank`, `andere_instantie`, … (``core.courts.TIERS``).",
    )
    court_kind: str | None = Field(
        None,
        description="The kind of court within the tier (`ambtenarengerecht`); a tier of "
        "one kind of court is its own kind.",
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

    ``total`` counts the judgments whose text is loaded, a decision published twice once
    (the ``total`` of ``/api/judgments``); ``stubs`` the judgments known only because a
    loaded text cites them (they cite nothing themselves).
    """

    model_config = ConfigDict(extra="forbid")

    total: int
    first_date: str | None = None
    last_date: str | None = None
    stubs: int = Field(..., description="Cited judgments whose text is not loaded.")
    replaced: int = Field(
        0,
        description="Publications of a decision that another loaded publication replaces "
        "(`SAME_AS`); not in `total`, the tiers or the courts.",
    )
    tiers: list[CoverageTierDTO] = Field(
        ...,
        description="Per tier: the highest courts first, the parket, the courts of first "
        "instance and appeal, the disciplinary tribunals, the other colleges, the "
        "Caribbean part, then the courts outside the Netherlands, the EHRM last.",
    )
    courts: list[CoverageCourtDTO] = Field(..., description="Per court, most first.")
