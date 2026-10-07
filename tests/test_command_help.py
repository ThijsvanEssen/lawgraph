"""The help of a command: its usage names it as one types it, it says its defaults, and
asking for it writes no log line and needs no database."""

from __future__ import annotations

import argparse
import logging

import pytest

from lawgraph import __main__ as cli
from lawgraph.core.logging import log_step
from lawgraph.pipelines import inputs
from lawgraph.pipelines.command import (
    add_since_argument,
    command_parser,
    docstring_title,
)
from lawgraph.sources.registry import PIPELINES


def test_the_usage_names_the_command_it_runs_under() -> None:
    with log_step("retrieve tk"):
        assert command_parser("x").prog == "lawgraph retrieve tk"
    assert command_parser("x").prog != "lawgraph "  # outside a step: argparse's own


def test_a_docstring_title_is_plain_text() -> None:
    assert docstring_title(
        "``lawgraph check``: is the database what it should be?"
    ) == ("Is the database what it should be?")
    assert docstring_title("``lawgraph curated``: the lists (``data/curated/``).") == (
        "The lists (data/curated/)."
    )
    assert docstring_title(None) == ""


def test_the_default_of_since_is_in_its_help() -> None:
    parser = command_parser("x")
    add_since_argument(parser, default="1d")
    assert "Default: 1d." in parser.format_help()


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "--help"],
        ["retrieve", "tk", "-h"],
        ["normalize", "bwb", "--help"],
        ["bootstrap", "--help"],
        ["curated", "--help"],
    ],
)
def test_help_prints_the_usage_and_logs_nothing(
    argv, capsys, caplog, monkeypatch
) -> None:
    monkeypatch.setattr(
        cli, "setup_logging", lambda: pytest.fail("help set up logging")
    )
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as ended:
        cli.main(argv)
    assert ended.value.code == 0
    label = " ".join(argv[:-1])
    assert capsys.readouterr().out.startswith(f"usage: lawgraph {label} ")
    assert not caplog.messages


class _Parsed(Exception):
    """Raised instead of parsing, with the parser a command built."""


def test_every_option_of_a_retrieve_says_what_it_does(monkeypatch) -> None:
    """No option of a retrieve command is listed in its help without a line of help."""

    def caught(
        parser: argparse.ArgumentParser, *args: object, **kwargs: object
    ) -> None:
        raise _Parsed(parser)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", caught)
    monkeypatch.setattr(inputs, "missing", lambda reads, argv: [])
    for pipeline in PIPELINES["retrieve"]:
        with log_step(pipeline.address), pytest.raises(_Parsed) as built:
            pipeline.command([])
        parser = built.value.args[0]
        bare = [
            action.option_strings[0]
            for action in parser._actions
            if action.option_strings and action.dest != "help" and not action.help
        ]
        assert bare == [], pipeline.address
