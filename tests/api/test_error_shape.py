"""Every error of the API comes from ``api/errors.py`` in one shape (``tests/pg/
test_error_answers.py`` asks each on a real database): a route raises ``NotFound`` for a
404 and ``Invalid`` for a 422, and an ``HTTPException`` of its own only for a 503. No
route answers a 400."""

from __future__ import annotations

import ast
from pathlib import Path

import lawgraph.api

API = Path(lawgraph.api.__file__).parent


def _status(call: ast.Call) -> object:
    for keyword in call.keywords:
        if keyword.arg == "status_code" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    if call.args and isinstance(call.args[0], ast.Constant):
        return call.args[0].value
    return None


def test_a_route_raises_an_http_exception_only_for_a_503() -> None:
    raised = [
        (f"{path.relative_to(API)}:{node.lineno}", _status(node))
        for path in sorted(API.rglob("*.py"))
        if path.name != "errors.py"
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", None))
        == "HTTPException"
    ]
    assert [(at, status) for at, status in raised if status != 503] == []
