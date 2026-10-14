"""What every reader of an ECLI finds, pinned per caller: the keys judgments are stored under,
the court code, the shape a query or an address must have, and the ECLIs a referral, a
summary and the curated names give."""

from __future__ import annotations

import pytest

from lawgraph.core.appeals import Instance, earlier_instance_relation
from lawgraph.core.judgment_cite import court_cite
from lawgraph.core.judgments import derive_court, read_referrals
from lawgraph.core.models import make_node_key
from lawgraph.core.notation import NotationParser
from lawgraph.core.readable_paths import parse_path, path_of
from lawgraph.core.related_cases import read_related_cases

# The key a judgment is stored under: the stored keys must never change.
STORED_KEYS = {
    "ECLI:NL:HR:2019:2006": "ecli_nl_hr_2019_2006",
    "ECLI:NL:RBDHA:2015:7145": "ecli_nl_rbdha_2015_7145",
    "ECLI:NL:CRVB:2010:BK9271": "ecli_nl_crvb_2010_bk9271",
    "ECLI:EU:C:2014:2041": "ecli_eu_c_2014_2041",
    "ECLI:CE:ECHR:2019:0101JUD001234510": "ecli_ce_echr_2019_0101jud001234510",
    "ECLI:BE:CASS:2019:ARR.20190101.1": "ecli_be_cass_2019_arr_20190101_1",
    "ECLI:DE:BGH:2020:010120UIZR1.20.0": "ecli_de_bgh_2020_010120uizr1_20_0",
}


@pytest.mark.parametrize(("ecli", "key"), STORED_KEYS.items())
def test_the_stored_key_of_an_ecli(ecli: str, key: str) -> None:
    assert make_node_key(ecli) == key


@pytest.mark.parametrize(
    ("ecli", "code", "cite"),
    [
        ("ECLI:NL:HR:2019:1858", "HR", "HR"),
        ("ecli:nl:gharl:2020:1", "GHARL", "Hof Arnhem-Leeuwarden"),
        ("ECLI:NL:RBDHA:2020:1", "RBDHA", "Rb. Den Haag"),
        ("ECLI:CE:ECHR:2019:1", "ECHR", "EHRM"),
        ("ECLI:EU:T:2019:1", "T", "Gerecht EU"),
        ("ECLI:EU:C:2019:1", "C", "HvJ EU"),
    ],
)
def test_the_court_code_each_reader_takes(ecli: str, code: str, cite: str) -> None:
    assert derive_court(ecli)[0] == code
    names = {"GHARL": "Gerechtshof Arnhem-Leeuwarden", "RBDHA": "Rechtbank Den Haag"}
    assert court_cite(ecli, names.get(code)) == cite


def test_a_missing_court_code() -> None:
    assert derive_court("ECLI:NL") == (None, None, None)
    assert derive_court(None) == (None, None, None)
    assert court_cite("ECLI:NL", "Rechtbank Den Haag") == "Rechtbank Den Haag"
    assert court_cite("ECLI") == ""


@pytest.mark.parametrize(
    ("later", "earlier", "relation"),
    [
        ("ECLI:NL:GHARL:2020:1", "ECLI:NL:HR:2019:1", "REFERRED_BY"),
        ("ecli:nl:hr:2020:2", "ECLI:NL:HR:2019:1", "CONTINUES"),
        ("ECLI:NL:HR:2020:2", "ECLI:NL:GHARL:2019:1", "APPEAL_OF"),
        ("ECLI:NL:GHARL:2020:2", "ECLI:NL:GHARL:2019:1", "CONTINUES"),
        ("ECLI:NL:GHARL:2020:2", "ECLI:NL", "APPEAL_OF"),
        ("ECLI:NL", "ECLI", "CONTINUES"),
    ],
)
def test_an_appeal_is_read_from_the_court_codes(
    later: str, earlier: str, relation: str
) -> None:
    def instance(ecli: str) -> Instance:
        return Instance(ecli, case_number="19/1", case_number_keys=("19/1",))

    assert earlier_instance_relation(instance(later), instance(earlier)) == relation


@pytest.mark.parametrize(
    ("query", "ecli"),
    [
        ("ECLI:NL:HR:2019:2006", "ECLI:NL:HR:2019:2006"),
        (" ecli:nl:rbams:2020:ab.12 ", "ECLI:NL:RBAMS:2020:AB.12"),
        ("ECLI:CE:ECHR:2019:0101JUD001234510", "ECLI:CE:ECHR:2019:0101JUD001234510"),
        ("ECLI:NL:HR:2009:BH", "ECLI:NL:HR:2009:BH"),
        ("ECLI:NL:HR:20:1234", None),
        ("ECLI:NL:HR:2019:2006 en meer", None),
        ("ECLI:NL:HR:2019:", None),
    ],
)
def test_a_query_that_is_an_ecli(query: str, ecli: str | None) -> None:
    from lawgraph.db.queries.judgments import JudgmentFilters, _exact_filters

    found = _exact_filters(JudgmentFilters(q=query.strip()))
    assert (found.ecli if found else None) == ecli
    notation = NotationParser({}, {}).parse(query)
    assert (
        notation.identifier if notation and notation.kind == "ecli" else None
    ) == ecli


@pytest.mark.parametrize(
    ("path", "ecli"),
    [
        ("/uitspraken/ECLI:NL:HR:2019:2006", "ECLI:NL:HR:2019:2006"),
        (
            "/uitspraken/ecli:be:cass:2019:arr.20190101.1",
            "ECLI:BE:CASS:2019:ARR.20190101.1",
        ),
        ("/uitspraken/ECLI:NL:HR:2019:.", "ECLI:NL:HR:2019:."),
        ("/uitspraken/ECLI:NL:HR:2019:20_06", None),
        ("/uitspraken/ECLI:NL:HR:2019:20-06", None),
        ("/uitspraken/ECLI:NLD:HR:2019:2006", None),
        ("/uitspraken/ECLI:NL:HR:19:2006", None),
    ],
)
def test_an_address_that_is_an_ecli(path: str, ecli: str | None) -> None:
    pad = parse_path(path)
    assert (pad.a if pad else None) == ecli


@pytest.mark.parametrize(
    ("key", "props", "path"),
    [
        ("ecli_nl_hr_2019_2006", {}, "/uitspraken/ECLI:NL:HR:2019:2006"),
        ("ecli_be_cass_2019_arr_20190101_1", {}, None),
        ("ecli_nl_hr_2019", {}, None),
        (
            "x",
            {"ecli": "ECLI:BE:CASS:2019:ARR.20190101.1"},
            "/uitspraken/ECLI:BE:CASS:2019:ARR.20190101.1",
        ),
        ("x", {"ecli": "ECLI:NL:HR:2019:20_06"}, None),
    ],
)
def test_the_address_of_a_judgment(
    key: str, props: dict[str, str], path: str | None
) -> None:
    assert path_of(f"judgments/{key}", props) == path


# The paragraphs of preliminary rulings as they name the decision that asked: an ECLI
# in the middle of a sentence, two, a lower-case one, and forms only the repairing
# reader would read (a range, a glued word, an LJN set apart).
REFERRALS = [
    (
        "Bij uitspraak van 1 mei 2020, ECLI:NL:RBDHA:2020:1234, heeft de rechtbank "
        "prejudiciële vragen gesteld.",
        ("ECLI:NL:RBDHA:2020:1234",),
    ),
    (
        "De rechtbanken hebben bij ECLI:NL:RBAMS:2021:1 en ecli:nl:rbrot:2021:22 "
        "prejudiciële vragen aan de Hoge Raad gesteld.",
        ("ECLI:NL:RBAMS:2021:1", "ECLI:NL:RBROT:2021:22"),
    ),
    (
        "Prejudiciële vragen gesteld in ECLI:EU:C:2019:1 en ECLI:NL:GHARL:2019:9.",
        ("ECLI:NL:GHARL:2019:9",),
    ),
    (
        "Bij ECLI:NL:RBOVE:2011:BQ1234 zijn prejudiciële vragen gesteld.",
        ("ECLI:NL:RBOVE:2011:BQ1234",),
    ),
]


@pytest.mark.parametrize(("text", "eclis"), REFERRALS)
def test_the_eclis_a_referral_names(text: str, eclis: tuple[str, ...]) -> None:
    (referral,) = read_referrals([{"text": text}])
    assert referral.eclis == eclis


def test_the_eclis_a_summary_names_as_the_courts_abbreviate_them() -> None:
    (related,) = read_related_cases(
        "Zie ook: HR:2025:404, ECLI:NL:HR:2024:12 en de zaken 24/03860 en 24/03861."
    )
    assert related.eclis == ["ECLI:NL:HR:2025:404", "ECLI:NL:HR:2024:12"]
    assert related.case_numbers == [["24/03860"], ["24/03861"]]
