"""The ministry that issued an official publication, from its ``dcterms:creator``.

The SRU of the KOOP repository names per publication of the Staatsblad and the Staatscourant
who issued it (``retrieve staatsblad-creators``, ``retrieve staatscourant-creators`` keep it in
the meta of its record): ``Ministerie van Volksgezondheid, Welzijn en Sport``. That name is
read as the ministry was named on the day of publication (``core.ministries.ministry_of``):
``Ministerie van Binnenlandse Zaken`` in 2005 is a former name, the same words in 2012 mean
Binnenlandse Zaken en Koninkrijksrelaties. The source names no person: who held the post on
that day is derived on read, not stored here.

A publication whose creators name no ministry keeps them, with ``ministry_missing``: a gap,
never filled by hand.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from lawgraph.core.ministries import ministry_of
from lawgraph.core.ministry_sources import ministry_name

CreatorMissing = Literal["no_creator", "unlinked"]
# The SRU names no creator, or holds no record of the publication.
NO_CREATOR: Final[CreatorMissing] = "no_creator"
# It names creators, none of them a ministry on the day of publication (a municipality, a
# court, a name the ministry table does not know).
UNLINKED: Final[CreatorMissing] = "unlinked"

# The meta of the record of a publication that holds what the SRU said: the creators, as
# ``{name, scheme}``, and the day of publication. Absent until it was asked.
META_CREATORS = "creators"
META_PUBLISHED = "published"


def creator_props(meta: dict[str, Any], date: str | None) -> dict[str, Any]:
    """The props of a publication from the meta of its record: ``creators`` (the names as
    the SRU writes them), ``ministries`` (the keys they name on the day of publication, the
    SRU's ``published``, else *date*) and ``ministry_missing``; none before the SRU was
    asked."""
    if META_CREATORS not in meta:
        return {}
    names = [c["name"] for c in meta.get(META_CREATORS) or () if c.get("name")]
    on = meta.get(META_PUBLISHED) or date
    keys = [ministry_of(ministry_name(name), on=on) for name in names]
    ministries = list(dict.fromkeys(k for k in keys if k))
    missing = None if ministries else (UNLINKED if names else NO_CREATOR)
    return {"creators": names, "ministries": ministries, "ministry_missing": missing}
