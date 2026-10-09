"""Resolve endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MatchKind = Literal[
    "article",
    "instrument",
    "judgment",
    "dossier",
    "document",
    "commitment",
    "faction",
    "member",
]


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
            "0.9: a law, faction or member by exact abbreviation or name; lower for "
            "partial names, an "
            "article without a law, or several equally good nodes (at most 0.5)"
        ),
    )


class ResolveResponse(BaseModel):
    """The best match for a query and the others that fit; ``kind`` ``none`` when nothing does."""

    model_config = ConfigDict(extra="forbid")

    q: str
    kind: MatchKind | Literal["none"]
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence of `match`; 0 for `none`; at most 0.5 for a choice",
    )
    match: ResolveMatch | None
    alternatives: list[ResolveMatch] = Field(
        description=(
            "The others that fit, best first; for a citation that leaves the book of a code "
            "open (`art. 3 BW`): `match` null, `kind` `article`, and the articles it may "
            "mean, in the order of the books (at most 10)"
        )
    )
    alternatives_total: int = Field(
        0,
        ge=0,
        description="How many alternatives were found (`alternatives` lists the first)",
    )
    qualifier: str | None = Field(
        None, description="The lid or onder of an article citation (`derde lid`)"
    )
