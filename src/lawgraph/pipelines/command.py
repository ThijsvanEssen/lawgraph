"""What a command is, how one is made from a pipeline, and how one is run.

A command is a function ``(argv) -> PipelineResult``: it parses its options, does its work
and returns what it did. Every ``lawgraph <...>`` is one: the hand-written ones
(``commands/``), the ``<phase> all`` of ``orchestration``, a ``RetrieveCommand``
(``retrieve_commands``) and a ``PipelineCommand`` of a pipeline class. A command does not
set up logging, measure time, catch what goes wrong or end the process.

A command of the registry is a ``Command``: it also says whether it takes ``--since`` and
``--touched-since`` (``accepts_since``, ``accepts_touched_since``), which is all ``<phase>
all`` and a poll ask before they pass the option on. A ``PipelineCommand`` reads it from the
``run`` of its class, a ``RetrieveCommand`` from the options it adds; a hand-written command
of the registry (``HandWritten``) takes neither.

``run_command`` does that, for whoever runs one: ``__main__`` for what was typed, a
composite command for its parts::

    outcome = run_command("normalize bwb", command, argv)

The label is what one types after ``lawgraph``, and it is the name of the step everywhere:
on every log line written inside, in the table of a phase, in the error of a parent. An
exception ends the command as ``FAILED`` and the caller goes on; a result without errors that
names a source that refused us (``PipelineResult.unavailable``) ends it as ``UNAVAILABLE``.
Only ``__main__`` turns an outcome into an exit code (``EXIT_UNAVAILABLE`` for the latter).
Ctrl-C and a wrong command line are not caught. A failure whose message says what to do (the
database cannot be reached, the schema is outdated, a source is down: ``KNOWN_FAILURES``) is
one log line; any other keeps its traceback.

The names say what they take, each built on the one before::

    pipeline.run()                        -> PipelineResult   the work
    command(argv)                         -> PipelineResult   options -> a pipeline run
    run_command(label, command, argv)     -> Outcome          label, time, catch
    run_steps(steps, jobs=...)            -> [Outcome]        skipped, or in lanes; the table
    run_pipelines(pipelines, argv_of)     -> [Outcome]        pipelines as steps
    _run_phase(phase, ...)                -> PipelineResult   --since last, the pipelines, the mark

(``run_steps`` in ``lanes``, which ``bootstrap`` runs its plan with too; the last two in
``orchestration``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from lawgraph.core.logging import current_step, describe, get_logger, log_step
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import format_duration, parse_since
from lawgraph.core.xml import collapse_ws
from lawgraph.db import GraphStore
from lawgraph.db.raw import StoreUnavailable
from lawgraph.db.schema import CollationMismatch, SchemaOutdated
from lawgraph.db.store import DatabaseUnavailable, LockNotGranted
from lawgraph.pipelines.retrieve.base import SourceDown
from lawgraph.pipelines.watchdog import watched
from lawgraph.pipelines.watermark import LAST, NothingOnRecord

logger = get_logger(__name__)

Main = Callable[..., PipelineResult]  # ``command(argv)``: what ``run_command`` runs


class Command(Protocol):
    """A command of the registry: ``command(argv)``, and the options of a window it takes."""

    @property
    def accepts_since(self) -> bool: ...

    @property
    def accepts_touched_since(self) -> bool: ...

    def __call__(self, argv: list[str] | None = None) -> PipelineResult: ...


_SINCE_HELP = (
    "Only records since this moment: ISO 8601 ('2024-01-01') or relative ('7d', '2h', "
    "'90m')."
)

# A step that reads everything because what decides it can change anywhere: only what was
# touched since then, which a poll asks for and ``<phase> all`` does not.
_TOUCHED_SINCE_HELP = (
    "Only what was touched since this moment (a poll); without it everything. ISO 8601 "
    "or relative ('2h')."
)


def command_parser(description: str = "", **kwargs: Any) -> argparse.ArgumentParser:
    """The parser of a command: its usage names the command as one types it (``lawgraph
    retrieve tk``), from the label ``run_command`` runs it under."""
    step = current_step()
    return argparse.ArgumentParser(
        prog=f"lawgraph {step}" if step else None, description=description, **kwargs
    )


def docstring_title(doc: str | None) -> str:
    r"""The first line of a command's docstring, without the command it opens with:
    ``\`\`lawgraph check\`\`: is the database …`` is ``Is the database …``."""
    first = (doc or "").strip().splitlines()[0] if (doc or "").strip() else ""
    rest = re.sub(r"``([^`]*)``", r"\1", re.sub(r"^``[^`]*``:\s*", "", first))
    return rest[:1].upper() + rest[1:]


def add_limit_argument(
    parser: argparse.ArgumentParser, help: str, *, default: int | None = None
) -> None:
    """``--limit N``: at most N of what a command reads or fetches; none for no limit."""
    parser.add_argument("--limit", type=int, default=default, metavar="N", help=help)


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
    if default:
        help = f"{help} Default: {default}."
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
    knows. ``add_args`` adds options to the parser; ``make_extra_kwargs`` turns the parsed options
    into constructor arguments of the pipeline.
    """

    pipeline_cls: type[Any]
    description: str
    add_args: Callable[[argparse.ArgumentParser], None] | None = None
    make_extra_kwargs: Callable[[argparse.Namespace], dict[str, Any]] | None = None

    @property
    def accepts_since(self) -> bool:
        return "since" in inspect.signature(self.pipeline_cls.run).parameters

    @property
    def accepts_touched_since(self) -> bool:
        return "touched_since" in inspect.signature(self.pipeline_cls.run).parameters

    def __call__(self, argv: list[str] | None = None) -> PipelineResult:
        parser = command_parser(self.description)
        if self.accepts_since:
            add_since_argument(parser)
        if self.accepts_touched_since:
            add_since_argument(parser, "--touched-since", help=_TOUCHED_SINCE_HELP)
        if self.add_args:
            self.add_args(parser)
        args = parser.parse_args(argv)

        extra = self.make_extra_kwargs(args) if self.make_extra_kwargs else {}
        pipeline = self.pipeline_cls(store=GraphStore(), **extra)
        options: dict[str, Any] = {}
        if self.accepts_since:
            options["since"] = args.since
        if self.accepts_touched_since:
            options["touched_since"] = args.touched_since
        result: PipelineResult = pipeline.run(**options)
        return result


@dataclass(frozen=True)
class HandWritten:
    """A command of the registry written as a function ``main(argv)``: it takes no window.
    One that would is a pipeline class whose ``run`` takes it."""

    main: Main
    accepts_since: bool = field(default=False, init=False)
    accepts_touched_since: bool = field(default=False, init=False)

    def __call__(self, argv: list[str] | None = None) -> PipelineResult:
        return self.main(argv)


def takes_option(parser: argparse.ArgumentParser, flag: str) -> bool:
    """Whether *parser* has the option *flag*."""
    return flag in parser._option_string_actions


# ── running one ──────────────────────────────────────────────────────────────


class State(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"  # left out on purpose (``LAWGRAPH_<PHASE>_SKIP_<SOURCE>``)
    UNAVAILABLE = "unavailable"  # a source refused us; the rest of the work went on


# The exit code of a command that ended ``UNAVAILABLE``: not a failure, but to be told
# (scripts/_run.sh alerts on it and goes on).
EXIT_UNAVAILABLE = 3


@dataclass(frozen=True)
class KnownFailure:
    """How the alert names a known failure (``lawgraph.alert``, docs/operations.md "Alerts")."""

    code: str  # "db-weg"
    passes: (
        bool  # it passes by itself: the next run tries again; else it asks for action
    )


# Failures of the environment whose message says what is wrong and what to do: logged in one
# line, the traceback at DEBUG. Any other exception is a bug and keeps its traceback.
KNOWN_FAILURES: dict[type[Exception], KnownFailure] = {
    DatabaseUnavailable: KnownFailure(
        "db-weg", passes=True
    ),  # the server cannot be reached
    # it did not take a write after the retries
    StoreUnavailable: KnownFailure("db-weigert", passes=True),
    SchemaOutdated: KnownFailure("schema", passes=False),
    CollationMismatch: KnownFailure("collatie", passes=False),
    # a source failed too many requests in a row
    SourceDown: KnownFailure("bron-down", passes=True),
    # ``--since last`` before a complete run
    NothingOnRecord: KnownFailure("geen-vorige-run", passes=False),
    # a statement waited past ``lock_timeout``: another session holds the table
    LockNotGranted: KnownFailure("lock-bezet", passes=True),
}


@dataclass(frozen=True)
class Outcome:
    """How one step ended."""

    label: str
    state: State
    result: PipelineResult = field(default_factory=PipelineResult)
    seconds: float = 0.0

    @property
    def reason(self) -> str:
        """Why it ended so, in one line: its errors, what was unavailable, or its counts."""
        if self.state is State.FAILED and self.result.errors:
            said = self.result.errors
        elif self.state is State.UNAVAILABLE:
            said = self.result.unavailable
        else:
            said = []
        return collapse_ws("; ".join(said)) or self.result.summary()


def run_command(
    label: str, command: Main, argv: list[str], *, description: str = ""
) -> Outcome:
    """Run ``command(argv)`` as the step *label*; never raises for what the step did wrong.
    While it runs, the watchdog names it in the log every ``LAWGRAPH_WATCHDOG_MINUTES``."""
    with log_step(label), watched(label):
        said = ": ".join(filter(None, ["Starting", description.rstrip(".")]))
        logger.info("%s%s", said, f" ({' '.join(argv)})." if argv else ".")
        started = time.monotonic()
        try:
            result = command(argv)
        except Exception as exc:  # noqa: BLE001 — a step that fails is an Outcome
            took = format_duration(time.monotonic() - started)
            known = isinstance(exc, tuple(KNOWN_FAILURES))
            logger.error("Failed after %s: %s", took, describe(exc), exc_info=not known)
            if known:
                logger.debug("The traceback of %s:", type(exc).__name__, exc_info=True)
            failure = PipelineResult(errors=[describe(exc)])
            return Outcome(label, State.FAILED, failure, time.monotonic() - started)

        seconds = time.monotonic() - started
        if result.errors:
            logger.error(
                "Failed after %s: %s.", format_duration(seconds), result.summary()
            )
            for error in result.errors:
                logger.error("Error: %s", error)
            return Outcome(label, State.FAILED, result, seconds)
        if result.unavailable:
            logger.warning(
                "Done in %s without what was unavailable: %s.",
                format_duration(seconds),
                result.summary(),
            )
            for unavailable in result.unavailable:
                logger.warning("Unavailable: %s", unavailable)
            return Outcome(label, State.UNAVAILABLE, result, seconds)
        logger.info("Done in %s: %s.", format_duration(seconds), result.summary())
        return Outcome(label, State.OK, result, seconds)


def combined_result(outcomes: Iterable[Outcome]) -> PipelineResult:
    """The result of a command made of steps: their counts, one error per failed step, and
    what was unavailable, named by the step it was unavailable to.

    What went wrong inside a step was logged under its own label; the parent names the step
    and its first reason (``semantic tk failed: KeyError: 'x' (and 2 more)``), so the outcome
    of the parent says why as well.
    """
    total = PipelineResult()
    for outcome in outcomes:
        total.created += outcome.result.created
        total.updated += outcome.result.updated
        total.unchanged += outcome.result.unchanged
        total.skipped += outcome.result.skipped
        total.notes += [f"{outcome.label}: {note}" for note in outcome.result.notes]
        total.unavailable += [
            f"{outcome.label}: {u}" for u in outcome.result.unavailable
        ]
        if outcome.state is State.FAILED:
            total.add_error(_failed(outcome))
    return total


def _failed(outcome: Outcome) -> str:
    first, *more = outcome.result.errors or [""]
    said = f"{outcome.label} failed" + (f": {first}" if first else "")
    return said + (f" (and {len(more)} more)" if more else "")
