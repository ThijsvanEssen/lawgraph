"""What ties judgments of one case: a conclusion to its judgment, a preliminary ruling to the
decision that asked it. Pure functions, from the RDF header and the text of a judgment."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lawgraph.core.judgments import (
    Referral,
    case_number_keys,
    extract_rdf_metadata,
    read_referral,
)
from lawgraph.pipelines.semantic.rechtspraak_conclusions import (
    case_number_pairs,
    formal_pairs,
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
    assert read_referral(paragraphs) == Referral(
        case_keys=("c/19/117301/haza16-256",), date="2018-10-10"
    )


def test_several_cases_and_an_ecli_in_the_referral() -> None:
    zaken = read_referral(
        [
            {
                "text": "Bij tussenbeschikking in de zaken 8674876/EJ VERZ 20-213 en "
                "8675941 EJ VERZ 20-214 van 8 februari 2021 heeft de kantonrechter te "
                "Alkmaar op de voet van art. 392 RV prejudiciële vragen aan de Hoge Raad "
                "gesteld."
            }
        ]
    )
    assert zaken == Referral(
        case_keys=("8674876/ejverz20-213", "8675941ejverz20-214"), date="2021-02-08"
    )
    named = read_referral(
        [
            {
                "text": "Het hof heeft bij beslissing van 17 maart 2026 "
                "(ECLI:NL:GHSHE:2026:724) prejudiciële vragen gesteld."
            }
        ]
    )
    assert named == Referral(eclis=("ECLI:NL:GHSHE:2026:724",))
    assert read_referral([{"text": "De Hoge Raad beantwoordt de vragen."}]) is None


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
    referral = Referral(case_keys=("c/19/117301/haza16-256",), date="2018-10-10")
    rows = [
        {
            "key": "c/19/117301/haza16-256",
            "ecli": "ECLI:NL:RBNNE:2018:1",
            "date": "2018-10-10",
            "is_conclusion": False,
        },
        # an earlier judgment in the same case
        {
            "key": "c/19/117301/haza16-256",
            "ecli": "ECLI:NL:RBNNE:2017:9",
            "date": "2017-03-01",
            "is_conclusion": False,
        },
    ]
    assert by_case_number("ECLI:NL:HR:2019:1278", referral, rows) == [
        "ECLI:NL:RBNNE:2018:1"
    ]
