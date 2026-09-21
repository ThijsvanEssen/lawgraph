"""Running a command: the one place that labels it, times it and decides how it ended.

A command (``pipelines/command.py``) only does its work and returns a ``PipelineResult``.
Whoever runs one — ``__main__`` for what was typed, ``<phase> all``, ``bootstrap`` and
``expand-graph`` for the commands they are made of — runs it through ``execute``::

    outcome = execute("normalize bwb", command, argv)

The label is what one types after ``lawgraph``, and it is the name of the step everywhere:
on every log line written inside, in the table of a phase, in the error of a parent. An
exception ends the step as ``FAILED`` and the run goes on; nothing in here ends the process
(``__main__`` does, from the outcome). Ctrl-C and a wrong command line are not caught.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from lawgraph.core.logging import get_logger, log_step
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import format_duration
from lawgraph.pipelines.command import Command

logger = get_logger(__name__)


class State(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"  # left out on purpose (``LAWGRAPH_<PHASE>_SKIP_<SOURCE>``)


@dataclass(frozen=True)
class Outcome:
    """How one step ended."""

    label: str
    state: State
    result: PipelineResult = field(default_factory=PipelineResult)
    seconds: float = 0.0


def execute(
    label: str, command: Command, argv: list[str], *, description: str = ""
) -> Outcome:
    """Run ``command(argv)`` as the step *label*; never raises for what the step did wrong."""
    with log_step(label):
        said = ": ".join(filter(None, ["Starting", description.rstrip(".")]))
        logger.info("%s%s", said, f" ({' '.join(argv)})." if argv else ".")
        started = time.monotonic()
        try:
            result = command(argv)
        except Exception as exc:
            took = format_duration(time.monotonic() - started)
            logger.error("Failed after %s: %s: %s", took, type(exc).__name__, exc)
            logger.debug("The traceback of %s:", label, exc_info=True)
            failure = PipelineResult(errors=[f"{type(exc).__name__}: {exc}"])
            return Outcome(label, State.FAILED, failure, time.monotonic() - started)

        seconds = time.monotonic() - started
        if result.errors:
            logger.error(
                "Failed after %s: %s.", format_duration(seconds), result.summary()
            )
            for error in result.errors:
                logger.error("Error: %s", error)
            return Outcome(label, State.FAILED, result, seconds)
        logger.info("Done in %s: %s.", format_duration(seconds), result.summary())
        return Outcome(label, State.OK, result, seconds)


def skipped(label: str, reason: str) -> Outcome:
    with log_step(label):
        logger.info("Skipped (%s).", reason)
    return Outcome(label, State.SKIPPED)


def combined(outcomes: Iterable[Outcome]) -> PipelineResult:
    """The result of a command made of steps: their counts, and one error per failed step.

    What went wrong inside a step was logged under its own label; the parent names the step.
    """
    total = PipelineResult()
    for outcome in outcomes:
        total.created += outcome.result.created
        total.updated += outcome.result.updated
        total.unchanged += outcome.result.unchanged
        total.skipped += outcome.result.skipped
        if outcome.state is State.FAILED:
            total.add_error(f"{outcome.label} failed")
    return total
