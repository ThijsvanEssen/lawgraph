"""``lawgraph poll <chain> --since 2h``: what one source published lately, up to the feed.

A poll is a light chain for one source: its retrieves over a window back, the normalize of
what they fetched, and only the semantic steps the feed needs of it. Every step gets the
same ``--since``, the moment the window starts, so the normalize reads what the retrieve
of this run (and of the run before it) stored. A poll keeps no mark of its own: it is
chronological, and its window is wider than the time between two polls, so that they
overlap; everything is an upsert. The nightly ``<phase> all --since last`` does the rest.

No ``VACUUM ANALYZE`` after a poll: what it writes is small, and the nightly run does it.
"""

from __future__ import annotations

from dataclasses import dataclass

from lawgraph.core.feed import FEED_TIERS
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines.command import (
    accepts_since,
    add_since_argument,
    combined_result,
    command_parser,
)
from lawgraph.pipelines.orchestration import run_pipelines
from lawgraph.sources.registry import Phase, Pipeline, find


@dataclass(frozen=True)
class Step:
    """A pipeline of the registry and the options it gets besides ``--since``."""

    phase: Phase
    name: str
    options: tuple[str, ...] = ()


# The chains, in the order their steps run. tk-dossier-outcomes: a vote that rejects a bill
# (Tweede or Eerste Kamer) closes its dossier; tk-government: the ministry and cabinet of a
# new paper or commitment. A judgment is in the feed when it is normalized.
POLLS: dict[str, tuple[Step, ...]] = {
    "tk": (
        Step("retrieve", "tk"),
        Step("retrieve", "tk-dossiers", ("--skip-members",)),
        Step("normalize", "tk"),
        Step("normalize", "tk-dossiers"),
        Step("semantic", "tk-dossier-outcomes"),
        Step("semantic", "tk-government"),
    ),
    "ek": (
        Step("retrieve", "eerstekamer-votes"),
        Step("normalize", "eerstekamer-votes"),
        Step("semantic", "tk-dossier-outcomes"),
    ),
    "rechtspraak": (
        # the courts of the judgments the feed shows; the others come with the nightly run
        Step(
            "retrieve",
            "rechtspraak",
            tuple(option for tier in FEED_TIERS for option in ("--court", tier)),
        ),
        Step("normalize", "rechtspraak"),
    ),
    "echr": (
        Step("retrieve", "echr"),
        Step("normalize", "echr"),
    ),
}


def _pipeline(step: Step) -> Pipeline:
    pipeline = find(step.phase, step.name)
    if pipeline is None:
        raise ValueError(f"poll: '{step.phase} {step.name}' is not in the registry")
    return pipeline


def chain(name: str) -> list[tuple[Pipeline, tuple[str, ...]]]:
    """The pipelines of the poll *name*, each with its own options."""
    return [(_pipeline(step), step.options) for step in POLLS[name]]


def argv_of(pipeline: Pipeline, options: tuple[str, ...], since: str) -> list[str]:
    """``--since`` for every retrieve (each has it; without it some read everything) and
    for a normalize or semantic step whose command has it; one without it runs in full."""
    with_since = pipeline.phase == "retrieve" or accepts_since(pipeline.command)
    return [*options, *(["--since", since] if with_since else [])]


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = command_parser(
        description="Retrieve, normalize and the semantic steps the feed needs, for one "
        "source, over a window back (a poll between the nightly runs)."
    )
    parser.add_argument("chain", choices=list(POLLS))
    add_since_argument(
        parser,
        help="The window: what changed since then ('2h', '90m', or an ISO moment). "
        "Choose it wider than the time between two polls.",
    )
    args = parser.parse_args(argv)
    if args.since is None:
        parser.error("--since is required: a poll without it would read everything")

    since = args.since.isoformat()
    steps = chain(args.chain)
    options = {pipeline.address: extra for pipeline, extra in steps}
    outcomes = run_pipelines(
        [pipeline for pipeline, _ in steps],
        lambda pipeline: argv_of(pipeline, options[pipeline.address], since),
    )
    return combined_result(outcomes)
