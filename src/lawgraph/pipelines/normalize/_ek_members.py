"""The member of each page of a person of the Eerste Kamer: shared by every step that names a
person by their page (the periods in ``normalize eerstekamer-persons``, the signers of a
motion in ``normalize eerstekamer-motions``)."""

from __future__ import annotations

from collections.abc import Mapping

from lawgraph.core import ek_persons
from lawgraph.db.counting import Store
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.db.queries.normalize import tk as normalize_tk


def members_of_pages(
    store: Store, pages: Mapping[str, ek_persons.PersonPage | None]
) -> dict[str, str]:
    """The key of the member of each page (by its path) that has one: the member the
    composition gave the page (``ek.path``), else ``ek_persons.match_member`` on the name and
    birth date the page gives. A path whose page is not stored (None) is matched by the
    composition's path alone."""
    found = normalize_ek.members_by_ek_path(store, sorted(pages))
    dates = sorted({p.birth_date for p in pages.values() if p and p.birth_date})
    born = list(normalize_tk.members_born_on(store, dates)) if dates else []
    for path, page in pages.items():
        if path in found or page is None:
            continue
        if key := ek_persons.match_member(page.name, page.birth_date, born):
            found[path] = key
    return found
