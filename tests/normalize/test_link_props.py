"""A written TK node keeps only the props its readers read (``LINK_PROPS``): a reader that
reads one not declared in ``LINK_READS`` would get None and stay silent, so every literal
``….props.get("…")`` and ``….props["…"]`` of a reader is held to its entry."""

from __future__ import annotations

import ast
import inspect
from types import ModuleType

from lawgraph.pipelines.normalize import _tk_cases, _tk_members, _tk_votes, tk_dossiers
from lawgraph.pipelines.normalize._tk_cases import LINK_PROPS, LINK_READS

# The modules whose functions read written nodes; in the first two every function that
# reads a prop is such a reader, the others read full nodes too.
_ALL_READERS = (_tk_cases, _tk_votes)
_MODULES = (*_ALL_READERS, tk_dossiers, _tk_members)


def _functions(module: ModuleType) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(inspect.getsource(module))
    return {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }


def _props_read(function: ast.FunctionDef) -> set[str]:
    """The literal names *function* reads of a ``props``: ``x.props.get("n")``,
    ``x.props["n"]``."""
    names: set[str] = set()
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "props"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.add(node.args[0].value)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "props"
            and isinstance(node.slice, ast.Constant)
        ):
            names.add(node.slice.value)
    return names


def test_every_reader_reads_only_what_it_declares() -> None:
    found = {}
    for module in _MODULES:
        for name, function in _functions(module).items():
            read = _props_read(function)
            if name in LINK_READS:
                found[name] = function
                assert read <= set(LINK_READS[name]), (module.__name__, name)
            elif module in _ALL_READERS:
                assert not read, f"{module.__name__}.{name} reads {read}: declare it"
    assert set(found) == set(LINK_READS)


def test_every_declared_prop_is_named_by_its_reader() -> None:
    """No entry names a prop its reader no longer reads (``link_documents`` reads the props
    as ``of``, not through ``.props``)."""
    functions = {
        name: function
        for module in _MODULES
        for name, function in _functions(module).items()
    }
    for name, props in LINK_READS.items():
        source = ast.unparse(functions[name])
        for prop in props:
            assert f"'{prop}'" in source, (name, prop)


def test_link_props_are_the_union_of_the_readers() -> None:
    assert set(LINK_PROPS) == {p for props in LINK_READS.values() for p in props}
    assert len(LINK_PROPS) == len(set(LINK_PROPS))
