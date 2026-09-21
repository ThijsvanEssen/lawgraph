"""Query parameters shared by several routes."""

from __future__ import annotations

from collections.abc import Collection

from fastapi import HTTPException


def parse_choices(
    value: str | None, allowed: Collection[str], name: str
) -> tuple[str, ...] | None:
    """A comma-separated parameter as a tuple, None when absent; 422 for a value not allowed."""
    if value is None:
        return None
    chosen = tuple(
        dict.fromkeys(part.strip() for part in value.split(",") if part.strip())
    )
    if not chosen:
        return None
    unknown = [part for part in chosen if part not in allowed]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown {name}: {', '.join(unknown)}; "
                f"allowed: {', '.join(sorted(allowed))}"
            ),
        )
    return chosen
