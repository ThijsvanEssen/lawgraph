"""What the convention guards scan: the source files, and the strings in them."""

from __future__ import annotations

import ast
import pathlib
import re

from tests.paths import SRC

DB = SRC / "db"

# Modules that mirror a source's own vocabulary: the Dutch field names of the
# Tweede Kamer API and of the BWB and KOOP XML. Their
# identifiers may carry the source's spelling.
SOURCE_FACING = (
    SRC / "clients",
    SRC / "pipelines" / "retrieve",
)

# ``RAW_KIND_*`` values name a source's own record kinds (``tk-zaak``,
# ``tk-stemming``), so their constants keep the source's spelling.
SOURCE_KIND_PREFIX = "RAW_KIND_"

# Dutch stems that must not appear in an identifier of an owned module. Each
# has an English counterpart in the vocabulary: Annex, Committee, Faction,
# Decision, Commitment, Activity, Case, Document.
DUTCH_STEMS = (
    "bijlage",
    "commissie",
    "fractie",
    "stemming",
    "toezegging",
    "activiteit",
    "zaak",
    "publicatie",
)

# The modules where a relation name may be written as a string.
RELATION_NAME_HOMES = {
    SRC / "config" / "constants.py",
    SRC / "core" / "relations.py",
}


def python_files(under: pathlib.Path = SRC) -> list[pathlib.Path]:
    """The Python files under *under* (the source by default), sorted."""
    return sorted(under.rglob("*.py"))


def owned_files() -> list[pathlib.Path]:
    """The source files outside ``SOURCE_FACING``."""
    return [
        path
        for path in python_files()
        if not any(path == entry or entry in path.parents for entry in SOURCE_FACING)
    ]


_DOCUMENTED = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def string_literals(
    tree: ast.AST, *, docstrings: bool = False
) -> list[tuple[int, str]]:
    """``(line, text)`` of every string literal of *tree*, in the order of the lines: an
    f-string whole, with ``{}`` for each field (a string inside a field is a literal of
    its own); docstrings only when asked."""
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skipped.update(id(part) for part in node.values)
        if not docstrings and isinstance(node, _DOCUMENTED) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skipped.add(id(first.value))
    found = []
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                str(part.value) if isinstance(part, ast.Constant) else "{}"
                for part in node.values
            )
            found.append((node.lineno, text))
    return sorted(found)


# A whole query (``FOR x IN`` and a clause of its body), a search, or a filter clause built
# apart to be put into one. Keywords are upper case, as the code writes AQL; prose ("for
# every record in the list") is not.
AQL = re.compile(
    r"\bFOR\s+\w+(\s*,\s*\w+)*\s+IN\b[\s\S]*\b"
    r"(RETURN|FILTER|COLLECT|SORT|LIMIT|UPDATE|UPSERT|REPLACE|REMOVE|INSERT)\b"
    r"|\bSEARCH\s+ANALYZER\b"
    r"|\bFILTER\s+[\w.@\[\]]+\s*(==|!=|>=|<=|<|>|IN|LIKE)\s"
)

# Access to the database handle itself: what ``db/`` wraps.
DRIVER_CALL = re.compile(
    r"\bstore\.query\(|\.aql\.execute\(|\bstore\.collection\(|\bstore\.db\."
)


def aql_in(source: str) -> list[int]:
    """The lines of *source* with a string that is AQL, docstrings included."""
    return [
        line
        for line, text in string_literals(ast.parse(source), docstrings=True)
        if AQL.search(text)
    ]
