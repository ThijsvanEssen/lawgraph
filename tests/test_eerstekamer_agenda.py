"""The agendas of the Eerste Kamer, read from pages of eerstekamer.nl as they were served on
2026-10-03 (``<title>`` and ``<main>`` only)."""

from __future__ import annotations

from lawgraph.core import eerstekamer_agenda as ea
from tests.paths import fixture_text


def test_a_plenary_sitting_block_by_block() -> None:
    sitting = ea.plenary(
        "/plenaire_vergadering/20261006", fixture_text("ek_plenary_20261006.html")
    )
    assert sitting.date == "2026-10-06"
    assert (sitting.earlier, sitting.later) == (
        "/plenaire_vergadering/20260929",
        "/plenaire_vergadering/20261013",
    )
    assert len(sitting.items) == 12
    assert sitting.items[0] == ea.AgendaItem("vn1cmihorywj", "09.30-09.30", "Opening")
    hammer = sitting.items[4]
    assert (hammer.time, hammer.title) == ("13.30-13.35", "Hamerstukken")
    # the bills and the note it is about, by the number each names
    assert hammer.dossiers == ["36920", "36932", "36937", "36939", "36952"]
    assert sitting.items[2].dossiers == ["37020"]


def test_a_day_of_committee_meetings_with_its_decision_points() -> None:
    day = ea.committee_day(fixture_text("ek_committee_day_20260929.html"))
    assert len(day.meetings) == 11
    assert day.later == "/commissievergaderingen_op?key=vn1hx0000000"
    joint = next(m for m in day.meetings if m.path.endswith("_lnv_en_vws"))
    assert (joint.date, joint.time) == ("2026-09-29", "14.15 uur")
    assert "(LNV)" in joint.committees and "(VWS)" in joint.committees
    (point,) = joint.points
    assert (point.number, point.reference) == ("1.", "28.973 / 29.683 / 32.793, AA")
    assert point.dossiers == ["28973", "29683", "32793"]
    assert point.subject and point.subject.startswith("Verslag van een schriftelijk")
    # the decision as the committee words it, kept, not read
    assert point.decision and point.decision.startswith("De commissies besluiten")


def test_a_meeting_has_its_kind_when_the_agenda_gives_one() -> None:
    (meeting,) = ea.committee_day(
        fixture_text("ek_committee_day_20261005.html")
    ).meetings
    assert (meeting.kind, meeting.time, meeting.points) == (
        "mondeling overleg",
        "18.30 uur",
        [],
    )


def test_a_reference_names_its_dossiers() -> None:
    assert ea.reference_dossiers("36.889") == ["36889"]
    assert ea.reference_dossiers("36.945 XXII, A") == ["36945-XXII"]
    assert ea.reference_dossiers("28.973 / 29.683 / 32.793, AA") == [
        "28973",
        "29683",
        "32793",
    ]


def test_a_reference_names_no_dossier_for_what_is_no_dossier_number() -> None:
    assert ea.reference_dossiers("Brief regering / 36.600 VII, B") == ["36600-VII"]
    assert ea.reference_dossiers("E260009 - 36.954, D") == ["36954"]
    assert ea.reference_dossiers("E250028") == []
    assert ea.reference_dossiers("COM(2026)660") == []
    assert ea.reference_dossiers("Rondvraag") == []
    assert ea.reference_dossiers("Gespreksverzoek premier Aruba, dhr. Mike Eman") == []


def test_a_rijkswet_on_the_agenda_names_its_dossier() -> None:
    page = (
        '<div id="b1"><div class="agendablok"><h3>13.30 - 13.35 uur Hamerstukken</h3>'
        '<div class="zaken"><a href="/wetsvoorstel/36455_rijkswet" class="grid-x">'
        "Rijkswet Caribisch orgaan (36.455 (R2188))</a></div></div></div></div>"
    )
    (item,) = ea.plenary("/plenaire_vergadering/20261006", page).items
    assert item.dossiers == ["36455-(R2188)"]
