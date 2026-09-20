"""``lawgraph bootstrap``: fill an empty database.

Runs ``retrieve all --mode full``, ``normalize all``, ``semantic all`` and ``expand-graph``.
The Tweede Kamer sources load a window (``--tk-since``, default 730d), the other sources
in full, and the retrieve step runs its sources in parallel (``--jobs``). A failing phase
does not stop the next one unless ``--strict`` is given; the exit code is 1 when any phase
failed.
"""

from __future__ import annotations

import argparse
import sys

from lawgraph.commands.expand_graph import main as expand_graph
from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.pipelines.factory import run_command
from lawgraph.pipelines.orchestration import (
    DEFAULT_RETRIEVE_JOBS,
    run_normalize_all,
    run_retrieve_all,
    run_semantic_all,
)

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Fill an empty LawGraph database.")
    parser.add_argument("--max-expand", type=int, default=5, metavar="N")
    parser.add_argument("--skip-expand", action="store_true")
    parser.add_argument("--skip-retrieve", action="store_true")
    parser.add_argument(
        "--tk-since",
        default="730d",
        metavar="DATE",
        help="Load the Tweede Kamer records modified since then (default: %(default)s); "
        "use 1995-01-01 for all of them.",
    )
    parser.add_argument("--jobs", type=int, default=DEFAULT_RETRIEVE_JOBS, metavar="N")
    parser.add_argument(
        "--strict", action="store_true", help="Stop at the first failing phase."
    )
    args = parser.parse_args(argv)

    phases = [
        (
            "retrieve all",
            run_retrieve_all,
            [
                "--mode",
                "full",
                "--tk-since",
                args.tk_since,
                "--jobs",
                str(args.jobs),
            ],
        ),
        ("normalize all", run_normalize_all, []),
        ("semantic all", run_semantic_all, ["--strict"] if args.strict else []),
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

    failed = False
    for name, main_fn, phase_argv in phases:
        if name in skipped:
            continue
        if not run_command(name, main_fn, phase_argv):
            failed = True
            if args.strict:
                break

    if failed:
        logger.error("bootstrap finished with failures.")
        sys.exit(1)
    logger.info("bootstrap completed.")
