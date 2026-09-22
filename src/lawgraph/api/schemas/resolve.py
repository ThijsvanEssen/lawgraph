"""Resolve endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MatchKind = Literal["article", "instrument", "judgment", "dossier", "document"]


class ResolveMatch(BaseModel):
    """One node a query may mean, with a target a client can navigate to."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="`collection/key`")
    key: str
    collection: str
    kind: MatchKind
    display_name: str | None
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "1: an identifier (ECLI, BWB id, CELEX); 0.95: a citation read whole; "
            "0.9: a law by exact abbreviation or name; lower for partial names, an "
            "article without a law, or several equally good nodes (at most 0.5)"
        ),
    )


class ResolveResponse(BaseModel):
    """The best match for a query and the others that fit; ``kind`` ``none`` when nothing does."""

    model_config = ConfigDict(extra="forbid")

    q: str
    kind: MatchKind | Literal["none"]
    confidence: float = Field(
        ge=0, le=1, description="Confidence of `match`; 0 for `none`"
    )
    match: ResolveMatch | None
    alternatives: list[ResolveMatch]
    qualifier: str | None = Field(
        None, description="The lid or onder of an article citation (`derde lid`)"
    )
