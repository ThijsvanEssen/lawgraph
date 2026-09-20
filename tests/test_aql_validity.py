"""Every static AQL query of the code is accepted by a real ArangoDB.

The rest of the suite runs on fake stores, so a query the server rejects (an operator it does
not know, a misspelt function) only shows in a real run: ``??`` is not AQL, and ``semantic
mvt-articles`` failed on it. This test collects the whole queries written as strings in
``src/lawgraph`` (constants and f-strings that only use constants), creates a scratch database
with the real schema, and asks the server to ``explain`` each of them. Queries that are only a
part, completed at run time, and bind values of the wrong type are not judged.

Needs a running ArangoDB and is skipped otherwise:
``ALLOW_DB_TESTS=1 pytest tests/test_aql_validity.py`` (shell only, like
``ALLOW_NETWORK_TESTS``).
"""

from __future__ import annotations

import ast
import os
import pathlib
import re

import pytest

import lawgraph.config.constants as constants
import lawgraph.pipelines.semantic.base as semantic_base

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "lawgraph"
_NAMES = {k: v for k, v in vars(constants).items() if not k.startswith("_")}
_NAMES["JUDGMENT_TEXT"] = semantic_base.JUDGMENT_TEXT
_STARTS = re.compile(r"^\s*(FOR|LET|WITH)\b")
_WRITES_OR_RETURNS = re.compile(r"\b(RETURN|REMOVE|UPDATE|INSERT|UPSERT)\b")
# A server answer that says the query is a fragment or the bind values are dummies.
_NOT_JUDGED = (
    "unexpected end of query string",
    "LIMIT offset/count values must be constant",
    "invalid traversal depth",
    "must be a positive integer",
)


def _whole_queries() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        inside_f_string: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    inside_f_string.update(id(x) for x in ast.walk(part))
        for node in ast.walk(tree):
            if id(node) in inside_f_string:
                continue
            text = _text(node)
            if text and _STARTS.match(text.strip()) and _WRITES_OR_RETURNS.search(text):
                found.append((str(path.relative_to(SRC)), node.lineno, text))
    return found


def _text(node: ast.AST) -> str | None:
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
                and part.value.id in _NAMES
            ):
                parts.append(str(_NAMES[part.value.id]))
            elif isinstance(part, ast.FormattedValue) and _is_slim(part.value):
                call = part.value
                parts.append(semantic_base.slim(*(arg.value for arg in call.args)))  # type: ignore[attr-defined]
            else:
                return None  # depends on something only known at run time
        return "".join(parts)
    return None


def _is_slim(node: ast.AST) -> bool:
    """``slim("doc", "title", ...)``: the props projection of the semantic pipelines."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "slim"
        and all(
            isinstance(a, ast.Constant) and isinstance(a.value, str) for a in node.args
        )
    )


def _bind_vars(query: str) -> dict[str, object]:
    binds: dict[str, object] = {}
    for name in set(re.findall(r"(?<![@\w])@(\w+)", query)):
        is_list = re.search(rf"(IN|,)\s*@{name}\b", query)
        binds[name] = (
            [] if is_list else ("x" if not re.search(rf"LIMIT\s+@{name}", query) else 1)
        )
    return binds


QUERIES = _whole_queries()


def test_the_queries_are_found() -> None:
    """The collection above must not silently find nothing (a moved constant, a new style)."""
    assert len(QUERIES) > 80


def test_the_helper_reads_constants_and_skips_run_time_parts() -> None:
    tree = ast.parse(
        'A = f"FOR d IN {COLLECTION_JUDGMENTS} RETURN d"\nB = f"FOR d IN {x} RETURN d"'
    )
    assign_a, assign_b = tree.body
    assert _text(assign_a.value) == "FOR d IN judgments RETURN d"  # type: ignore[attr-defined]
    assert _text(assign_b.value) is None  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def scratch_db():
    if os.getenv("ALLOW_DB_TESTS") != "1":
        pytest.skip("Database tests disabled (set ALLOW_DB_TESTS=1 to enable).")
    from arango import ArangoClient

    from lawgraph.config.settings import ARANGO_PASSWORD, ARANGO_URL, ARANGO_USER
    from lawgraph.db.schema import ensure_schema

    client = ArangoClient(hosts=ARANGO_URL)
    system = client.db("_system", username=ARANGO_USER, password=ARANGO_PASSWORD)
    name = "lawgraph_aql_validity"
    if system.has_database(name):
        system.delete_database(name)
    system.create_database(name)
    db = client.db(name, username=ARANGO_USER, password=ARANGO_PASSWORD)
    ensure_schema(db)
    yield db
    system.delete_database(name)


@pytest.mark.parametrize(
    ("path", "line", "query"), QUERIES, ids=[f"{p}:{n}" for p, n, _ in QUERIES]
)
def test_the_server_accepts_the_query(scratch_db, path, line, query) -> None:
    try:
        scratch_db.aql.explain(query, bind_vars=_bind_vars(query))
    except Exception as exc:  # noqa: BLE001 - the server's answer is the verdict
        message = str(exc)
        if any(text in message for text in _NOT_JUDGED):
            pytest.skip(f"not a whole query or dummy binds: {message[:80]}")
        raise AssertionError(f"{path}:{line}: {message[:300]}") from exc
