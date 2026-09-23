"""Reading a TK OData payload yields the props the graph stores."""

from __future__ import annotations

from lawgraph.core import tk_records


def test_committee_reads_name_abbreviation_and_slug() -> None:
    key, props = tk_records.committee(
        {"Id": "c-1", "NaamNL": "Vaste commissie voor Financiën", "Afkorting": "FIN"}
    )
    assert key == "c_1"
    assert props["name"] == "Vaste commissie voor Financiën"
    assert props["abbreviation"] == "FIN"
    assert props["slug"] == "fin"


def test_committee_without_an_id_is_skipped() -> None:
    assert tk_records.committee({"NaamNL": "Naamloos"}) is None


def test_committee_seats_collect_every_period_per_person() -> None:
    periods = tk_records.committee_seats(
        {
            "CommissieZetel": [
                {
                    "CommissieZetelVastPersoon": [
                        {
                            "Persoon_Id": "p1",
                            "Van": "2020-01-01",
                            "TotEnMet": "2021-01-01",
                        },
                        {"Persoon_Id": "p1", "Van": "2022-01-01", "TotEnMet": None},
                        {"Persoon_Id": "p2", "Van": "2019-01-01", "TotEnMet": None},
                    ]
                }
            ]
        }
    )
    assert periods["p1"] == [("2020-01-01", "2021-01-01"), ("2022-01-01", None)]
    assert periods["p2"] == [("2019-01-01", None)]


def test_representative_period_prefers_an_open_one() -> None:
    meta = tk_records.representative_period(
        [("2020-01-01", "2021-01-01"), ("2022-01-01", None)]
    )
    assert meta == {"from_date": "2022-01-01"}


def test_representative_period_takes_the_latest_closed_one() -> None:
    meta = tk_records.representative_period(
        [("2015-01-01", "2016-01-01"), ("2019-01-01", "2020-01-01")]
    )
    assert meta == {"from_date": "2019-01-01", "to_date": "2020-01-01"}


def test_member_joins_the_name_parts() -> None:
    _, props = tk_records.member(
        {
            "Id": "p-1",
            "Voornamen": "Mark",
            "Tussenvoegsel": "van der",
            "Achternaam": "Berg",
        }
    )
    assert props["name"] == "Mark van der Berg"
    assert props["display_name"] == "Mark van der Berg"
    # Party is not read here: it comes from the dated seat timeline.
    assert "party" not in props


def test_seat_holding_reads_the_period_and_the_faction() -> None:
    assert tk_records.seat_holding(
        {
            "Persoon_Id": "p1",
            "FractieZetel": {"Fractie_Id": "f1"},
            "Van": "2021-03-31T00:00:00",
            "TotEnMet": None,
            "Functie": "Lid",
        }
    ) == ("p1", "f1", {"from_date": "2021-03-31", "to_date": None, "role": "Lid"})


def test_seat_holding_without_a_faction_is_skipped() -> None:
    assert tk_records.seat_holding({"Persoon_Id": "p1", "FractieZetel": {}}) is None


def test_faction_aliases_accept_an_acronym_a_vote_uses() -> None:
    payload = {
        "Afkorting": "Nieuw Sociaal Contract",
        "NaamNL": "Nieuw Sociaal Contract",
    }
    aliases = tk_records.faction_aliases(payload, {"NSC", "VVD"})
    assert "NSC" in aliases
    assert "Nieuw Sociaal Contract" in aliases


def test_faction_aliases_reject_an_acronym_no_vote_uses() -> None:
    payload = {"Afkorting": "XYZ", "NaamNL": "Partij Voor Iets"}
    assert "PVI" not in tk_records.faction_aliases(payload, {"VVD"})


def test_faction_is_current_prefers_a_seated_record() -> None:
    seated = {"DatumInactief": None, "GewijzigdOp": "2020-01-01"}
    dissolved = {"DatumInactief": "2021-01-01", "GewijzigdOp": "2025-01-01"}
    assert tk_records.faction_is_current(seated) > tk_records.faction_is_current(
        dissolved
    )


def test_dossier_keys_on_number_and_toevoeging() -> None:
    key, label, props = tk_records.dossier(
        {"Id": "d-1", "Nummer": 35590, "Toevoeging": "I", "Titel": "Tijdelijke wet"}
    )
    assert (key, label) == ("35590_i", "35590-I")
    assert props["number"] == "35590"
    assert props["title_source"] == "dossier"
    assert props["display_name"] == "Kamerstukdossier 35590-I: Tijdelijke wet"


def test_dossier_without_a_title_leaves_it_open_for_the_backfill() -> None:
    _, _, props = tk_records.dossier({"Id": "d-1", "Nummer": 36000})
    assert props["title"] is None
    assert props["title_source"] is None
    assert "current_stage" not in props


def test_a_dossier_record_says_nothing_of_how_far_it_got() -> None:
    """``Afgesloten`` is false on every dossier, also on one whose law was published, and the
    record has no dates: closed and opened are derived from the graph, and a run of the record
    must not blank what was derived."""
    _, _, props = tk_records.dossier(
        {
            "Id": "d-1",
            "Nummer": 34851,
            "Titel": "Uitvoeringswet Algemene verordening gegevensbescherming",
            "Afgesloten": False,
            "HoogsteVolgnummer": 101,
        }
    )
    for derived in ("closed", "closed_on", "opened_on", "outcome", "current_stage"):
        assert derived not in props


def test_a_document_and_a_decision_keep_the_kind_of_their_case() -> None:
    bill = {"Id": "z-1", "Soort": "Wetgeving", "Kamerstukdossier": [{"Nummer": 36000}]}
    _, document = tk_records.document(
        {"Id": "doc-1", "Soort": "Brief regering", "Zaak": [bill]}
    )
    assert document["case_kinds"] == ["Wetgeving"]
    _, decision = tk_records.decision(
        "b-1",
        {"Agendapunt": [{"Zaak": [bill]}], "AgendapuntZaakBesluitVolgorde": 1},
        [],
    )
    assert decision["primary_case_kind"] == "Wetgeving"


def test_activity_reads_its_cases_dossiers_and_lead_committee() -> None:
    _, props = tk_records.activity(
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
    assert props["case_ids"] == ["z-1", "z-2"]
    assert props["dossier_numbers"] == ["36000"]
    assert props["case_kinds"] == ["Wetgeving", "Motie"]
    assert props["committee_id"] == "c-1"
    assert props["date"] == "2024-01-02"


def test_a_plenary_activity_has_no_lead_committee() -> None:
    _, props = tk_records.activity({"Id": "a-1", "Soort": "Plenaire vergadering"})
    assert props["committee_id"] is None


def test_commitment_reads_the_minister_and_maps_the_status() -> None:
    _, props = tk_records.commitment(
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
    assert props["status"] == "open"
    assert props["minister_name"] == "Wiersma, F.M."
    assert props["activity_number"] == "2024A05766"
    assert props["made_on"] == "2024-12-16"


def test_statuses_seen_in_the_real_data_are_not_reported_as_open() -> None:
    """The retrieve run warned about these two: they used to fall back to "open"."""
    _, partly = tk_records.commitment({"Id": "t-3", "Status": "Deels Afgedaan"})
    _, lapsed = tk_records.commitment({"Id": "t-4", "Status": "Vervallen"})
    assert (partly["status"], lapsed["status"]) == ("partly_done", "lapsed")
    assert not tk_records.unknown_commitment_statuses(
        [{"Status": "Deels Afgedaan"}, {"Status": "Vervallen"}]
    )


def test_an_unfulfilled_commitment_keeps_that_apart_from_done() -> None:
    _, done = tk_records.commitment({"Id": "t-1", "Status": "Nagekomen"})
    _, failed = tk_records.commitment({"Id": "t-2", "Status": "Niet nagekomen"})
    assert (done["status"], failed["status"]) == ("done", "unfulfilled")


def test_unknown_commitment_statuses_are_reported() -> None:
    assert tk_records.unknown_commitment_statuses(
        [{"Status": "Openstaand"}, {"Status": "Iets nieuws"}, {}]
    ) == {"Iets nieuws"}


def test_document_reads_its_cases_dossiers_and_signatories() -> None:
    _, props = tk_records.document(
        {
            "Id": "doc-1",
            "Soort": "Amendement",
            "Titel": "Amendement over iets",
            "Volgnummer": 7,
            "Datum": "2024-03-01T00:00:00",
            "Zaak": [{"Id": "z-1", "Kamerstukdossier": [{"Nummer": 29684}]}],
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
    assert props["case_ids"] == ["z-1"]
    assert props["dossier_numbers"] == ["29684"]
    assert props["sequence"] == 7
    assert [a["person_id"] for a in props["actors"]] == ["p-1"]
    assert props["display_name"].startswith("Kamerstuk 29684, nr. 7 — Amendement")


def test_a_non_kamerstuk_document_has_no_volgnummer() -> None:
    _, props = tk_records.document({"Id": "doc-1", "Volgnummer": -1})
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


def test_a_faction_decision_tallies_seats() -> None:
    votes = [
        tk_records.vote(_vote(Soort="Voor", FractieGrootte=76)),
        tk_records.vote(_vote(Soort="Tegen", FractieGrootte=74, Fractie_Id="f-pvv")),
    ]
    _, props = tk_records.decision(
        "b-1", {"BesluitSoort": "Stemmen - aangenomen"}, votes
    )
    assert props["vote_kind"] == "faction"
    assert props["tally"] == {"Voor": 76, "Tegen": 74}
    assert props["voters"] == {"Voor": 1, "Tegen": 1}
    assert props["passed"] is True


def test_a_roll_call_counts_members_not_faction_sizes() -> None:
    votes = [
        tk_records.vote(_vote(Soort="Voor", FractieGrootte=34, Persoon_Id="p-1")),
        tk_records.vote(_vote(Soort="Voor", FractieGrootte=34, Persoon_Id="p-2")),
        tk_records.vote(_vote(Soort="Tegen", FractieGrootte=14, Persoon_Id="p-3")),
    ]
    _, props = tk_records.decision("b-1", {"StemmingsSoort": "Hoofdelijk"}, votes)
    assert props["vote_kind"] == "member"
    assert props["tally"] == {"Voor": 2, "Tegen": 1}
    assert props["passed"] is True


def test_the_outcome_falls_back_to_the_tally_when_the_source_is_silent() -> None:
    votes = [
        tk_records.vote(_vote(Soort="Voor", FractieGrootte=10)),
        tk_records.vote(_vote(Soort="Tegen", FractieGrootte=40, Fractie_Id="f-x")),
    ]
    _, props = tk_records.decision("b-1", {}, votes)
    assert props["passed"] is False


def test_a_decision_names_the_case_it_singled_out() -> None:
    decision = {
        "AgendapuntZaakBesluitVolgorde": 2,
        "Agendapunt": [
            {
                "Onderwerp": "Moties bij de Wet versterking regie volkshuisvesting",
                "Zaak": [
                    {"Id": "z-1", "Nummer": "2024Z01", "Soort": "Motie"},
                    {
                        "Id": "z-2",
                        "Nummer": "2024Z02",
                        "Soort": "Motie",
                        "Onderwerp": "openbaar maken wachtlijsten",
                    },
                ],
            }
        ],
    }
    _, props = tk_records.decision("b-1", decision, [tk_records.vote(_vote())])
    assert props["primary_case_id"] == "z-2"
    assert props["case_ids"] == ["z-1", "z-2"]
    assert props["subject"] == "openbaar maken wachtlijsten"
    assert props["display_name"] == "Motie 2024Z02 — openbaar maken wachtlijsten"


def test_siblings_on_one_agenda_item_fall_back_to_its_subject() -> None:
    decision = {
        "Agendapunt": [{"Onderwerp": "Stemmingen moties", "Zaak": [{"Id": "z-1"}]}]
    }
    _, props = tk_records.decision("b-1", decision, [tk_records.vote(_vote())])
    assert props["subject"] == "Stemmingen moties"


def test_a_vote_without_a_decision_is_skipped() -> None:
    assert tk_records.vote({"Soort": "Voor"}) is None


def test_a_vote_cast_is_a_slotted_object_with_shared_strings() -> None:
    """190K casts are kept until the VOTED edges are written: no dict per cast."""
    first = tk_records.vote(_vote(Soort="Voor", Fractie_Id="f-" + "vvd"))
    second = tk_records.vote(_vote(Soort="Vo" + "or", Fractie_Id="f-vvd"))
    assert first is not None and second is not None
    assert not hasattr(first, "__dict__")
    assert first.choice is second.choice and first.faction_id is second.faction_id


def test_a_document_says_which_source_it_is_from() -> None:
    """Every other source does; without it `/api/documents?source=tk` found none of the
    126,710 papers and `/api/stats` counted them as unknown."""
    _, props = tk_records.document({"Id": "doc-1", "Soort": "Motie"})  # type: ignore[misc]
    assert props["source"] == "tk"
