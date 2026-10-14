"""Slugs of their own: the first free one of what a name may be called."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import chain, count


def numbered(base: str) -> Iterator[str]:
    """``base-2``, ``base-3``, … without end."""
    return (f"{base}-{n}" for n in count(2))


def claim(candidates: Iterable[str], taken: set[str]) -> str:
    """The first of *candidates* not in *taken*, now added to it."""
    slug = next(c for c in candidates if c not in taken)
    taken.add(slug)
    return slug


def claim_numbered(base: str, taken: set[str]) -> str:
    """*base*, else ``base-2``, ``base-3``, …: the first not in *taken*, now added to it."""
    return claim(chain([base], numbered(base)), taken)
