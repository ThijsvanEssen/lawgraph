"""The kind of a decision, the language of a summary and the names of a judgment: pure rules
over the metadata and the kop, and over real judgments of the Rechtspraak."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from lawgraph.api.schemas.judgments import DecisionKind
from lawgraph.core.judgment_names import CURATED_NAMES, judgment_names
from lawgraph.core.judgments import (
    DECISION_KINDS,
    KIND_OF_TIER,
    TIERS,
    decision_kind,
    derive_court_tier,
    extract_judgment_text,
    extract_rdf_metadata,
    is_english,
    kind_in_kop,
    kop_lines,
    parse_judgment,
    translated_case_number,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _kind(
    *,
    document_type: str | None = "Uitspraak",
    procedure: str | None = None,
    kop: list[str] | None = None,
    tier: str | None = None,
    subjects: list[str] | None = None,
) -> str | None:
    return decision_kind(
        document_type=document_type,
        procedure=procedure,
        kop=kop or [],
        tier=tier,
        subjects=subjects,
    )


def test_a_conclusion_and_a_preliminary_ruling_are_named_by_the_metadata() -> None:
    assert _kind(document_type="Conclusie", kop=["ARREST"], tier="parket") == (
        "conclusie"
    )
    assert _kind(procedure="Prejudiciële beslissing", kop=["ARREST"]) == (
        "prejudiciële beslissing"
    )


@pytest.mark.parametrize(
    ("kop", "kind"),
    [
        (["HOGE RAAD DER NEDERLANDEN", "ARREST", "in de zaak van"], "arrest"),
        (["RECHTBANK AMSTERDAM", "Tussenvonnis van 3 mei 2024"], "vonnis"),
        (["uitspraak van de enkelvoudige kamer van 12 maart 2025"], "uitspraak"),
        (["Uitspraak op het hoger beroep van:"], "uitspraak"),
        (["beschikking van de meervoudige kamer"], "beschikking"),
        # a label with its value names no kind: the date of the decision
        (["Uitspraak : 10 augustus 2026", "Arrest van de meervoudige kamer"], "arrest"),
        (["Uitspraak d.d. : 28 augustus 2026", "Arrest op het hoger beroep"], "arrest"),
        (["Datum uitspraak: 1 mei 2020"], None),
        # a date only, above the line that names the kind; alone it still counts
        (
            ["Uitspraak van 21 september 2026", "Arrest van de meervoudige kamer"],
            "arrest",
        ),
        (["arrest van 8 september 2026", "inzake"], "arrest"),
    ],
)
def test_the_kop_names_the_kind(kop: list[str], kind: str | None) -> None:
    assert kind_in_kop(kop) == kind


def test_the_kop_goes_before_the_procedure_and_the_procedure_before_the_court() -> None:
    assert _kind(procedure="Beschikking", kop=["Uitspraak"], tier="rechtbank") == (
        "uitspraak"
    )
    assert _kind(procedure="Beschikking", tier="hoge_raad") == "beschikking"
    assert _kind(procedure="Cassatie", tier="hoge_raad") == "arrest"


@pytest.mark.parametrize(
    ("tier", "subjects", "kind"),
    [
        ("hoge_raad", ["Bestuursrecht; Belastingrecht"], "arrest"),
        ("gerechtshof", ["Civiel recht"], "arrest"),
        ("gerechtshof", ["Bestuursrecht; Belastingrecht"], "uitspraak"),
        ("rechtbank", ["Strafrecht"], "vonnis"),
        ("rechtbank", ["Bestuursrecht; Vreemdelingenrecht"], "uitspraak"),
        ("raad_van_state", [], "uitspraak"),
        ("centrale_raad_van_beroep", ["Bestuursrecht"], "uitspraak"),
        ("parket", [], "conclusie"),
        ("ehrm", [], "arrest"),
        ("kroon", [], None),
        (None, [], None),
    ],
)
def test_without_metadata_the_court_and_the_area_of_law_tell(
    tier: str | None, subjects: list[str], kind: str | None
) -> None:
    assert _kind(tier=tier, subjects=subjects) == kind


def test_the_kinds_are_those_of_the_api_and_every_tier_is_a_real_one() -> None:
    assert set(get_args(DecisionKind)) == set(DECISION_KINDS)
    assert set(KIND_OF_TIER) <= set(TIERS)
    assert set(KIND_OF_TIER.values()) <= set(DECISION_KINDS)


@pytest.mark.parametrize(
    ("name", "ecli", "kind"),
    [
        # "Uitspraak : 10 augustus 2026" comes before "Arrest van de meervoudige kamer"
        ("rechtspraak_ghshe_2026_2210.xml", "ECLI:NL:GHSHE:2026:2210", "arrest"),
        ("rechtspraak_hr_2019_2006.xml", "ECLI:NL:HR:2019:2006", "arrest"),
        # an old judgment without a kop the reader can tell apart
        ("rechtspraak_hr_1965_ab7079.xml", "ECLI:NL:HR:1965:AB7079", "arrest"),
        # "Uitspraak van 21 september 2026" comes before "Arrest van de meervoudige kamer"
        ("rechtspraak_gharl_2026_6060.xml", "ECLI:NL:GHARL:2026:6060", "arrest"),
        ("rechtspraak_ghams_2026_2707.xml", "ECLI:NL:GHAMS:2026:2707", "beschikking"),
        (
            "rechtspraak_hr_2019_1278.xml",
            "ECLI:NL:HR:2019:1278",
            "prejudiciële beslissing",
        ),
        ("rechtspraak_rvs_2026_5668.xml", "ECLI:NL:RVS:2026:5668", "uitspraak"),
        ("rechtspraak_rbams_2024_81.xml", "ECLI:NL:RBAMS:2024:81", "vonnis"),
        ("rechtspraak_rbams_2025_3600.xml", "ECLI:NL:RBAMS:2025:3600", "uitspraak"),
    ],
)
def test_the_kind_of_real_judgments(name: str, ecli: str, kind: str) -> None:
    root = parse_judgment((FIXTURES / name).read_text())
    meta, subjects = extract_rdf_metadata(root)
    _, tier = derive_court_tier(ecli, meta.get("court"))
    found = decision_kind(
        document_type=meta.get("document_type"),
        procedure=meta.get("type"),
        kop=kop_lines(root),
        tier=tier,
        subjects=subjects,
    )
    assert found == kind


def _summary(name: str) -> str | None:
    return extract_judgment_text(parse_judgment((FIXTURES / name).read_text()))[0]


def test_the_english_translation_has_an_english_summary() -> None:
    assert is_english(_summary("rechtspraak_hr_2019_2007.xml"))
    assert not is_english(_summary("rechtspraak_hr_2019_2006.xml"))


@pytest.mark.parametrize(
    "text",
    [
        "Toepassing artikel 9a Sr.",
        "Art. 8:69a Awb i.v.m. art. 17 Wet WOZ.",
        "OK; Enquete; afwijzing verzoek nadere onmiddellijke voorzieningen; 2:349a BW",
        "Gezag en omgang. Verzoek tot beëindiging gezamenlijk gezag. Is dat in het "
        "belang van het kind? Of niet?",
        "",
    ],
)
def test_a_short_dutch_summary_is_not_english(text: str) -> None:
    assert not is_english(text)


@pytest.mark.parametrize(
    ("case_number", "original"),
    [
        ("19/00135 (Engels)", "19/00135"),
        ("200.178.245/01 (Engelse vertaling)", "200.178.245/01"),
        (
            "C/09/456689 / HA ZA 13-1396 (English translation)",
            "C/09/456689 / HA ZA 13-1396",
        ),
        ("19/00135", None),
        (None, None),
    ],
)
def test_the_case_number_a_translation_translates(
    case_number: str | None, original: str | None
) -> None:
    assert translated_case_number(case_number) == original


def test_a_landmark_judgment_has_its_names_and_another_none() -> None:
    assert judgment_names("ECLI:NL:HR:1981:AG4158") == ["Haviltex"]
    assert judgment_names("ecli:nl:hr:1919:ag1776") == ["Lindenbaum/Cohen"]
    assert judgment_names("ECLI:NL:HR:2019:2007") == ["Urgenda"]
    assert judgment_names("ECLI:NL:HR:2020:1") == []
    assert judgment_names(None) == []


def test_the_curated_names_are_keyed_by_ecli() -> None:
    ecli = re.compile(r"^ECLI:NL:[A-Z]+:\d{4}:[A-Z0-9]+$")
    assert all(ecli.match(key) for key in CURATED_NAMES)
    assert all(
        names and all(n.strip() == n for n in names) for names in CURATED_NAMES.values()
    )
