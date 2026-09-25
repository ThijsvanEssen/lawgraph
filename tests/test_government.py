"""Which Tweede Kamer person holds a post: by surname, initials and age, or by signatures."""

from __future__ import annotations

from lawgraph.core import tk_records
from lawgraph.core.government import initial_letters, match_holder, match_signatory


def _holder(surname: str, letters: str, *days: str, factions=()) -> dict:
    return {
        "surname": surname,
        "letters": letters,
        "days": list(days) or ["2025-06-03"],
        "factions": list(factions),
    }


def _member(key: str, name: str, family: str, born: str | None, *factions: str):
    return {
        "key": key,
        "name": name,
        "family_name": family,
        "birth_date": born,
        "factions": list(factions),
    }


HERMANS = _member("sh", "Sophia Theodora Monique Hermans", "Hermans", "1981-05-01")
LOEK = _member(
    "lh", "Louis Marie Lucien Henri Alphonse Hermans", "Hermans", "1951-04-23"
)
VAN_WEEL = _member("vw", "David Mattheus van Weel", "Weel", "1976-01-01")
MEMBERS = [HERMANS, LOEK, VAN_WEEL]


def test_a_holder_is_the_member_with_the_surname_and_the_initials() -> None:
    assert match_holder(_holder("Hermans", "stm"), MEMBERS) == "sh"
    assert match_holder(_holder("Hermans", "lmlha", "1998-08-03"), MEMBERS) == "lh"
    assert match_holder(_holder("van Weel", "dm"), MEMBERS) == "vw"
    # other initials, or another surname: nobody
    assert match_holder(_holder("Hermans", "k"), MEMBERS) is None
    assert match_holder(_holder("Weeling", "dm"), MEMBERS) is None


def test_initials_count_ij_as_one_letter() -> None:
    assert initial_letters(["ijsbrand", "jan"]) == "ijj"


def test_a_member_too_young_or_too_old_for_the_post_is_not_the_holder() -> None:
    sr = _member("sr", "Willem Drees", "Drees", "1886-07-05", "pvda")
    jr = _member("jr", "Willem Drees", "Drees", "1922-12-24", "ds70")
    assert match_holder(_holder("Drees", "w", "1948-08-07"), [sr, jr]) == "sr"
    # both of an age in 1971: the faction of the party tells them apart
    assert (
        match_holder(_holder("Drees", "w", "1971-07-06", factions=["ds70"]), [sr, jr])
        == "jr"
    )
    assert match_holder(_holder("Drees", "w", "1971-07-06"), [sr, jr]) is None


def test_a_member_without_first_names_is_matched_by_surname_alone() -> None:
    stee = _member("s", "van der Stee", "Stee", "1928-07-30")
    assert match_holder(_holder("van der Stee", "apjmm", "1971-07-14"), [stee]) == "s"


def test_a_particle_is_no_surname_word() -> None:
    kappeyne = _member(
        "k", "Annelien Kappeyne van de Coppello", "Kappeyne van de Coppello", None
    )
    assert match_holder(_holder("de Vries", "a"), [kappeyne]) is None
    assert match_holder(_holder("Kappeyne van de Coppello", "a"), [kappeyne]) == "k"


def test_ij_and_y_agree_only_when_the_spelling_finds_nobody() -> None:
    gruyters = [_member("g", "Johannes Gruyters", "Gruyters", "1931-10-18")]
    assert match_holder(_holder("Gruijters", "j", "1973-05-11"), gruyters) == "g"
    twice = [
        _member("ij", "Marcel Peijnenburg", "Peijnenburg", "1928-04-08"),
        _member("y", "Marcel Peynenburg", "Peynenburg", "1928-04-08"),
    ]
    assert match_holder(_holder("Peijnenburg", "m", "1965-05-13"), twice) == "ij"


def test_a_person_record_keeps_the_names_initials_and_birth_date() -> None:
    _, props = tk_records.member(
        {
            "Id": "e6e673f5-f0a7-4d34-a6aa-d2f12fed24ed",
            "Voornamen": "Gerard Adriaan",
            "Roepnaam": "Ard",
            "Tussenvoegsel": "van der",
            "Achternaam": "Steur",
            "Initialen": "G.A.",
            "Geboortedatum": "1975-12-20",
        }
    )
    assert (props["name"], props["full_name"]) == (
        "Ard van der Steur",
        "Gerard Adriaan van der Steur",
    )
    assert (props["family_name"], props["initials"], props["birth_date"]) == (
        "Steur",
        "G.A.",
        "1975-12-20",
    )
    # without a roepnaam: the first names
    _, props = tk_records.member(
        {"Id": "x", "Voornamen": "Joop", "Achternaam": "Atsma"}
    )
    assert (props["name"], props["full_name"]) == ("Joop Atsma", "Joop Atsma")


def test_the_initials_of_the_tweede_kamer_come_before_the_first_names() -> None:
    # the TK gives only the name Stef, but its initials S.A.
    blok = {**_member("blok", "Stef Blok", "Blok", "1964-12-10"), "initials": "S.A."}
    assert match_holder(_holder("Blok", "sa", "2012-11-05"), [blok]) == "blok"
    assert match_holder(_holder("Blok", "s", "2012-11-05"), [blok]) == "blok"  # loosely
    graaff = {
        **_member("g", "Dieuwke de Graaff-Nauta", "Graaff-Nauta", "1930-01-01"),
        "initials": "D.IJ.W.",
    }
    assert (
        match_holder(_holder("de Graaff-Nauta", "dijw", "1986-07-14"), [graaff]) == "g"
    )


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


def test_a_looser_pass_finds_a_member_known_by_one_first_name_or_a_double_surname() -> (
    None
):
    blok = _member("blok", "Stef Blok", "Blok", "1964-12-10")
    assert match_holder(_holder("Blok", "sa", "2012-11-05"), [blok]) == "blok"
    bijleveld = _member(
        "b",
        "Anna Theodora Bernardina Bijleveld-Schouten",
        "Bijleveld-Schouten",
        "1962-03-17",
    )
    assert match_holder(_holder("Bijleveld", "atb", "2017-10-26"), [bijleveld]) == "b"
    # the strict pass wins where it finds someone
    stef = _member("stef", "Stef Blok", "Blok", "1964-12-10")
    exact = _member("exact", "Sara Anna Blok", "Blok", "1970-01-01")
    assert match_holder(_holder("Blok", "sa", "2012-11-05"), [stef, exact]) == "exact"
