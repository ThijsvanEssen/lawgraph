"""The facets of ``GET /api/judgments``: the judgments under the filters, counted."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import FacetCountDTO, StrictModel


class SubjectFacetCount(StrictModel):
    """A subject of the Rechtspraak under a main area, as the source writes it."""

    value: str = Field(
        description="The subject as the source writes it (`Bestuursrecht; Belastingrecht`); "
        "the `subject` filter takes it."
    )
    label: str = Field(description="The part after the main area: `Belastingrecht`.")
    count: int


class SubjectAreaFacetCount(FacetCountDTO):
    """A main area of law with the subjects under it."""

    narrower: list[SubjectFacetCount] = Field(
        default_factory=list,
        description="The subjects of the source under this main area, most first; "
        "counted without the `subject_area` and `subject` filters.",
    )


class JudgmentFacets(StrictModel):
    """The judgments under the filters, counted; each without its own filter."""

    tier: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per tier, most first; counted without the `tier` and "
        "`court_kind` filters.",
    )
    court_kind: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per kind of court, most first; counted without the `court_kind` "
        "filter (within a chosen `tier`).",
    )
    source: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per source (`rechtspraak`, `echr`), most first; counted without "
        "the `source` filter.",
    )
    year: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per year of `date` (`2024`), oldest first after null (no date); "
        "counted without `from` and `to`.",
    )
    subjects: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per area of law, as the source writes it (`Strafrecht`, "
        "`Bestuursrecht; Belastingrecht`), most first; a judgment counts for each of its "
        "areas; counted without the `subject` filter.",
    )
    subject_area: list[SubjectAreaFacetCount] = Field(
        default_factory=list,
        description="Per main area of law: a subject up to its first `;` (`Bestuursrecht` "
        "holds `Bestuursrecht; Belastingrecht`), most first; a judgment counts once for "
        "each of its main areas. `narrower`: the subjects under it as the source writes "
        "them. The whole tree is counted without the `subject_area` and `subject` filters, "
        "so the other areas stay in view when one is chosen.",
    )
    procedure: list[FacetCountDTO] = Field(
        default_factory=list,
        description="Per procedure (Rechtspraak `psi:procedure`, as written: `Hoger "
        "beroep`, `Cassatie`; null when it gives none), most first; counted without the "
        "`procedure` filter.",
    )
