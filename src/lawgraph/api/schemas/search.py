"""Search endpoint."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from lawgraph.api.schemas.common import FacetCountDTO, StrictModel, WithPath
from lawgraph.api.schemas.completeness import Completeness
from lawgraph.api.schemas.resolve import ResolveResponse
from lawgraph.config.constants import Collection
from lawgraph.db.queries.search.searched import Searched


class SearchResultItem(WithPath):
    """One search hit, typed by collection."""

    id: str
    key: str
    collection: Collection
    type: str
    display_name: str | None
    snippet: str | None = None
    score: float = Field(
        ge=0,
        le=1,
        description="Rank tier of the hit for the query: 1, 0.75, 0.5, 0.25 or 0.1",
    )
    exact: bool = Field(
        default=False,
        description="Whether the hit is the one thing the query names: by its citation "
        "(an article of the law it names), its ECLI or LJN, its number or identifier, "
        "the abbreviation or whole title of a law, the name of a judgment, the whole "
        "name of a member, faction, committee or cabinet, a term of the curated list "
        "of concepts (`concept`). Never by a heading or words of its text, however well "
        "they score.",
    )
    concept: str | None = Field(
        default=None,
        description="The term of the curated list of concepts the query is (`wanprestatie`, "
        "`GDPR`), when the hit is the article or law that term is about (art. 6:74 BW, the "
        "AVG): a hit found by the list, not by its own words. Null for every other hit.",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class SignedForDTO(StrictModel):
    """A faction the query names, which the hits of a type are signed for."""

    words: str = Field(description="The words of `q` that name it, in lower case.")
    name: str = Field(
        description="Its abbreviation (`VVD`), else its name: of the Tweede Kamer's "
        "faction of that name first."
    )
    factions: list[str] = Field(
        description="The keys of the factions of that name (`vvd`, and `ek_…` of the "
        "Eerste Kamer)."
    )


class SearchedDTO(StrictModel):
    """What the search of one type reads."""

    fields: list[Searched] = Field(
        description="What of a record its words are found in: `title` (its title, "
        "heading or name as shown, what a vote was on), `name` (the names it goes by: "
        "parties, aliases, abbreviations, persons), `number` (its number or identifier), "
        "`summary` (the inhoudsindicatie of a judgment), `text`, `kind` (of a vote)."
    )
    completeness: Completeness = Field(
        description="`text`: `done` when the search reads the text of the type, `none` "
        "when the type has a text it does not read (a judgment, a paper); no `text` for "
        'a type without one (docs/api.md "Completeness").'
    )
    signed_for: list[SignedForDTO] = Field(
        default_factory=list,
        description="Of the papers and the votes: the factions `q` names, whose words are "
        "not searched; each hit is signed for every one of them (a paper by one of its "
        "Kamerleden for it, a vote on such a paper). Empty when `q` names none, or is no "
        "more than a faction.",
    )


class SearchCountDTO(StrictModel):
    """How many hits a type has."""

    total: int = Field(
        description="The hits of the type that hold the words, before `offset` and "
        "`limit`: the rows that hold every word of `q` (not fewer than the hits "
        "listed). At least this many when `capped`."
    )
    capped: bool = Field(
        description="Counting stopped at the cap (5,000 rows): `total` is a lower bound "
        "and the facets are those of the rows found first, not of all."
    )


class SearchResponse(StrictModel):
    """Full-text search response, grouped by type."""

    q: str
    types: list[str]
    total: int
    results: dict[str, list[SearchResultItem]]
    partial: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "With `mode=live`: the types cut off at their budget, `true` each (their "
            "results may be empty or short; the full search has more). A type that was not "
            "cut off is not in it."
        ),
    )
    searched: dict[str, SearchedDTO] = Field(
        description="Per type of `types`: what its search reads, so no hit is not read "
        'as "not there".'
    )
    resolved: ResolveResponse | None = Field(
        default=None,
        description="With `resolve=true`: what `/api/resolve` answers for `q`, in the "
        "same request (kind `none` when nothing fits). Null without it.",
    )
    words: list[str] = Field(
        default_factory=list,
        description="The words of `q` searched for, in lower case: without its stop "
        "words (`left_out`).",
    )
    left_out: list[str] = Field(
        default_factory=list,
        description="The stop words of `q` left out of the search (`wat`, `de`, `van`, "
        "`mijn`: the Dutch stop words of PostgreSQL's Snowball dictionary); none when "
        "they are all of `q`.",
    )
    matched: Literal["all", "any"] = Field(
        default="all",
        description="`all`: every hit holds every word of `words`; `any`: no hit held "
        "them all, and the hits are those that hold one at least (of a ranked type those "
        "with more of them first). Only of the full search: while typing (`mode=live`) "
        "always `all`.",
    )
    best: str | None = Field(
        default=None,
        description="The id of what `q` names exactly, for a search box to open on "
        "Enter: the match of `resolved` when its confidence is 0.9 or more (a citation, "
        "an identifier, a law, faction or member by its whole name or abbreviation), "
        "else the hit of the concept `q` is the term of (`concept`), else the one hit of "
        "`results` that is `exact`. Null when none is, or more than "
        "one (`BW`: each book), however well words match (`huurverhoging`).",
    )
    offset: int = Field(
        default=0,
        description="The hits of each type skipped (`offset` of the request): `results` "
        "holds the hits from the offset-th on.",
    )
    counts: dict[str, SearchCountDTO | None] | None = Field(
        default=None,
        description="With `facets=true`: per type of `types` that is counted "
        "(`articles`, `dossiers`, `documents`, `instruments`, `judgments`) how many hits "
        "it has; null for a type whose count took longer than a second. Null without "
        "`facets=true`.",
    )
    facets: dict[str, dict[str, list[FacetCountDTO]]] | None = Field(
        default=None,
        description="With `facets=true`: per type the hits divided by a property, each "
        "value with its count, the largest first (`year` the newest first; a null value "
        "counts the hits without one), over the hits counted (`counts`, `capped`): "
        "`judgments.tier` (the instance: `hoge_raad`, `gerechtshof`, ...) and "
        "`judgments.year` (of the decision), `documents.kind`, `instruments.validity` "
        "(`in_force`, `expired`, `not_in_force_yet`, as `/api/instruments` says it; null "
        "when its source says none). Null without `facets=true`.",
    )
