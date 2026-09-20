"""expand-graph goes on while fill-gaps retrieves something, whatever the stub count does."""

from __future__ import annotations

from lawgraph.commands import expand_graph


def test_the_loop_ends_when_fill_gaps_retrieves_nothing_new(monkeypatch) -> None:
    ran: list[str] = []
    # Loading judgments opens as many stubs as it closes: the number of stubs stood still
    # and the old test ("no stub disappeared") stopped after one iteration.
    records = iter([100, 160, 160, 160])
    monkeypatch.setattr(expand_graph, "ArangoStore", lambda: object())
    monkeypatch.setattr(expand_graph, "_count_records", lambda store: next(records))
    monkeypatch.setattr(
        expand_graph, "run_command", lambda name, main, argv: ran.append(name) or True
    )

    assert expand_graph._expand(max_iterations=10) is True
    assert ran == ["fill-gaps", "normalize all", "semantic all", "fill-gaps"]


def test_a_failing_step_makes_the_command_fail_and_the_loop_goes_on(
    monkeypatch,
) -> None:
    records = iter([0, 5, 5, 5])
    monkeypatch.setattr(expand_graph, "ArangoStore", lambda: object())
    monkeypatch.setattr(expand_graph, "_count_records", lambda store: next(records))
    monkeypatch.setattr(
        expand_graph, "run_command", lambda name, main, argv: name != "semantic all"
    )
    assert expand_graph._expand(max_iterations=3) is False
