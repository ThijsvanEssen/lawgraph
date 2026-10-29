"""Stats endpoint."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.api.schemas.completeness import COMPLETENESS, Completeness


class EdgeStatsDTO(StrictModel):
    """Edge counts: total and per relation type."""

    total: int
    by_relation: dict[str, int]


class InstrumentStatsDTO(StrictModel):
    by_kind: dict[str, int] = {}
    by_jurisdiction: dict[str, int] = {}


class DataAsOfDTO(StrictModel):
    """How current the graph is for one source."""

    retrieved_at: str | None = Field(
        None, description="When its newest raw record was fetched (UTC, ISO 8601)."
    )
    newest: str | None = Field(
        None,
        description="The date of its newest dated record, on or before today: a paper of "
        "the Kamer, a judgment, a publication, a version of a law coming into force. Null "
        "for a source without dated records.",
    )
    commitments_registered: str | None = Field(
        None,
        description="Of `tk` only: the newest day the Kamer registered a commitment "
        "(`registered_on` of `/api/commitments`), on or before today; a commitment is "
        "fetched apart from the papers.",
    )
    completeness: Completeness = Field(
        description=f"{COMPLETENESS} Of a source its `source`: `done`, `paused` (off: no "
        "scheduled run asks it anything), `unavailable` (it refused the last run) or "
        "`pending` (nothing fetched yet), with `as_of`.",
    )


class StatsResponse(StrictModel):
    """Database statistics: document counts per collection and edge counts."""

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
    lists: dict[str, int | None] = Field(
        default_factory=dict,
        description="Per list of the explorer the ``total`` its endpoint gives without a "
        "filter, as its first page answers it (the count each row of Bronnen shows): "
        "``instruments``, ``judgments``, ``dossiers``, ``documents``, ``members`` (who held "
        "a seat), ``bewindspersonen`` (``/api/members?government=true``), ``factions``, "
        "``committees``, ``cabinets``, ``commitments`` and ``decisions`` as the list opens "
        "(``chamber=TK``). ``decisions`` is null while it is still being counted (after a "
        "change of the decisions; the warm-up counts it): show nothing then, not 0.",
    )
    data_as_of: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="Per source (`tk`, `eerstekamer`, `rechtspraak`, `staatsblad`, "
        "`staatscourant`, `bwb`, `eurlex`, …, every source of the registry): how current "
        "the graph is.",
    )


class CoverageCourtDTO(StrictModel):
    """The judgments of one court in the graph."""

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


class CoverageTierDTO(StrictModel):
    """The judgments of one court tier in the graph."""

    tier: str | None = None
    count: int
    first_date: str | None = None
    last_date: str | None = None


class JudgmentCoverageResponse(StrictModel):
    """Which judgments the graph holds: a count of case law is a count of this selection.

    ``total`` counts the judgments whose text is loaded, a decision published twice once
    (the ``total`` of ``/api/judgments``); ``stubs`` the judgments known only because a
    loaded text cites them (they cite nothing themselves).
    """

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
    chambers: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="How current the papers of the Kamers are: `tk` and `eerstekamer`, as "
        "`data_as_of` of `/api/stats` gives them (`newest`: the date of the newest paper, "
        "`retrieved_at`: when it was fetched); a source with no row is left out.",
    )
