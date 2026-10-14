"""A test module imports no other test module: what tests share lives in a module of its
own (``seed``, ``graph``, ``plans``, the fakes in ``tests/fakes``), so that renaming a helper
in one test breaks no other, and no test patches another's globals."""

from __future__ import annotations

import ast

from tests.conventions._scan import TESTS


def _test_module_imports(tree: ast.AST, package: str) -> list[tuple[int, str]]:
    """``(line, module)`` of every import of a test module (``test_*``) of ``tests`` in
    *tree*, a module of *package*: ``from a import b`` names ``a`` or ``a.b``."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            parts = package.split(".")
            base = ".".join(parts[: len(parts) - node.level + 1] if node.level else [])
            module = ".".join(p for p in (base, node.module or "") if p)
            modules = [module] + [f"{module}.{alias.name}" for alias in node.names]
        else:
            continue
        found += [
            (node.lineno, module)
            for module in modules
            if module.startswith("tests.")
            and module.rsplit(".", 1)[-1].startswith("test_")
        ]
    return found


def test_the_scan_finds_an_import_of_a_test_module() -> None:
    tree = ast.parse(
        "from tests.pg.test_feed import _seed\n"
        "from tests.pg import test_feed\n"
        "import tests.pg.test_feed\n"
        "from .test_feed import _seed\n"
        "from tests.pg.plans import explain\n"
        "from tests.fakes import InMemoryStore\n"
        "from lawgraph.db.queries import test_like\n"
    )
    assert _test_module_imports(tree, "tests.pg") == [
        (1, "tests.pg.test_feed"),
        (2, "tests.pg.test_feed"),
        (3, "tests.pg.test_feed"),
        (4, "tests.pg.test_feed"),
    ]


def test_no_test_module_imports_another() -> None:
    found = [
        f"{path.relative_to(TESTS.parent)}:{line} imports {module}"
        for path in sorted(TESTS.rglob("test_*.py"))
        for line, module in _test_module_imports(
            ast.parse(path.read_text()),
            ".".join(path.relative_to(TESTS.parent).parent.parts),
        )
    ]
    assert not found, "\n".join(found)
