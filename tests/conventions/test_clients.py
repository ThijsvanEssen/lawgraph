"""The clients ask their sources in one way: through ``BaseClient.get``, at a host of
``config/sources.py``, with a named timeout; and a retrieve runs in the lane of its host.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from lawgraph.config.sources import HOSTS
from lawgraph.sources.registry import PIPELINES
from tests.paths import SRC

CLIENTS = sorted((SRC / "clients").glob("*.py"))
# The two modules that are the HTTP of the clients.
_HTTP = {SRC / "clients" / "base.py", SRC / "clients" / "pacing.py"}
_HOST = re.compile(r"https://\w")


def _code_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, text)`` of every string literal that is no docstring."""
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _session_calls(tree: ast.AST) -> list[int]:
    """Lines that ask HTTP past ``BaseClient.get``: ``session.get`` or ``requests.get``."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("get", "request", "post")
        and (
            (isinstance(node.func.value, ast.Name) and node.func.value.id == "requests")
            or (
                isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "session"
            )
        )
    ]


def _literal_timeouts(tree: ast.AST) -> list[int]:
    return [
        node.value.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg == "timeout"
        and isinstance(node.value, ast.Constant)
    ]


def _id(path: pathlib.Path) -> str:
    return path.name


@pytest.mark.parametrize("path", CLIENTS, ids=_id)
def test_a_client_has_no_host_of_its_own(path: pathlib.Path) -> None:
    lines = [
        line
        for line, text in _code_strings(ast.parse(path.read_text()))
        if _HOST.search(text)
    ]
    assert not lines, (
        f"clients/{path.name}:{lines}: a host belongs in config/sources.py"
    )


@pytest.mark.parametrize("path", [p for p in CLIENTS if p not in _HTTP], ids=_id)
def test_a_client_asks_through_base_client_get(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text())
    lines = _session_calls(tree) + _literal_timeouts(tree)
    assert not lines, (
        f"clients/{path.name}:{lines}: ask with BaseClient.get (get_text, get_xml, "
        "get_json) and a timeout of clients/base.py"
    )


def test_the_scan_finds_a_request_past_get_and_a_literal_timeout() -> None:
    tree = ast.parse(
        "self.session.get(url)\nrequests.get(url)\nself.get(url, timeout=60)\n"
    )
    assert _session_calls(tree) == [1, 2]
    assert _literal_timeouts(tree) == [3]


def test_the_user_agent_is_named_in_one_place() -> None:
    homes = {SRC / "config" / "sources.py"}
    offenders = [
        f"{path.relative_to(SRC)}:{line}"
        for path in sorted(SRC.rglob("*.py"))
        if path not in homes
        for line, text in _code_strings(ast.parse(path.read_text()))
        if text.startswith("Concordans (")
    ]
    assert not offenders, f"use config.sources.USER_AGENT: {offenders}"


def test_every_retrieve_runs_in_the_lane_of_a_host() -> None:
    lanes = {host.lane for host in HOSTS}
    outside = [p.name for p in PIPELINES["retrieve"] if p.lane not in lanes]
    assert not outside, f"name the lane of a host of config/sources.py: {outside}"


def test_every_host_is_listed_once() -> None:
    names = [host.name for host in HOSTS]
    assert len(names) == len(set(names))
