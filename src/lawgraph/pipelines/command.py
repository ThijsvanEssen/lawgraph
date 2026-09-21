"""What a command is, and how one is made from a pipeline.

A command is a function ``(argv) -> PipelineResult``: it parses its options, does its work
and returns what it did. Every ``lawgraph <...>`` is one: the hand-written ones
(``retrieve_cli``, ``commands/``), the ``<phase> all`` of ``orchestration`` and the ones
``pipeline_command`` makes from a pipeline class. A command does not set up logging, measure
time, catch what goes wrong or end the process: ``execution.execute`` does that for every
command, and only ``__main__`` turns the outcome into an exit code.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Callable
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


def pipeline_command(
    pipeline_cls: type,
    *,
    description: str,
    with_since: bool = False,
    add_args: Callable[[argparse.ArgumentParser], None] | None = None,
    make_extra_kwargs: Callable[[argparse.Namespace], dict[str, Any]] | None = None,
) -> Command:
    """The command of a pipeline whose ``run`` takes at most ``since``.

    ``add_args`` adds options to the parser; ``make_extra_kwargs`` turns the parsed options
    into constructor arguments of *pipeline_cls*.
    """

    def command(argv: list[str] | None = None) -> PipelineResult:
        parser = argparse.ArgumentParser(description=description)
        if with_since:
            add_since_argument(parser)
        if add_args:
            add_args(parser)
        args = parser.parse_args(argv)

        extra = make_extra_kwargs(args) if make_extra_kwargs else {}
        pipeline = pipeline_cls(store=ArangoStore(), **extra)
        return pipeline.run(since=args.since) if with_since else pipeline.run()

    return command
