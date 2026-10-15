"""A group of change relations is built from ``CHANGE_RELATIONS`` in ``config.constants``,
never spelled out again: what a publication does to a regulation is written once."""

from __future__ import annotations

import ast

from tests.paths import SRC
from tests.source_scan import RELATION_NAME_HOMES, python_files

_CHANGE_NAMES = {"RELATION_AMENDS", "RELATION_INTRODUCES", "RELATION_REPEALS"}


def _change_sets_spelled_out(source: str) -> list[int]:
    """The lines of *source* where a tuple, list or set (or an f-string) names all three
    change relations: a group to build from ``CHANGE_RELATIONS`` instead."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            parts: list[ast.AST] = list(node.elts)
        elif isinstance(node, ast.JoinedStr):
            parts = list(ast.walk(node))
        else:
            continue
        if _CHANGE_NAMES <= {n.id for n in parts if isinstance(n, ast.Name)}:
            lines.append(node.lineno)
    return lines


def test_change_relations_are_grouped_in_the_constants() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{line}"
        for path in python_files()
        if path not in RELATION_NAME_HOMES
        for line in _change_sets_spelled_out(path.read_text())
    ]
    assert not offenders, f"build the group from CHANGE_RELATIONS: {offenders}"


def test_the_change_set_scan_would_catch_a_spelled_out_group() -> None:
    spelled = "X = [RELATION_ESTABLISHES, RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS]"
    assert _change_sets_spelled_out(spelled) == [1]
    joined = (
        "X = f\"'{RELATION_AMENDS}', '{RELATION_INTRODUCES}', '{RELATION_REPEALS}'\""
    )
    assert _change_sets_spelled_out(joined) == [1]
    assert (
        _change_sets_spelled_out("X = (RELATION_ESTABLISHES, *CHANGE_RELATIONS)") == []
    )
