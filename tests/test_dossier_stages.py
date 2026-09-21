"""Dossier stage and title derivation — one implementation for API and pipeline."""

from __future__ import annotations

from lawgraph.core.dossier_stages import (
    accumulate_stage_signals,
    dossier_display_name,
    pick_current_stage,
    select_title,
)


def _doc(kind: str, date: str | None = None, title: str | None = None) -> dict:
    return {"kind": kind, "date": date, "title": title}


def test_stages_are_ordered_chronologically_and_latest_is_current() -> None:
    signals = accumulate_stage_signals(
        docs=[
            _doc("Voorstel van wet", "2020-01-01"),
            _doc("Memorie van toelichting", "2020-01-05"),
            _doc("Verslag", "2020-03-01"),
        ],
        activities=[],
        decisions=[],
        case_kinds=[],
    )

    fase, stages = pick_current_stage(signals, closed=False)

    assert stages == ["wetsvoorstel", "mvt", "verslag"]
    assert fase == "verslag"


def test_a_vote_implies_the_stemming_stage_with_its_dates() -> None:
    signals = accumulate_stage_signals(
        docs=[_doc("Voorstel van wet", "2020-01-01")],
        activities=[],
        decisions=[{"date": "2020-06-01"}, {"date": "2020-05-01"}],
        case_kinds=[],
    )

    assert signals.first["stemming"] == "2020-05-01"
    assert signals.last["stemming"] == "2020-06-01"
    assert pick_current_stage(signals, closed=False)[0] == "stemming"


def test_zaak_roll_up_counts_without_a_date() -> None:
    signals = accumulate_stage_signals([], [], [], ["Wetgeving"])

    assert signals.any_signal and signals.first == {"wetsvoorstel": ""}


def test_a_closed_dossier_is_afgehandeld_and_gets_that_stage_once() -> None:
    signals = accumulate_stage_signals([_doc("Verslag", "2020-01-01")], [], [], [])

    fase, stages = pick_current_stage(signals, closed=True)

    assert (fase, stages) == ("afgehandeld", ["verslag", "afgehandeld"])


def test_no_evidence_gives_no_stage_and_leaves_the_fallback_to_the_caller() -> None:
    signals = accumulate_stage_signals([_doc("Onbekende soort")], [], [], [])

    assert pick_current_stage(signals, closed=False) == (None, [])


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
