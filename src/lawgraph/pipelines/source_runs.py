"""What a scheduled run did with each source, kept for the API (``completeness.source``).

After its steps, ``<phase> all`` and a poll record per source whose retrieves it had: ``paused``
when the source is off (``LAWGRAPH_SOURCES_OFF``: no step asked it anything), ``unavailable``
when one of its retrieves ended so, ``done`` when all of them ended well. A retrieve that failed
or was skipped records nothing: the next run says it again.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from lawgraph.config import settings
from lawgraph.core.completeness import SOURCE_RUN_STATE, Coverage
from lawgraph.core.time import iso_timestamp
from lawgraph.db.counting import Store
from lawgraph.db.queries import state as state_queries
from lawgraph.pipelines.command import Outcome, State
from lawgraph.sources.registry import Pipeline


def source_states(
    pipelines: Iterable[Pipeline], outcomes: Iterable[Outcome]
) -> dict[str, Coverage]:
    """Per source with a retrieve among *pipelines*: what the run says of it, by *outcomes*;
    a source whose retrieves did not all end in a state of their own is left out."""
    ended = {outcome.label: outcome.state for outcome in outcomes}
    asked: dict[str, list[State | None]] = {}
    for pipeline in pipelines:
        if pipeline.phase == "retrieve":
            asked.setdefault(pipeline.source, []).append(ended.get(pipeline.address))
    found: dict[str, Coverage] = {}
    for source, states in asked.items():
        if source in settings.SOURCES_OFF:
            found[source] = Coverage.PAUSED
        elif State.UNAVAILABLE in states:
            found[source] = Coverage.UNAVAILABLE
        elif all(state is State.OK for state in states):
            found[source] = Coverage.DONE
    return found


def record_source_runs(
    store: Store, pipelines: Iterable[Pipeline], outcomes: Iterable[Outcome]
) -> None:
    """Keep what the run says of each source (``source_states``) under ``source <name>``,
    with ``as_of`` the moment its retrieves last all ended well."""
    now = iso_timestamp(dt.datetime.now(dt.UTC).replace(microsecond=0))
    for source, state in source_states(pipelines, outcomes).items():
        key = SOURCE_RUN_STATE + source
        before = state_queries.get_state(store, key) or {}
        as_of = now if state is Coverage.DONE else before.get("as_of")
        state_queries.set_state(
            store, key, {"state": state.value, "at": now, "as_of": as_of}
        )
