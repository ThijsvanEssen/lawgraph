"""Cabinet posts from Wikidata, and which Tweede Kamer person they belong to."""

from __future__ import annotations

from lawgraph.clients.wikidata import group_by_person
from lawgraph.core import tk_records
from lawgraph.core.government import government_functions, match_member

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
