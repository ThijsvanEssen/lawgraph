"""The laws a dossier title names, found by the names of the instruments."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.db import GraphStore
from lawgraph.db.version_cache import cached

# Of every instrument that is no stub: its key, BWB id and the names a dossier title may
# give it, in lower case. Read whole, once per version of the instruments
# (``load_law_names``): a name looked up in the table itself read every instrument per name
# (4-5 s for the dossier of a bill that names its laws). The title and short title from
# ``lg_instrument_names``, not the props (5 s cold on the full graph).
_LAW_NAMES_SQL = f"""
SELECT i.key, to_json(i.bwb_id) AS bwb_id,
       lower(coalesce(i.citation_title, '')) AS citation_title,
       lower(n.title) AS title, lower(n.short_title) AS short_title
FROM {COLLECTION_INSTRUMENTS} i
JOIN lg_instrument_names n ON n.id = i.id
WHERE i.stub IS DISTINCT FROM TRUE
ORDER BY i.key ASC NULLS LAST
"""


@dataclass(frozen=True)
class _LawNames:
    """The names of the instruments: of each name in lower case the first instrument (by
    key) whose citation title, title or short title it is, and the citation titles in
    order, to find the ones a name begins."""

    exact: dict[str, tuple[str, Any]]
    titles: list[tuple[str, str, Any]]


def _read_law_names(store: GraphStore) -> _LawNames:
    exact: dict[str, tuple[str, Any]] = {}
    titles: list[tuple[str, str, Any]] = []
    for row in store.query(_LAW_NAMES_SQL):
        found = (row["key"], row["bwb_id"])
        for name in (row["citation_title"], row["title"], row["short_title"]):
            if name:
                exact.setdefault(name, found)
        if row["citation_title"]:
            titles.append((row["citation_title"], *found))
    titles.sort(key=lambda title: (title[0], title[1]))
    return _LawNames(exact, titles)


def load_law_names(store: GraphStore) -> _LawNames:
    """``_LawNames``, kept while the instruments stand still: computed on first use, and in
    the warm-up (``api/warm.py``)."""
    return cached(
        store,
        ("dossier-law-names",),
        lambda: _read_law_names(store),
        tables=(COLLECTION_INSTRUMENTS,),
    )


def _law_named(names: _LawNames, name: str) -> tuple[str, Any] | None:
    """The instrument *name* is the name of, else the one instrument whose citation title it
    begins (a name the title cut at "in"); None when there is none, or more than one."""
    lowered = name.lower()
    if lowered in names.exact:
        return names.exact[lowered]
    begins = f"{lowered} "
    at = bisect_left(names.titles, (begins,))
    found = [
        title for title in names.titles[at : at + 2] if title[0].startswith(begins)
    ]
    return (found[0][1], found[0][2]) if len(found) == 1 else None


def get_laws_named(store: GraphStore, names: list[str]) -> list[dict[str, Any]]:
    """``{name, loaded, key, bwb_id}`` of each law *names* holds (the laws a dossier title
    names), found by the citation title, title or short title of an instrument; else by
    the one citation title the name begins (a name the title cut at "in")."""
    if not names:
        return []
    known = load_law_names(store)
    rows = []
    for name in names:
        found = _law_named(known, name)
        key, bwb_id = found or (None, None)
        rows.append(
            {"name": name, "loaded": found is not None, "key": key, "bwb_id": bwb_id}
        )
    return rows
