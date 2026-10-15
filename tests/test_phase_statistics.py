"""What ``<phase> all`` leaves the planner: a run over everything vacuums and analyzes the
database, a run ``--since`` analyzes the tables it changed."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.pipelines import orchestration
from lawgraph.pipelines.command import Outcome, State
from tests.fakes import PipelineStateFake, patch_pipeline_state


class _Store(PipelineStateFake):
    def __init__(self) -> None:
        super().__init__()
        self.maintenance: list[str] = []

    def vacuum_analyze(self) -> None:
        self.maintenance.append("vacuum analyze")

    def analyze_changed(self) -> None:
        self.maintenance.append("analyze changed")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    patch_pipeline_state(monkeypatch)
    store = _Store()

    def run_pipelines(pipelines: list[Any], argv_of: Any, **kw: Any) -> list[Outcome]:
        return [Outcome("a", State.OK)]

    monkeypatch.setattr(orchestration, "GraphStore", lambda: store)
    monkeypatch.setattr(orchestration, "run_pipelines", run_pipelines)
    return store


@pytest.mark.parametrize(
    "run", [orchestration.normalize_all, orchestration.semantic_all]
)
def test_a_run_since_a_date_analyzes_what_it_changed(store: _Store, run: Any) -> None:
    run(["--since", "1d"])
    assert store.maintenance == ["analyze changed"]


@pytest.mark.parametrize(
    "run", [orchestration.normalize_all, orchestration.semantic_all]
)
def test_a_run_over_everything_vacuums_the_database(store: _Store, run: Any) -> None:
    run([])
    assert store.maintenance == ["vacuum analyze"]


def test_retrieve_leaves_the_planner_alone(store: _Store) -> None:
    orchestration.retrieve_all(["--mode", "full", "--jobs", "1"])
    assert store.maintenance == []
