"""Query parameters shared by several routes."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Query

from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.code_families import native_number
from lawgraph.core.courts import COURT_KINDS, TIERS
from lawgraph.core.ministries import MINISTRIES, POSTS
from lawgraph.core.models import make_node_key

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


def iso_day(day: dt.date | None) -> str | None:
    """A day as the queries take it, ``YYYY-MM-DD``; None stays None."""
    return day.isoformat() if day else None


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
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown {name}: {', '.join(unknown)}; "
                f"allowed: {', '.join(sorted(allowed or ()))}"
            ),
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
    key = make_node_key(bwb_id, number)
    return ArticleRef(bwb_id, number, key, f"{COLLECTION_ARTICLES}/{key}")


ArticleAddress = Annotated[ArticleRef, Depends(article_ref)]
