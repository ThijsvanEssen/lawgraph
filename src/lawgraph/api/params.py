"""Query parameters shared by several routes."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import Depends, Query

from lawgraph.api.errors import Invalid
from lawgraph.config.constants import Chamber
from lawgraph.core.code_families import native_number
from lawgraph.core.courts import COURT_KINDS, TIERS
from lawgraph.core.ministries import MINISTRIES, POSTS
from lawgraph.core.models import article_id, key_of
from lawgraph.db.schema import NODE_COLLECTIONS

# A dossier number as the API takes it: 29684, or its label with the addition of a
# budget chapter or a sub-series: 29684-I, 21501-31, 36956-(R2220).
DOSSIER_NUMBER_PATTERN = r"^\d+(-[A-Za-z0-9()]+)?$"
# A dossier label or the start of one: 36600, 36600-VII, 37020- (its chapters).
DOSSIER_PREFIX_PATTERN = r"^\d+(-[A-Za-z0-9()]*)?$"

# The most rows a page of a list may hold, per kind of list: a page one leafs through, a
# list a page shows whole, the longest lists (the articles of a law, the judgments citing
# one), the first few (a search, the laws a member touched) and every member. ``/openapi.json``
# states each as the ``maximum`` of its ``limit``; the explorer reads it from there.
PAGE_MAX = 200
LIST_MAX = 500
LONG_LIST_MAX = 2000
TOP_MAX = 100
MEMBER_LIST_MAX = 1000
PageLimit = Annotated[int, Query(ge=1, le=PAGE_MAX)]
ListLimit = Annotated[int, Query(ge=1, le=LIST_MAX)]
LongListLimit = Annotated[int, Query(ge=1, le=LONG_LIST_MAX)]
TopLimit = Annotated[int, Query(ge=1, le=TOP_MAX)]
MemberListLimit = Annotated[int, Query(ge=1, le=MEMBER_LIST_MAX)]

# The tier of a judgment and its kind of court, as query parameters (``core.courts.TIERS``
# and ``COURT_KINDS``), so the schema lists them and a value that is none is 422.
Tier = StrEnum("Tier", {tier: tier for tier in TIERS})  # type: ignore[misc]
CourtKind = StrEnum("CourtKind", {kind: kind for kind in COURT_KINDS})  # type: ignore[misc]

# A ministry (``core.ministries.MINISTRIES``) and a post in a cabinet (``POSTS``).
MinistryKey = StrEnum("MinistryKey", {m.key: m.key for m in MINISTRIES})  # type: ignore[misc]
Post = StrEnum("Post", {post: post for post in POSTS})  # type: ignore[misc]

# What the edges of a graph view (the neighbours of a node, a neighbourhood, paths) carry of
# their ``meta``: ``light`` as it is, ``passages`` with the passages a judgment cites in
# (``_rows.mentioned_passages``), so a row or a card shows them without the judgment.
EdgeMeta = Annotated[
    Literal["light", "passages"],
    Query(
        description="`passages`: an edge that keeps where a judgment cites (its "
        "`meta.mentions`) has its passages (`paragraph_id`, `paragraph_number`, `footnote`, "
        "`snippet`, `text`, `start`, `end`: `snippet[start:end]` is `text`), the first "
        "place in each of its first three paragraphs; `light` (the default) none."
    ),
]


def parse_choices(
    value: str | None, allowed: Collection[str] | None, name: str
) -> tuple[str, ...] | None:
    """A comma-separated parameter as a tuple, None when absent; 422 for a value not
    *allowed* (None: any value, a value of the source that is not listed)."""
    if value is None:
        return None
    chosen = tuple(
        dict.fromkeys(part.strip() for part in value.split(",") if part.strip())
    )
    if not chosen:
        return None
    unknown = [part for part in chosen if allowed is not None and part not in allowed]
    if unknown:
        raise Invalid(
            name,
            f"unknown {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed or ()))}.",
        )
    return chosen


@dataclass(frozen=True)
class ArticleRef:
    """An article as its path names it: ``number`` is its own number in its book
    (``162`` for ``6:162`` under BW Boek 6), ``key`` and ``id`` its node."""

    bwb_id: str
    number: str
    key: str
    id: str


def article_ref(bwb_id: str, article_number: str) -> ArticleRef:
    """The article of ``/{bwb_id}/{article_number}``, cited or own numbering alike."""
    number = native_number(bwb_id, article_number)
    node = article_id(bwb_id, number)
    return ArticleRef(bwb_id, number, key_of(node), node)


ArticleAddress = Annotated[ArticleRef, Depends(article_ref)]


def is_node_id(value: str) -> bool:
    """Whether *value*, as a request names it, is ``collection/key`` of a node collection
    with a key."""
    collection, slash, key = value.partition("/")
    return bool(slash and key) and collection in NODE_COLLECTIONS


# A period of the lists (inclusive; one side alone is open on the other): those active in it.
ActiveFrom = Annotated[
    dt.date | None,
    Query(
        description="Active on or after this day (a period that overlaps), YYYY-MM-DD."
    ),
]
ActiveTo = Annotated[
    dt.date | None,
    Query(
        description="Active on or before this day (a period that overlaps), YYYY-MM-DD."
    ),
]

# The Kamer of a list of committees, members or factions.
ListChamber = Annotated[
    Chamber,
    Query(
        description="``EK``: the Eerste Kamer, as eerstekamer.nl shows it today "
        "(periods as observed: ``observed_from``, ``observed_until``)."
    ),
]
