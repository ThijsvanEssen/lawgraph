"""How a motion or an amendment ended (``core/paper_outcomes.py``)."""

from __future__ import annotations

from lawgraph.core.paper_outcomes import decision_outcome, paper_outcome


def _decision(key: str, date: str, passed: bool | None, kind: str, **rest):
    return {"key": key, "date": date, "passed": passed, "decision_kind": kind, **rest}


def test_a_vote_gives_the_outcome_with_its_day_and_seats() -> None:
    # Cbw, amendement nr. 25: aangenomen 150-0 on 15 April 2026
    adopted = _decision(
        "decision_e959", "2026-04-15", True, "Stemmen - aangenomen", tally={"Voor": 150}
    )
    assert paper_outcome([adopted], replaced=False) == {
        "outcome": "aangenomen",
        "decided_on": "2026-04-15",
        "tally": {"Voor": 150},
        "decision": "decision_e959",
    }
    # nr. 12: verworpen 65-85
    rejected = _decision(
        "decision_58fd",
        "2026-04-15",
        False,
        "Stemmen - verworpen",
        tally={"Voor": 65, "Tegen": 85},
    )
    assert paper_outcome([rejected], replaced=False)["outcome"] == "verworpen"


def test_a_vote_decides_before_a_decision_without_one_the_latest_first() -> None:
    held = _decision("d1", "2026-03-31", None, "Stemmen - aangehouden")
    held_again = _decision("d2", "2026-04-07", None, "Stemmen - aangehouden")
    voted = _decision("d3", "2026-04-01", True, "Stemmen - aangenomen")
    assert paper_outcome([held, held_again], replaced=True) == {
        "outcome": "aangehouden",
        "decided_on": "2026-04-07",
        "tally": None,
        "decision": "d2",
    }
    assert paper_outcome([held, voted, held_again], replaced=False)["decision"] == "d3"


def test_without_a_decision_a_replaced_paper_is_vervangen_and_another_none() -> None:
    assert paper_outcome([], replaced=True)["outcome"] == "vervangen"
    assert paper_outcome([], replaced=False) == dict.fromkeys(
        ("outcome", "decided_on", "tally", "decision")
    )
    # a postponed vote is no outcome
    postponed = _decision("d", "2026-01-01", None, "Stemmen - uitstellen")
    assert paper_outcome([postponed], replaced=False)["outcome"] is None


def test_a_motion_of_the_eerste_kamer_without_a_decision_has_its_stated_status() -> (
    None
):
    assert (
        paper_outcome([], replaced=False, stated="verworpen")["outcome"] == "verworpen"
    )
    assert paper_outcome([], replaced=False, stated="in behandeling")["outcome"] is None


def test_a_decision_without_a_vote_says_its_outcome_by_its_kind() -> None:
    assert decision_outcome(None, "Stemmen - ingetrokken", None) == "ingetrokken"
    assert decision_outcome(None, "Stemmen - vervallen", None) == "vervallen"
    assert decision_outcome(None, None, "Aangehouden") == "aangehouden"
    assert (
        decision_outcome(True, "Stemmen - zonder stemming aannemen", None)
        == "aangenomen"
    )
