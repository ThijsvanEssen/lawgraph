"""Query parameters shared by several routes."""

from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum

from fastapi import HTTPException

from lawgraph.core.courts import COURT_KINDS, TIERS
from lawgraph.core.ministries import MINISTRIES, POSTS

# The tier of a judgment and its kind of court, as query parameters (``core.courts.TIERS``
# and ``COURT_KINDS``), so the schema lists them and a value that is none is 422.
Tier = StrEnum("Tier", {tier: tier for tier in TIERS})  # type: ignore[misc]
CourtKind = StrEnum("CourtKind", {kind: kind for kind in COURT_KINDS})  # type: ignore[misc]

# A ministry (``core.ministries.MINISTRIES``) and a post in a cabinet (``POSTS``).
MinistryKey = StrEnum("MinistryKey", {m.key: m.key for m in MINISTRIES})  # type: ignore[misc]
Post = StrEnum("Post", {post: post for post in POSTS})  # type: ignore[misc]


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
