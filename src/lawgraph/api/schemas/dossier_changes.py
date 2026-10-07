"""``GET /api/dossiers/{number}/changed-articles``: the articles a bill changes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChangedArticleRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="`articles/<key>`")
    key: str | None = Field(description="Null for an article that is not in the graph.")
    article_number: str | None = None
    display_name: str | None = None
    stub: bool = False
    judgment_total: int = Field(
        default=0,
        description="The judgments that cite the article (as in `/cited-by`).",
    )


class ChangeSource(BaseModel):
    """What makes the change: the publication that enacts it, or the paper that proposes
    it (the bill, an amendment)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str | None = None
    display_name: str | None = None
    official_id: str | None = Field(
        default=None,
        description="Of a publication, its id on officielebekendmakingen.nl "
        "(`stb-2026-154`); null for a paper.",
    )
    kind: str | None = Field(
        default=None,
        description="Its kind as its source writes it: of a paper `Amendement`, `Voorstel "
        "van wet`; of a publication `publicatie`.",
    )
    sequence: int | None = Field(
        default=None, description="Of a Tweede Kamer paper its nr. in its dossier."
    )
    number: str | None = Field(
        default=None,
        description="Of a paper its number as its chamber cites it: the nr. (`12`), the "
        "letter of an Eerste Kamer paper (`A`); null for a publication.",
    )


class DossierChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article: ChangedArticleRef
    relation: Literal["amends", "introduces", "repeals"] = Field(
        description="As the dossier hub names its laws' relations."
    )
    stage: Literal["enacted", "proposed"] = Field(
        description="`enacted`: a publication legislated in this dossier changes the "
        "article; `proposed`: a paper of the dossier proposes it (status `voorgesteld`)."
    )
    source: ChangeSource
    effective_date: str | None = Field(
        default=None,
        description="Of an enacted change, the date it takes effect (YYYY-MM-DD), as the "
        "BWB dates the version it makes; null for a proposed one.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DossierChange:
        return cls(
            article=ChangedArticleRef(**row["article"]),
            relation=row["relation"],
            stage=row["stage"],
            source=ChangeSource(**row["source"]),
            effective_date=row["effective_date"],
        )


class ChangedLawRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(description="Null for a law that is not in the graph.")
    bwb_id: str | None = None
    celex: str | None = None
    display_name: str | None = None


class DossierChangedLaw(BaseModel):
    """The changes to one law, in the order of the law."""

    model_config = ConfigDict(extra="forbid")

    law: ChangedLawRef
    total: int
    changes: list[DossierChange]


class DossierChangedArticlesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str
    total: int = Field(description="Every change, in every law.")
    articles: int = Field(description="The articles changed, each once.")
    enacted: int = Field(description="The enacted changes.")
    proposed: int = Field(description="The proposed changes.")
    laws: list[DossierChangedLaw] = Field(
        description="Per law, by title (a law not in the graph last)."
    )
