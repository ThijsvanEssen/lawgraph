"""The name a dossier goes by (pure): one rule for the feed, the articles, the nodes and the
server HTML. From its title (a budget's chapter and year, the parentheses that end a bill's
title), else the name its bill goes by in official data (``official_short`` of the feed:
the citation title the bill gives itself or the one the Kamer gives its case), else the name
the Eerste Kamer gives the bill (``ek_name``), else that of the one law it changes
(``official_short`` too): the last names no bill apart from another of that law."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, get_args

from lawgraph.core.dossier_numbers import short_title

ShortTitleBasis = Literal["title", "citation", "case", "eerstekamer", "amended_law"]


def _official(
    dossier: Mapping[str, Any],
) -> tuple[str | None, ShortTitleBasis | None]:
    official = dossier.get("official_short")
    if not isinstance(official, Mapping):
        return None, None
    title, basis = official.get("title"), official.get("basis")
    if not isinstance(title, str) or not title.strip():
        return None, None
    return title.strip(), basis if basis in get_args(ShortTitleBasis) else None


def dossier_name(
    dossier: Mapping[str, Any],
) -> tuple[str | None, ShortTitleBasis | None]:
    """The short title of a dossier and where it comes from: its ``title`` (``title``), else
    its ``official_short`` (``{title, basis}``: ``citation`` or ``case``), else its
    ``ek_name`` (``eerstekamer``) unless that is its whole title, else its ``official_short``
    of basis ``amended_law``; ``(None, None)`` without."""
    own = short_title(dossier.get("title"))
    if own:
        return own, "title"
    official, basis = _official(dossier)
    if official and basis != "amended_law":
        return official, basis
    senate = dossier.get("ek_name")
    if isinstance(senate, str) and senate.strip() and senate != dossier.get("title"):
        return senate.strip(), "eerstekamer"
    return official, basis


def dossier_own_name(dossier: Mapping[str, Any]) -> str | None:
    """The name alone: its short title, or where that is the law its bill changes
    ``wijziging van <law>``; None where the data knows no name."""
    short, basis = dossier_name(dossier)
    if not short:
        return None
    return f"wijziging van {short}" if basis == "amended_law" else short
