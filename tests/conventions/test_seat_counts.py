"""The seats of the Tweede Kamer and the Eerste Kamer are ``core.coalition.TK_SEATS`` and
``EK_SEATS``; the API names them, it does not write 150 or 75."""

from __future__ import annotations

import ast

from tests.paths import SRC


def test_the_api_names_the_seat_counts() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path in sorted((SRC / "api").rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Constant)
        and type(node.value) is int
        and node.value in (150, 75)
    ]
    assert not offenders, f"use TK_SEATS / EK_SEATS: {offenders}"
