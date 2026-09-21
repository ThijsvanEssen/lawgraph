"""What a command is, how one is made from a pipeline, and how one is run.

A command is a function ``(argv) -> PipelineResult``: it parses its options, does its work
and returns what it did. Every ``lawgraph <...>`` is one: the hand-written ones
(``retrieve_commands``, ``commands/``), the ``<phase> all`` of ``orchestration`` and a
``PipelineCommand`` of a pipeline class. A command does not set up logging, measure time,
catch what goes wrong or end the process.

``run_command`` does that, for whoever runs one: ``__main__`` for what was typed, a
composite command for its parts::

    outcome = run_command("normalize bwb", command, argv)

The label is what one types after ``lawgraph``, and it is the name of the step everywhere:
on every log line written inside, in the table of a phase, in the error of a parent. An
exception ends the command as ``FAILED`` and the caller goes on; only ``__main__`` turns an
outcome into an exit code. Ctrl-C and a wrong command line are not caught.

The names say what they take, each built on the one before::

    pipeline.run()                        -> PipelineResult   the work
    command(argv)                         -> PipelineResult   options -> a pipeline run
    run_command(label, command, argv)     -> Outcome          label, time, catch
    run_step(step)                        -> Outcome          skipped, or run_command
    run_steps(steps)                      -> [Outcome]        in turn or in lanes; the table
    _run_phase(phase, ...)                -> PipelineResult   --since last, the steps, the mark

(the last three in ``orchestration``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from lawgraph.core.logging import get_logger, log_step
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import format_duration, parse_since
from lawgraph.db import ArangoStore
from lawgraph.pipelines.watermark import LAST

logger = get_logger(__name__)

Command = Callable[..., PipelineResult]  # ``command(argv)``

_SINCE_HELP = (
    "Only records since this moment: ISO 8601 ('2024-01-01') or relative ('7d')."
)


def add_since_argument(
    parser: argparse.ArgumentParser,
    flag: str = "--since",
    *,
    default: str | None = None,
    help: str = _SINCE_HELP,
    last: bool = False,
) -> None:
    """With *last* the value ``last`` is passed on as it is (see ``pipelines/watermark``)."""
    parse = _since_or_last if last else _since
    parser.add_argument(flag, type=parse, default=_since(default), help=help)


def _since_or_last(value: str) -> dt.datetime | str | None:
    return LAST if value.strip().lower() == LAST else _since(value)


def _since(value: str | None) -> dt.datetime | None:
    try:
        return parse_since(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


@dataclass(frozen=True)
class PipelineCommand:
    """The command of a pipeline class whose ``run`` takes ``since`` or nothing.

    Whether the command has ``--since`` is read from ``run`` itself, the one place that
    knows: ``<phase> all`` asks ``accepts_since`` before it passes the option on.
    ``add_args`` adds options to the parser; ``make_extra_kwargs`` turns the parsed options
    into constructor arguments of the pipeline.
    """

    pipeline_cls: type[Any]
    description: str
    add_args: Callable[[argparse.ArgumentParser], None] | None = None
    make_extra_kwargs: Callable[[argparse.Namespace], dict[str, Any]] | None = None

    @property
    def accepts_since(self) -> bool:
        return "since" in inspect.signature(self.pipeline_cls.run).parameters

    def __call__(self, argv: list[str] | None = None) -> PipelineResult:
        parser = argparse.ArgumentParser(description=self.description)
        if self.accepts_since:
            add_since_argument(parser)
        if self.add_args:
            self.add_args(parser)
        args = parser.parse_args(argv)

        extra = self.make_extra_kwargs(args) if self.make_extra_kwargs else {}
        pipeline = self.pipeline_cls(store=ArangoStore(), **extra)
        return pipeline.run(since=args.since) if self.accepts_since else pipeline.run()


def accepts_since(command: Command) -> bool:
    """Whether *command* takes ``--since``; a hand-written command says so itself."""
    return bool(getattr(command, "accepts_since", False))


# ── running one ──────────────────────────────────────────────────────────────


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


def run_command(
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


def combined_result(outcomes: Iterable[Outcome]) -> PipelineResult:
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
