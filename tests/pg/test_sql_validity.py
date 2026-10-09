"""Every static SQL statement of the code is accepted by a real PostgreSQL.

The rest of the suite runs on fake stores, so a statement the server rejects (a function it
does not know, a column that is not there, an ambiguous operator) only shows in a real run.
This test collects the whole statements written as strings in ``src/lawgraph`` (constants
and f-strings that only use constants: those of ``config/constants.py`` and the string
constants of the module itself), and asks the server to plan each of them on a database
with the real schema: ``EXPLAIN (GENERIC_PLAN)``, with the ``%(name)s`` parameters as
``$n``. Statements completed at run time are not judged here; the tests of their module
run them: templates (``{table}``, for ``sql.SQL(...).format``) and the tails of a ``WITH``
whose head is put together at run time. A fragment that reads a row of the statement it
goes into is named in ``_CORRELATED``; that statement is judged whole.
"""

from __future__ import annotations

import ast
import pathlib
import re

import psycopg
import pytest

import lawgraph.config.constants as constants

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "lawgraph"
_CONSTANTS = {
    k: v for k, v in vars(constants).items() if isinstance(v, str | int | float)
}
_STARTS = re.compile(r"^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_SQL_WORDS = re.compile(r"\b(FROM|SET|VALUES|RETURNING)\b")
_PARAMETER = re.compile(r"%\((\w+)\)s|%s")
_TEMPLATE = re.compile(r"\{\w*\}")
# The common table expressions that a tail reads and its caller puts in front.
_HEADS = ("stale", "grouped", "resolved", "matching")
_TAIL = re.compile(rf"\b(FROM|JOIN)\s+({'|'.join(_HEADS)})\b")
# Fragments that read a row of the statement they go into (a LATERAL subquery), by file and
# the alias of that row; the statement around them is judged whole.
_CORRELATED = {"db/queries/cabinets.py": "m"}


def _module_names(tree: ast.Module) -> dict[str, object]:
    """The constants the module's statements may use: those of ``config/constants.py``
    and the module's own string constants (``_EDGE = "e.key AS edge_key, ..."``), which
    may in turn be f-strings of constants."""
    names: dict[str, object] = dict(_CONSTANTS)
    assignments = [
        (node.targets[0].id, node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]
    for _ in range(3):  # a constant made of a constant made of a constant
        for name, value in assignments:
            text = _text(value, names)
            if text is not None:
                names[name] = text
    return names


def _text(node: ast.AST, names: dict[str, object]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
            elif (
                isinstance(part, ast.FormattedValue)
                and isinstance(part.value, ast.Name)
                and part.value.id in names
                and part.format_spec is None
            ):
                parts.append(str(names[part.value.id]))
            else:
                return None  # depends on something only known at run time
        return "".join(parts)
    return None


def _judged(text: str) -> bool:
    """Whether *text* is a whole statement: not a template, not a tail."""
    return bool(
        _STARTS.match(text)
        and _SQL_WORDS.search(text)
        and not _TEMPLATE.search(text)
        and not (_TAIL.search(text) and "WITH" not in text)
    )


def _whole_statements() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        names = _module_names(tree)
        inside_f_string: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    inside_f_string.update(id(x) for x in ast.walk(part))
        for node in ast.walk(tree):
            if id(node) in inside_f_string:
                continue
            text = _text(node, names)
            if text and _judged(text):
                found.append((str(path.relative_to(SRC)), node.lineno, text))
    return found


def _numbered(statement: str) -> str:
    """``%(name)s`` as ``$n`` (one number per name), ``%s`` as the next ``$n`` and ``%%``
    as ``%``."""
    numbers: dict[str, int] = {}

    def number(match: re.Match[str]) -> str:
        name = match.group(1) or f"_{len(numbers)}"
        return f"${numbers.setdefault(name, len(numbers) + 1)}"

    return _PARAMETER.sub(number, statement).replace("%%", "%")


STATEMENTS = _whole_statements()


def test_the_statements_are_found() -> None:
    """The collection must not silently find nothing (a moved constant, a new style)."""
    assert len(STATEMENTS) > 90


def test_the_helper_reads_constants_and_skips_run_time_parts() -> None:
    tree = ast.parse(
        '_T = f"{COLLECTION_JUDGMENTS} j"\n'
        'A = f"SELECT j.id FROM {_T}"\n'
        'B = f"SELECT j.id FROM {x}"'
    )
    names = _module_names(tree)
    _, assign_a, assign_b = tree.body
    assert _text(assign_a.value, names) == "SELECT j.id FROM judgments j"  # type: ignore[attr-defined]
    assert _text(assign_b.value, names) is None  # type: ignore[attr-defined]


def test_parameters_are_numbered_once_per_name() -> None:
    assert (
        _numbered("SELECT %(a)s, %(b)s, %(a)s LIKE 'x%%'")
        == "SELECT $1, $2, $1 LIKE 'x%'"
    )
    assert _numbered("SELECT %s, %s") == "SELECT $1, $2"


def test_templates_and_tails_are_left_to_their_module() -> None:
    assert not _judged("SELECT id FROM {table}")
    assert not _judged("SELECT count(*)::int FROM stale")
    assert _judged("WITH stale AS (SELECT 1 AS id) SELECT id FROM stale")
    assert _judged("SELECT id FROM judgments")


@pytest.mark.parametrize(
    ("path", "line", "statement"),
    STATEMENTS,
    ids=[f"{p}:{n}" for p, n, _ in STATEMENTS],
)
def test_the_server_accepts_the_statement(
    conn: psycopg.Connection, path: str, line: int, statement: str
) -> None:
    try:
        conn.execute(f"EXPLAIN (GENERIC_PLAN) {_numbered(statement)}".encode())
    except psycopg.errors.UndefinedTable as exc:
        alias = _CORRELATED.get(path)
        if alias and f'missing FROM-clause entry for table "{alias}"' in str(exc):
            pytest.skip(
                f"a fragment of a LATERAL over {alias}; judged in its statement"
            )
        pytest.fail(f"{path}:{line}: {exc}\n{statement}")
    except psycopg.Error as exc:
        pytest.fail(f"{path}:{line}: {exc}\n{statement}")
