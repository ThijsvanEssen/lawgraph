"""Retrieves that choose their work from normalized nodes say so when there are none, and a
run that takes only the first part of its gaps says so in the table of ``retrieve all``."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import inputs
from lawgraph.pipelines.command import Outcome, State, combined_result
from lawgraph.pipelines.inputs import Reads, reading
from lawgraph.pipelines.orchestration import run_pipelines
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.sources.registry import PIPELINES, Pipeline, find


@pytest.fixture
def graph(monkeypatch) -> set[tuple[str, str]]:
    """The ``(collection, label)`` pairs the graph holds; empty unless a test adds some."""
    held: set[tuple[str, str]] = set()
    monkeypatch.setattr(inputs, "GraphStore", lambda: object())
    monkeypatch.setattr(
        inputs.gap_queries,
        "holds_label",
        lambda store, collection, label: (collection, label) in held,
    )
    return held


def _command(calls: list[list[str]]) -> Any:
    def retrieve_example(argv: list[str] | None = None) -> PipelineResult:
        calls.append(list(argv or []))
        return PipelineResult()

    return retrieve_example


# ── the registry ─────────────────────────────────────────────────────────────


def test_the_retrieves_that_read_normalized_nodes_say_so() -> None:
    reads = {
        p.name: [(r.pipeline, r.collection, r.label) for r in p.reads]
        for p in PIPELINES["retrieve"]
        if p.reads
    }
    assert reads == {
        "tk-content": [("tk-dossiers", "documents", "TK")],
        "eurlex": [("eurlex", "instruments", "EU")],
        "eerstekamer-bills": [("eerstekamer-votes", "decisions", "EK")],
        "eerstekamer-motions": [("eerstekamer-votes", "decisions", "EK")],
    }


def test_what_a_retrieve_reads_is_written_by_a_normalize_pipeline() -> None:
    for pipeline in PIPELINES["retrieve"]:
        for r in pipeline.reads:
            assert find("normalize", r.pipeline) is not None, (pipeline.name, r)


def test_the_registered_command_keeps_its_name_and_checks() -> None:
    command = find("retrieve", "tk-content").command  # type: ignore[union-attr]
    assert command.__name__ == "retrieve_tk_content"
    assert command.__wrapped__.__name__ == "retrieve_tk_content"  # type: ignore[attr-defined]


# ── the warning ──────────────────────────────────────────────────────────────


def test_a_run_on_a_graph_without_what_it_reads_warns_and_notes_it(
    graph, caplog
) -> None:
    calls: list[list[str]] = []
    command = reading(_command(calls), [Reads("tk-dossiers", "documents", "TK")])
    with caplog.at_level("WARNING"):
        result = command([])
    assert calls == [[]]  # it still runs: what it chooses from may come later
    assert result.notes == ["no TK documents yet: run normalize tk-dossiers first"]
    assert any("Run normalize tk-dossiers first" in m for m in caplog.messages)


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_needs_no_database(monkeypatch, flag: str) -> None:
    """``retrieve tk-content --help`` printed its options only after a query."""

    def no_database() -> object:
        raise AssertionError("the help asked the database")

    monkeypatch.setattr(inputs, "GraphStore", no_database)
    calls: list[list[str]] = []
    command = reading(_command(calls), [Reads("tk-dossiers", "documents", "TK")])
    assert command([flag]).notes == []
    assert calls == [[flag]]


def test_a_run_on_a_graph_that_holds_it_says_nothing(graph, caplog) -> None:
    graph.add(("documents", "TK"))
    command = reading(_command([]), [Reads("tk-dossiers", "documents", "TK")])
    with caplog.at_level("WARNING"):
        result = command([])
    assert result.notes == []
    assert not caplog.messages


@pytest.mark.parametrize(
    ("argv", "checked"),
    [
        ([], True),  # incremental: the acts already in the graph
        (["--mode", "com"], True),
        (["--mode=incremental"], True),
        (["--mode", "full"], False),  # lists them at EUR-Lex
        (["--mode", "nim"], False),
        (["--mode", "gaps"], False),  # reads what BWB names
    ],
)
def test_only_the_modes_that_choose_from_the_graph_are_checked(
    graph, argv: list[str], checked: bool
) -> None:
    eurlex = Reads("eurlex", "instruments", "EU", modes=("incremental", "com"))
    result = reading(_command([]), [eurlex])(argv)
    assert bool(result.notes) is checked


def test_the_note_reaches_the_table_of_retrieve_all(graph, caplog) -> None:
    command = reading(_command([]), [Reads("tk-dossiers", "documents", "TK")])
    pipeline = Pipeline("retrieve", "tk", "content", command, "", None, "koop")
    with caplog.at_level("INFO"):
        [outcome] = run_pipelines([pipeline], lambda p: [])
    assert outcome.state is State.OK
    assert any(
        "retrieve tk-content" in m
        and m.rstrip().endswith(
            "ok  (no TK documents yet: run normalize tk-dossiers first)"
        )
        for m in caplog.messages
    )


# ── the cap of a gaps run ────────────────────────────────────────────────────


def test_a_list_cut_at_the_cap_carries_a_note() -> None:
    rows = [f"ECLI:{n}" for n in range(_gaps.MAX_GAPS_PER_RUN + 5)]
    taken = _gaps._capped(rows, "stub judgments")
    assert taken.note == "50,000 of 50,005 stub judgments, again for the rest"


def test_a_list_below_the_cap_carries_none() -> None:
    assert _gaps._capped(["a"], "stub judgments").note is None


def test_the_note_of_a_cut_list_goes_on_the_result() -> None:
    cut = _gaps._capped(list(range(_gaps.MAX_GAPS_PER_RUN + 1)), "dossiers")
    whole = _gaps._capped([1, 2], "dossiers")
    result = _gaps.noted(PipelineResult(created=3), cut, whole)
    assert result.notes == ["50,000 of 50,001 dossiers, again for the rest"]


def test_a_phase_keeps_the_notes_of_its_steps() -> None:
    noted = PipelineResult(notes=["50,000 of 93,818 Kamerstukken without XML, again"])
    total = combined_result(
        [
            Outcome("retrieve tk-content", State.OK, noted),
            Outcome("retrieve tk", State.OK),
        ]
    )
    assert total.notes == [
        "retrieve tk-content: 50,000 of 93,818 Kamerstukken without XML, again"
    ]
