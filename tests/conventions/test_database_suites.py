"""The two suites on the test server split by what a test does: one in ``tests/integration``
runs the CLI or a pipeline; one that writes the graph directly and reads a query or a route
is in ``tests/pg``. A test of a helper module of ``tests/integration`` stays with it."""

from __future__ import annotations

import re

from tests.paths import TESTS

INTEGRATION = TESTS / "integration"
_RUNS = re.compile(
    r"\bcli\b|lawgraph_runner|from lawgraph\.(?:pipelines|commands)\b"
    r"|from lawgraph import (?:pipelines|commands)\b"
)


def test_an_integration_test_runs_the_cli_or_a_pipeline() -> None:
    found = [
        path.name
        for path in sorted(INTEGRATION.glob("test_*.py"))
        if not _RUNS.search(path.read_text())
        and not (INTEGRATION / path.name.removeprefix("test_")).exists()
    ]
    assert found == [], "a test that only reads queries or routes belongs in tests/pg"
