"""``lawgraph bootstrap``: fill an empty database.

Runs ``retrieve all --mode full``, ``normalize all``, ``semantic all`` and ``expand-graph``.
The sources that keep producing (Tweede Kamer, Rechtspraak, Staatscourant, Eerste Kamer,
ECHR) load a
window (``--window``, default 730d; ``all`` loads their whole history), the reference
sources (BWB, Verdragenbank) load in full, and the retrieve step runs its sources in
parallel (``--jobs``). A failing phase does not stop the next one unless ``--strict`` is
given; the exit code is 1 when any phase failed.

``--plan`` prints the plan of a build instead (``commands/bootstrap_plan.py``): its window,
every step in its lane with what it waits for, and which steps are done, on which code.
"""

from __future__ import annotations

import argparse

from lawgraph.commands import bootstrap_plan
from lawgraph.commands.expand_graph import main as expand_graph
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines.command import Outcome, State, combined_result, run_command
from lawgraph.pipelines.orchestration import (
    DEFAULT_RETRIEVE_JOBS,
    DEFAULT_WINDOW,
    normalize_all,
    retrieve_all,
    semantic_all,
    window_since,
)


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description="Fill an empty LawGraph database.")
    parser.add_argument(
        "--max-expand",
        type=int,
        default=bootstrap_plan.DEFAULT_MAX_EXPAND,
        metavar="N",
    )
    parser.add_argument("--skip-expand", action="store_true")
    parser.add_argument("--skip-retrieve", action="store_true")
    parser.add_argument(
        "--window",
        default=DEFAULT_WINDOW,
        metavar="DATE",
        help="Load what the producing sources changed since then (default: %(default)s); "
        "'all' loads their whole history.",
    )
    parser.add_argument("--jobs", type=int, default=DEFAULT_RETRIEVE_JOBS, metavar="N")
    parser.add_argument(
        "--strict", action="store_true", help="Stop at the first failing phase."
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the plan of the build (lanes, steps, what each waits for, what is "
        "done) and run nothing.",
    )
    args = parser.parse_args(argv)
    if args.plan:
        try:
            since = window_since(args.window)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        plan = bootstrap_plan.make_plan(args.window, since, max_expand=args.max_expand)
        done = bootstrap_plan.marks(GraphStore())
        print(bootstrap_plan.describe(plan, done, bootstrap_plan.current_code()))
        return PipelineResult()

    phases = [
        (
            "retrieve all",
            retrieve_all,
            [
                "--mode",
                "full",
                "--window",
                args.window,
                "--jobs",
                str(args.jobs),
            ],
        ),
        ("normalize all", normalize_all, []),
        ("semantic all", semantic_all, ["--strict"] if args.strict else []),
        ("expand-graph", expand_graph, ["--max-iterations", str(args.max_expand)]),
    ]
    skipped = {
        name
        for name, skip in (
            ("retrieve all", args.skip_retrieve),
            ("expand-graph", args.skip_expand),
        )
        if skip
    }

    outcomes: list[Outcome] = []
    for label, command, command_argv in phases:
        if label in skipped:
            continue
        outcomes.append(run_command(label, command, command_argv))
        if args.strict and outcomes[-1].state is State.FAILED:
            break
    return combined_result(outcomes)
