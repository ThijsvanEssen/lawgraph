"""What the convention guards scan: the source files, and the strings in them."""

from __future__ import annotations

import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "lawgraph"
TESTS = SRC.parents[1] / "tests"
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


def _python_files() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


def _owned_files() -> list[pathlib.Path]:
    skipped = SOURCE_FACING
    return [
        path
        for path in _python_files()
        if not any(path == entry or entry in path.parents for entry in skipped)
    ]


# A whole query (``FOR x IN`` and a clause of its body), a search, or a filter clause built
# apart to be put into one. Keywords are upper case, as the code writes AQL; prose ("for
# every record in the list") is not.
_AQL = re.compile(
    r"\bFOR\s+\w+(\s*,\s*\w+)*\s+IN\b[\s\S]*\b"
    r"(RETURN|FILTER|COLLECT|SORT|LIMIT|UPDATE|UPSERT|REPLACE|REMOVE|INSERT)\b"
    r"|\bSEARCH\s+ANALYZER\b"
    r"|\bFILTER\s+[\w.@\[\]]+\s*(==|!=|>=|<=|<|>|IN|LIKE)\s"
)

# Access to the database handle itself: what ``db/`` wraps.
_DRIVER_CALL = re.compile(
    r"\bstore\.query\(|\.aql\.execute\(|\bstore\.collection\(|\bstore\.db\."
)


def _string_texts(tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, text)`` of every string literal; an f-string with ``{}`` for its fields."""
    inside: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                inside.update(id(sub) for sub in ast.walk(part))
    found = []
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) else "{}"
                for part in node.values
            )
            found.append((node.lineno, text))
    return found


def _aql_in(source: str) -> list[int]:
    return [
        line for line, text in _string_texts(ast.parse(source)) if _AQL.search(text)
    ]
