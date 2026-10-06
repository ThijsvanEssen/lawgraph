"""The plan of ``lawgraph bootstrap``: every step of a build, the lane it runs in and what it
waits for, and the marks of the steps that are done.

A build runs in lanes side by side. Every server has a lane of its own for its retrieve
pipelines (``Pipeline.lane_id``, as in ``retrieve all``); the graph has one, the write lane,
that runs one step at a time: every normalize and semantic pipeline, ``expand-graph`` and
``check``. A step waits for the steps it reads (``Step.after``), all taken from the registry:

* a retrieve for the retrieves of its ``after``, and for the normalize step its ``reads``
  names (``retrieve tk-content`` after ``normalize tk-dossiers``);
* a normalize for the retrieve of its own name and of its ``fed_by``, and for the normalize
  steps of its ``after``;
* the first semantic step for every retrieve and normalize step, each next one for the one
  before it (the semantic phase reads raw records too); ``expand-graph`` for the last of them
  and ``check`` for ``expand-graph``.

A retrieve that chooses its work from what its own normalize step makes of it (``retrieve
eurlex``: the acts already in the graph) has nothing to choose from in a build and is left
out; ``expand-graph`` fetches what the graph refers to.

A step that ended ``ok`` is marked in ``pipeline_state`` (``bootstrap <step>``) with the code
it ran on, so a build that is started again skips it.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lawgraph.commands.check import main as check_main
from lawgraph.commands.expand_graph import main as expand_graph
from lawgraph.core.time import format_duration
from lawgraph.db.queries import state as state_queries
from lawgraph.pipelines.command import Command
from lawgraph.sources.registry import PIPELINES, Pipeline, RetrieveCtx

WRITE_LANE = "graph"  # the lane of every step that writes the graph
MARK_PREFIX = "bootstrap "
DEFAULT_MAX_EXPAND = 5


@dataclass(frozen=True)
class Step:
    """One step of a build: what it runs, in which lane, after which steps."""

    label: str  # what one types after ``lawgraph``: retrieve tk, normalize tk, check
    lane: str
    command: Command
    argv: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    window: str  # as given: 730d, a date, or all
    since: dt.datetime | None  # the window as a moment; None: the whole history
    steps: list[Step]
    left_out: dict[str, str] = field(default_factory=dict)  # step -> why

    def lanes(self) -> dict[str, list[Step]]:
        """The steps per lane, the retrieve lanes first and the write lane last."""
        lanes: dict[str, list[Step]] = {}
        for step in self.steps:
            lanes.setdefault(step.lane, []).append(step)
        lanes[WRITE_LANE] = lanes.pop(WRITE_LANE, [])
        return lanes


def make_plan(
    window: str, since: dt.datetime | None, *, max_expand: int = DEFAULT_MAX_EXPAND
) -> Plan:
    """The plan of a build that loads the producing sources since *since* (all without)."""
    ctx = RetrieveCtx(
        since="", mode="full", window=since.isoformat() if since else None
    )
    normalize = {p.name: p for p in PIPELINES["normalize"]}
    retrieve = {p.name: p for p in PIPELINES["retrieve"]}
    left_out = {
        f"retrieve {r.name}": (
            f"it chooses from normalize {pipeline}, which normalizes what it fetches; "
            "expand-graph fetches what the graph refers to"
        )
        for r in retrieve.values()
        for pipeline in _reads(r, ctx)
        if r.name in _fed_by(normalize, pipeline, retrieve)
    }
    planned = [r for r in retrieve.values() if f"retrieve {r.name}" not in left_out]
    steps = [_retrieve_step(r, ctx) for r in planned]
    names = {r.name for r in planned}
    steps += [
        Step(
            f"normalize {n.name}",
            WRITE_LANE,
            n.command,
            after=(
                *(f"retrieve {r}" for r in _feeding(n) if r in names),
                *(f"normalize {a}" for a in n.after),
            ),
        )
        for n in normalize.values()
    ]
    previous = tuple(step.label for step in steps)
    for pipeline in PIPELINES["semantic"]:
        steps.append(
            Step(pipeline.address, WRITE_LANE, pipeline.command, after=previous)
        )
        previous = (pipeline.address,)
    steps.append(
        Step(
            "expand-graph",
            WRITE_LANE,
            expand_graph,
            ("--max-iterations", str(max_expand)),
            previous,
        )
    )
    steps.append(Step("check", WRITE_LANE, check_main, after=("expand-graph",)))
    return Plan(window, since, steps, left_out)


def _reads(pipeline: Pipeline, ctx: RetrieveCtx) -> list[str]:
    """The normalize pipelines *pipeline* chooses from, run as a build runs it."""
    argv = pipeline.argv_for_all(ctx) if pipeline.argv_for_all else []
    return [r.pipeline for r in pipeline.reads if r.applies(argv)]


def _feeding(pipeline: Pipeline) -> tuple[str, ...]:
    """The retrieve pipelines whose raw records the normalize *pipeline* reads."""
    return (pipeline.name, *pipeline.fed_by)


def _fed_by(
    normalize: dict[str, Pipeline], name: str, retrieve: dict[str, Pipeline]
) -> set[str]:
    """Every retrieve the normalize step *name* waits for, through the steps it comes after."""
    fed: set[str] = set()
    todo = [name]
    while todo:
        pipeline = normalize[todo.pop()]
        fed |= {r for r in _feeding(pipeline) if r in retrieve}
        todo += pipeline.after
    return fed


def _retrieve_step(pipeline: Pipeline, ctx: RetrieveCtx) -> Step:
    return Step(
        pipeline.address,
        pipeline.lane_id,
        pipeline.command,
        tuple(pipeline.argv_for_all(ctx) if pipeline.argv_for_all else []),
        (
            *(f"retrieve {a}" for a in pipeline.after),
            *(f"normalize {n}" for n in _reads(pipeline, ctx)),
        ),
    )


# ── marks ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Code:
    """The code a step ran on: the version of the API and the commit of the checkout."""

    version: str | None
    commit: str | None  # git describe: build-0.78.3-12-g142ffed
    sha: str | None

    def doc(self) -> dict[str, Any]:
        return {"version": self.version, "commit": self.commit, "sha": self.sha}

    def __str__(self) -> str:
        commit = f"({self.commit})" if self.commit else None
        return " ".join(filter(None, [self.version, commit])) or "unknown code"


def current_code() -> Code:
    from lawgraph.api.app import (
        app,
    )  # the version a release sets, without a second copy

    root = Path(__file__).resolve().parents[3]  # the checkout of an editable install
    return Code(
        app.version,
        _git(root, "describe", "--tags", "--always", "--dirty"),
        _git(root, "rev-parse", "HEAD"),
    )


def _git(root: Path, *args: str) -> str | None:
    """What git says of the checkout at *root*; None where it is no checkout or has no git."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


@dataclass(frozen=True)
class Mark:
    """A step that ended ``ok``: when, after how long, on which code."""

    ended_at: str
    seconds: float
    code: Code


def marks(store: Any) -> dict[str, Mark]:
    """The marks of the steps that are done, by step."""
    return {
        key.removeprefix(MARK_PREFIX): Mark(
            str(doc.get("ended_at")),
            float(doc.get("seconds") or 0),
            Code(doc.get("version"), doc.get("commit"), doc.get("sha")),
        )
        for key, doc in state_queries.states_starting_with(store, MARK_PREFIX).items()
    }


def mark_done(store: Any, label: str, seconds: float, code: Code) -> None:
    ended = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    state_queries.set_state(
        store,
        MARK_PREFIX + label,
        {"ended_at": ended, "seconds": round(seconds, 1), **code.doc()},
    )


def unmark(store: Any, label: str) -> None:
    state_queries.set_state(store, MARK_PREFIX + label, None)


# ── --plan ───────────────────────────────────────────────────────────────────


def describe(plan: Plan, done: dict[str, Mark], code: Code) -> str:
    """The plan as ``lawgraph bootstrap --plan`` prints it."""
    window = (
        f"since {plan.since.date().isoformat()} ({plan.window})"
        if plan.since
        else "all: the whole history"
    )
    lines = [
        f"Window of the producing sources: {window}.",
        f"Code: {code}.",
        f"{sum(s.label in done for s in plan.steps)} of {len(plan.steps)} steps done.",
    ]
    for lane, steps in plan.lanes().items():
        title = (
            "write lane, one step at a time: the first whose wait is over"
            if lane == WRITE_LANE
            else f"lane {lane}"
        )
        lines += ["", f"{title}:"]
        lines += [_line(step, done.get(step.label), code) for step in steps]
    if plan.left_out:
        lines += ["", "left out:"]
        lines += [f"  {label}: {why}" for label, why in plan.left_out.items()]
    return "\n".join(lines)


def _line(step: Step, mark: Mark | None, code: Code) -> str:
    waits = (
        f"after {', '.join(step.after)}" if step.after and len(step.after) <= 3 else ""
    )
    if step.after and not waits:
        waits = f"after {len(step.after)} steps"
    state = ""
    if mark:
        state = f"done {mark.ended_at} in {format_duration(mark.seconds)}"
        if mark.code.sha != code.sha:
            state += f" on {mark.code}"
    argv = f" {' '.join(step.argv)}" if step.argv else ""
    return f"  {step.label + argv:<56} {state or waits}".rstrip()
