"""expand-graph goes on while a round retrieves something, whatever the stub count does."""

from __future__ import annotations

from lawgraph.commands import expand_graph
from lawgraph.pipelines.command import Outcome, State, combined_result


def _recorded(monkeypatch, counts: list[int]) -> list[tuple[str, list[str]]]:
    ran: list[tuple[str, list[str]]] = []
    records = iter(counts)
    monkeypatch.setattr(expand_graph, "ArangoStore", lambda: object())
    monkeypatch.setattr(expand_graph, "_count_records", lambda store: next(records))
    monkeypatch.setattr(
        expand_graph,
        "run_command",
        lambda label, command, argv: (
            ran.append((label, list(argv))) or Outcome(label, State.OK)
        ),
    )
    return ran


def test_the_loop_ends_when_a_round_retrieves_nothing_new(monkeypatch) -> None:
    # Loading judgments opens as many stubs as it closes: the number of stubs stood still
    # and the old test ("no stub disappeared") stopped after one iteration.
    ran = _recorded(monkeypatch, [100, 160, 160, 160])
    assert not combined_result(expand_graph._expand(max_iterations=10)).errors
    assert [name for name, _ in ran] == [
        "retrieve all",
        "normalize all",
        "semantic all",
        "retrieve all",
        "semantic all",
    ]


def test_a_round_works_on_what_it_retrieved_and_the_end_on_everything(
    monkeypatch,
) -> None:
    """A round of the rebuild of 2026-09-20 ran 16 minutes of normalize and 25 of semantic
    over the whole database, for the few percent the round had added."""
    ran = _recorded(monkeypatch, [100, 160, 160, 200, 200, 200])
    expand_graph._expand(max_iterations=10)
    rounds = [argv for name, argv in ran if name != "retrieve all"]
    assert [argv[:1] for argv in rounds] == [["--since"]] * 4 + [[]]
    first, second = rounds[0][1], rounds[2][1]
    assert rounds[1][1] == first and rounds[3][1] == second  # since the round began
    assert first <= second
    assert ran[-1] == ("semantic all", [])  # old texts that name a law loaded just now


def test_nothing_retrieved_means_nothing_to_work_on(monkeypatch) -> None:
    ran = _recorded(monkeypatch, [100, 100])
    expand_graph._expand(max_iterations=10)
    assert [name for name, _ in ran] == ["retrieve all"]


def test_a_failing_step_makes_the_command_fail_and_the_loop_goes_on(
    monkeypatch,
) -> None:
    records = iter([0, 5, 5, 5])
    monkeypatch.setattr(expand_graph, "ArangoStore", lambda: object())
    monkeypatch.setattr(expand_graph, "_count_records", lambda store: next(records))
    monkeypatch.setattr(
        expand_graph,
        "run_command",
        lambda label, command, argv: Outcome(
            label, State.FAILED if label == "semantic all" else State.OK
        ),
    )
    outcomes = expand_graph._expand(max_iterations=3)
    assert (
        combined_result(outcomes).errors == ["semantic all failed"] * 2
    )  # the round, the end
    assert [o.label for o in outcomes].count("retrieve all") == 2
