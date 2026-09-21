"""Until when a phase has worked through its sources: where ``--since last`` starts.

``retrieve all --since 1d`` every day leaves a hole the day it does not run, and no later run
looks into it. Each ``<phase> all`` that completes (no failed and no skipped step) records
the moment it began in ``pipeline_state``; ``--since last`` starts there, less the overlap
every relative ``--since`` gets. A run whose own ``--since`` lies after the mark leaves a
hole before it and does not move the mark.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import COLLECTION_PIPELINE_STATE
from lawgraph.core.logging import get_logger
from lawgraph.core.time import RELATIVE_SINCE_OVERLAP

logger = get_logger(__name__)

LAST = "last"


class NothingOnRecord(RuntimeError):
    """``--since last`` before any complete run of the phase."""


def covered_until(store: Any, phase: str) -> dt.datetime | None:
    doc = store.collection(COLLECTION_PIPELINE_STATE).get(phase)
    return dt.datetime.fromisoformat(doc["covered_until"]) if doc else None


def since_last(store: Any, phase: str) -> dt.datetime:
    mark = covered_until(store, phase)
    if mark is None:
        raise NothingOnRecord(
            f"No complete `{phase} all` is on record: run it once with a date "
            "(or in full) before `--since last`."
        )
    return mark - RELATIVE_SINCE_OVERLAP


def advance(
    store: Any, phase: str, *, began: dt.datetime, since: dt.datetime | None
) -> bool:
    """Record that *phase* is complete until *began*; False when the run left a hole."""
    mark = covered_until(store, phase)
    if since is not None and mark is not None and since > mark:
        logger.warning(
            "%s all read since %s, but the last complete run began %s: what lies between "
            "is not covered, `--since last` still starts there.",
            phase,
            since.isoformat(timespec="seconds"),
            mark.isoformat(timespec="seconds"),
        )
        return False
    store.collection(COLLECTION_PIPELINE_STATE).insert(
        {"_key": phase, "covered_until": began.isoformat()}, overwrite=True
    )
    return True
