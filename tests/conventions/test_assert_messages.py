"""An assert that fails says what it found. A status assert shows the answer
(``assert_status``), and an ``any``/``all`` shows the items it judged
(``show_items``): bare, pytest says only ``500 == 200`` or ``assert False``.
"""

from __future__ import annotations

import ast

from tests.paths import TESTS


def _silent(tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, why)`` of every assert of *tree* without a message that reads a status or
    is an ``any``/``all``."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or node.msg is not None:
            continue
        test = node.test
        if any(
            isinstance(part, ast.Attribute) and part.attr == "status_code"
            for part in ast.walk(test)
        ):
            found.append((node.lineno, "assert_status(response, N)"))
            continue
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            test = test.operand
        if (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id in ("any", "all")
        ):
            found.append(
                (
                    node.lineno,
                    "failing = [...]; assert not failing, show_items(failing)",
                )
            )
    return found


def test_the_scan_finds_a_silent_status_and_any() -> None:
    source = (
        "assert response.status_code == 200\n"
        "assert response.status_code == 200, response.text\n"
        "assert (moved.status_code, moved.headers['location']) == (301, '/x')\n"
        "assert any(x for x in xs)\n"
        "assert not all(x for x in xs)\n"
        "assert any(x for x in xs), show_items(xs)\n"
        "assert sum(x for x in xs) == 2\n"
    )
    assert [line for line, _ in _silent(ast.parse(source))] == [1, 3, 4, 5]


def test_a_failing_assert_says_what_it_found() -> None:
    found = [
        f"{path.relative_to(TESTS.parent)}:{line} says only 'assert False' when it fails: "
        f"{fix}"
        for path in sorted(TESTS.rglob("*.py"))
        for line, fix in _silent(ast.parse(path.read_text()))
    ]
    assert not found, "\n".join(found)
