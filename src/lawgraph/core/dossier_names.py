"""The name a dossier goes by (pure): one rule for the feed, the articles, the nodes and the
server HTML. From its title (a budget's chapter and year, the parentheses that end a bill's
title), else the name its bill goes by in official data (``official_short`` of the feed:
the citation title the bill gives itself, the one the Kamer gives its case, or of the one
law it changes)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, get_args

from lawgraph.core.dossier_numbers import short_title

ShortTitleBasis = Literal["title", "citation", "case", "amended_law"]


def dossier_name(
    dossier: Mapping[str, Any],
) -> tuple[str | None, ShortTitleBasis | None]:
    """The short title of a dossier and where it comes from: its ``title`` (``title``),
    else its ``official_short`` (``{title, basis}``: ``citation``, ``case`` or
    ``amended_law``); ``(None, None)`` without."""
    own = short_title(dossier.get("title"))
    if own:
        return own, "title"
    official = dossier.get("official_short")
    if not isinstance(official, Mapping):
        return None, None
    title, basis = official.get("title"), official.get("basis")
    if not isinstance(title, str) or not title.strip():
        return None, None
    return title.strip(), basis if basis in get_args(ShortTitleBasis) else None


def dossier_own_name(dossier: Mapping[str, Any]) -> str | None:
    """The name alone: its short title, or where that is the law its bill changes
    ``wijziging van <law>``; None where the data knows no name."""
    short, basis = dossier_name(dossier)
    if not short:
        return None
    return f"wijziging van {short}" if basis == "amended_law" else short
