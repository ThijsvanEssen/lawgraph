"""``completeness``: what the graph holds of a record or a source, and what it lacks.

One shape wherever the API says it (docs/api.md "Completeness")::

    completeness: {<part>: {state, as_of?, missing?}}

A part is one of ``Part``, a state one of ``Coverage``; both lists are closed. Every state
is derived from what a step wrote or what a run recorded, never set by hand: a source's from
the outcome of its retrieves (``pipelines/source_runs.py``) and ``raw_sources``.
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


# The key in ``pipeline_state`` of what the last scheduled run did with a source's retrieves
# (``source echr``): ``{state, at, as_of}``, ``state`` a ``Coverage``, ``at`` when the run
# recorded it, ``as_of`` when its retrieves last all ended well.
SOURCE_RUN_STATE = "source "


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
