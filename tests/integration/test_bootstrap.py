"""``lawgraph bootstrap`` on stored raw records: the write lane, its marks, a second run that
runs only what did not end ok, ``--redo``, and the phases on record for ``--since last``."""

from __future__ import annotations

import re
from typing import Any

from lawgraph.commands import bootstrap_plan
from lawgraph.db import GraphStore
from lawgraph.db.queries import state as state_queries
from tests.integration.seed import seed

# The raw records are there; expand-graph would ask the sources what the graph refers to.
OFFLINE = ("--skip-retrieve", "--skip-expand")


def _steps(store: GraphStore, prefix: str) -> set[str]:
    return {label for label in bootstrap_plan.marks(store) if label.startswith(prefix)}


def test_a_build_runs_every_step_once_and_a_second_run_none(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    seed(store, documents=60, judgments=10, regulations=3)
    plan = bootstrap_plan.make_plan("730d", None)
    normalize = {s.label for s in plan.steps if s.label.startswith("normalize ")}
    semantic = {s.label for s in plan.steps if s.label.startswith("semantic ")}

    first = cli("bootstrap", *OFFLINE, check=False)
    log = first.stderr
    assert "normalize tk ok in" in log, log[-3000:]
    assert _steps(store, "normalize ") == normalize
    assert _steps(store, "semantic ") == semantic
    assert _steps(store, "retrieve ") == set()  # counted as done, not run: no mark
    assert "analyze" in bootstrap_plan.marks(store)
    # normalize and semantic are on record for --since last; retrieve is not
    assert state_queries.covered_until(store, "normalize") is not None
    assert state_queries.covered_until(store, "semantic") is not None
    assert state_queries.covered_until(store, "retrieve") is None

    # a second run runs what did not end ok, and only that (check fails on so small a
    # seed: it is run again, as it should)
    counted = {s.label for s in plan.steps if s.label.startswith("retrieve ")}
    unmarked = {s.label for s in plan.steps} - set(bootstrap_plan.marks(store))
    unmarked -= counted | {"expand-graph"}
    second = cli("bootstrap", *OFFLINE, check=False)
    ended = re.findall(r"\d+ of \d+ ended: (.*)", second.stderr)
    ran = {
        s.label for s in plan.steps if any(e.startswith(f"{s.label} ") for e in ended)
    }
    assert ran == unmarked
    assert second.returncode == (1 if unmarked else 0)

    before = bootstrap_plan.marks(store)["normalize tk"].ended_at
    cli("bootstrap", *OFFLINE, "--redo", "normalize tk", check=False)
    after = bootstrap_plan.marks(store)
    assert after["normalize tk"].ended_at >= before
    redone = cli("bootstrap", "--plan").stdout
    assert f"{len(after)} of {len(plan.steps)} steps done." in redone


def test_the_plan_of_an_empty_database(database: str, cli: Any) -> None:
    out = cli("bootstrap", "--plan", "--window", "all").stdout
    assert out.startswith("Window of the producing sources: all: the whole history.")
    assert "0 of " in out and "write lane" in out and "retrieve eurlex:" in out
