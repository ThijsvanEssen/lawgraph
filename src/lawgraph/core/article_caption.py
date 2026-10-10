"""What an article is about, for its title (pure): ``Art. 6:162 BW, Onrechtmatige daad``.

An article of the BWB seldom has a heading of its own; the divisions it stands in have titles
(Boek 6 > Titel 3 Onrechtmatige daad > Afdeling 1 Algemene bepalingen). Its caption is the
deepest of those titles that only one division of its law has: "Algemene bepalingen" opens
nearly every titel of Boek 6 and says nothing of 6:162, "Onrechtmatige daad" does. Derived
from the breadcrumbs of the articles of the law alone, no list of words kept by hand.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def _divisions(crumbs: Any) -> list[tuple[str, str, str]]:
    """``(type, label, title)`` of each division of a breadcrumb, outermost first."""
    found = []
    for crumb in crumbs if isinstance(crumbs, list) else []:
        if not isinstance(crumb, Mapping):
            continue
        title = str(crumb.get("title") or "").strip()
        if title:
            found.append(
                (str(crumb.get("type") or ""), str(crumb.get("label") or ""), title)
            )
    return found


def captions(articles: Iterable[Mapping[str, Any]]) -> dict[str, str | None]:
    """Article key -> its caption, of the articles of one law (``{key, breadcrumb}``): the
    deepest title of its breadcrumb that one division of the law has, None without one."""
    rows: Sequence[Mapping[str, Any]] = list(articles)
    crumbs = {str(row["key"]): _divisions(row.get("breadcrumb")) for row in rows}
    # a division is its whole path: "Afdeling 1 Algemene bepalingen" of Titel 1 and of
    # Titel 3 are two divisions with one title
    divisions = {
        tuple(found[: depth + 1])
        for found in crumbs.values()
        for depth in range(len(found))
    }
    held = Counter(path[-1][2].lower() for path in divisions)
    return {
        key: next(
            (title for _, _, title in reversed(found) if held[title.lower()] == 1), None
        )
        for key, found in crumbs.items()
    }
