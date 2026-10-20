"""The help of a command: its usage names it as one types it, it says its defaults, and
asking for it writes no log line and needs no database."""

from __future__ import annotations

import argparse
import logging

import pytest

from lawgraph import __main__ as cli
from lawgraph.commands import poll
from lawgraph.core.logging import log_step
from lawgraph.pipelines.command import (
    HandWritten,
    add_since_argument,
    command_parser,
    docstring_title,
)
from lawgraph.sources.addresses import PHASES
from lawgraph.sources.registry import PIPELINES, Pipeline, find


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


def _parser_of(pipeline: Pipeline, monkeypatch) -> argparse.ArgumentParser:
    """The parser the command of *pipeline* builds, before it parses (or opens a store)."""

    def caught(
        parser: argparse.ArgumentParser, *args: object, **kwargs: object
    ) -> None:
        raise _Parsed(parser)

    with monkeypatch.context() as patched:
        patched.setattr(argparse.ArgumentParser, "parse_args", caught)
        with log_step(pipeline.address), pytest.raises(_Parsed) as built:
            pipeline.command([])
    return built.value.args[0]


_EVERY_PIPELINE = [pipeline for phase in PHASES for pipeline in PIPELINES[phase]]


def test_every_option_of_a_retrieve_says_what_it_does(monkeypatch) -> None:
    """No option of a retrieve command is listed in its help without a line of help."""
    for pipeline in PIPELINES["retrieve"]:
        parser = _parser_of(pipeline, monkeypatch)
        bare = [
            action.option_strings[0]
            for action in parser._actions
            if action.option_strings and action.dest != "help" and not action.help
        ]
        assert bare == [], pipeline.address


@pytest.mark.parametrize("pipeline", _EVERY_PIPELINE, ids=lambda p: p.address)
def test_every_pipeline_prints_its_help(pipeline, capsys, monkeypatch) -> None:
    """With the one description of the registry (a hand-written command: its own), and no
    database."""
    monkeypatch.setattr(
        cli, "setup_logging", lambda: pytest.fail("help set up logging")
    )
    with pytest.raises(SystemExit) as ended:
        cli.main([pipeline.phase, pipeline.name, "--help"])
    assert ended.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith(f"usage: lawgraph {pipeline.address} ")
    if not isinstance(pipeline.command, HandWritten):
        assert " ".join(pipeline.description.split()) in " ".join(out.split())


@pytest.mark.parametrize("pipeline", _EVERY_PIPELINE, ids=lambda p: p.address)
def test_a_command_says_the_window_its_parser_takes(pipeline, monkeypatch) -> None:
    """``accepts_since`` is what ``<phase> all`` and a poll ask before they pass ``--since``
    on: it never says other than the parser that reads the option."""
    parser = _parser_of(pipeline, monkeypatch)
    command = pipeline.command
    assert command.accepts_since == ("--since" in parser._option_string_actions)
    assert command.accepts_touched_since == (
        "--touched-since" in parser._option_string_actions
    )


def test_of_the_graph_steps_only_the_terms_take_since() -> None:
    """``semantic all --since`` passes it to ``graph-article-terms`` alone; the others run in
    full."""
    graph = [p for p in PIPELINES["semantic"] if p.source == "graph"]
    assert [p.name for p in graph if p.command.accepts_since] == ["graph-article-terms"]
    assert not any(p.command.accepts_touched_since for p in graph)


@pytest.mark.parametrize("name", list(poll.POLLS))
def test_every_step_of_a_poll_parses_the_argv_it_gets(name, monkeypatch) -> None:
    """A step given an option it lacks would end the whole poll with exit code 2."""
    since = "2026-10-14T10:00:00+00:00"
    for pipeline, options in poll.chain(name):
        argv = poll.argv_of(pipeline, options, since)
        parser = _parser_of(pipeline, monkeypatch)
        parser.parse_args(argv)  # argparse ends the test on an option it does not know


def test_a_retrieve_without_since_gets_none_in_a_poll() -> None:
    tk_content = find("retrieve", "tk-content")
    assert tk_content is not None and not tk_content.command.accepts_since
    assert poll.argv_of(tk_content, ("--limit", "5"), "2h") == ["--limit", "5"]


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_the_help_of_a_phase_lists_its_pipelines(phase, flag, capsys) -> None:
    cli.main([phase, flag])
    out = capsys.readouterr().out
    assert out.startswith(f"Usage: lawgraph {phase} <pipeline|all> [options]"), out
    listed = {line.split()[0] for line in out.splitlines()[1:] if line.strip()}
    names = {pipeline.name for pipeline in PIPELINES[phase]}
    assert {"all", *names} <= listed, sorted({"all", *names} - listed)
