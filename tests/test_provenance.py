"""The provenance catalogue is complete, the pipelines write only its values, and the docs
show it as it is."""

from __future__ import annotations

import ast
import pathlib
from typing import get_args

from lawgraph.config.constants import IMPLEMENTS_BASES
from lawgraph.core import provenance
from lawgraph.core.citations import CitationHit, hit_reason
from lawgraph.core.provenance import PROVENANCE, Basis, Reason
from lawgraph.core.relations import RELATION_NAMES
from tests.paths import ROOT

PIPELINES = ROOT / "src" / "lawgraph" / "pipelines"
DOCS = ROOT / "docs" / "data-model.md"
_KEYS = {"basis", "bases", "reason"}


def test_the_catalogue_is_the_literals_and_each_value_once() -> None:
    by_field = {
        field: [p.value for p in PROVENANCE if p.field == field] for field in _KEYS
    }
    assert sorted(by_field["basis"]) == sorted(get_args(Basis))
    assert sorted(by_field["bases"]) == sorted(IMPLEMENTS_BASES)
    assert sorted(by_field["reason"]) == sorted(get_args(Reason))
    for values in by_field.values():
        assert len(values) == len(set(values))
    for p in PROVENANCE:
        assert p.relations and set(p.relations) <= RELATION_NAMES, p.value
        assert p.meaning.endswith("."), p.value


def test_every_constant_is_in_the_catalogue() -> None:
    values = {p.value for p in PROVENANCE}
    for name, value in vars(provenance).items():
        if name.startswith(("BASIS_", "REASON_")) and isinstance(value, str):
            assert value in values, name
    assert set(get_args(Basis)) | set(get_args(Reason)) <= values


def test_hit_reason_gives_a_reason_of_the_catalogue() -> None:
    hits = [
        CitationHit(bwb_id=b, celex=c, article_number=a)
        for b in ("BWBR0005289", None)
        for c in ("32016R0679", None)
        for a in ("6:162", None)
    ]
    assert {hit_reason(hit) for hit in hits} <= set(get_args(Reason))


def _offences(path: pathlib.Path) -> list[str]:
    """Where *path* writes a provenance value as a literal of its own: ``{"basis": "x"}``,
    ``reason="x"``, or a module constant ``BASIS… = "x"`` beside the catalogue."""
    tree = ast.parse(path.read_text())
    found: list[str] = []
    for node in ast.walk(tree):
        pairs: list[tuple[ast.expr | None, ast.expr]] = []
        if isinstance(node, ast.Dict):
            pairs = list(zip(node.keys, node.values, strict=True))
        elif isinstance(node, ast.Call):
            pairs = [(ast.Constant(k.arg), k.value) for k in node.keywords if k.arg]
        for key, value in pairs:
            if (
                isinstance(key, ast.Constant)
                and key.value in _KEYS
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                found.append(f"{path.name}:{node.lineno} {key.value}={value.value!r}")
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id.startswith(
                    ("BASIS", "REASON")
                ):
                    found.append(f"{path.name}:{statement.lineno} {target.id}")
    return found


def test_the_pipelines_write_only_the_values_of_the_catalogue() -> None:
    offences = [o for path in sorted(PIPELINES.rglob("*.py")) for o in _offences(path)]
    assert not offences, "use a constant of lawgraph.core.provenance: " + ", ".join(
        offences
    )


def test_the_docs_show_the_catalogue() -> None:
    assert provenance.block_of(DOCS.read_text()) == provenance.render_table(), (
        "docs/data-model.md is out of date: python -m lawgraph.core.provenance"
    )
