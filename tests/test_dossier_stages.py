"""Dossier stage and title derivation — one implementation for API and pipeline."""

from __future__ import annotations

import pytest

from lawgraph.core.dossier_stages import (
    accumulate_stage_signals,
    classify_activity_kind,
    classify_document_kind,
    classify_track_kind,
    dossier_display_name,
    dossier_stages,
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


@pytest.mark.parametrize(
    ("kind", "stage"),
    [
        ("Verslag", "verslag"),
        ("Verslag (initiatief)wetsvoorstel (nader)", "verslag"),
        (
            "Nota n.a.v. het (nader/tweede nader/enz.) verslag",
            "nota_naar_aanleiding_van_verslag",
        ),
        ("Nota van wijziging", "amendementen"),
        ("Motie (gewijzigd/nader)", "behandeling"),
        ("Nader rapport", "advies_rvs"),
        # Reports of a meeting, a policy memo and the minutes of a procedure meeting
        # say nothing about where a bill stands.
        ("Verslag van een commissiedebat", None),
        ("Inbreng verslag schriftelijk overleg", None),
        ("Jaarverslag", None),
        ("Initiatiefnota", None),
        ("Nota van toelichting", None),
        ("Besluitenlijst procedurevergadering", None),
    ],
)
def test_a_document_kind_marks_a_stage_of_a_bill_or_none(
    kind: str, stage: str | None
) -> None:
    assert classify_document_kind(kind) == stage


def test_a_debate_on_a_bill_is_its_treatment_not_its_start() -> None:
    assert classify_activity_kind("Plenair debat (wetgeving)") == "behandeling"
    assert classify_activity_kind("Notaoverleg") is None
    assert classify_activity_kind("Stemmingen") == "stemming"


@pytest.mark.parametrize(
    ("case_kinds", "document_kinds", "track"),
    [
        (["Begroting", "Brief regering", "Motie"], [], "begroting"),
        (["Initiatiefnota"], [], "initiatiefnota"),
        (["Verdrag"], [], "verdrag"),
        (["Wetgeving", "Motie"], [], "wetsvoorstel"),
        ([], ["Voorstel van wet (initiatiefvoorstel)"], "initiatiefwetsvoorstel"),
        ([], ["Voorstel van wet"], "wetsvoorstel"),
        (["Brief regering", "Motie"], [], "motie"),
        (["Brief regering"], [], "overig"),
        ([], [], None),
    ],
)
def test_the_track_follows_the_dossiers_own_cases_and_documents(
    case_kinds: list[str], document_kinds: list[str], track: str | None
) -> None:
    assert classify_track_kind(case_kinds, document_kinds=document_kinds) == track


def test_a_dossier_that_is_no_bill_has_no_stage_until_it_is_closed() -> None:
    docs = [_doc("Motie", "2026-01-01"), _doc("Verslag", "2026-02-01")]

    assert dossier_stages("motie", docs, [], [], ["Motie"], closed=False) == (None, [])
    assert dossier_stages("initiatiefnota", docs, [], [], [], closed=True) == (
        "afgehandeld",
        ["afgehandeld"],
    )
    assert dossier_stages("begroting", docs, [], [], [], closed=False) == (
        "verslag",
        ["behandeling", "verslag"],
    )
