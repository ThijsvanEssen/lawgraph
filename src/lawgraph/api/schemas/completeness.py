"""``completeness``: one shape for what the graph holds of a record or a source and what it
lacks (``core/completeness.py``, docs/api.md "Completeness")."""

from __future__ import annotations

from typing import Any

from pydantic import Field, TypeAdapter

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.completeness import (
    Coverage,
    Part,
    Reason,
    ReferenceCounts,
    references_part,
)
from lawgraph.core.document_completeness import XmlRetrieval, document_text_parts
from lawgraph.core.dossier_stages import outcome_part
from lawgraph.core.staatsblad_laws import law_completeness, publication_completeness
from lawgraph.core.time import dutch_today


class PartStateDTO(StrictModel):
    """How far one part is complete."""

    state: Coverage = Field(
        description="`done` (the step ran and holds all it found), `partial` (it left "
        "some: `missing`), `none` (it ran and found nothing), `pending` (not reached yet: "
        "what it lacks is not known, though links laid before may show), "
        "`paused` (the source or the step is off), `unavailable` (the source refused the "
        "last run), `not_in_source` (the source does not give it), `not_fetched` (the "
        "source gives it, the graph does not take it in)."
    )
    as_of: str | None = Field(
        None,
        description="Of a source: when its retrieves last all ended well (UTC, ISO 8601), "
        "else when its newest record was fetched. Of the `outcome` of a dossier: the day it "
        "closed (`done`), or of its last activity (`pending`). Of the `text` of a paper: "
        "when its XML was fetched, or last asked for when the repository had none.",
    )
    missing: int | None = Field(
        None,
        description="With `partial`: how many are missing. Of `references`: those the "
        "step could not link, and those linked to a stub (a target the graph has not "
        "loaded).",
    )
    reason: Reason | None = Field(
        None,
        description="Why, where one state has more than one cause. Of the `text` of a "
        "Kamerstuk that is `pending` as of a day: `awaiting_normalize` (its XML is fetched, "
        "not read yet), `source_pdf_only` (the source has its PDF only; its XML follows). Of "
        "`references` that are `partial`: `target_not_loaded` (every one missing is linked "
        "to a stub; without a reason, some could not be linked).",
    )


# Per part (``text``, ``paragraphs``, ``tables``, ``references``, ``definitions``,
# ``versions``, ``succession``, ``outcome``, ``source``) its state; a part left out is not
# known to lack anything.
Completeness = dict[Part, PartStateDTO]

COMPLETENESS = (
    "Per part (`text`, `paragraphs`, `tables`, `references`, `definitions`, `versions`, "
    "`succession`, `outcome`, `source`) `{state, as_of, missing, reason}` (docs/api.md "
    '"Completeness").'
)


COMPLETENESS_ADAPTER: TypeAdapter[Completeness] = TypeAdapter(Completeness)


def completeness_dto(
    props: dict[str, Any],
    law: dict[str, Any] | None = None,
    references: ReferenceCounts | None = None,
) -> Completeness | None:
    """The ``completeness`` of a record with these *props*: of a law of the Staatsblad the
    BWB does not hold (yet) or of an article of one (*law* the props of its law) as
    ``core.staatsblad_laws.law_completeness`` says it, of a publication as
    ``publication_completeness`` does; of any other its ``references``. *references*
    counts those (``db.queries.unlinked_references``). None when no step derived any
    part."""
    found = law_completeness(
        props if law is None else law, references
    ) or publication_completeness(props)
    if found is None and (part := references_part(references)) is not None:
        found = {Part.REFERENCES.value: part}
    return COMPLETENESS_ADAPTER.validate_python(found) if found is not None else None


def document_completeness(
    props: dict[str, Any],
    labels: list[str],
    retrieval: XmlRetrieval | None,
    references: ReferenceCounts | None,
) -> Completeness | None:
    """The ``completeness`` of a paper with these *props* and *labels*: of one of the Tweede
    Kamer its ``text``, ``paragraphs`` and ``tables`` (``core.document_completeness``, *retrieval*
    what raw_sources holds of its XML), beside the parts ``completeness_dto`` gives it. None
    when no step derived any part."""
    found = document_text_parts(props, labels, retrieval, today=dutch_today()) or {}
    if (own := completeness_dto(props, references=references)) is not None:
        found.update({part.value: state.model_dump() for part, state in own.items()})
    return COMPLETENESS_ADAPTER.validate_python(found) if found else None


def dossier_completeness(props: dict[str, Any]) -> Completeness:
    """The ``completeness`` of a dossier with these *props*: its ``outcome``
    (``core.dossier_stages.outcome_part``)."""
    return COMPLETENESS_ADAPTER.validate_python(
        {Part.OUTCOME.value: outcome_part(props)}
    )
