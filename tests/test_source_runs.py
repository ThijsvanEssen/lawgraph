"""What a scheduled run did with each source (``pipelines/source_runs.py``), and the
``completeness.source`` the API derives from it (``core/completeness.py``)."""

from __future__ import annotations

import pytest

from lawgraph.commands import poll
from lawgraph.config import settings
from lawgraph.core.completeness import SOURCE_RUN_STATE, Coverage, source_completeness
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import orchestration
from lawgraph.pipelines.command import HandWritten, Outcome, State
from lawgraph.pipelines.orchestration import retrieve_all
from lawgraph.pipelines.source_runs import record_source_runs, source_states
from lawgraph.sources.registry import Pipeline
from tests.fakes import PipelineStateFake, patch_pipeline_state


@pytest.fixture(autouse=True)
def _pipeline_state(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_pipeline_state(monkeypatch)


def _retrieve(source: str, part: str | None = None) -> Pipeline:
    command = HandWritten(lambda argv=None: PipelineResult())
    return Pipeline("retrieve", source, part, command, "", None, source)


def _ended(pipeline: Pipeline, state: State) -> Outcome:
    return Outcome(pipeline.address, state)


def test_each_source_is_named_by_how_its_retrieves_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SOURCES_OFF", frozenset({"echr"}))
    tk, tk_dossiers = _retrieve("tk"), _retrieve("tk", "dossiers")
    eurlex, bwb, echr = _retrieve("eurlex"), _retrieve("bwb"), _retrieve("echr")
    rs, rs_texts = _retrieve("rechtspraak"), _retrieve("rechtspraak", "texts")
    outcomes = [
        _ended(tk, State.OK),
        _ended(tk_dossiers, State.OK),
        _ended(eurlex, State.UNAVAILABLE),
        _ended(bwb, State.FAILED),
        _ended(rs, State.OK),
        _ended(rs_texts, State.SKIPPED),
    ]  # echr is off: no step, no outcome
    states = source_states([tk, tk_dossiers, eurlex, bwb, echr, rs, rs_texts], outcomes)
    assert states == {
        "tk": Coverage.DONE,
        "eurlex": Coverage.UNAVAILABLE,
        "echr": Coverage.PAUSED,
    }  # a failure or a skip is no state of the source: the next run says it


def test_as_of_is_when_the_retrieves_of_a_source_last_ended_well() -> None:
    store = PipelineStateFake()
    echr = _retrieve("echr")
    record_source_runs(store, [echr], [_ended(echr, State.OK)])
    done = store.kept[SOURCE_RUN_STATE + "echr"]
    assert done["state"] == "done" and done["as_of"] == done["at"]

    store.kept[SOURCE_RUN_STATE + "echr"] = {**done, "as_of": "2026-10-08T03:00:00Z"}
    record_source_runs(store, [echr], [_ended(echr, State.UNAVAILABLE)])
    refused = store.kept[SOURCE_RUN_STATE + "echr"]
    assert refused["state"] == "unavailable"
    assert refused["as_of"] == "2026-10-08T03:00:00Z"


def test_retrieve_all_records_its_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PipelineStateFake()
    monkeypatch.setattr(orchestration, "GraphStore", lambda: store)
    monkeypatch.setattr(settings, "SOURCES_OFF", frozenset({"echr"}))

    def run_pipelines(pipelines, argv_of, **_):
        return [Outcome(p.address, State.OK) for p in pipelines if p.source != "echr"]

    monkeypatch.setattr(orchestration, "run_pipelines", run_pipelines)
    retrieve_all(["--since", "1d"])
    assert store.kept[SOURCE_RUN_STATE + "echr"]["state"] == "paused"
    assert store.kept[SOURCE_RUN_STATE + "tk"]["state"] == "done"


def test_a_poll_records_its_source(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PipelineStateFake()
    monkeypatch.setattr(poll, "GraphStore", lambda: store)

    def run_pipelines(pipelines, argv_of, **_):
        return [
            Outcome(p.address, State.UNAVAILABLE if p.phase == "retrieve" else State.OK)
            for p in pipelines
        ]

    monkeypatch.setattr(poll, "run_pipelines", run_pipelines)
    poll.main(["rechtspraak", "--since", "2h"])
    assert store.kept[SOURCE_RUN_STATE + "rechtspraak"]["state"] == "unavailable"


@pytest.mark.parametrize(
    ("run", "retrieved_at", "expected"),
    [
        (None, None, {"state": "pending", "as_of": None}),
        (
            None,
            "2026-10-20T03:00:00Z",
            {"state": "done", "as_of": "2026-10-20T03:00:00Z"},
        ),
        (
            {"state": "paused", "at": "2026-10-20T03:00:00Z", "as_of": None},
            "2026-10-08T03:00:00Z",
            {"state": "paused", "as_of": "2026-10-08T03:00:00Z"},
        ),
        (
            {
                "state": "done",
                "at": "2026-10-20T03:00:00Z",
                "as_of": "2026-10-20T03:00:00Z",
            },
            "2026-10-19T22:00:00Z",
            {"state": "done", "as_of": "2026-10-20T03:00:00Z"},
        ),
    ],
)
def test_the_source_part_of_a_source(run, retrieved_at, expected) -> None:
    assert source_completeness(run, retrieved_at) == expected
