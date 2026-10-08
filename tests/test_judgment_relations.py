"""What ties judgments of one case: a conclusion to its judgment, a preliminary ruling to the
decision that asked it. Pure functions, from the RDF header and the text of a judgment."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from lawgraph.core.appeals import (
    AppealTarget,
    Instance,
    earlier_instance_relation,
    read_appeal_targets,
)
from lawgraph.core.judgments import (
    IndexEntry,
    Referral,
    case_number_keys,
    extract_rdf_metadata,
    read_referrals,
    same_case_number,
)
from lawgraph.pipelines.semantic.rechtspraak_conclusions import (
    case_number_pairs,
    formal_pairs,
    own_bench_pairs,
    own_bench_span,
)
from lawgraph.pipelines.semantic.rechtspraak_referrals import by_case_number

RDF = (
    '<open xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:psi="http://psi.rechtspraak.nl/" '
    'xmlns:ecli="https://e-justice.europa.eu/ecli"><rdf:RDF><rdf:Description>{}'
    "</rdf:Description></rdf:RDF></open>"
)


def _metadata(body: str) -> dict:
    meta, _ = extract_rdf_metadata(ET.fromstring(RDF.format(body)))
    return meta


def test_a_judgment_names_its_conclusion_apart_from_its_earlier_instances() -> None:
    # the header of ECLI:NL:HR:2019:1278
    meta = _metadata(
        '<dcterms:type resourceIdentifier="http://psi.rechtspraak.nl/uitspraak">Uitspraak'
        "</dcterms:type><psi:procedure>Prejudiciële beslissing</psi:procedure>"
        '<dcterms:relation ecli:resourceIdentifier="ECLI:NL:PHR:2019:496" '
        'psi:type="http://psi.rechtspraak.nl/conclusie" '
        'psi:aanleg="http://psi.rechtspraak.nl/eerdereAanleg">Conclusie: '
        "ECLI:NL:PHR:2019:496</dcterms:relation>"
    )
    assert meta["document_type"] == "Uitspraak"
    assert meta["type"] == "Prejudiciële beslissing"
    assert meta["conclusion_eclis"] == ["ECLI:NL:PHR:2019:496"]
    assert "related_eclis" not in meta


def test_a_conclusion_names_its_judgment() -> None:
    # the header of ECLI:NL:PHR:2019:496
    meta = _metadata(
        '<dcterms:type resourceIdentifier="http://psi.rechtspraak.nl/conclusie">Conclusie'
        '</dcterms:type><dcterms:relation ecli:resourceIdentifier="ECLI:NL:HR:2019:1278" '
        'psi:type="http://psi.rechtspraak.nl/conclusie" '
        'psi:aanleg="http://psi.rechtspraak.nl/latereAanleg">Arrest Hoge Raad: '
        "ECLI:NL:HR:2019:1278</dcterms:relation>"
    )
    assert meta["document_type"] == "Conclusie"
    assert meta["conclusion_eclis"] == ["ECLI:NL:HR:2019:1278"]


def test_a_judgment_names_its_later_instances_apart_from_its_earlier_ones() -> None:
    # a rechtbank whose judgment the hof ruled on (latereAanleg), after its own interim one
    meta = _metadata(
        '<dcterms:relation ecli:resourceIdentifier="ECLI:NL:GHAMS:2026:100" '
        'psi:type="http://psi.rechtspraak.nl/hogerBeroep" '
        'psi:aanleg="http://psi.rechtspraak.nl/latereAanleg">Uitspraak hoger beroep: '
        "ECLI:NL:GHAMS:2026:100</dcterms:relation>"
        '<dcterms:relation ecli:resourceIdentifier="ECLI:NL:RBAMS:2024:9" '
        'psi:type="http://psi.rechtspraak.nl/tussenuitspraak" '
        'psi:aanleg="http://psi.rechtspraak.nl/eerdereAanleg">Tussenuitspraak: '
        "ECLI:NL:RBAMS:2024:9</dcterms:relation>"
    )
    assert meta["later_eclis"] == ["ECLI:NL:GHAMS:2026:100"]
    assert meta["related_eclis"] == ["ECLI:NL:RBAMS:2024:9"]


def test_case_numbers_are_compared_without_spaces_or_case() -> None:
    assert case_number_keys("C/19/117301 / HA ZA 16-256") == ["c/19/117301/haza16-256"]
    assert case_number_keys("18/04298 en 18/04299") == ["18/04298", "18/04299"]
    assert case_number_keys("200.1, 200.2") == ["200.1", "200.2"]
    assert case_number_keys(None) == []


def test_the_referral_is_read_from_the_paragraph_that_says_questions_were_asked() -> (
    None
):
    paragraphs = [
        {"text": "advocaat in de prejudiciële procedure: mr. H.J.W. Alt,"},
        {
            "text": "Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober "
            "2018 heeft de rechtbank Assen op de voet van art. 392 Rv prejudiciële vragen "
            "aan de Hoge Raad gesteld."
        },
    ]
    assert read_referrals(paragraphs) == [
        Referral(case_numbers=("C/19/117301/HA ZA 16-256",), date="2018-10-10")
    ]


def test_several_cases_and_an_ecli_in_the_referral() -> None:
    zaken = read_referrals(
        [
            {
                "text": "Bij tussenbeschikking in de zaken 8674876/EJ VERZ 20-213 en "
                "8675941 EJ VERZ 20-214 van 8 februari 2021 heeft de kantonrechter te "
                "Alkmaar op de voet van art. 392 RV prejudiciële vragen aan de Hoge Raad "
                "gesteld."
            }
        ]
    )
    assert zaken == [
        Referral(
            case_numbers=("8674876/EJ VERZ 20-213", "8675941 EJ VERZ 20-214"),
            date="2021-02-08",
        )
    ]
    named = read_referrals(
        [
            {
                "text": "Het hof heeft bij beslissing van 17 maart 2026 "
                "(ECLI:NL:GHSHE:2026:724) prejudiciële vragen gesteld."
            }
        ]
    )
    assert named == [Referral(eclis=("ECLI:NL:GHSHE:2026:724",))]
    assert read_referrals([{"text": "De Hoge Raad beantwoordt de vragen."}]) == []


def test_a_ruling_that_answers_two_courts_names_both() -> None:
    """ECLI:NL:HR:2021:1677, paragraphs 27 and 31."""
    assert read_referrals(
        [
            {
                "text": "Bij tussenvonnis in de zaak 87166635/CV EXPL 20-5415 van 24 "
                "november 2020 heeft de kantonrechter te Leeuwarden op de voet van art. "
                "392 RV prejudiciële vragen aan de Hoge Raad gesteld."
            },
            {"text": "De conclusie strekt tot beantwoording van de vragen."},
            {
                "text": "Bij tussenvonnis in de zaak 7926895 CV EXPL 19-16007 van 21 "
                "december 2020 heeft de kantonrechter te Amsterdam op de voet van art. "
                "392 RV prejudiciële vragen aan de Hoge Raad gesteld."
            },
        ]
    ) == [
        Referral(case_numbers=("87166635/CV EXPL 20-5415",), date="2020-11-24"),
        Referral(case_numbers=("7926895 CV EXPL 19-16007",), date="2020-12-21"),
    ]


def test_the_date_can_come_before_the_case_number() -> None:
    """ECLI:NL:HR:2025:1799 and ECLI:NL:RVS:2023:3617."""
    assert read_referrals(
        [
            {
                "text": "Bij tussenvonnis van 14 november 2024 met zaaknummer C/15/351661 "
                "/ KG ZA 24-199 heeft de rechtbank Noord-Holland op de voet van art. 392 "
                "Rv prejudiciële vragen aan de Hoge Raad gesteld."
            },
            {
                "text": "Bij tussenuitspraak van 28 april 2023, in zaak nr. 22/2463T, heeft "
                "de rechtbank Noord-Nederland op grond van art. 16 van de Tijdelijke wet "
                "Groningen (TwG) prejudiciële vragen aan de Afdeling gesteld."
            },
        ]
    ) == [
        Referral(case_numbers=("C/15/351661 / KG ZA 24-199",), date="2024-11-14"),
        Referral(case_numbers=("22/2463T",), date="2023-04-28"),
    ]


def test_an_older_ruling_refers_to_the_last_named_decision() -> None:
    """ECLI:NL:HR:2016:2998: the procedure is told by reference, the questions follow."""
    assert read_referrals(
        [
            {
                "text": "Voor het verloop van het geding in feitelijke instantie verwijst "
                "de Hoge Raad naar de beschikkingen in de zaak 4986381\\EJ VERZ 16-142 en "
                "5026511\\EJ VERZ 16-163 van de kantonrechter te Enschede van 26 april "
                "2016 en 20 mei 2016."
            },
            {
                "text": "De beschikkingen van de kantonrechter zijn aan deze beslissing gehecht."
            },
            {
                "text": "In haar laatstgenoemde beschikking heeft de kantonrechter op de "
                "voet van art. 392 Rv de volgende prejudiciële vragen aan de Hoge Raad "
                "gesteld:"
            },
        ]
    ) == [
        Referral(
            case_numbers=("4986381\\EJ VERZ 16-142", "5026511\\EJ VERZ 16-163"),
            date="2016-05-20",
        )
    ]


def test_the_criminal_chamber_names_the_parketnummers_in_its_heading() -> None:
    """ECLI:NL:HR:2023:913; the referral of the other court names no number."""
    assert read_referrals(
        [
            {
                "text": "PREJUDICIËLE BESLISSING (Zaak 23/00010 PJV) op de door de "
                "rechtbank Noord-Nederland bij beslissing van 19 december 2022, nummers "
                "18-018510-21, 18-298097-21 en 18-298079-21, gestelde rechtsvragen in de "
                "zaken van [verdachte 1]"
            },
            {
                "text": "De rechtbank Overijssel heeft bij beslissing van 30 december 2022 "
                "een prejudiciële vraag gesteld aan de Hoge Raad."
            },
        ]
    ) == [
        Referral(
            case_numbers=("18-018510-21", "18-298097-21", "18-298079-21"),
            date="2022-12-19",
        )
    ]


@pytest.mark.parametrize(
    ("named", "listed"),
    [
        # punctuation and spaces
        ("C/09/610280/ KG ZA 21/346", "C-09-610280-KG ZA 21-346"),
        # a suffix, and the initials of the clerk
        ("200.273.775/01", "200.273.775"),
        ("C/13/694440 / KG ZA 20-1118 MvW/JE", "C/13/694440 / KG ZA 20-1118"),
        # a roll number within a longer one, and a parketnummer
        ("22/2463T", "LEE 22/2463T"),
        ("18-018510-21", "18/018510-21"),
        # one of the numbers of the index title
        ("8674876/EJ VERZ 20-213", "8674876 EJ VERZ 20-213, 8675941 EJ VERZ 20-214"),
    ],
)
def test_the_same_case_number_written_otherwise(named: str, listed: str) -> None:
    assert same_case_number(named, listed)


@pytest.mark.parametrize(
    ("named", "listed"),
    [
        # the same roll number, another court's number
        ("8527084 VZ VERZ 20-9656", "8527085 CV EXPL 20-9656"),
        ("22/2463T", "22/2463"),
        ("C/09/610280", "C/09/610281"),
        ("SXM2018H00025", None),
    ],
)
def test_another_case_number(named: str, listed: str | None) -> None:
    assert not same_case_number(named, listed)


def test_the_case_numbers_of_an_index_title_follow_the_date() -> None:
    title = (
        "ECLI:NL:OGHACMB:2021:108, Gemeenschappelijk Hof van Justitie van Aruba, "
        "Curaçao, Sint Maarten en van Bonaire, Sint Eustatius en Saba, 04-05-2021, "
        "SXM2018H00025"
    )
    entry = IndexEntry(ecli="ECLI:NL:OGHACMB:2021:108", updated=None, title=title)
    assert entry.case_numbers == "SXM2018H00025"
    assert IndexEntry(ecli="x", updated=None, title="x").case_numbers == ""


def test_a_formal_relation_counts_from_either_side() -> None:
    rows = [
        {
            "ecli": "ECLI:NL:HR:2019:1278",
            "is_conclusion": False,
            "conclusion_eclis": ["ECLI:NL:PHR:2019:496"],
        },
        {
            "ecli": "ECLI:NL:PHR:2019:496",
            "is_conclusion": True,
            "conclusion_eclis": ["ECLI:NL:HR:2019:1278"],
        },
    ]
    assert formal_pairs(rows) == {("ECLI:NL:PHR:2019:496", "ECLI:NL:HR:2019:1278")}


def test_a_conclusion_goes_to_the_judgment_of_its_bench_with_its_case_number() -> None:
    conclusion = {
        "ecli": "ECLI:NL:PHR:2020:1",
        "court_code": "PHR",
        "case_number_keys": ["19/00001"],
    }
    candidates = [
        {
            "key": "19/00001",
            "ecli": "ECLI:NL:HR:2020:2",
            "court_code": "HR",
            "is_conclusion": False,
        },
        # the conclusion itself, and a court of appeal with the same number
        {
            "key": "19/00001",
            "ecli": "ECLI:NL:PHR:2020:1",
            "court_code": "PHR",
            "is_conclusion": True,
        },
        {
            "key": "19/00001",
            "ecli": "ECLI:NL:GHAMS:2019:5",
            "court_code": "GHAMS",
            "is_conclusion": False,
        },
    ]
    assert case_number_pairs([conclusion], candidates) == {
        ("ECLI:NL:PHR:2020:1", "ECLI:NL:HR:2020:2")
    }


def test_the_referring_decision_has_the_case_number_and_the_date() -> None:
    referral = Referral(case_numbers=("C/19/117301/HA ZA 16-256",), date="2018-10-10")
    rows = [
        {
            "ecli": "ECLI:NL:RBNNE:2018:1",
            "date": "2018-10-10",
            "case_number": "C/19/117301 / HA ZA 16-256",
        },
        # an earlier judgment in the same case, and another case of that day
        {
            "ecli": "ECLI:NL:RBNNE:2017:9",
            "date": "2017-03-01",
            "case_number": "C/19/117301 / HA ZA 16-256",
        },
        {
            "ecli": "ECLI:NL:RBNNE:2018:2",
            "date": "2018-10-10",
            "case_number": "C/19/117302 / HA ZA 16-257",
        },
    ]
    assert by_case_number("ECLI:NL:HR:2019:1278", referral, rows) == [
        "ECLI:NL:RBNNE:2018:1"
    ]


def test_a_formal_relation_to_a_judgment_that_is_no_conclusion_ties_nothing() -> None:
    # ECLI:NL:RVS:2014:188 and ECLI:NL:CBB:2014:291 call each other the conclusion
    rows = [
        {
            "ecli": "ECLI:NL:RVS:2014:188",
            "is_conclusion": False,
            "conclusion_eclis": ["ECLI:NL:CBB:2014:291"],
        },
        {
            "ecli": "ECLI:NL:CBB:2014:291",
            "is_conclusion": False,
            "conclusion_eclis": ["ECLI:NL:CBB:2014:3", "ECLI:NL:RVS:2014:188"],
        },
    ]
    loaded = frozenset({"ECLI:NL:RVS:2014:188", "ECLI:NL:CBB:2014:291"})
    assert formal_pairs(rows, loaded) == {
        ("ECLI:NL:CBB:2014:3", "ECLI:NL:CBB:2014:291")
    }


def test_a_court_that_advises_itself_has_its_judgment_under_the_dossier_number() -> (
    None
):
    conclusion = {
        "ecli": "ECLI:NL:RVS:2016:1421",
        "court_code": "RVS",
        "date": "2016-05-25",
        "case_number": "201406676/2/A3",
    }
    candidates = [
        {
            "court_code": "RVS",
            "ecli": "ECLI:NL:RVS:2016:2927",
            "date": "2016-11-02",
            "case_number": "201406676/1/A3",
        },
        # another dossier; and the dossier before the conclusion
        {
            "court_code": "RVS",
            "ecli": "ECLI:NL:RVS:2016:2928",
            "date": "2016-11-02",
            "case_number": "201406677/1/A3",
        },
        {
            "court_code": "RVS",
            "ecli": "ECLI:NL:RVS:2015:1",
            "date": "2015-01-07",
            "case_number": "201406676/1/A3",
        },
    ]
    assert own_bench_span(conclusion) == {
        "court_code": "RVS",
        "start": "2016-05-25",
        "end": "2019-05-25",
    }
    assert own_bench_pairs([conclusion], candidates) == {
        ("ECLI:NL:RVS:2016:1421", "ECLI:NL:RVS:2016:2927")
    }
    # the Parket bij de Hoge Raad advises another court: its case numbers are the same
    assert own_bench_span({**conclusion, "court_code": "PHR"}) is None


@pytest.mark.parametrize(
    ("later", "earlier", "relation"),
    [
        # the hof of the rechtbank
        (
            Instance("ECLI:NL:GHDHA:2020:1", "200.1/01"),
            Instance("ECLI:NL:RBDHA:2019:1", "C/09/1"),
            "APPEAL_OF",
        ),
        # interim and final judgment: one court, one case (the number written otherwise)
        (
            Instance("ECLI:NL:GHARL:2026:5720", "200.335.407/01"),
            Instance("ECLI:NL:GHARL:2024:7481", "200.335.407"),
            "CONTINUES",
        ),
        # the hof after referral, and one whose Hoge Raad ruling is not loaded
        (
            Instance("ECLI:NL:GHDHA:2021:1023", "200.278.757/01"),
            Instance("ECLI:NL:HR:2019:1858", "18/03295", procedure="Cassatie"),
            "REFERRED_BY",
        ),
        (
            Instance("ECLI:NL:GHSHE:2021:1620", "200.280.190_01"),
            Instance("ECLI:NL:HR:2020:809"),
            "REFERRED_BY",
        ),
        # the Hoge Raad itself, in another case: as before
        (
            Instance("ECLI:NL:HR:2022:1241", "21/04162"),
            Instance("ECLI:NL:HR:2021:1427", "20/01396"),
            "APPEAL_OF",
        ),
        # the answer to the questions the hof asked; a conclusion
        (
            Instance("ECLI:NL:GHSHE:2025:74", "22/148"),
            Instance(
                "ECLI:NL:HR:2024:1299", "24/00806", procedure="Prejudiciële beslissing"
            ),
            None,
        ),
        (
            Instance("ECLI:NL:HR:2020:1", "19/00001"),
            Instance("ECLI:NL:PHR:2019:9", "19/00001", is_conclusion=True),
            None,
        ),
        # a later instance the metadata does not call one (ECLI:NL:GHAMS:2015:5823)
        (
            Instance("ECLI:NL:GHAMS:2015:5823", "23-000949-15", date="2015-07-29"),
            Instance("ECLI:NL:HR:2017:236", "16/00223", date="2017-02-14"),
            None,
        ),
    ],
)
def test_what_an_earlier_instance_is(
    later: Instance, earlier: Instance, relation: str | None
) -> None:
    assert earlier_instance_relation(later, earlier) == relation


@pytest.mark.parametrize(
    ("text", "targets"),
    [
        (
            "Uitspraak op de hoger beroepen van: 1. de minister, appellanten, tegen de "
            "uitspraak van de rechtbank Gelderland van 9 juli 2025 in zaak nr. 24/6811 in "
            "het geding tussen: [appellant] en de minister.",
            [AppealTarget("rechtbank Gelderland", "2025-07-09", "24/6811")],
        ),
        (
            "gewezen op het hoger beroep, ingesteld tegen het vonnis van de "
            "arrondissementsrechtbank te 's-Hertogenbosch van 2 mei 2000 in de strafzaak "
            "onder parketnummer 01/034668-97 tegen: [verdachte]",
            [
                AppealTarget(
                    "arrondissementsrechtbank te 's-Hertogenbosch",
                    "2000-05-02",
                    "01/034668-97",
                )
            ],
        ),
        (
            "op het hoger beroep tegen de beslissing van de kantonrechter van de rechtbank "
            "Rotterdam van 5 april 2011 betreffende [betrokkene]",
            [AppealTarget("kantonrechter van de rechtbank Rotterdam", "2011-04-05")],
        ),
        # a seat after the court, a soft hyphen in its name
        (
            "tegen de uitspraak van de rechtbank Den Haag, zittingsplaats Rotterdam, van 18 "
            "juli 2013 in zaak nr. 13/252 en tegen de uitspraak van de rechtbank "
            "Noord­-Nederland van 23 februari 2023 in zaak nr. 22/2160",
            [
                AppealTarget(
                    "rechtbank Den Haag, zittingsplaats Rotterdam",
                    "2013-07-18",
                    "13/252",
                ),
                AppealTarget("rechtbank Noord-Nederland", "2023-02-23", "22/2160"),
            ],
        ),
        # the decision of an administrative body is no decision appealed
        (
            "Appellant heeft beroep ingesteld tegen de beschikking van het college van "
            "burgemeester en wethouders van 3 mei 2020.",
            [],
        ),
    ],
)
def test_an_appeal_names_the_decision_it_appeals(
    text: str, targets: list[AppealTarget]
) -> None:
    assert read_appeal_targets([{"text": "Procesverloop"}, {"text": text}]) == targets


def test_the_decision_appealed_has_the_date_and_the_case_number() -> None:
    target = AppealTarget("rechtbank Den Haag", "2025-03-03", "24/1234")
    assert target.is_decision({"date": "2025-03-03", "case_number": "SGR 24/1234"})
    assert not target.is_decision({"date": "2025-03-03", "case_number": "SGR 24/1235"})
    assert not target.is_decision({"date": "2025-03-04", "case_number": "SGR 24/1234"})
    assert not AppealTarget("rechtbank Den Haag", "2025-03-03").is_decision(
        {"date": "2025-03-03", "case_number": "SGR 24/1234"}
    )
