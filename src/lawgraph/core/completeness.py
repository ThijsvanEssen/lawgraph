"""``completeness``: what the graph holds of a record or a source, and what it lacks.

One shape wherever the API says it (docs/api.md "Completeness")::

    completeness: {<part>: {state, as_of?, missing?, reason?}}

A part is one of ``Part``, a state one of ``Coverage``, a reason one of ``Reason``; the
lists are closed. Every state
is derived from what a step wrote or what a run recorded, never set by hand: a source's from
the outcome of its retrieves (``pipelines/source_runs.py``) and ``raw_sources``; a record's
``references`` from how many references its text makes that the step that reads them
recognized and could not link (``references_part``); a dossier's ``outcome`` from what
``semantic tk-dossier-outcomes`` wrote (``core.dossier_stages.outcome_part``).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class Part(StrEnum):
    """What of a record or a source a state is about."""

    TEXT = "text"
    PARAGRAPHS = "paragraphs"
    TABLES = "tables"
    REFERENCES = "references"
    DEFINITIONS = "definitions"
    VERSIONS = "versions"
    SUCCESSION = "succession"
    OUTCOME = "outcome"  # how it ended: of a dossier, the end of its bill
    SOURCE = "source"  # the source itself: whether the runs still fetch from it


class Coverage(StrEnum):
    """How far a part is complete."""

    DONE = "done"  # the step ran and holds all it found
    PARTIAL = "partial"  # it ran and left some (``missing``: how many)
    NONE = "none"  # it ran and found nothing
    PENDING = "pending"  # the step has not reached it yet
    PAUSED = "paused"  # the source or the step is off (``LAWGRAPH_SOURCES_OFF``)
    UNAVAILABLE = "unavailable"  # the source refused the last run (HTTP 401/403)
    NOT_IN_SOURCE = "not_in_source"  # the source does not give it
    NOT_FETCHED = "not_fetched"  # the source gives it; the graph does not take it in


class Reason(StrEnum):
    """Why a part is in its state, where one state has more than one cause: of the ``text``
    of a Kamerstuk that is ``pending`` as of a day (``core.document_completeness``)."""

    AWAITING_NORMALIZE = "awaiting_normalize"  # its XML is fetched, not read yet
    SOURCE_PDF_ONLY = "source_pdf_only"  # the source has its PDF only, its XML follows


# The key in ``pipeline_state`` of what the last scheduled run did with a source's retrieves
# (``source echr``): ``{state, at, as_of}``, ``state`` a ``Coverage``, ``at`` when the run
# recorded it, ``as_of`` when its retrieves last all ended well.
SOURCE_RUN_STATE = "source "


def references_part(unlinked: int | None) -> dict[str, Any] | None:
    """The ``references`` part of a record of which the step that reads its references
    could not link *unlinked* (``lg_unlinked_references``, or the props of a law of the
    Staatsblad): ``done`` at 0, ``partial`` with that count as ``missing``; None when the
    step has not read it."""
    if unlinked is None:
        return None
    if unlinked:
        return {"state": Coverage.PARTIAL.value, "missing": int(unlinked)}
    return {"state": Coverage.DONE.value}


def source_completeness(
    run: Mapping[str, Any] | None, retrieved_at: str | None
) -> dict[str, Any]:
    """The ``source`` part of a source: the state the last run recorded (*run*), and
    ``as_of`` when its retrieves last ended well. A source no run recorded yet is ``done``
    as of its newest fetched record (*retrieved_at*) when it has one, else ``pending``."""
    if run is not None:
        return {"state": run["state"], "as_of": run.get("as_of") or retrieved_at}
    state = Coverage.DONE if retrieved_at else Coverage.PENDING
    return {"state": state.value, "as_of": retrieved_at}
