"""A dossier's kind, phases, title and outcome — one implementation for API and pipeline."""

from __future__ import annotations

import pytest

from lawgraph.core.curated import LISTS, problems
from lawgraph.core.dossier_stages import (
    CARRYING_KINDS,
    LEGISLATIVE_KINDS,
    PHASES,
    DossierOutcome,
    current_phase,
    derive_outcome,
    dossier_display_name,
    dossier_kind,
    dossier_phases,
    last_decision,
    outcome_props,
    phase_props,
    select_title,
)


def _doc(kind: str, date: str | None = None, title: str | None = None) -> dict:
    return {"kind": kind, "date": date, "title": title}


def _done(phases: list[dict] | None) -> list[str]:
    return [p["name"] for p in phases or [] if p["done"]]


# ── kind ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", CARRYING_KINDS)
def test_the_kind_is_the_soort_of_the_dossiers_own_zaak(kind: str) -> None:
    assert dossier_kind(["Motie", kind, "Brief regering"], []) == (kind, "case")


def test_a_zaak_wins_over_the_papers() -> None:
    assert dossier_kind(["Begroting"], ["Voorstel van wet"]) == ("Begroting", "case")


@pytest.mark.parametrize(
    ("documents", "kind"),
    [
        (["Motie", "Voorstel van wet"], "Wetgeving"),
        (["Voorstel van wet (tweede lezing)"], "Wetgeving"),
        (["Voorstel van wet (initiatiefvoorstel)"], "Initiatiefwetgeving"),
    ],
)
def test_without_a_zaak_a_voorstel_van_wet_makes_it_a_bill(
    documents: list[str], kind: str
) -> None:
    assert dossier_kind(["Motie"], documents) == (kind, "document")


def test_a_dossier_of_letters_and_motions_has_no_kind() -> None:
    assert dossier_kind(["Motie", "Brief regering"], ["Brief regering"]) == (None, None)
    # a paper whose Soort only begins with the words is no bill
    assert dossier_kind([], ["Voorstel van wetenschap"]) == (None, None)


# ── phases ────────────────────────────────────────────────────────────────────


def test_the_phases_are_the_curated_list_in_its_order() -> None:
    names = [p.name for p in PHASES]
    assert names == list(LISTS["phases"].entries())
    assert (names[0], names[-1]) == ("Voorstel van wet", "Eindtekst")
    assert not [p for p in problems() if p.startswith("phases: ")]


def test_a_phase_is_done_only_when_a_record_of_the_kamer_marks_it() -> None:
    phases = dossier_phases(
        "Wetgeving",
        [
            _doc("Voorstel van wet", "2024-01-10"),
            _doc("Memorie van toelichting", "2024-01-10"),
            _doc("Verslag (initiatief)wetsvoorstel (nader)", "2024-03-01"),
            # a report of a debate is no Verslag of the bill
            _doc("Verslag van een commissiedebat", "2024-02-01"),
        ],
        [],
        [],
    )
    assert _done(phases) == ["Voorstel van wet", "Memorie van toelichting", "Verslag"]
    assert [p["name"] for p in phases or []] == [p.name for p in PHASES]
    advice = next(p for p in phases or [] if p["name"] == "Advies Raad van State")
    assert advice == {"name": "Advies Raad van State", "done": False, "date": None}


def test_a_phase_takes_its_first_date() -> None:
    phases = dossier_phases(
        "Wetgeving",
        [_doc("Amendement", "2024-05-02"), _doc("Nota van wijziging", "2024-04-01")],
        [],
        [],
    )
    name = "Nota van wijziging / Amendement"
    phase = next(p for p in phases or [] if p["name"] == name)
    assert phase == {"name": name, "done": True, "date": "2024-04-01"}


def test_the_decisions_on_the_bill_itself_mark_the_stemmingen() -> None:
    motion = {"decision_kind": "Stemmen - aangenomen", "case_kind": "Motie"}
    postponed = {"decision_kind": "Stemmen - uitstellen", "case_kind": "Wetgeving"}
    assert _done(dossier_phases("Wetgeving", [], [], [motion, postponed])) == []
    hamerstuk = {
        "decision_kind": "Stemmen - zonder stemming aannemen",
        "case_kind": "Wetgeving",
        "date": "2024-06-25",
    }
    assert _done(dossier_phases("Wetgeving", [], [], [hamerstuk])) == ["Stemmingen"]


def test_an_activity_marks_a_phase_only_when_it_took_place() -> None:
    held = {"kind": "Hamerstukken", "date": "2024-06-25", "status": "Uitgevoerd"}
    planned = {**held, "status": "Gepland"}
    assert _done(dossier_phases("Wetgeving", [], [held], [])) == ["Stemmingen"]
    assert _done(dossier_phases("Wetgeving", [], [planned], [])) == []


@pytest.mark.parametrize(
    "kind", ["Verdrag", "Initiatiefnota", "PKB/Structuurvisie", None]
)
def test_only_a_bill_has_phases(kind: str | None) -> None:
    assert kind not in LEGISLATIVE_KINDS
    assert (
        dossier_phases(kind, [_doc("Voorstel van wet", "2024-01-01")], [], []) is None
    )


def test_the_current_phase_is_the_done_one_with_the_latest_date() -> None:
    phases = dossier_phases(
        "Begroting",
        [
            _doc("Voorstel van wet", "2024-09-17"),
            _doc("Memorie van toelichting", "2024-09-17"),
            _doc("Amendement", "2024-11-01"),
        ],
        [],
        [],
    )
    assert current_phase(phases) == "Nota van wijziging / Amendement"
    # on one day, the later in the order
    assert current_phase((phases or [])[:2]) == "Memorie van toelichting"
    assert current_phase(None) is None
    assert current_phase(dossier_phases("Wetgeving", [], [], [])) is None


def test_phase_props_records_kind_and_phases() -> None:
    props = phase_props(["Wetgeving"], [_doc("Voorstel van wet", "2024-01-01")], [], [])
    assert (props["kind"], props["kind_basis"], props["current_phase"]) == (
        "Wetgeving",
        "case",
        "Voorstel van wet",
    )
    assert phase_props([], [_doc("Motie")], [], []) == {
        "kind": None,
        "kind_basis": None,
        "phases": None,
        "current_phase": None,
    }


# ── title ─────────────────────────────────────────────────────────────────────


def test_a_stored_title_is_kept() -> None:
    assert select_title({"title": "Wet X", "number": "36000"}, []) == (
        "Wet X",
        "dossier",
    )


def test_a_title_equal_to_the_dossier_number_is_a_placeholder() -> None:
    docs = [
        _doc("Motie", title="Motie over X"),
        _doc("Memorie van toelichting", title="MvT titel"),
    ]

    assert select_title({"title": "36000", "number": "36000"}, docs) == (
        "MvT titel",
        "document",
    )


def test_title_preference_is_bill_then_mvt_then_any_document() -> None:
    docs = [
        _doc("Motie", title="Motie"),
        _doc("Memorie van toelichting", title="MvT"),
        _doc("Voorstel van wet", title="Bill"),
    ]

    assert select_title({}, docs) == ("Bill", "document")
    assert select_title({}, docs[:2]) == ("MvT", "document")
    assert select_title({}, docs[:1]) == ("Motie", "document")
    assert select_title({}, []) == (None, None)


def test_display_name_includes_the_toevoeging() -> None:
    assert dossier_display_name("36554", "I", "Wet") == "Kamerstukdossier 36554-I: Wet"
    assert dossier_display_name("36554", None, "Wet") == "Kamerstukdossier 36554: Wet"


# ── outcome ───────────────────────────────────────────────────────────────────


def test_a_published_law_closes_its_dossier_on_the_first_publication() -> None:
    outcome = derive_outcome(
        [
            {"date_published": "2024-07-01", "date_signed": "2024-06-20"},
            {"date_published": "2024-05-01"},
        ],
        [],
    )
    assert outcome == DossierOutcome(True, "aangenomen", "2024-05-01")


def test_a_law_legislated_by_a_regulation_alone_has_no_closing_date() -> None:
    assert derive_outcome([{}], []) == DossierOutcome(True, "aangenomen", None)


def test_the_last_vote_on_the_bill_decides_a_rejection() -> None:
    passed = {"date": "2024-03-01", "passed": True}
    rejected = {"date": "2024-04-01", "passed": False}
    outcome = derive_outcome([], [passed, rejected])
    assert (outcome.closed, outcome.outcome, outcome.closed_on) == (
        True,
        "verworpen",
        "2024-04-01",
    )
    assert (
        derive_outcome([], [{**passed, "date": "2024-05-01"}, rejected]).closed is False
    )


def test_a_bill_without_publication_or_rejection_is_open() -> None:
    assert derive_outcome([], []) == DossierOutcome(False)
    # a postponement is no vote, and no withdrawal is read from anything
    postponed = {
        "date": "2024-04-01",
        "passed": None,
        "decision_kind": "Stemmen - uitstellen",
    }
    assert derive_outcome([], [postponed]).closed is False


def test_the_last_decision_of_the_kamer_is_kept_as_it_writes_it() -> None:
    decisions = [
        {"date": "2024-06-18", "decision_kind": "Stemmen - uitstellen"},
        {
            "date": "2024-06-25",
            "decision_kind": "Stemmen - zonder stemming aannemen",
            "decision_text": "Wetsvoorstel zonder stemming aangenomen.",
        },
        {"date": "2024-07-01", "passed": True},  # no BesluitSoort
    ]
    decision = {
        "kind": "Stemmen - zonder stemming aannemen",
        "text": "Wetsvoorstel zonder stemming aangenomen.",
        "date": "2024-06-25",
    }
    assert last_decision(decisions) == decision
    assert derive_outcome([], decisions).tk_decision == decision
    assert last_decision([]) is None


def test_outcome_props_records_the_outcome() -> None:
    outcome = DossierOutcome(True, "aangenomen", "2024-05-01", {"kind": "k"})
    assert outcome_props(outcome) == {
        "closed": True,
        "outcome": "aangenomen",
        "closed_on": "2024-05-01",
        "tk_decision": {"kind": "k"},
    }
