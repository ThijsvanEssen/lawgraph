"""Resolve endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.notation import NotationKind

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


class ResolveMatch(StrictModel):
    """One node a query may mean, with a target a client can navigate to."""

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


class NotationArticleDTO(StrictModel):
    """One article a citation names."""

    law_id: str | None = Field(
        description="The BWB or CELEX id of its law; null when the citation names no law."
    )
    number: str = Field(
        description="The number as the article is stored: `162` of `6:162 BW` (in the "
        "book's own regulation), `3:4` of the Awb."
    )


class NotationPartsDTO(StrictModel):
    """What a notation is made of; null or empty what it does not name."""

    identifier: str | None = Field(
        None,
        description="Of an `ecli`, `bwb`, `celex` or `commitment`: the identifier, upper "
        "case; of a `publication` its id at officielebekendmakingen.nl (`stb-2026-94`, "
        "`stcrt-2026-12345`, `trb-2018-201`).",
    )
    dossier_number: str | None = Field(
        None, description="Of a `dossier` or `document`: the dossier number (`36327`)."
    )
    suffix: str | None = Field(None, description="Its suffix (`VII` of `35925 VII`).")
    sequence: str | None = Field(
        None,
        description="Of a `document`: its number in the dossier (`3`), or the letter of "
        "a paper of the Eerste Kamer (`A`).",
    )
    articles: list[NotationArticleDTO] = Field(
        default_factory=list, description="Of an `article`: the articles it names."
    )
    qualifier: str | None = Field(
        None, description="Of an `article`: the lid or onder it names (`derde lid`)."
    )
    choice: bool = Field(
        False,
        description="Of an `article`: the articles are those the citation may mean, not "
        "all of them (`art. 3 BW`: article 3 of every book).",
    )


class NotationDTO(StrictModel):
    """What `q` is as a notation: an identifier or a citation, taken apart. There with a
    match and without one: a citation that names nothing in the graph is still one."""

    kind: NotationKind
    parts: NotationPartsDTO


class ResolveResponse(StrictModel):
    """The best match for a query and the others that fit; ``kind`` ``none`` when nothing does."""

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
    notation: NotationDTO | None = Field(
        None,
        description="The notation `q` is (`TZ202603-130`, `Sr 287`, `Stcrt. 2026, 12`), "
        "with a match or without one; null for words.",
    )
