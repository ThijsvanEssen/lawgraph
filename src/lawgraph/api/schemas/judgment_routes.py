"""DTOs of ``GET /api/judgments/routes``."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.api.schemas.judgment_course import CourseBasis


class RouteStep(StrictModel):
    """A court in the route of an area of law, with the article that gives it its say."""

    tier: str = Field(description="`rechtbank`, `gerechtshof`, `hoge_raad`, ...")
    procedures: list[str] = Field(
        description="The procedures the metadata names that fit (their start): "
        "`Eerste aanleg`, `Hoger beroep`, `Cassatie`, `Eerste en enige aanleg`, "
        "`Verwijzing na Hoge Raad`."
    )
    after_tier: str | None = Field(
        default=None,
        description="The court whose judgments this step hears, when only that one's: "
        "`centrale_raad_van_beroep` for cassation in `bestuur`, `rechtbank` for leapfrog "
        "cassation (sprongcassatie) in `civiel` and `belasting`, `hoge_raad` for the "
        "`gerechtshof` the Hoge Raad sent the case to (`Verwijzing na Hoge Raad`); null "
        "when it hears those of the step before it, or none (`Eerste en enige aanleg`: "
        "the Hoge Raad for ambtsmisdrijven, art. 76 RO).",
    )
    basis: CourseBasis = Field(
        description="The article a step of the Verloop gets (`/course`)."
    )
    designations: list[CourseBasis] = Field(
        description="The other articles that give this court its say in this step, "
        "besides `basis`: the article of the Bevoegdheidsregeling bestuursrechtspraak "
        "(Awb bijlage 2: `bijlage 2 artikel 2`) that names it, the Awb beside the RO in "
        "`belasting` (`8:6`, `8:105`), the laws that open cassation against the Centrale "
        "Raad van Beroep (`BWBR0002221` art. `53`, ...), art. `398` Rv (`BWBR0001827`) "
        "for leapfrog cassation in `civiel`; empty when there are none."
    )


class RouteGap(StrictModel):
    """A court in the route whose article is not read in the source: a gap, marked."""

    tier: str
    procedures: list[str]
    why: str = Field(description="What is not read (in English).")


class AreaRoute(StrictModel):
    area: str = Field(description="`civiel`, `straf`, `bestuur` or `belasting`.")
    steps: list[RouteStep]
    gaps: list[RouteGap]


class RegelingLaw(StrictModel):
    bwb_id: str
    name: str | None = Field(
        description="Its citation title in the graph, else as the regeling names it."
    )


class RegelingArticle(StrictModel):
    number: str = Field(description="`bijlage 2 artikel 2`.")
    key: str = Field(
        description="The article in the graph: `bwbr0005537_bijlage_2_artikel_2`."
    )
    heading: str | None
    laws: list[RegelingLaw] = Field(
        description="The laws its list names, each once, in the order of the text."
    )


class RegelingChapter(StrictModel):
    label: str = Field(description="`Hoofdstuk 2`.")
    title: str | None
    articles: list[RegelingArticle]


class JudgmentRoutesResponse(StrictModel):
    areas: list[AreaRoute] = Field(
        description="Per area of law, the courts of its route from `data/route_articles."
        "json` in their order, and its gaps."
    )
    regeling: list[RegelingChapter] = Field(
        description="The Bevoegdheidsregeling bestuursrechtspraak by chapter; empty when "
        "the Awb is not loaded."
    )
