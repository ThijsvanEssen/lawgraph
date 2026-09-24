"""Cabinet posts from Wikidata, and which Tweede Kamer person they belong to."""

from __future__ import annotations

from lawgraph.clients.wikidata import group_by_person
from lawgraph.core import tk_records
from lawgraph.core.government import (
    government_functions,
    match_member,
    match_signatory,
)

E = "http://www.wikidata.org/entity/"


def _row(person, name, birth, position, cabinet, start, end=None, precision="11"):
    row = {
        "person": {"value": E + person},
        "personLabel": {"value": name},
        "birth": {"value": f"{birth}T00:00:00Z"},
        "birthPrecision": {"value": precision},
        "position": {"value": E + "Q" + position},
        "positionLabel": {"value": position},
        "cabinet": {"value": E + "Q1"},
        "cabinetLabel": {"value": cabinet},
        "start": {"value": f"{start}T00:00:00Z"},
    }
    if end:
        row["end"] = {"value": f"{end}T00:00:00Z"}
    return row


def test_the_rows_of_a_person_become_one_record_with_every_post_once() -> None:
    rows = [
        _row(
            "Q28860866",
            "Rob Jetten",
            "1987-03-25",
            "minister-president",
            "kabinet-Jetten",
            "2026-02-23",
        ),
        _row(
            "Q28860866",
            "Rob Jetten",
            "1987-03-25",
            "Minister voor Klimaat en Energie",
            "kabinet-Rutte IV",
            "2022-01-10",
            "2024-07-02",
        ),
        # the same post again, for a second date of birth of lower precision
        _row(
            "Q28860866",
            "Rob Jetten",
            "1987-01-01",
            "minister-president",
            "kabinet-Jetten",
            "2026-02-23",
            precision="9",
        ),
    ]
    (jetten,) = group_by_person(rows)
    assert (jetten["id"], jetten["birth_date"], jetten["birth_precision"]) == (
        "Q28860866",
        "1987-03-25",
        11,
    )
    assert [(p["function"], p["from_date"], p["to_date"]) for p in jetten["posts"]] == [
        ("Minister voor Klimaat en Energie", "2022-01-10", "2024-07-02"),
        ("minister-president", "2026-02-23", None),
    ]
    assert government_functions(jetten)[0]["cabinet"] == "kabinet-Rutte IV"


MEMBERS = [
    {"key": "jetten", "family_name": "Jetten", "birth_date": "1987-03-25"},
    {"key": "namesake", "family_name": "Jansen", "birth_date": "1987-03-25"},
    {"key": "yesilgoz", "family_name": "Yeşilgöz-Zegerius", "birth_date": "1977-06-18"},
    {"key": "vdburg", "family_name": "Burg", "birth_date": "1965-10-09"},
]


def _person(name: str, birth: str, precision: int = 11) -> dict:
    return {"name": name, "birth_date": birth, "birth_precision": precision}


def test_a_person_is_the_member_with_the_birth_date_and_the_surname() -> None:
    assert match_member(_person("Rob Jetten", "1987-03-25"), MEMBERS) == "jetten"
    assert match_member(_person("Dilan Yeşilgöz", "1977-06-18"), MEMBERS) == "yesilgoz"
    assert match_member(_person("Eric van der Burg", "1965-10-09"), MEMBERS) == "vdburg"


def test_a_birth_date_without_the_surname_is_nobody() -> None:
    assert match_member(_person("Piet de Vries", "1987-03-25"), MEMBERS) is None
    assert match_member({"name": "Rob Jetten"}, MEMBERS) is None


def test_a_date_known_to_the_year_needs_one_person_of_that_year() -> None:
    assert match_member(_person("Rob Jetten", "1987-01-01", 9), MEMBERS) == "jetten"
    twins = [
        *MEMBERS,
        {"key": "other", "family_name": "Jetten", "birth_date": "1987-11-02"},
    ]
    assert match_member(_person("Rob Jetten", "1987-01-01", 9), twins) is None


def test_a_person_record_keeps_the_birth_date_and_the_surname() -> None:
    _, props = tk_records.member(
        {
            "Id": "49be3576-cea3-46c0-87eb-89beb108248d",
            "Voornamen": "Rob Arnoldus Adrianus",
            "Achternaam": "Jetten",
            "Geboortedatum": "1987-03-25",
        }
    )
    assert (props["family_name"], props["birth_date"]) == ("Jetten", "1987-03-25")


def test_a_particle_is_no_surname_word() -> None:
    # born the same day; only "de" is shared
    members = [
        {
            "key": "kappeyne",
            "family_name": "Kappeyne van de Coppello",
            "birth_date": "1936-10-24",
        },
    ]
    assert (
        match_member(_person("Gerard Wallis de Vries", "1936-10-24"), members) is None
    )
    assert (
        match_member(
            _person("Annelien Kappeyne van de Coppello", "1936-10-24"), members
        )
        == "kappeyne"
    )


def test_ij_and_y_agree_only_when_the_spelling_finds_nobody() -> None:
    gruyters = [{"key": "g", "family_name": "Gruyters", "birth_date": "1931-10-18"}]
    assert match_member(_person("Hans Gruijters", "1931-10-18"), gruyters) == "g"
    twice = [
        {"key": "ij", "family_name": "Peijnenburg", "birth_date": "1928-04-08"},
        {"key": "y", "family_name": "Peynenburg", "birth_date": "1928-04-08"},
    ]
    assert match_member(_person("Marcel Peijnenburg", "1928-04-08"), twice) == "ij"


def test_a_date_with_one_slip_needs_the_first_name_and_one_member() -> None:
    bolkestein = {
        "key": "b",
        "family_name": "Bolkestein",
        "first_names": "Frederik Bolkestein",
        "birth_date": "1931-04-04",
    }
    assert match_member(_person("Frits Bolkestein", "1933-04-04"), [bolkestein]) == "b"
    # a member with only a surname has no first name to disagree
    stee = {
        "key": "s",
        "family_name": "Stee",
        "first_names": "van der Stee",
        "birth_date": "1928-06-30",
    }
    assert match_member(_person("Fons van der Stee", "1928-07-30"), [stee]) == "s"
    # the spouse: same surname word, another first name
    spouse = {
        "key": "o",
        "family_name": "Scheltema-de Nie",
        "first_names": "Olga Scheltema-de Nie",
        "birth_date": "1947-06-29",
    }
    assert match_member(_person("Michiel Scheltema", "1947-06-28"), [spouse]) is None
    # two parts differ, or the year by more than two
    assert match_member(_person("Frits Bolkestein", "1933-05-04"), [bolkestein]) is None
    assert match_member(_person("Frits Bolkestein", "1941-04-04"), [bolkestein]) is None


def _minister(qid: str, name: str, function: str, start: str, end: str | None) -> dict:
    return {
        "id": qid,
        "name": name,
        "posts": [{"function": function, "from_date": start, "to_date": end}],
    }


PEOPLE = [
    _minister(
        "Q1", "Ivo Opstelten", "minister van Justitie", "2010-10-14", "2015-03-10"
    ),
    _minister(
        "Q2", "Fred Teeven", "staatssecretaris van Justitie", "2010-10-14", "2015-03-10"
    ),
    _minister(
        "Q3",
        "Hugo de Jonge",
        "minister van Volksgezondheid",
        "2017-10-26",
        "2022-01-10",
    ),
    _minister(
        "Q4", "Henk de Jonge", "minister van Financiën", "1950-01-01", "1952-01-01"
    ),
]


def _signed(name: str, function: str, first: str, last: str | None = None) -> dict:
    return {"name": name, "function": function, "first": first, "last": last or first}


def test_a_signatory_is_the_person_with_the_surname_and_a_post_of_that_kind() -> None:
    assert (
        match_signatory(
            [
                _signed(
                    "I.W. Opstelten",
                    "minister van Veiligheid en Justitie",
                    "2012-05-01",
                )
            ],
            PEOPLE,
        )
        == "Q1"
    )
    # the other De Jonge held no post then
    assert (
        match_signatory(
            [_signed("H.M. de Jonge", "minister van VWS", "2018-02-15", "2021-06-01")],
            PEOPLE,
        )
        == "Q3"
    )
    # a minister's name on a state secretary's signature is nobody
    assert (
        match_signatory(
            [_signed("I.W. Opstelten", "staatssecretaris van Justitie", "2012-05-01")],
            PEOPLE,
        )
        is None
    )
    # a letter signed shortly after the post ended still belongs to it; a year later not
    assert (
        match_signatory(
            [_signed("I.W. Opstelten", "minister van Justitie", "2015-03-20")], PEOPLE
        )
        == "Q1"
    )
    assert (
        match_signatory(
            [_signed("I.W. Opstelten", "minister van Justitie", "2016-03-20")], PEOPLE
        )
        is None
    )


def test_the_signatures_of_one_person_must_point_at_one_person() -> None:
    both = [
        _signed("I.W. Opstelten", "minister van Justitie", "2012-05-01"),
        _signed("F. Teeven", "staatssecretaris van Justitie", "2012-05-01"),
    ]
    assert match_signatory(both, PEOPLE) is None
    misspelt = [
        _signed("I.W. Opstelten", "minister van Justitie", "2012-05-01"),
        _signed("I.W. Opstelen", "minister van Justitie", "2013-05-01"),
    ]
    assert match_signatory(misspelt, PEOPLE) == "Q1"
