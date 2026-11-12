"""DTOs of ``GET /api/judgments/{ecli}/course``."""

from __future__ import annotations

from pydantic import Field, computed_field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.models import make_node_key
from lawgraph.db.queries.judgment_course import COURSE_DEPTH, COURSE_LIMIT


class CourseBasis(StrictModel):
    """The article of law that gives the court its say in this step."""

    bwb_id: str = Field(description="The law: `BWBR0001830` (RO), `BWBR0005537` (Awb).")
    article_number: str = Field(description="Its article as numbered: `60`, `8:105`.")

    @computed_field(  # type: ignore[prop-decorator]
        description="The node key of the article: `bwbr0001830_60`, "
        "`bwbr0005537_bijlage_2_artikel_2`."
    )
    @property
    def key(self) -> str:
        return make_node_key(self.bwb_id, self.article_number)


class CourseLink(StrictModel):
    """An edge from this step to another step of the course."""

    relation: str = Field(
        description="`APPEAL_OF`, `REFERRED_BY` or `CONTINUES` (to an earlier step), "
        "`ADVISES_ON` (a conclusion to the judgment it advises on)."
    )
    to: str = Field(description="The ECLI of the other step.")
    source_outcome: str | None = Field(
        default=None,
        description="How the appeal ended as the Rechtspraak records it (`psi:gevolg`: "
        "`Bekrachtiging/bevestiging`); null when neither judgment says.",
    )


class CourseStep(StrictModel):
    """One judgment of the case."""

    ecli: str | None
    key: str
    court_code: str | None
    court_name: str | None = Field(
        description="The court as its metadata names it; of a stub as the Instanties "
        "list names its code."
    )
    tier: str | None
    court_kind: str | None
    date: str | None
    procedure: str | None = Field(
        description="The procedure as the source writes it (`psi:procedure`, the first)."
    )
    decision_kind: str | None
    outcome: str | None = Field(
        description="How it ended as its text says (`judgment.outcome`)."
    )
    area: str | None = Field(
        description="`civiel`, `straf`, `bestuur` or `belasting`, from its subjects."
    )
    basis: CourseBasis | None = Field(
        description="From a fixed list (`data/route_articles.json`) by tier, procedure "
        "and area; null where the list has none (a gap, never a guess)."
    )
    loaded: bool = Field(description="False for a stub: named, not in the graph.")
    current: bool = Field(description="The judgment asked for.")
    links: list[CourseLink]


class JudgmentCourseResponse(StrictModel):
    steps: list[CourseStep] = Field(
        description="The judgments of the case in its order: an earlier instance before "
        "the judgment that names it, a conclusion just before the judgment it advises "
        "on, judgments of one place by date."
    )
    unresolved: list[dict[str, str | None]] = Field(
        description="The decisions the judgment asked for names in its text as the one it "
        "appeals that are not loaded (`unresolved_appeal_targets`: `court`, `date`, "
        "`case_number`)."
    )
    truncated: bool = Field(
        description=f"The case goes on past {COURSE_DEPTH} edges from the judgment or "
        f"{COURSE_LIMIT} judgments."
    )
