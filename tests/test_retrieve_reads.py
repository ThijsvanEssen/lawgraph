"""Retrieves that choose their work from normalized nodes say so when there are none, and a
run that takes only the first part of its gaps says so in the table of ``retrieve all``."""

from __future__ import annotations

import argparse

import pytest

from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import retrieve_commands
from lawgraph.pipelines.command import Outcome, State, combined_result
from lawgraph.pipelines.orchestration import run_pipelines
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve_commands import (
    Reads,
    RetrieveCommand,
    RetrieveMode,
    add_mode_argument,
)
from lawgraph.sources.registry import PIPELINES, Pipeline, find

TK_DOCUMENTS = Reads("tk-dossiers", "documents", "TK")


@pytest.fixture
def graph(monkeypatch) -> set[tuple[str, str]]:
    """The ``(collection, label)`` pairs the graph holds; empty unless a test adds some."""
    held: set[tuple[str, str]] = set()
    monkeypatch.setattr(retrieve_commands, "GraphStore", lambda: object())
    monkeypatch.setattr(
        retrieve_commands.gap_queries,
        "holds_label",
        lambda store, collection, label: (collection, label) in held,
    )
    return held


def _command(
    calls: list[argparse.Namespace],
    reads: tuple[Reads, ...],
    default: RetrieveMode = RetrieveMode.INCREMENTAL,
) -> RetrieveCommand:
    """A retrieve with the modes of ``retrieve eurlex`` and *default*, that records what it
    was asked."""

    def retrieve_example(args: argparse.Namespace) -> PipelineResult:
        calls.append(args)
        return PipelineResult()

    def add_args(parser: argparse.ArgumentParser) -> None:
        add_mode_argument(
            parser,
            (
                RetrieveMode.INCREMENTAL,
                RetrieveMode.FULL,
                RetrieveMode.NIM,
                RetrieveMode.COM,
                RetrieveMode.GAPS,
            ),
            default=default,
            help="The mode.",
        )

    return RetrieveCommand(retrieve_example, "An example.", add_args, reads)


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


def test_the_registered_command_checks_what_it_reads() -> None:
    for name in ("tk-content", "eerstekamer-motions"):  # a function and a class
        pipeline = find("retrieve", name)
        assert pipeline is not None
        assert isinstance(pipeline.command, RetrieveCommand)
        assert pipeline.command.reads == pipeline.reads != ()


# ── the warning ──────────────────────────────────────────────────────────────


def test_a_run_on_a_graph_without_what_it_reads_warns_and_notes_it(
    graph, caplog
) -> None:
    calls: list[argparse.Namespace] = []
    command = _command(calls, (TK_DOCUMENTS,))
    with caplog.at_level("WARNING"):
        result = command([])
    assert len(calls) == 1  # it still runs: what it chooses from may come later
    assert result.notes == ["no TK documents yet: run normalize tk-dossiers first"]
    assert any("Run normalize tk-dossiers first" in m for m in caplog.messages)


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_needs_no_database(monkeypatch, capsys, flag: str) -> None:
    """``retrieve tk-content --help`` printed its options only after a query."""

    def no_database() -> object:
        raise AssertionError("the help asked the database")

    monkeypatch.setattr(retrieve_commands, "GraphStore", no_database)
    calls: list[argparse.Namespace] = []
    with pytest.raises(SystemExit) as ended:
        _command(calls, (TK_DOCUMENTS,))([flag])
    assert ended.value.code == 0
    assert "An example." in capsys.readouterr().out
    assert calls == []


def test_a_run_on_a_graph_that_holds_it_says_nothing(graph, caplog) -> None:
    graph.add(("documents", "TK"))
    with caplog.at_level("WARNING"):
        result = _command([], (TK_DOCUMENTS,))([])
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
    eurlex = Reads(
        "eurlex",
        "instruments",
        "EU",
        modes=(RetrieveMode.INCREMENTAL, RetrieveMode.COM),
    )
    result = _command([], (eurlex,))(argv)
    assert bool(result.notes) is checked


@pytest.mark.parametrize(
    ("argv", "checked"), [([], True), (["--mode", "incremental"], False)]
)
def test_a_command_with_another_default_mode_is_checked_in_that_mode(
    graph, argv: list[str], checked: bool
) -> None:
    """The mode is the one argparse read, its default included, not ``incremental``."""
    com = Reads("eurlex", "instruments", "EU", modes=(RetrieveMode.COM,))
    result = _command([], (com,), default=RetrieveMode.COM)(argv)
    assert bool(result.notes) is checked


def test_the_note_reaches_the_table_of_retrieve_all(graph, caplog) -> None:
    command = _command([], (TK_DOCUMENTS,))
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
    taken = _gaps.Gaps.capped(rows, "stub judgments")
    assert taken.note == "50,000 of 50,005 stub judgments, again for the rest"


def test_a_list_cut_at_a_limit_of_its_own_carries_that_limit() -> None:
    taken = _gaps.Gaps.capped(list(range(1500)), "Kamerstukken without XML", 1000)
    assert len(taken) == 1000
    assert taken.note == "1,000 of 1,500 Kamerstukken without XML, again for the rest"


def test_a_list_below_the_cap_carries_none() -> None:
    assert _gaps.Gaps.capped(["a"], "stub judgments").note is None


def test_the_note_of_a_cut_list_goes_on_the_result() -> None:
    cut = _gaps.Gaps.capped(list(range(_gaps.MAX_GAPS_PER_RUN + 1)), "dossiers")
    whole = _gaps.Gaps.capped([1, 2], "dossiers")
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
