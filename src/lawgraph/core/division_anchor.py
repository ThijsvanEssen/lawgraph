"""The anchor of a division of a law, by the path of labels down to it.

``deel-hoofdstuk-10-titel-10.2-afdeling-10.2.2`` names Afdeling 10.2.2 of the Awb: each
division of a breadcrumb by its label (its title when it has none), folded to lower case
without accents, every run of other characters than letters, digits and dots one ``-``.
The reader of the whole law names its divisions alike (``deelIds`` in the explorer).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

PREFIX = "deel-"

_OTHER = re.compile(r"[^a-z0-9.]+")


def _slug(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    bare = "".join(c for c in decomposed if not "̀" <= c <= "ͯ")
    return _OTHER.sub("-", bare.lower()).strip("-")


def _name(crumb: Any) -> str:
    if not isinstance(crumb, dict):
        return ""
    label, title = crumb.get("label"), crumb.get("title")
    value = label if label is not None else title
    return value if isinstance(value, str) else ""


def division_anchors(crumbs: Any) -> list[str]:
    """The anchor of each division of a breadcrumb (outermost first), one per crumb."""
    path: list[str] = []
    anchors = []
    for crumb in crumbs if isinstance(crumbs, list) else []:
        path.append(_slug(_name(crumb)))
        anchors.append(PREFIX + "-".join(part for part in path if part))
    return anchors


def as_anchor(division: str) -> str:
    """*division* as an anchor: ``#deel-hoofdstuk-6``, ``deel-hoofdstuk-6`` and
    ``hoofdstuk-6`` alike, in lower case."""
    bare = division.strip().lstrip("#").lower()
    return bare if bare.startswith(PREFIX) else PREFIX + bare


def division_path(crumbs: Any, anchor: str) -> list[dict[str, Any]] | None:
    """The crumbs from the outermost down to the division *anchor* names, when the
    breadcrumb stands in it; else None."""
    for depth, found in enumerate(division_anchors(crumbs)):
        if found == anchor:
            return [c for c in crumbs[: depth + 1] if isinstance(c, dict)]
    return None


def breadcrumb_on(props: dict[str, Any], day: str) -> Any:
    """The stored breadcrumb of an article version on *day*: the last of its
    ``breadcrumb_changes`` from on or before *day*, else its ``breadcrumb``."""
    crumbs = props.get("breadcrumb")
    for change in props.get("breadcrumb_changes") or []:
        if (change.get("from") or "") <= day:
            crumbs = change.get("breadcrumb")
    return crumbs
