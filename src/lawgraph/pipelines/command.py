"""What a command is, and how one is made from a pipeline.

A command is a function ``(argv) -> PipelineResult``: it parses its options, does its work
and returns what it did. Every ``lawgraph <...>`` is one: the hand-written ones
(``retrieve_commands``, ``commands/``), the ``<phase> all`` of ``orchestration`` and the ones
a ``PipelineCommand`` of a pipeline class. A command does not set up logging, measure
time, catch what goes wrong or end the process: ``execution.execute`` does that for every
command, and only ``__main__`` turns the outcome into an exit code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lawgraph.core.models import PipelineResult
from lawgraph.core.time import parse_since
from lawgraph.db import ArangoStore
from lawgraph.pipelines.watermark import LAST

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
