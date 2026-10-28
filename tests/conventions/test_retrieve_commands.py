"""The retrieve commands: one description, a class where there is nothing to parse, modes
named once, and every command line the scripts type still read as it was."""

from __future__ import annotations

import argparse
import ast
import re
import shlex
from collections.abc import Callable, Sequence

import pytest

from lawgraph.core.logging import log_step
from lawgraph.pipelines import retrieve_commands
from lawgraph.pipelines.retrieve_commands import RetrieveCommand, RetrieveMode
from lawgraph.sources.registry import PIPELINES, find
from tests.paths import SRC

ROOT = SRC.parents[1]


class _Parsed(Exception):
    """Raised instead of parsing, with the parser a command built."""


def _parser_of(
    command: Callable[[list[str]], object], address: str, monkeypatch
) -> argparse.ArgumentParser:
    def caught(parser: argparse.ArgumentParser, *args: object, **kw: object) -> None:
        raise _Parsed(parser)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", caught)
    with log_step(address), pytest.raises(_Parsed) as built:
        command([])
    monkeypatch.undo()
    return built.value.args[0]


def test_the_help_of_a_retrieve_is_its_registry_description(monkeypatch) -> None:
    """``--help``, ``lawgraph sources`` and the first log line say one text."""
    for pipeline in PIPELINES["retrieve"]:
        parser = _parser_of(pipeline.command, pipeline.address, monkeypatch)
        assert parser.description == pipeline.description, pipeline.address


def test_a_retrieve_without_options_of_its_own_is_its_pipeline_class() -> None:
    """A function in ``retrieve_commands`` is there for what it parses; one that would only
    run its pipeline is the class, registered as it is."""
    for pipeline in PIPELINES["retrieve"]:
        command = pipeline.command
        assert isinstance(command, RetrieveCommand), pipeline.address
        if command.run.__module__ == retrieve_commands.__name__:
            assert command.add_args is not None, pipeline.address


def _mode_literals(path) -> list[str]:
    """The strings in *path* that are a retrieve mode, outside the enum that names them."""
    modes = {mode.value for mode in RetrieveMode}
    tree = ast.parse(path.read_text())
    enum = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "RetrieveMode"
        ),
        None,
    )
    inside = {id(node) for node in ast.walk(enum)} if enum else set()
    return [
        f"{path.name}:{node.lineno} {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and node.value in modes
        and id(node) not in inside
    ]


def test_a_retrieve_mode_is_named_once() -> None:
    """``RetrieveMode``, not the string: a default and a check can not drift apart."""
    files = [
        SRC / "pipelines" / "retrieve_commands.py",
        SRC / "pipelines" / "orchestration.py",
        SRC / "sources" / "registry.py",
        SRC / "commands" / "bootstrap_plan.py",
        SRC / "commands" / "expand_graph.py",
    ]
    found = [hit for path in files for hit in _mode_literals(path)]
    assert found == []


# ── what the scripts type ────────────────────────────────────────────────────

_RETRIEVE = re.compile(r"(?:^|\s)retrieve\s+([a-z][a-z-]*)(.*)$")
# a shell value whose content the script gives at run time
_PLACEHOLDERS = {
    '"$number"': "1",
    '"$@"': "",
    '"${TK_LIMIT:-3600}"': "3600",
    '"${TK_MINUTES:-28}"': "28",
    '"$TK_UNTIL"': "2016-01-01",
}


def _typed_retrieves() -> list[tuple[str, str, list[str]]]:
    """``(where, name, argv)`` of every ``retrieve <name> …`` a script or ops step runs."""
    found = []
    for path in sorted([*ROOT.glob("scripts/*.sh"), *ROOT.glob("ops/*.sh")]):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            match = _RETRIEVE.search(line.split(";")[1] if "; do " in line else line)
            if not match:
                continue
            rest = match[2]
            for placeholder, value in _PLACEHOLDERS.items():
                rest = rest.replace(placeholder, value)
            where = f"{path.relative_to(ROOT)}:{number}"
            found.append((where, match[1], shlex.split(rest)))
    return found


def test_the_scripts_type_retrieves() -> None:
    names = {name for _, name, _ in _typed_retrieves()}
    assert {"all", "tk-dossiers", "eerstekamer-persons", "kiesraad"} <= names


@pytest.mark.parametrize(
    ("where", "name", "argv"), _typed_retrieves(), ids=lambda v: str(v)
)
def test_every_retrieve_a_script_types_is_read(
    where: str, name: str, argv: list[str], monkeypatch
) -> None:
    """The flags of the nightly, the weekly, the test database and the ops steps."""
    if name == "all":
        from lawgraph.pipelines.orchestration import retrieve_all as command
    else:
        pipeline = find("retrieve", name)
        assert pipeline is not None, where
        command = pipeline.command

    def caught(
        parser: argparse.ArgumentParser, args: Sequence[str] | None = None, *a: object
    ):
        raise _Parsed(_original(parser, args))

    _original = argparse.ArgumentParser.parse_args
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", caught)
    with log_step(f"retrieve {name}"), pytest.raises(_Parsed):
        command(argv)
