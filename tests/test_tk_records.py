"""Reading a TK OData payload yields the props the graph stores."""

from __future__ import annotations

import pytest

from lawgraph.core.models import make_node_key
from lawgraph.core.tk_records import (
    activities,
    actors,
    cases,
    commitments,
    committees,
    decisions,
    documents,
    dossiers,
    factions,
    members,
    seats,
)
from tests.optional import present


def test_committee_reads_name_abbreviation_and_slug() -> None:
    key, props = present(
        committees.committee(
            {
                "Id": "c-1",
                "NaamNL": "Vaste commissie voor Financiën",
                "Afkorting": "FIN",
            }
        )
    )
    assert key == "c_1"
    assert props["name"] == "Vaste commissie voor Financiën"
    assert props["abbreviation"] == "FIN"
    assert props["slug"] == "fin"


def test_committee_without_an_id_is_skipped() -> None:
    assert committees.committee({"NaamNL": "Naamloos"}) is None


def test_committee_without_a_name_is_not_named_by_its_id() -> None:
    # the record the voortouw of every plenary activity names: nothing but an id
    record = {"Id": "38aacfcd-2cfa-4727-949d-e4270237dbbe", "NaamNL": None}
    assert committees.committee(record) is None


def test_committee_seats_collect_every_seat_per_person() -> None:
    held = committees.committee_seats(
        {
            "CommissieZetel": [
                {
                    "CommissieZetelVastPersoon": [
                        {
                            "Persoon_Id": "p1",
                            "Van": "2020-01-01",
                            "TotEnMet": "2021-01-01",
                            "Functie": "Lid",
                        },
                        {
                            "Persoon_Id": "p1",
                            "Van": "2022-01-01",
                            "TotEnMet": None,
                            "Functie": "Voorzitter",
                        },
                        {"Persoon_Id": "p2", "Van": "2019-01-01", "TotEnMet": None},
                        {"Persoon_Id": "p3", "Van": "2019-01-01", "Verwijderd": True},
                    ],
                    "CommissieZetelVervangerPersoon": [
                        {"Persoon_Id": "p2", "Van": "2018-01-01", "Functie": "Plv. lid"}
                    ],
                }
            ]
        }
    )
    Seat = committees.CommitteeSeat
    assert held["p1"] == [
        Seat("2020-01-01", "2021-01-01", "Lid"),
        Seat("2022-01-01", None, "Voorzitter"),
    ]
    assert held["p2"] == [
        Seat("2019-01-01", None),
        Seat("2018-01-01", None, "PlvLid", substitute=True),
    ]
    # a seat the Kamer deleted is none
    assert "p3" not in held


@pytest.mark.parametrize(
    ("functie", "role"),
    [
        ("Plv. lid", "PlvLid"),
        ("PlvLid", "PlvLid"),
        ("OnderVz", "OnderVz"),
        ("Lid", "Lid"),
        ("Voorzitter", "Voorzitter"),
        ("", None),
        (None, None),
    ],
)
def test_a_seat_role_has_one_spelling(functie: str | None, role: str | None) -> None:
    # the Kamer wrote "Plv. lid" on older seats and writes "PlvLid" now
    assert committees.seat_role(functie) == role


def test_representative_period_prefers_an_open_one_with_its_role() -> None:
    Seat = committees.CommitteeSeat
    meta = committees.representative_period(
        [
            Seat("2020-01-01", "2021-01-01", "Lid"),
            Seat("2022-01-01", None, "Voorzitter"),
        ]
    )
    assert meta == {
        "from_date": "2022-01-01",
        "role": "Voorzitter",
        "periods": [
            {"from_date": "2020-01-01", "to_date": "2021-01-01", "role": "Lid"},
            {"from_date": "2022-01-01", "role": "Voorzitter"},
        ],
    }


def test_representative_period_takes_the_latest_closed_one() -> None:
    Seat = committees.CommitteeSeat
    meta = committees.representative_period(
        [Seat("2015-01-01", "2016-01-01"), Seat("2019-01-01", "2020-01-01")]
    )
    assert meta["from_date"] == "2019-01-01" and meta["to_date"] == "2020-01-01"
    # one seat without a role: no periods
    assert committees.representative_period([Seat("2019-01-01", None)]) == {
        "from_date": "2019-01-01"
    }


def test_a_members_seat_represents_before_a_substitutes() -> None:
    Seat = committees.CommitteeSeat
    meta = committees.representative_period(
        [Seat("2018-01-01", None, "Lid"), Seat("2023-01-01", None, "Plv. lid", True)]
    )
    assert (meta["role"], meta.get("substitute")) == ("Lid", None)


def test_member_joins_the_name_parts() -> None:
    _, props = present(
        members.member(
            {
                "Id": "p-1",
                "Voornamen": "Mark",
                "Tussenvoegsel": "van der",
                "Achternaam": "Berg",
            }
        )
    )
    assert props["name"] == "Mark van der Berg"
    assert props["display_name"] == "Mark van der Berg"
    # the parts as the Kamer gives them, for a list by surname: Berg, van der
    assert (props["family_name"], props["name_prefix"]) == ("Berg", "van der")
    # Party is not read here: it comes from the dated seat timeline.
    assert "party" not in props


def test_a_member_of_old_is_named_by_initials_and_surname() -> None:
    _, props = present(
        members.member({"Id": "p-1", "Initialen": "WB", "Achternaam": "Buma"})
    )
    assert (props["name"], props["full_name"]) == ("W.B. Buma", "W.B. Buma")
    _, props = present(
        members.member({"Id": "p-2", "Initialen": "S.", "Achternaam": "Dekker"})
    )
    assert props["name"] == "S. Dekker"


def test_an_ended_faction_has_no_seats() -> None:
    record = {
        "Id": "f-1",
        "Afkorting": "Nieuw Sociaal Contract",
        "DatumActief": "2023-12-05",
        "DatumInactief": "2025-11-11",
        "AantalZetels": 19,
    }
    _, props = present(factions.faction(record, []))
    assert (props["active"], props["seats"]) == (False, 0)
    _, props = present(factions.faction({**record, "DatumInactief": None}, []))
    assert props["seats"] == 19


def test_seat_holding_reads_the_period_and_the_faction() -> None:
    assert seats.seat_holding(
        {
            "Persoon_Id": "p1",
            "FractieZetel": {"Fractie_Id": "f1"},
            "Van": "2021-03-31T00:00:00",
            "TotEnMet": None,
            "Functie": "Lid",
        }
    ) == ("p1", "f1", {"from_date": "2021-03-31", "to_date": None, "role": "Lid"})


def test_seat_holding_without_a_faction_is_skipped() -> None:
    assert seats.seat_holding({"Persoon_Id": "p1", "FractieZetel": {}}) is None


def test_faction_aliases_are_its_names_and_those_of_its_votes() -> None:
    payload = {
        "Afkorting": "Nieuw Sociaal Contract",
        "NaamNL": "Nieuw Sociaal Contract",
    }
    assert factions.faction_aliases(payload, {"NSC"}) == [
        "NSC",
        "Nieuw Sociaal Contract",
    ]


def test_a_faction_whose_afkorting_is_its_name_goes_by_the_acronym_its_votes_use() -> (
    None
):
    payload = {
        "Id": "f-nsc",
        "Afkorting": "Nieuw Sociaal Contract",
        "NaamNL": "Nieuw Sociaal Contract",
    }
    parsed = factions.faction(payload, factions.faction_aliases(payload, {"NSC"}))
    assert parsed is not None
    key, props = parsed
    assert key == "nieuw_sociaal_contract"
    assert props["abbreviation"] == "NSC"
    assert props["display_name"] == "NSC"
    assert props["name"] == "Nieuw Sociaal Contract"


def test_a_faction_keeps_its_afkorting_without_an_acronym_its_votes_use() -> None:
    # Groep Lazrak: "GL" is what GroenLinks votes as, no name its own votes give it
    payload = {"Afkorting": "Groep Lazrak", "NaamNL": "Groep Lazrak"}
    assert factions.short_name(payload, ["Groep Lazrak"]) == "Groep Lazrak"
    # an Afkorting of its own stays, whatever its votes say
    payload = {"Afkorting": "PvdD", "NaamNL": "Partij voor de Dieren"}
    assert factions.short_name(payload, ["PvdD", "PVDD"]) == "PvdD"


def test_faction_is_current_prefers_a_seated_record() -> None:
    seated = {"DatumInactief": None, "GewijzigdOp": "2020-01-01"}
    dissolved = {"DatumInactief": "2021-01-01", "GewijzigdOp": "2025-01-01"}
    assert factions.faction_is_current(seated) > factions.faction_is_current(dissolved)


def test_dossier_keys_on_number_and_toevoeging() -> None:
    key, label, props = present(
        dossiers.dossier(
            {"Id": "d-1", "Nummer": 35590, "Toevoeging": "I", "Titel": "Tijdelijke wet"}
        )
    )
    assert (key, label) == ("35590_i", "35590-I")
    assert (props["number"], props["label"]) == ("35590", "35590-I")
    assert props["title_source"] == "dossier"
    assert props["display_name"] == "Kamerstukdossier 35590-I: Tijdelijke wet"


def test_a_case_names_its_dossier_by_the_label_of_the_dossier_node() -> None:
    """A budget chapter is its own dossier: the Toevoeging is part of what a record names."""
    records = [
        {
            "Soort": "Begroting",
            "Kamerstukdossier": [
                {"Nummer": 37020, "Toevoeging": "XV"},
                {"Nummer": 37020, "Toevoeging": None},
            ],
        }
    ]
    assert cases.dossier_numbers(records) == ["37020-XV", "37020"]
    assert cases.case_kinds_by_dossier(records) == {
        "37020-XV": ["Begroting"],
        "37020": ["Begroting"],
    }
    key, label, _ = present(
        dossiers.dossier({"Id": "d-1", "Nummer": 37020, "Toevoeging": "XV"})
    )
    assert (label, key) == ("37020-XV", make_node_key("37020-XV"))


def test_dossier_without_a_title_leaves_it_open_for_the_backfill() -> None:
    _, _, props = present(dossiers.dossier({"Id": "d-1", "Nummer": 36000}))
    assert props["title"] is None
    assert props["title_source"] is None
    assert "current_phase" not in props


def test_a_dossier_record_says_nothing_of_how_far_it_got() -> None:
    """``Afgesloten`` is false on every dossier, also on one whose law was published, and the
    record has no dates: closed and opened are derived from the graph, and a run of the record
    must not blank what was derived."""
    _, _, props = present(
        dossiers.dossier(
            {
                "Id": "d-1",
                "Nummer": 34851,
                "Titel": "Uitvoeringswet Algemene verordening gegevensbescherming",
                "Afgesloten": False,
                "HoogsteVolgnummer": 101,
            }
        )
    )
    for derived in ("closed", "closed_on", "opened_on", "outcome", "current_phase"):
        assert derived not in props


def test_a_document_and_a_decision_keep_the_kind_of_their_case() -> None:
    bill = {"Id": "z-1", "Soort": "Wetgeving", "Kamerstukdossier": [{"Nummer": 36000}]}
    _, document = present(
        documents.document({"Id": "doc-1", "Soort": "Brief regering", "Zaak": [bill]})
    )
    assert document["case_kinds"] == ["Wetgeving"]
    _, decision = decisions.decision("b-1", {"Zaak": [bill]}, [])
    assert decision["primary_case_kind"] == "Wetgeving"


@pytest.mark.parametrize(
    "soort", ["Motie", "Amendement", "Wetgeving", "Begroting", "Brief regering", None]
)
def test_a_decision_takes_its_kind_from_the_soort_of_its_case(
    soort: str | None,
) -> None:
    decision = {"Zaak": [{"Id": "z-1", "Soort": soort}], "Agendapunt": []}
    _, props = decisions.decision("b-1", decision, [])
    assert props["kind"] == soort


def test_a_decision_kind_ignores_the_subject() -> None:
    motion = {"Id": "z-1", "Soort": "Motie", "Onderwerp": "Wijziging van de Wet"}
    _, props = decisions.decision("b-1", {"Zaak": [motion]}, [])
    assert props["kind"] == "Motie"


def test_without_its_own_case_the_kind_is_that_of_an_agenda_item_of_one_kind() -> None:
    motions = [{"Id": "z-1", "Soort": "Motie"}, {"Id": "z-2", "Soort": "Motie"}]
    _, props = decisions.decision("b-1", {"Agendapunt": [{"Zaak": motions}]}, [])
    assert (props["primary_case_id"], props["kind"]) == (None, "Motie")
    mixed = [*motions, {"Id": "z-3", "Soort": "Amendement"}]
    _, props = decisions.decision("b-1", {"Agendapunt": [{"Zaak": mixed}]}, [])
    assert props["kind"] is None
    _, props = decisions.decision("b-1", {}, [])
    assert props["kind"] is None


def test_a_hamerstuk_is_a_decision_that_passed_without_votes() -> None:
    bill = {"Id": "z-1", "Soort": "Wetgeving"}
    _, props = decisions.decision(
        "b-1",
        {
            "Zaak": [bill],
            "BesluitSoort": "Stemmen - zonder stemming aannemen",
            "BesluitTekst": "Wetsvoorstel zonder stemming aangenomen.",
        },
        [],
    )
    assert props["decision_kind"] == "Stemmen - zonder stemming aannemen"
    assert (props["passed"], props["vote_kind"], props["tally"]) == (True, None, {})


def test_a_postponement_is_no_vote() -> None:
    _, props = decisions.decision(
        "b-1", {"Zaak": [], "BesluitSoort": "Stemmen - uitstellen"}, []
    )
    assert (props["decision_kind"], props["passed"]) == ("Stemmen - uitstellen", None)


def test_activity_reads_its_cases_dossiers_and_lead_committee() -> None:
    _, props = present(
        activities.activity(
            {
                "Id": "a-1",
                "Datum": "2024-01-02T00:00:00",
                "Soort": "Commissiedebat",
                "Nummer": "2024A05766",
                "Voortouwcommissie_Id": "c-1",
                "Agendapunt": [
                    {
                        "Zaak": [
                            {
                                "Id": "z-1",
                                "Soort": "Wetgeving",
                                "Kamerstukdossier": [{"Nummer": 36000}],
                            },
                            {"Id": "z-2", "Soort": "Motie", "Kamerstukdossier": []},
                        ]
                    }
                ],
            }
        )
    )
    assert props["case_ids"] == ["z-1", "z-2"]
    assert props["dossier_numbers"] == ["36000"]
    assert props["case_kinds_by_dossier"] == {"36000": ["Wetgeving"]}
    assert props["committee_id"] == "c-1"
    assert props["date"] == "2024-01-02"


def test_a_moved_activity_names_the_activities_that_replaced_it() -> None:
    _, props = present(
        activities.activity(
            {
                "Id": "a-1",
                "Nummer": "2026A04251",
                "Status": "Verplaatst",
                "VervangenDoor": [{"Id": "a-2", "Nummer": "2026A06208"}],
            }
        )
    )
    assert props["replaced_by"] == ["2026A06208"]
    _, props = present(activities.activity({"Id": "a-3", "Nummer": "2026A1"}))
    assert props["replaced_by"] == []


def test_a_case_names_the_cases_it_replaces() -> None:
    """An amended amendment ("ter vervanging van nr. 21") replaces the case of nr. 21
    (``Zaak.VervangenVanuit``); a deleted one is none."""
    record = {
        "Id": "z-71",
        "Nummer": "2024Z07443",
        "Soort": "Amendement",
        "VervangenVanuit": [
            {"Id": "z-21", "Verwijderd": False},
            {"Id": "z-gone", "Verwijderd": True},
        ],
    }
    assert cases.replaced_cases(record) == ["z-21"]
    assert cases.replaced_cases({"Id": "z-1"}) == []


def test_a_plenary_activity_has_no_lead_committee() -> None:
    _, props = present(
        activities.activity({"Id": "a-1", "Soort": "Plenaire vergadering"})
    )
    assert props["committee_id"] is None


def test_the_kamer_as_voortouw_is_no_lead_committee() -> None:
    _, props = present(
        activities.activity(
            {
                "Id": "a-1",
                "Soort": "Plenair debat (wetgeving)",
                "Voortouwcommissie_Id": "38aacfcd-2cfa-4727-949d-e4270237dbbe",
                "Voortouwafkorting": "TK",
                "Voortouwnaam": "TK",
            }
        )
    )
    assert props["committee_id"] is None


def test_activity_reads_its_subject_and_status() -> None:
    _, props = present(
        activities.activity(
            {
                "Id": "a-1",
                "Soort": "Commissiedebat",
                "Onderwerp": "Digitale grondrechten en data-ethiek",
                "Status": "Gepland",
                "Datum": "2027-02-11T10:00:00+01:00",
            }
        )
    )
    assert props["agenda_title"] == "Digitale grondrechten en data-ethiek"
    assert props["status"] == "Gepland"
    assert props["display_name"] == "Digitale grondrechten en data-ethiek (2027-02-11)"


def test_activity_reads_how_precise_its_date_is() -> None:
    # a vote planned for a week, not yet for a day: the Kamer dates it on the Monday
    _, props = present(
        activities.activity(
            {
                "Id": "a-1",
                "Soort": "Stemmingen",
                "Status": "Gepland",
                "Datum": "2026-12-07T00:00:00+01:00",
                "DatumSoort": "Weeknummer",
            }
        )
    )
    assert props["precision"] == "Weeknummer"
    _, undated = present(activities.activity({"Id": "a-2"}))
    assert undated["precision"] is None


def test_commitment_reads_the_minister_and_the_status() -> None:
    _, props = present(
        commitments.commitment(
            {
                "Id": "t-1",
                "Nummer": "TZ202412-116",
                "ActiviteitNummer": "2024A05766",
                "Naam": "Wiersma, F.M.",
                "Functie": "Minister van Landbouw",
                "Status": "Openstaand",
                "Tekst": "De minister stuurt de terugkoppeling naar de Kamer.",
                "Aanmaakdatum": "2024-12-16T15:01:11.847+01:00",
            }
        )
    )
    assert props["status"] == "Openstaand"
    assert props["minister_name"] == "Wiersma, F.M."
    assert props["activity_number"] == "2024A05766"
    assert props["made_on"] == "2024-12-16"


def test_a_commitment_reads_the_dossiers_of_the_letters_that_fulfil_it() -> None:
    _, props = present(
        commitments.commitment(
            {
                "Id": "t-1",
                "KamerbriefNakoming": [
                    {
                        "Id": "b-1",
                        "Kamerstukdossier": [{"Nummer": 29389, "Toevoeging": None}],
                    },
                    {
                        "Id": "b-2",
                        "Kamerstukdossier": [{"Nummer": 36600, "Toevoeging": "VII"}],
                    },
                    {
                        "Id": "b-3",
                        "Kamerstukdossier": [{"Nummer": 29389, "Toevoeging": None}],
                    },
                    {"Id": "b-4", "Kamerstukdossier": []},
                ],
            }
        )
    )
    assert props["letter_ids"] == ["b-1", "b-2", "b-3", "b-4"]
    assert props["letter_dossiers"] == ["29389", "36600-VII"]
    assert present(commitments.commitment({"Id": "t"}))[1]["letter_dossiers"] == []


def test_a_commitment_keeps_the_status_the_kamer_gives_it() -> None:
    statuses = ("Deels Afgedaan", "Vervallen", "Nagekomen", "Niet nagekomen", "Iets")
    kept = [
        present(commitments.commitment({"Id": "t", "Status": s}))[1]["status"]
        for s in statuses
    ]
    assert tuple(kept) == statuses
    assert present(commitments.commitment({"Id": "t"}))[1]["status"] is None


def test_document_reads_its_cases_dossiers_and_signatories() -> None:
    _, props = present(
        documents.document(
            {
                "Id": "doc-1",
                "Soort": "Amendement",
                "Titel": "Amendement over iets",
                "Volgnummer": 7,
                "Datum": "2024-03-01T00:00:00",
                "Zaak": [
                    {"Id": "z-1", "Kamerstukdossier": [{"Nummer": 29684}]},
                    {"Id": "z-2", "Kamerstukdossier": [{"Nummer": 31058}]},
                ],
                "Kamerstukdossier": [{"Nummer": 29684, "Toevoeging": None}],
                "DocumentActor": [
                    {
                        "Persoon_Id": "p-1",
                        "ActorNaam": "Jansen",
                        "ActorFractie": "VVD",
                        "Relatie": "Eerste ondertekenaar",
                    },
                    {"ActorNaam": "", "Persoon_Id": None},
                ],
            }
        )
    )
    assert props["case_ids"] == ["z-1", "z-2"]
    assert props["dossier_numbers"] == ["29684", "31058"]
    # It is part of both and numbered in one.
    assert (props["dossier_number"], props["dossier_suffix"]) == ("29684", None)
    assert props["sequence"] == 7
    assert [a["person_id"] for a in props["actors"]] == ["p-1"]
    assert props["display_name"].startswith("Kamerstuk 29684, nr. 7")
    assert " — " not in props["display_name"]


def test_a_document_keeps_the_number_tweedekamer_nl_knows_it_by_and_no_link() -> None:
    _, props = present(
        documents.document(
            {
                "Id": "a0ec76e1-44ff-49d3-924b-2a4a8af4698c",
                "DocumentNummer": "2026D44984",
            }
        )
    )
    assert props["document_number"] == "2026D44984"
    # the link is derived when a response is built (core.tk_links), never stored
    assert "tk_url" not in props
    _, activity = present(activities.activity({"Id": "a-1", "Nummer": "2026A02571"}))
    assert activity["number"] == "2026A02571" and "tk_url" not in activity


def test_a_case_keeps_the_cases_the_kamer_relates_it_to_with_their_dossiers() -> None:
    related = cases.related_cases(
        {
            "Id": "z-brief",
            "Soort": "Brief regering",
            "GerelateerdNaar": [
                {
                    "Id": "z-motie",
                    "Soort": "Motie",
                    "Verwijderd": False,
                    "Kamerstukdossier": [{"Nummer": 36800, "Toevoeging": "V"}],
                },
                {"Id": "z-weg", "Soort": "Motie", "Verwijderd": True},
                {"Id": "z-los", "Soort": "Brief commissie", "Kamerstukdossier": []},
            ],
        }
    )
    assert related == [
        {"id": "z-motie", "kind": "Motie", "dossier_numbers": ["36800-V"]},
        {"id": "z-los", "kind": "Brief commissie", "dossier_numbers": []},
    ]
    assert cases.related_cases({"Id": "z-1"}) == []


@pytest.mark.parametrize(
    ("function", "faction", "capacity"),
    [
        # R.A.A. Jetten, 2026: no faction, the government
        ("minister-president", None, "bewindspersoon"),
        ("minister van Algemene Zaken", None, "bewindspersoon"),
        # and before, as a member of the Kamer and as a minister
        ("Tweede Kamerlid", "f-d66", "kamerlid"),
        ("minister voor Klimaat en Energie", None, "bewindspersoon"),
        ("staatssecretaris van Financiën", None, "bewindspersoon"),
        ("viceminister-president", None, "bewindspersoon"),
        # S. van Haersma Buma, 2026: a former member, now for the Raad van State
        ("vicepresident van de Raad van State", None, "overig"),
        # Aruba's minister is no member of the Dutch government
        ("gevolmachtigde minister van Aruba", None, "overig"),
        ("griffier", None, "overig"),
        ("president van de Algemene Rekenkamer", None, "overig"),
        # a member who chairs a committee still signs for a faction
        ("voorzitter van de vaste commissie voor Financiën", "f-vvd", "kamerlid"),
        (None, None, "overig"),
    ],
)
def test_the_capacity_of_a_signature_follows_its_function_and_faction(
    function: str | None, faction: str | None, capacity: str
) -> None:
    assert actors.signing_capacity(function, faction) == capacity


def test_a_signatory_keeps_the_function_they_signed_in() -> None:
    _, props = present(
        documents.document(
            {
                "Id": "doc-1",
                "Soort": "Brief regering",
                "DocumentActor": [
                    {
                        "Persoon_Id": "p-jetten",
                        "ActorNaam": "R.A.A. Jetten",
                        "Functie": "minister-president",
                        "Relatie": "Eerste ondertekenaar",
                    },
                    {
                        "Persoon_Id": "p-lid",
                        "ActorNaam": "Lid",
                        "ActorFractie": "VVD",
                        "Fractie_Id": "f-vvd",
                        "Functie": "Tweede Kamerlid",
                        "Relatie": "Mede ondertekenaar",
                    },
                ],
            }
        )
    )
    assert [(a["function"], a["capacity"]) for a in props["actors"]] == [
        ("minister-president", "bewindspersoon"),
        ("Tweede Kamerlid", "kamerlid"),
    ]


def test_a_non_kamerstuk_document_has_no_volgnummer() -> None:
    _, props = present(documents.document({"Id": "doc-1", "Volgnummer": -1}))
    assert props["sequence"] is None


def _vote(**overrides: object) -> dict:
    payload = {
        "Besluit_Id": "b-1",
        "Soort": "Voor",
        "FractieGrootte": 24,
        "ActorFractie": "VVD",
        "Fractie_Id": "f-vvd",
        "Persoon_Id": None,
        "GewijzigdOp": "2024-10-16T11:34:18.673+02:00",
    }
    payload.update(overrides)
    return payload


def _cast(**overrides: object) -> decisions.VoteCast:
    """The vote ``decisions.vote`` reads of a Stemming with *overrides*."""
    return present(decisions.vote(_vote(**overrides)))


def test_a_faction_decision_tallies_seats() -> None:
    votes = [
        _cast(Soort="Voor", FractieGrootte=76),
        _cast(Soort="Tegen", FractieGrootte=74, Fractie_Id="f-pvv"),
    ]
    _, props = decisions.decision(
        "b-1", {"BesluitSoort": "Stemmen - aangenomen"}, votes
    )
    assert props["vote_kind"] == "faction"
    assert props["tally"] == {"Voor": 76, "Tegen": 74}
    assert props["voters"] == {"Voor": 1, "Tegen": 1}
    assert props["passed"] is True


def test_a_tally_reads_for_against_and_the_rest_whatever_came_first() -> None:
    """The rows of a decision come in no fixed order; its tally does (``props.tally`` is
    served as it is, key order included)."""
    rows = [
        _vote(Id="s-3", Soort="Niet deelgenomen", FractieGrootte=1, Fractie_Id="f-a"),
        _vote(Id="s-2", Soort="Tegen", FractieGrootte=74, Fractie_Id="f-pvv"),
        _vote(Id="s-1", Soort="Voor", FractieGrootte=75),
    ]
    for order in (rows, rows[::-1]):
        votes = [present(decisions.vote(row)) for row in order]
        _, props = decisions.decision("b-1", {}, votes)
        assert list(props["tally"]) == ["Voor", "Tegen", "Niet deelgenomen"]
        assert list(props["voters"]) == ["Voor", "Tegen", "Niet deelgenomen"]


def test_a_roll_call_counts_members_not_faction_sizes() -> None:
    votes = [
        _cast(Soort="Voor", FractieGrootte=34, Persoon_Id="p-1"),
        _cast(Soort="Voor", FractieGrootte=34, Persoon_Id="p-2"),
        _cast(Soort="Tegen", FractieGrootte=14, Persoon_Id="p-3"),
    ]
    _, props = decisions.decision("b-1", {"StemmingsSoort": "Hoofdelijk"}, votes)
    assert props["vote_kind"] == "member"
    assert props["tally"] == {"Voor": 2, "Tegen": 1}
    assert props["passed"] is True
    # each member's vote weighs one seat, not the size of the faction (K4)
    assert [cast.seats for cast in votes] == [1, 1, 1]


def _faber() -> list[decisions.VoteCast]:
    """Motie Faber, 12 May 2026, in part: Groep Markuszower (7) against, but for three of
    its members, each a row of their own with the size of the group."""
    rows = [
        _vote(Id="s-1", Soort="Voor", FractieGrootte=22),
        _vote(Id="s-2", Soort="Tegen", FractieGrootte=7, Fractie_Id="f-gm"),
        *(
            _vote(Id=f"s-{n}", Soort="Voor", FractieGrootte=7, Fractie_Id="f-gm",
                  Persoon_Id=f"p-{n}")
            for n in (3, 4, 5)
        ),
        _vote(Id="s-6", Soort="Tegen", FractieGrootte=26, Fractie_Id="f-d66"),
    ]  # fmt: skip
    return [vote for row in rows if (vote := decisions.vote(row))]


def test_a_faction_vote_with_members_voting_apart_is_no_roll_call() -> None:
    """A member who votes apart from their faction has a row of their own: the faction
    then counts its seats without them, each of them one seat. It is no roll call, which
    names every member."""
    votes = _faber()
    _, props = decisions.decision("b-1", {"BesluitSoort": "Stemmen - verworpen"}, votes)
    assert props["vote_kind"] == "faction"
    assert props["tally"] == {"Voor": 25, "Tegen": 30}
    assert decisions.seats_of(votes) == [22, 4, 1, 1, 1, 26]


def test_the_outcome_falls_back_to_the_tally_when_the_source_is_silent() -> None:
    votes = [
        _cast(Soort="Voor", FractieGrootte=10),
        _cast(Soort="Tegen", FractieGrootte=40, Fractie_Id="f-x"),
    ]
    _, props = decisions.decision("b-1", {}, votes)
    assert props["passed"] is False


def test_a_decision_names_the_case_it_decided() -> None:
    """The Besluit's own Zaak, as TK sends it for the Visserijwet (36899) on 22 September
    2026: an amendment, the bill and an amendment on one agenda item, and
    AgendapuntZaakBesluitVolgorde 3 on the vote on the bill, which is second in the list."""
    amendment = {"Id": "z-1", "Nummer": "2026Z18401", "Soort": "Amendement"}
    bill = {
        "Id": "z-2",
        "Nummer": "2026Z03557",
        "Soort": "Wetgeving",
        "Onderwerp": "Wijziging van de Visserijwet 1963",
    }
    other = {"Id": "z-3", "Nummer": "2026Z18274", "Soort": "Amendement"}
    decision = {
        "AgendapuntZaakBesluitVolgorde": 3,
        "BesluitSoort": "Stemmen - aangenomen",
        "Zaak": [bill],
        "Agendapunt": {
            "Onderwerp": "Wijziging van de Visserijwet 1963",
            "Activiteit": {"Soort": "Stemmingen", "Datum": "2026-09-22T15:00:00+02:00"},
            "Zaak": [amendment, bill, other],
        },
    }
    vote = _cast(GewijzigdOp="2026-09-23T09:00:00+02:00")
    _, props = decisions.decision("b-1", decision, [present(vote)])
    assert (props["primary_case_id"], props["primary_case_kind"]) == (
        "z-2",
        "Wetgeving",
    )
    assert props["case_ids"] == ["z-2", "z-1", "z-3"]
    assert props["subject"] == "Wijziging van de Visserijwet 1963"
    assert (
        props["display_name"]
        == "Wetgeving 2026Z03557: Wijziging van de Visserijwet 1963"
    )
    # The day of the vote, not the day the row was last edited.
    assert props["date"] == "2026-09-22"


def test_without_its_own_case_only_an_agenda_item_of_one_case_names_it() -> None:
    records = [{"Id": "z-1", "Soort": "Motie"}, {"Id": "z-2", "Soort": "Motie"}]
    decision = {"AgendapuntZaakBesluitVolgorde": 2, "Agendapunt": [{"Zaak": records}]}
    _, props = decisions.decision("b-1", decision, [_cast()])
    assert props["primary_case_id"] is None
    _, props = decisions.decision(
        "b-1",
        {"Agendapunt": [{"Zaak": records[:1]}]},
        [_cast()],
    )
    assert props["primary_case_id"] == "z-1"


def test_siblings_on_one_agenda_item_fall_back_to_its_subject() -> None:
    decision = {
        "Agendapunt": [{"Onderwerp": "Stemmingen moties", "Zaak": [{"Id": "z-1"}]}]
    }
    _, props = decisions.decision("b-1", decision, [_cast()])
    assert props["subject"] == "Stemmingen moties"


def test_a_vote_without_a_decision_is_skipped() -> None:
    assert decisions.vote({"Soort": "Voor"}) is None


def test_a_vote_cast_is_a_slotted_object_with_shared_strings() -> None:
    """190K casts are kept until the VOTED edges are written: no dict per cast."""
    first = _cast(Soort="Voor", Fractie_Id="f-" + "vvd")
    second = _cast(Soort="Vo" + "or", Fractie_Id="f-vvd")
    assert first is not None and second is not None
    assert not hasattr(first, "__dict__")
    assert first.choice is second.choice and first.faction_id is second.faction_id


def test_a_document_says_which_source_it_is_from() -> None:
    """Every other source does; without it a filter on `source=tk` found none of the
    126,710 papers and `/api/stats` counted them as unknown."""
    _, props = present(documents.document({"Id": "doc-1", "Soort": "Motie"}))
    assert props["source"] == "tk"


_DOSSIER_TITLE = "Rechtsstaat en Rechtsorde"


@pytest.mark.parametrize(
    ("kind", "subject", "case_subject", "title", "dossier_title"),
    [
        # a motie or amendement is named by its own Onderwerp, stripped
        (
            "Motie",
            "Motie van het lid Faber over fouilleren ",
            None,
            "Motie van het lid Faber over fouilleren",
            _DOSSIER_TITLE,
        ),
        (
            "Amendement (gewijzigd/nader/vervangend)",
            "Amendement van het lid Ergin",
            None,
            "Amendement van het lid Ergin",
            _DOSSIER_TITLE,
        ),
        # without one, by the Onderwerp of its Zaak; without that, by its Titel
        (
            "Motie (gewijzigd/nader)",
            None,
            "Gewijzigde motie van het lid Kostić",
            "Gewijzigde motie van het lid Kostić",
            _DOSSIER_TITLE,
        ),
        ("Motie", None, None, _DOSSIER_TITLE, _DOSSIER_TITLE),
        # so is a letter or the report of a debate
        (
            "Brief regering",
            "Voortgang aanpak ondermijning",
            None,
            "Voortgang aanpak ondermijning",
            _DOSSIER_TITLE,
        ),
        (
            "Verslag van een commissiedebat",
            "Verslag van een commissiedebat, gehouden op 1 juli 2026, over mkb",
            None,
            "Verslag van een commissiedebat, gehouden op 1 juli 2026, over mkb",
            _DOSSIER_TITLE,
        ),
        # an Onderwerp that only repeats the kind names nothing
        ("Mededeling", "Mededeling", None, _DOSSIER_TITLE, _DOSSIER_TITLE),
        # a bill and the papers on it keep their Titel: their Onderwerp is their kind
        ("Voorstel van wet", "Voorstel van wet", None, _DOSSIER_TITLE, None),
        (
            "Memorie van toelichting",
            "Memorie van toelichting",
            None,
            _DOSSIER_TITLE,
            None,
        ),
        ("Geleidende brief", "Geleidende brief", None, _DOSSIER_TITLE, None),
    ],
)
def test_a_paper_is_named_by_its_own_subject(
    kind: str,
    subject: str | None,
    case_subject: str | None,
    title: str,
    dossier_title: str | None,
) -> None:
    _, props = present(
        documents.document(
            {
                "Id": "d-1",
                "Soort": kind,
                "Titel": _DOSSIER_TITLE,
                "Onderwerp": subject,
                "Zaak": [{"Id": "z-1", "Soort": "Motie", "Onderwerp": case_subject}],
            }
        )
    )
    assert (props["title"], props["dossier_title"]) == (title, dossier_title)


def test_the_case_of_a_motion_is_named_by_its_subject_and_a_bill_by_its_title() -> None:
    key, props = present(
        cases.case(
            {
                "Id": "z-1",
                "Nummer": "2026Z18284",
                "Soort": "Motie",
                "Titel": _DOSSIER_TITLE,
                "Onderwerp": "Motie van het lid Faber over fouilleren ",
            }
        )
    )
    assert key == "z_1"
    assert props["title"] == "Motie van het lid Faber over fouilleren"
    assert props["display_name"] == props["title"]
    assert (props["number"], props["kind"]) == ("2026Z18284", "Motie")

    _, bill = present(
        cases.case(
            {
                "Id": "z-2",
                "Soort": "Wetgeving",
                "Titel": "Wijziging van de Wegenwet",
                "Onderwerp": "Wijziging van de Wegenwet in verband met wegen",
            }
        )
    )
    assert bill["title"] == "Wijziging van de Wegenwet"
    assert bill["started_on"] is None
    assert cases.case({"Soort": "Motie"}) is None


def test_a_case_keeps_the_day_it_started() -> None:
    _, bill = present(
        cases.case(
            {
                "Id": "z-3",
                "Soort": "Wetgeving",
                "GestartOp": "2025-09-03T00:00:00+02:00",
            }
        )
    )
    # of a bill: the day it was submitted to the Tweede Kamer (36799)
    assert bill["started_on"] == "2025-09-03"


def test_the_submitters_of_a_motion_are_its_signatories_the_indiener_first() -> None:
    signatures = actors.document_actors(
        {
            "DocumentActor": [
                {
                    "Persoon_Id": "p-2",
                    "ActorNaam": "I. Ellian",
                    "ActorFractie": "VVD",
                    "Relatie": "Mede ondertekenaar",
                },
                {"ActorNaam": "Griffier", "Relatie": "Afzender"},
                {
                    "Persoon_Id": "p-1",
                    "ActorNaam": "M. Faber",
                    "ActorFractie": "PVV",
                    "Relatie": "Eerste ondertekenaar",
                },
            ]
        }
    )
    assert actors.submitters("Motie", signatures) == [
        {"name": "M. Faber", "faction": "PVV", "member_key": "p_1", "role": "indiener"},
        {
            "name": "I. Ellian",
            "faction": "VVD",
            "member_key": "p_2",
            "role": "medeindiener",
        },
    ]
    # the first signatory of a letter is no indiener
    assert actors.submitters("Brief regering", signatures) == []


@pytest.mark.parametrize(
    ("dossier", "sequence", "kind", "title", "name"),
    [
        (
            "29684",
            7,
            "Amendement",
            "Over de huur",
            "Kamerstuk 29684, nr. 7. Amendement: Over de huur",
        ),
        (
            "29684",
            8,
            "Motie",
            "Motie van de leden Jansen over de huur",
            "Kamerstuk 29684, nr. 8: Motie van de leden Jansen over de huur",
        ),
        (
            "29684",
            1,
            "Brief regering",
            "Brief regering",
            "Kamerstuk 29684, nr. 1. Brief regering",
        ),
        (None, 0, "Motie", "Motie van het lid Jansen", "Motie van het lid Jansen"),
    ],
)
def test_a_document_name_is_a_heading_without_a_dash(
    dossier: str | None, sequence: int, kind: str, title: str, name: str
) -> None:
    assert documents.document_display_name(dossier, sequence, kind, title) == name


def test_a_vote_on_a_motion_is_named_by_the_motion() -> None:
    primary = {"Soort": "Motie", "Nummer": "2026Z17941"}
    subject = "Motie van de leden Jansen en De Vries over de huur"
    assert decisions.decision_display_name(primary, 1, 1, subject) == subject
    assert decisions.decision_display_name(primary, 1, 1, "Over de huur") == (
        "Motie 2026Z17941: Over de huur"
    )


def test_a_paper_numbered_in_no_dossier_is_no_kamerstuk() -> None:
    """A nader rapport sent along with a bill: part of its case, numbered nowhere."""
    _, props = present(
        documents.document(
            {
                "Id": "doc-2",
                "Soort": "Nader rapport",
                "Onderwerp": "Nader rapport",
                "Volgnummer": -1,
                "Zaak": [
                    {
                        "Id": "z-1",
                        "Kamerstukdossier": [{"Nummer": 37020, "Toevoeging": "XV"}],
                    }
                ],
                "Kamerstukdossier": [],
            }
        )
    )
    assert props["dossier_numbers"] == ["37020-XV"]
    assert (props["dossier_number"], props["sequence"]) == (None, None)
    assert not props["display_name"].startswith("Kamerstuk")


def test_the_links_of_a_document_are_its_activities_attachments_and_letters() -> None:
    # 2023D18976, a stenogram as the Gegevensmagazijn gives it with these expansions
    stenogram = {
        "Id": "9cd4c32c-77fb-4713-821d-faf5ebd49b61",
        "Soort": "Stenogram",
        "Onderwerp": "Kunstmatige intelligentie",
        "Datum": "2023-03-28T18:35:00+02:00",
        "DocumentNummer": "2023D18976",
        "Vergaderjaar": "2022-2023",
        "Volgnummer": -1,
        "Zaak": [],
        "Kamerstukdossier": [],
        "DocumentActor": [],
        "Activiteit": [{"Id": "a76eec4d-9cde-48de-aefa-6385e69dd0e1"}],
        "BijlageDocument": [],
        "BronDocument": [],
    }
    _key, props = present(documents.document(stenogram))
    assert props["case_ids"] == [] and props["dossier_numbers"] == []
    assert props["activity_ids"] == ["a76eec4d-9cde-48de-aefa-6385e69dd0e1"]
    assert props["attachment_ids"] == [] and props["attached_to_ids"] == []

    letter = {"BijlageDocument": [{"Id": "b1"}, {"Id": "b2"}, {"Id": "b1"}, {}]}
    assert documents.document_links(letter) == {
        "activity_ids": [],
        "attachment_ids": [
            "b1",
            "b2",
        ],  # once each, in order; one without an id is none
        "attached_to_ids": [],
    }
    # a record of retrieve tk-document-links: the same fields, nothing else
    assert documents.document_links({"Id": "b1", "BronDocument": [{"Id": "x"}]})[
        "attached_to_ids"
    ] == ["x"]


def test_the_actors_of_a_case_are_its_submitters_and_lead_committee() -> None:
    # a motion of a member, and a bill of a minister, as retrieve tk-case-signatures stores them
    motion = {
        "Id": "2965764e-cc8e-45f1-8f55-00003c0ab2dd",
        "ZaakActor": [
            {
                "Relatie": "Voortouwcommissie",
                "ActorAfkorting": "TK",
                "Commissie_Id": "tk",
            },
            {"Relatie": "Indiener", "Persoon_Id": "p1", "Fractie_Id": "f1"},
            {"Relatie": "Medeindiener", "Persoon_Id": "p2", "Fractie_Id": "f2"},
            {"Relatie": "Gericht aan", "Persoon_Id": "p3", "Functie": "minister"},
            {"Relatie": "Indiener", "Persoon_Id": None},  # no person: no submitter
        ],
    }
    signatures = actors.case_actors(motion)
    assert signatures["submitters"] == [
        {
            "person_id": "p1",
            "role": "Indiener",
            "function": None,
            "capacity": "kamerlid",
        },
        {
            "person_id": "p2",
            "role": "Medeindiener",
            "function": None,
            "capacity": "kamerlid",
        },
    ]
    assert signatures["committee_ids"] == []  # the plenary leads: no committee

    bill = {
        "ZaakActor": [
            {
                "Relatie": "Voortouwcommissie",
                "ActorAfkorting": "VWS",
                "Commissie_Id": "befe416e-ca1b-4804-97d0-7aca1dcba888",
            },
            {
                "Relatie": "Indiener",
                "Persoon_Id": "07de26f3-a939-4ae4-b7a5-43f868a665d1",
                "Functie": "minister voor Medische Zorg",
            },
            {"Relatie": "Volgcommissie", "Commissie_Id": "other"},
        ]
    }
    signatures = actors.case_actors(bill)
    assert [(s["role"], s["capacity"]) for s in signatures["submitters"]] == [
        ("Indiener", "bewindspersoon")
    ]
    assert signatures["committee_ids"] == ["befe416e-ca1b-4804-97d0-7aca1dcba888"]


def test_a_vacant_seat_ends_the_day_before_the_successor_takes_it() -> None:
    def record(start: str, until: str | None) -> dict:
        return {
            "Van": f"{start}T00:00:00+01:00",
            "TotEnMet": f"{until}T00:00:00+01:00" if until else None,
            "FractieZetel": {"Id": "z", "Fractie_Id": "d66"},
        }

    # kabinet-Jetten: vacant from 23 February, the successor installed on the 25th
    assert seats.seat_vacancy(record("2026-02-23", "2026-02-25")) == (
        "d66",
        {"from_date": "2026-02-23", "to_date": "2026-02-24"},
    )
    assert present(seats.seat_vacancy(record("2026-02-23", None)))[1]["to_date"] is None
    # the source holds a vacancy that ends before it begins: none
    assert seats.seat_vacancy(record("2026-02-23", "2026-02-22")) is None


def test_the_seat_of_a_vacancy_and_of_a_holding() -> None:
    vacancy = {"Van": "2026-02-16T00:00:00+01:00", "FractieZetel": {"Id": "z1"}}
    assert seats.vacancy_seat(vacancy) == "z1"
    holding = {
        "Van": "2025-11-12T00:00:00+01:00",
        "TotEnMet": "2026-02-16T00:00:00+01:00",
        "FractieZetel_Id": "z1",
    }
    assert seats.holding_of_seat(holding) == (
        "z1",
        {"from_date": "2025-11-12", "to_date": "2026-02-16"},
    )


def _held(*periods: tuple[str, str | None]) -> list[dict[str, str | None]]:
    return [{"from_date": a, "to_date": b} for a, b in periods]


def test_a_vacancy_counts_only_the_days_its_seat_is_held_by_no_one() -> None:
    """The source holds vacancies that overlap the seat's own members: the day the member
    leaves (D66, 16 Feb 2026), and one never closed (BBB, from 5 Feb 2025, while Helder
    sat until 4 March and Oostenbrink from 5 March). A seat is held or vacant, never both;
    and a vacancy ends at the latest the day before the seat is taken again."""
    vacancy = seats.vacant_periods
    # D66: the predecessor's last day is no vacant day
    assert vacancy(
        {"from_date": "2026-02-16", "to_date": "2026-02-24"},
        _held(("2025-11-12", "2026-02-16"), ("2026-02-25", None)),
    ) == [{"from_date": "2026-02-17", "to_date": "2026-02-24"}]
    # BBB: never vacant at all
    assert (
        vacancy(
            {"from_date": "2025-02-05", "to_date": None},
            _held(("2023-09-01", "2025-03-04"), ("2025-03-05", "2025-11-11")),
        )
        == []
    )
    # an open vacancy of a seat no one took again stays open
    assert vacancy(
        {"from_date": "2026-03-01", "to_date": None},
        _held(("2025-11-12", "2026-02-28")),
    ) == [{"from_date": "2026-03-01", "to_date": None}]
    # Fractie Bontes: seat b5ab8da3 has a vacancy (13 to 14 February 2017) and no member
    # ever held it; a seat of the Kamer it never was
    bontes = {
        "Van": "2017-02-13T00:00:00+01:00",
        "TotEnMet": "2017-02-15T00:00:00+01:00",
        "FractieZetel": {"Id": "b5ab8da3", "Fractie_Id": "bontes"},
    }
    period = seats.seat_vacancy(bontes)
    assert period == (
        "bontes",
        {"from_date": "2017-02-13", "to_date": "2017-02-14"},
    )
    assert vacancy(period[1], []) == []


@pytest.mark.parametrize(
    ("afgedaan", "done"), [(True, True), (False, False), (None, None)]
)
def test_a_case_says_whether_the_kamer_is_done_with_it(
    afgedaan: bool | None, done: bool | None
) -> None:
    """``Zaak.Afgedaan``: an amendment not done with and without a decision is not voted
    on yet; one done with and without a decision was withdrawn or replaced."""
    payload = {"Id": "z-1", "Soort": "Amendement", "Afgedaan": afgedaan}
    _, props = present(cases.case(payload))
    assert props["done"] is done
