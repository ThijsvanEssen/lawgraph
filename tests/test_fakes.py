"""The fakes of the unit tests stand in for the real store: same methods, same calls."""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from lawgraph.db.store import GraphStore

TESTS = pathlib.Path(__file__).parent


def _fake_stores() -> list[tuple[str, ast.ClassDef]]:
    """Every class of the unit tests named ``…Store``, nested ones included."""
    return [
        (f"{path.relative_to(TESTS)}:{node.lineno} {node.name}", node)
        for path in sorted(TESTS.rglob("*.py"))
        if not {"integration", "pg"} & set(path.parts)
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef) and node.name.endswith("Store")
    ]


def _public_methods(fake: ast.ClassDef) -> list[ast.FunctionDef]:
    return [
        item
        for item in fake.body
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
    ]


def _incompatibilities(method: ast.FunctionDef, real: inspect.Signature) -> list[str]:
    """Why a call that fits *real* would not fit *method*, or the other way round."""
    args = method.args
    positional = [a.arg for a in [*args.posonlyargs, *args.args]][1:]  # without self
    required = positional[: len(positional) - len(args.defaults)] + [
        a.arg
        for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True)
        if d is None
    ]
    accepted = set(positional) | {a.arg for a in args.kwonlyargs}
    params = [p for p in real.parameters.values() if p.name != "self"]
    real_positional = [
        p.name for p in params if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]
    real_required = {p.name for p in params if p.default is inspect.Parameter.empty}
    problems = [
        f"{name} is required here, not on GraphStore"
        for name in required
        if name not in real_required
    ]
    problems += [
        f"does not take {p.name}"
        for p in params
        if p.name not in accepted
        and not (args.kwarg or (args.vararg and p.name in real_positional))
    ]
    shared = min(len(positional), len(real_positional))
    if positional[:shared] != real_positional[:shared]:
        problems.append(f"positions {positional} differ from {real_positional}")
    return problems


def test_the_scan_finds_the_shared_fake_store() -> None:
    assert "InMemoryStore" in {node.name for _, node in _fake_stores()}


@pytest.mark.parametrize(
    ("fake", "real_name", "fits"),
    [
        ("def existing_keys(self, collection, keys, **_): ...", "existing_keys", True),
        ("def existing_keys(self, collection, keys): ...", "existing_keys", False),
        ("def get_node(self, collection, key, extra): ...", "get_node", False),
        ("def get_node(self, key, collection): ...", "get_node", False),
        ("def get_node(self, collection): ...", "get_node", False),
        ("def get_node(self, *args, **kwargs): ...", "get_node", True),
        ("def query(self, statement, params=None, **_): ...", "query", True),
    ],
)
def test_the_signature_check(fake: str, real_name: str, fits: bool) -> None:
    method = ast.parse(fake).body[0]
    assert isinstance(method, ast.FunctionDef)
    real = inspect.signature(getattr(GraphStore, real_name))
    assert (not _incompatibilities(method, real)) is fits


@pytest.mark.parametrize(
    "fake", [node for _, node in _fake_stores()], ids=[n for n, _ in _fake_stores()]
)
def test_a_fake_store_has_the_methods_of_graph_store(fake: ast.ClassDef) -> None:
    problems = []
    for method in _public_methods(fake):
        real = getattr(GraphStore, method.name, None)
        if not callable(real):
            problems.append(f"{method.name}: GraphStore has no such method")
            continue
        problems += [
            f"{method.name}: {problem}"
            for problem in _incompatibilities(method, inspect.signature(real))
        ]
    assert not problems, (
        f"{fake.name} stands in for a GraphStore it does not match; answer a query "
        f"function by patching it (see tests/fakes.py): {problems}"
    )
