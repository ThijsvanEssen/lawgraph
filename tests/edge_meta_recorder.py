"""Hold the ``meta`` of every edge a test makes against the model of its relation
(``RelationSpec.meta`` in ``core/relations.py``) and report what does not fit, without
failing: a key the model lacks, or a value of another type.

``make_edge_doc`` is wrapped for the whole run (in ``lawgraph.db.edges`` and every module
that has it by name), so every writer a test drives is held to the models. The report is a
section at the end of the run; under xdist each worker hands its findings to the controller.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from pydantic import ValidationError

# (relation, edge source, problem) -> edges
FOUND: Counter[tuple[str, str, str]] = Counter()
_KEY = "edge_meta"


def meta_problems(relation: str, meta: Mapping[str, Any]) -> list[str]:
    """What of *meta* the model of *relation* does not allow: ``unknown key x`` or
    ``x[].y: <pydantic error type>``."""
    from lawgraph.core.relations import BY_NAME

    spec = BY_NAME.get(relation)
    if spec is None or not meta:
        return []
    if spec.meta is None:
        return [f"unknown key {key}" for key in sorted(meta)]
    try:
        spec.meta.model_validate(dict(meta), strict=True)
    except ValidationError as error:
        found = []
        for item in error.errors():
            where = "".join(
                f".{part}" if isinstance(part, str) else "[]" for part in item["loc"]
            ).lstrip(".")
            found.append(
                f"unknown key {where}"
                if item["type"] == "extra_forbidden"
                else f"{where}: {item['type']}"
            )
        return sorted(set(found))
    return []


def _recording(make: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def make_edge_doc(*args: Any, **kwargs: Any) -> dict[str, Any]:
        doc = make(*args, **kwargs)
        for problem in meta_problems(doc["relation"], doc["meta"]):
            FOUND[(doc["relation"], doc["source"], problem)] += 1
        return doc

    make_edge_doc.__wrapped__ = make  # type: ignore[attr-defined]
    return make_edge_doc


def pytest_sessionstart(session: pytest.Session) -> None:
    from lawgraph.db import edges

    original = edges.make_edge_doc
    wrapped = _recording(original)
    for module in list(sys.modules.values()):
        if getattr(module, "make_edge_doc", None) is original:
            module.make_edge_doc = wrapped  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session) -> None:
    output = getattr(session.config, "workeroutput", None)
    if output is not None:  # an xdist worker: the controller reports
        output[_KEY] = [[*key, count] for key, count in FOUND.items()]


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: Any) -> None:
    for relation, source, problem, count in node.workeroutput.get(_KEY, []):
        FOUND[(relation, source, problem)] += count


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if not FOUND:
        return
    terminalreporter.section("edge meta outside the models of core/relations.py")
    for (relation, source, problem), count in sorted(FOUND.items()):
        terminalreporter.line(f"{relation} {source or '-'}: {problem} ({count} edges)")
