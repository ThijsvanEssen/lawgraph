"""``completeness``: one shape for what the graph holds of a record or a source and what it
lacks (``core/completeness.py``, docs/api.md "Completeness")."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.completeness import Coverage, Part


class PartStateDTO(StrictModel):
    """How far one part is complete."""

    state: Coverage = Field(
        description="`done` (the step ran and holds all it found), `partial` (it left "
        "some: `missing`), `none` (it ran and found nothing), `pending` (not reached yet), "
        "`paused` (the source or the step is off), `unavailable` (the source refused the "
        "last run), `not_in_source` (the source does not give it)."
    )
    as_of: str | None = Field(
        None,
        description="Of a source: when its retrieves last all ended well (UTC, ISO 8601), "
        "else when its newest record was fetched.",
    )
    missing: int | None = Field(
        None, description="With `partial`: how many are missing."
    )


# Per part (``text``, ``paragraphs``, ``tables``, ``references``, ``definitions``,
# ``versions``, ``succession``, ``source``) its state; a part left out is not known to lack
# anything.
Completeness = dict[Part, PartStateDTO]

COMPLETENESS = (
    "Per part (`text`, `paragraphs`, `tables`, `references`, `definitions`, `versions`, "
    '`succession`, `source`) `{state, as_of, missing}` (docs/api.md "Completeness").'
)
