"""Every definition in the source has a reader outside its own definition.

The guard lists the functions, classes and constants at module level and the methods of
the classes in ``src``, and looks for each name in the code of ``src``, ``scripts``,
``ops`` and ``deploy``, in their shell, YAML and unit files, in the CI workflows and in
``pyproject.toml``. Tests do not count: code that only a test calls is dead. Comments and
docstrings do not count either.

A name counts as read where the code loads it (``name``, ``obj.name``), imports it, or
spells it whole in a string (``getattr(x, "name")``, ``"pkg.module:name"``); in the other
files a whole word counts. A definition with a decorator that registers it (a route, a
validator, an exception handler) is read by its framework; ``staticmethod``,
``classmethod``, ``property``, the caches and ``dataclass`` do not register. A method the
standard library calls by its name (``handle_starttag``, ``visit_Name``) is read too.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections import Counter

from tests.paths import ROOT, SRC
from tests.source_scan import python_files

# Definitions kept without a reader in the code, each with its reason.
ALLOWED: dict[str, str] = {
    "forget": "test seam: api.warm and seo.shell start every test with nothing kept",
    "detect_tk_citations": "test seam: the citations of a TK text without the pipeline",
    "block_of": "docs guard: the generated block of a doc, which a test compares",
    "BY_NAME": "test seam: the spec of a relation by its name",
    "ARANGO_REQUEST_TIMEOUT": "goes with the rest of ArangoDB (B125)",
}

# Methods the standard library or pydantic calls by their name.
_CALLED_BY_NAME = re.compile(
    r"__\w+__"
    r"|handle_(starttag|endtag|startendtag|data|entityref|charref|comment)"
    r"|visit_\w+|generic_visit"
    r"|emit|format|filter|default|model_post_init"
)

# The decorators that wrap a definition without registering it anywhere.
_NOT_REGISTERING = {
    "abstractmethod",
    "asynccontextmanager",
    "cache",
    "cached_property",
    "classmethod",
    "contextmanager",
    "dataclass",
    "final",
    "lru_cache",
    "overload",
    "override",
    "property",
    "setter",
    "staticmethod",
    "wraps",
}

_DIRS = ("scripts", "ops", "deploy")
_TEXT_SUFFIXES = {".sh", ".yml", ".yaml", ".toml", ".service", ".timer"}
_WORD = re.compile(r"[A-Za-z_]\w*")
_DOCUMENTED = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    return target.id if isinstance(target, ast.Name) else ""


def _registered(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    return any(_decorator_name(d) not in _NOT_REGISTERING for d in node.decorator_list)


def _assigned(node: ast.stmt) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return node.targets
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def definitions(tree: ast.Module) -> list[tuple[int, str]]:
    """``(line, name)`` of the module-level definitions and the methods of *tree*."""
    found: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
            if not _registered(node):
                found.append((node.lineno, node.name))
            if isinstance(node, ast.ClassDef):
                found.extend(
                    (item.lineno, item.name)
                    for item in node.body
                    if isinstance(item, _FUNCTIONS)
                    and not _registered(item)
                    and not _CALLED_BY_NAME.fullmatch(item.name)
                )
        else:
            found.extend(
                (node.lineno, target.id)
                for target in _assigned(node)
                if isinstance(target, ast.Name)
            )
    return [(line, name) for line, name in found if not name.startswith("__")]


def references(tree: ast.AST) -> Counter[str]:
    """How often *tree* reads each name: loads, attributes, imports and whole strings."""
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, _DOCUMENTED)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            found[node.id] += 1
        elif isinstance(node, ast.Attribute) and not isinstance(node.ctx, ast.Store):
            found[node.attr] += 1
        elif isinstance(node, ast.alias):
            found[node.name.rsplit(".", 1)[-1]] += 1
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            # a name spelled whole, or the last part of a dotted path or entry point
            last = re.split(r"[.:]", node.value.strip())[-1]
            if _WORD.fullmatch(last):
                found[last] += 1
    return found


def _read_everywhere() -> tuple[dict[pathlib.Path, ast.Module], Counter[str]]:
    trees = {
        path: ast.parse(path.read_text())
        for under in (SRC, *(ROOT / d for d in _DIRS))
        for path in python_files(under)
    }
    read: Counter[str] = Counter()
    for tree in trees.values():
        read.update(references(tree))
    texts = [ROOT / "pyproject.toml"] + [
        path
        for under in (*_DIRS, ".github")
        for path in (ROOT / under).rglob("*")
        if path.is_file() and path.suffix in _TEXT_SUFFIXES
    ]
    for path in texts:
        read.update(_WORD.findall(path.read_text(errors="replace")))
    return trees, read


def test_every_definition_has_a_reader() -> None:
    trees, read = _read_everywhere()
    dead = [
        f"{path.relative_to(ROOT)}:{line} {name}"
        for path, tree in trees.items()
        if SRC in path.parents
        for line, name in definitions(tree)
        if not read[name] and name not in ALLOWED
    ]
    assert not dead, (
        "no reader outside the tests; remove it or allow it:\n" + "\n".join(dead)
    )


def test_every_allowed_name_is_defined_and_has_no_reader() -> None:
    trees, read = _read_everywhere()
    defined = {
        name
        for path, tree in trees.items()
        if SRC in path.parents
        for _, name in definitions(tree)
    }
    stale = {name for name in ALLOWED if name not in defined or read[name]}
    assert not stale, f"take these off ALLOWED: {sorted(stale)}"


_SOURCE = '''"""The module, which names unused_in_docstring."""

import json
from pkg import imported

LIMIT = 3
_UNUSED = 4


def helper():
    """Calls nothing; ``spelled_in_docstring`` is no reader."""
    return LIMIT + json.dumps(imported)


@router.get("/x")
def route():
    return helper()


class Parser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        self.tagged = tag

    @property
    def kept(self):
        return getattr(self, "looked_up")

    def looked_up(self):
        return None
'''


def test_the_scan_lists_definitions_but_not_registered_ones() -> None:
    names = [name for _, name in definitions(ast.parse(_SOURCE))]
    assert names == ["LIMIT", "_UNUSED", "helper", "Parser", "kept", "looked_up"]


def test_the_scan_reads_loads_imports_and_whole_strings_not_docstrings() -> None:
    read = references(ast.parse(_SOURCE))
    assert read["LIMIT"] and read["helper"] and read["looked_up"] and read["imported"]
    assert not read["_UNUSED"] and not read["kept"] and not read["tagged"]
    assert not read["spelled_in_docstring"] and not read["unused_in_docstring"]
