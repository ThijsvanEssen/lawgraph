"""Dossier stage and title derivation — one implementation for API and pipeline."""

from __future__ import annotations

import pytest

from lawgraph.core.dossier_stages import (
    OPEN,
    DossierOutcome,
    accumulate_stage_signals,
    classify_activity_kind,
    classify_document_kind,
    classify_track_kind,
    derive_outcome,
    dossier_display_name,
    dossier_stages,
    is_withdrawal_letter,
    outcome_props,
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
        # What is filed under a dossier does not make it a motion or a letter.
        (["Brief regering", "Motie"], [], "overig"),
        (["Brief regering"], [], "overig"),
        ([], [], None),
    ],
)
def test_the_track_follows_the_dossiers_own_cases_and_documents(
    case_kinds: list[str], document_kinds: list[str], track: str | None
) -> None:
    assert classify_track_kind(case_kinds, document_kinds=document_kinds) == track


@pytest.mark.parametrize(
    ("title", "track"),
    [
        # 37020: the motions of the Algemene Politieke Beschouwingen are filed under it
        ("Nota over de toestand van ’s Rijks Financiën", "nota"),
        ("Voorjaarsnota 2026", "nota"),
        ("Najaarsnota 2025", "nota"),
        ("Financieel Jaarverslag van het Rijk 2025", "nota"),
        ("Defensienota 2024 - Sterk, slim en samen", "nota"),
        ("Homogene Groep Internationale samenwerking 2027 (HGIS-nota 2027)", "nota"),
        # a bill or a budget whose title names a nota is a bill or a budget
        (
            "Wijziging van de begrotingsstaten van het Ministerie van Financiën (IXB) voor "
            "het jaar 2026 (wijziging samenhangende met de Voorjaarsnota)",
            "begroting",
        ),
        ("Jaarverslag en slotwet Ministerie van Defensie 2007", "begroting"),
        ("Initiatiefnota van het lid Omtzigt over goed bestuur", "initiatiefnota"),
        # the letters and motions of a policy area or an EU Council series
        ("Raad Algemene Zaken en Raad Buitenlandse Zaken", "overig"),
        ("Jeugdzorg", "overig"),
        ("Planologische Kernbeslissing Nota Mobiliteit", "overig"),
        ("Jaarverslag van de Nationale ombudsman over 2015", "overig"),
    ],
)
def test_the_track_of_a_dossier_that_is_no_bill_comes_from_its_title(
    title: str, track: str
) -> None:
    assert classify_track_kind(["Brief regering", "Motie"], title=title) == track


def _stages(track: str, docs, case_kinds, closed: bool) -> tuple:
    found = dossier_stages(track, docs, [], [], case_kinds, closed=closed)
    return found.current, found.present


def test_a_dossier_that_is_no_bill_has_no_stage_until_it_is_closed() -> None:
    docs = [_doc("Motie", "2026-01-01"), _doc("Verslag", "2026-02-01")]

    assert _stages("overig", docs, ["Motie"], closed=False) == (None, [])
    assert _stages("nota", docs, ["Motie"], closed=False) == (None, [])
    assert _stages("initiatiefnota", docs, [], closed=True) == (
        "afgehandeld",
        ["afgehandeld"],
    )
    assert _stages("begroting", docs, [], closed=False) == (
        "verslag",
        ["behandeling", "verslag"],
    )


def _passed_bill() -> list[dict]:
    return [
        _doc("Voorstel van wet", "2024-01-01"),
        _doc("Memorie van toelichting", "2024-01-01"),
        _doc("Advies Afdeling advisering Raad van State", "2024-01-01"),
        _doc("Verslag", "2024-03-01"),
    ]


def test_a_bill_with_a_paper_for_every_stage_it_passed_is_complete() -> None:
    found = dossier_stages(
        "wetsvoorstel",
        _passed_bill(),
        [],
        [{"date": "2024-06-01", "passed": True}],
        ["Wetgeving"],
        closed=True,
        outcome="aangenomen",
    )
    assert found.current == "afgehandeld"
    assert found.complete is True


def test_an_adopted_bill_without_its_memorandum_or_vote_is_incomplete() -> None:
    # 36264 in a test database: the bill, a nota and amendments known only from the kinds
    # of its cases, and its law published.
    docs = [_doc("Voorstel van wet", "2022-12-21")]
    cases = ["Wetgeving", "Nota n.a.v. het verslag", "Amendement"]
    found = dossier_stages(
        "wetsvoorstel", docs, [], [], cases, closed=True, outcome="aangenomen"
    )
    assert found.present == [
        "nota_naar_aanleiding_van_verslag",
        "amendementen",
        "wetsvoorstel",
        "afgehandeld",
    ]
    assert found.complete is False

    everything = dossier_stages(
        "wetsvoorstel",
        [
            *_passed_bill(),
            _doc("Nota n.a.v. het verslag", "2024-04-01"),
            _doc("Amendement", "2024-05-01"),
        ],
        [],
        [{"date": "2024-06-01", "passed": True}],
        cases,
        closed=True,
        outcome="aangenomen",
    )
    assert everything.complete is True


def test_a_withdrawn_bill_needs_no_vote() -> None:
    found = dossier_stages(
        "wetsvoorstel", _passed_bill(), [], [], [], closed=True, outcome="ingetrokken"
    )
    assert found.complete is True


def test_a_bill_under_way_needs_the_stages_up_to_its_current_one() -> None:
    docs = [_doc("Voorstel van wet", "2024-01-01"), _doc("Verslag", "2024-03-01")]
    found = dossier_stages("wetsvoorstel", docs, [], [], [], closed=False)
    assert found.current == "verslag"
    assert found.complete is False  # no memorandum, no advice
    assert dossier_stages(
        "wetsvoorstel", _passed_bill(), [], [], [], closed=False
    ).complete


def test_an_activity_that_did_not_take_place_marks_no_stage() -> None:
    docs = _passed_bill()
    held = {
        "kind": "Plenair debat (wetgeving)",
        "date": "2024-05-01",
        "status": "Uitgevoerd",
    }
    for status in ("Gepland", "Geannuleerd", "Verplaatst", "Vervallen"):
        found = dossier_stages(
            "wetsvoorstel", docs, [{**held, "status": status}], [], [], closed=False
        )
        assert "behandeling" not in found.present, status
    assert (
        "behandeling"
        in dossier_stages("wetsvoorstel", docs, [held], [], [], closed=False).present
    )


def test_a_dossier_that_is_no_bill_is_complete() -> None:
    assert dossier_stages("overig", [], [], [], ["Motie"], closed=True).complete


# ── how a dossier ended ──────────────────────────────────────────────────────


def _letter(subject: str, kind: str = "Brief regering", case_kinds=None) -> dict:
    return {
        "kind": kind,
        "subject": subject,
        "date": "2025-06-02",
        "case_kinds": ["Wetgeving", kind] if case_kinds is None else case_kinds,
    }


def _vote(date: str, passed: bool) -> dict:
    return {"date": date, "passed": passed}


def test_a_published_law_closes_its_dossier_on_the_first_publication() -> None:
    outcome = derive_outcome(
        [
            {"date_published": "2018-05-16", "date_signed": "2018-05-16"},
            {"date_published": None, "date_signed": "2018-05-09"},
            {},  # a regulation that names the dossier, without publication dates
        ],
        [],
        [_vote("2018-03-13", True)],
    )
    assert outcome == DossierOutcome(True, "aangenomen", "2018-05-09")


def test_a_law_legislated_by_a_regulation_alone_has_no_closing_date() -> None:
    assert derive_outcome([{}], [], []) == DossierOutcome(True, "aangenomen", None)


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        ("Brief houdende intrekking van het wetsvoorstel", "Brief regering"),
        ("Brief houdende intrekking van het voorstel", "Brief lid / fractie"),
        (
            "Brief houdende overname en intrekking van het wetsvoorstel",
            "Brief lid / fractie",
        ),
        (
            "Brief van het lid Becker houdende overname van de verdediging en intrekking "
            "van het initiatiefvoorstel",
            "Brief lid / fractie",
        ),
        (
            "Intrekking wetsvoorstel wijziging van de Algemene Ouderdomswet",
            "Brief regering",
        ),
    ],
)
def test_a_letter_that_withdraws_the_bill_closes_the_dossier(
    subject: str, kind: str
) -> None:
    outcome = derive_outcome([], [_letter(subject, kind)], [_vote("2025-01-01", True)])
    assert outcome == DossierOutcome(True, "ingetrokken", "2025-06-02")


@pytest.mark.parametrize(
    "letter",
    [
        _letter("Voornemen tot intrekken van het wetsvoorstel"),
        _letter("Herroeping aankondiging intrekking wetsvoorstel bevoorrechting"),
        _letter("Brief houdende verzoek tot intrekking van het wetsvoorstel"),
        _letter("Beweegredenen voor het niet intrekken van het wetsvoorstel"),
        # a bill that repeals a law is not withdrawn
        _letter(
            "Brief over het voorstel tot intrekking van de Wet op de lijkbezorging"
        ),
        # a letter of a committee, and a letter on another case than the bill
        _letter(
            "Intrekking wetsvoorstel Wet ruimte",
            kind="Brief commissie aan bewindspersoon",
        ),
        _letter("Intrekking wetsvoorstel 35722", case_kinds=["Brief regering"]),
        # a motion that asks for it
        _letter("Motie over het intrekken van het wetsvoorstel", kind="Motie"),
    ],
)
def test_a_letter_about_a_withdrawal_does_not_withdraw(letter: dict) -> None:
    assert not is_withdrawal_letter(letter)
    assert derive_outcome([], [letter], []) == OPEN


def test_the_last_vote_on_the_bill_decides_a_rejection() -> None:
    rejected = derive_outcome(
        [], [], [_vote("2024-01-10", True), _vote("2024-02-20", False)]
    )
    assert rejected == DossierOutcome(True, "verworpen", "2024-02-20")
    # Passed by the Tweede Kamer: it waits for the Eerste Kamer and the Staatsblad.
    assert derive_outcome([], [], [_vote("2024-02-20", True)]) == OPEN


def test_a_dossier_without_evidence_is_open() -> None:
    assert derive_outcome([], [], []) == OPEN


def test_closing_a_dossier_recomputes_its_stages() -> None:
    # 35786 in a test database: open, the stages up to ``behandeling`` complete; closed as
    # aangenomen, it passed ``stemming`` too, and no vote is on record.
    docs = [*_passed_bill(), _doc("Motie", "2024-05-01")]
    open_ = dossier_stages("wetsvoorstel", docs, [], [], [], closed=False)
    assert (open_.current, open_.complete) == ("behandeling", True)

    enacted = DossierOutcome(True, "aangenomen", "2022-08-30")
    stages = dossier_stages(
        "wetsvoorstel", docs, [], [], [], closed=True, outcome=enacted.outcome
    )
    assert outcome_props(enacted, stages) == {
        "closed": True,
        "outcome": "aangenomen",
        "closed_on": "2022-08-30",
        "current_stage": "afgehandeld",
        "stages_present": [
            "wetsvoorstel",
            "mvt",
            "advies_rvs",
            "verslag",
            "behandeling",
            "afgehandeld",
        ],
        "stages_complete": False,
        "stages_missing": ["stemming"],
    }

    reopened = dossier_stages("wetsvoorstel", docs, [], [], [], closed=False)
    assert outcome_props(OPEN, reopened) == {
        "closed": False,
        "outcome": None,
        "closed_on": None,
        "current_stage": "behandeling",
        "stages_present": [
            "wetsvoorstel",
            "mvt",
            "advies_rvs",
            "verslag",
            "behandeling",
        ],
        "stages_complete": True,
        "stages_missing": [],
    }


# ── the stages a track requires ──────────────────────────────────────────────


def test_a_treaty_needs_the_advice_but_no_bill_memorandum_or_vote() -> None:
    # 37013 in a test database: submitted for tacit approval with a letter and the advice.
    docs = [
        _doc("Brief regering", "2026-08-25"),
        _doc(
            "Advies Afdeling advisering Raad van State en Nader rapport", "2026-08-25"
        ),
    ]
    found = dossier_stages("verdrag", docs, [], [], ["Verdrag"], closed=False)
    assert (found.current, found.missing) == ("advies_rvs", [])
    approved = dossier_stages(
        "verdrag", docs, [], [], ["Verdrag"], closed=True, outcome="aangenomen"
    )
    assert approved.complete
    without_advice = [_doc("Motie", "2026-09-01"), docs[0]]
    assert dossier_stages(
        "verdrag", without_advice, [], [], [], closed=False
    ).missing == ["advies_rvs"]


def test_a_budget_needs_no_advice_of_the_raad_van_state() -> None:
    docs = [
        _doc("Voorstel van wet", "2026-06-01"),
        _doc("Memorie van toelichting", "2026-06-01"),
        _doc("Verslag", "2026-06-20"),
    ]
    assert dossier_stages("begroting", docs, [], [], [], closed=False).complete
    found = dossier_stages("wetsvoorstel", docs, [], [], [], closed=False)
    assert found.missing == ["advies_rvs"]
    assert dossier_stages("begroting", docs[:1], [], [], [], closed=False).missing == []
    assert dossier_stages(
        "begroting", [docs[0], docs[2]], [], [], [], closed=False
    ).missing == ["mvt"]


def test_the_text_as_adopted_counts_as_the_vote() -> None:
    assert classify_document_kind("Eindtekst") == "stemming"
    # 34851 in a test database: a hamerstuk, no vote on record, its adopted text is.
    docs = [*_passed_bill(), _doc("Eindtekst", "2018-03-13")]
    found = dossier_stages(
        "wetsvoorstel", docs, [], [], [], closed=True, outcome="aangenomen"
    )
    assert found.missing == []
    found = dossier_stages(
        "wetsvoorstel", _passed_bill(), [], [], [], closed=True, outcome="aangenomen"
    )
    assert found.missing == ["stemming"]


def test_the_missing_stages_are_in_stage_order() -> None:
    docs = [_doc("Amendement", "2024-05-01")]
    found = dossier_stages(
        "wetsvoorstel", docs, [], [], ["Wetgeving"], closed=True, outcome="verworpen"
    )
    assert found.missing == ["wetsvoorstel", "mvt", "advies_rvs", "stemming"]
    assert not found.complete
