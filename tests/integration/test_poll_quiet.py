"""A poll that finds nothing new leaves the data version as it was.

Every write to a table of the graph raises the data version, and a new version empties the
answers the API keeps and starts its warm-up (minutes on the full graph). A poll every half
hour that rewrote what it read would do that every half hour. The records a poll fetches
again come back as they were, so its normalize and semantic steps must write nothing.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.commands import poll
from lawgraph.db import GraphStore
from tests.integration.seed import seed


@pytest.mark.parametrize("chain", ["tk", "rechtspraak"])
def test_a_poll_over_records_that_did_not_change_writes_nothing(
    database: str, cli: Any, chain: str
) -> None:
    store = GraphStore()
    seed(store, documents=60, judgments=10, regulations=3)
    empty = store.data_version()
    cli("normalize", "all")
    cli("semantic", "all")
    before = store.data_version()
    assert before != empty  # a write does move it

    # the window holds every seeded record: as if a poll fetched them all again, unchanged
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
    for pipeline, options in poll.chain(chain):
        if pipeline.phase == "retrieve":
            continue
        cli(pipeline.phase, pipeline.name, *poll.argv_of(pipeline, options, since))

    assert store.data_version() == before
