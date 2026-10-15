"""``lawgraph poll <chain> --since 2h``: what one source published lately, up to the feed.

A poll is a light chain for one source: its retrieves over a window back, the normalize of
what they fetched, and only the semantic steps the feed needs of it. A retrieve reads from
the moment the window starts. A normalize or semantic step reads from there too, or from
where the last complete ``<phase> all`` of its phase began when that is later
(``pipelines/watermark``): the nightly run already did what lies before, and a record it
fetched carries the moment of that fetch, so the first poll of a day would otherwise
normalize all of it again. So the normalize reads what the retrieve of this run (and of the
run before it) stored; a semantic step that reads everything gets its moment as
``--touched-since`` (``pipelines/semantic/_touched.py``). A nightly phase that fails does
not move its mark, and the poll then reads the whole window. A poll keeps no mark of its
own: it is chronological, and its window is wider than the time between two polls, so that
they overlap; everything is an upsert. The nightly ``<phase> all --since last`` does the
rest.

No ``VACUUM ANALYZE`` after a poll: what it writes is small, and the nightly run does it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from lawgraph.core.feed import FEED_TIERS
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines import watermark
from lawgraph.pipelines.command import (
    add_since_argument,
    combined_result,
    command_parser,
)
from lawgraph.pipelines.orchestration import run_pipelines
from lawgraph.sources.addresses import Phase
from lawgraph.sources.registry import Pipeline, find

logger = get_logger(__name__)


@dataclass(frozen=True)
class Step:
    """A pipeline of the registry and the options it gets besides ``--since``."""

    phase: Phase
    name: str
    options: tuple[str, ...] = ()


# The chains, in the order their steps run. tk-dossier-outcomes: a vote that rejects a bill
# (Tweede or Eerste Kamer) closes its dossier; tk-government: the ministry and cabinet of a
# new document or commitment; tk-cited-papers: the motion a new letter answers. A judgment is
# in the feed when it is normalized.
POLLS: dict[str, tuple[Step, ...]] = {
    "tk": (
        Step("retrieve", "tk"),
        Step("retrieve", "tk-dossiers", ("--skip-members",)),
        Step("retrieve", "tk-document-links"),
        Step("retrieve", "tk-case-actors"),
        Step("normalize", "tk"),
        Step("normalize", "tk-dossiers"),
        Step("normalize", "tk-document-links"),
        Step("normalize", "tk-case-actors"),
        Step("semantic", "tk-dossier-outcomes"),
        Step("semantic", "tk-government"),
        Step("semantic", "tk-cited-papers"),
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
    """``--since`` for a step whose command takes it; ``--touched-since`` for a semantic
    step that would otherwise read everything; one with neither runs in full."""
    if pipeline.command.accepts_since:
        return [*options, "--since", since]
    if pipeline.command.accepts_touched_since:
        return [*options, "--touched-since", since]
    return list(options)


def since_of(store: GraphStore, window: dt.datetime) -> dict[Phase, str]:
    """Per phase the moment its steps read from: the window, for normalize and semantic no
    earlier than where the last complete run of that phase began."""
    since: dict[Phase, str] = {"retrieve": window.isoformat()}
    phases: tuple[Phase, ...] = ("normalize", "semantic")
    for phase in phases:
        mark = watermark.covered_until(store, phase)
        since[phase] = max(window, mark).isoformat() if mark else window.isoformat()
        if mark and mark > window:
            logger.info(
                "%s since the last complete run (%s).",
                phase,
                mark.isoformat(timespec="seconds"),
            )
    return since


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

    since = since_of(GraphStore(), args.since)
    steps = chain(args.chain)
    options = {pipeline.address: extra for pipeline, extra in steps}
    outcomes = run_pipelines(
        [pipeline for pipeline, _ in steps],
        lambda pipeline: argv_of(
            pipeline, options[pipeline.address], since[pipeline.phase]
        ),
    )
    return combined_result(outcomes)
