"""The slug of a member (``core.member_slugs``): stable, and one per member."""

from __future__ import annotations

from lawgraph.core.member_slugs import new_slugs, slugify


def test_a_name_becomes_a_slug() -> None:
    assert slugify("Rob Jetten") == "rob-jetten"
    assert slugify("Dilan Yeşilgöz-Zegerius") == "dilan-yesilgoz-zegerius"
    assert slugify("mr. B.O. Dittrich") == "mr-b-o-dittrich"
    assert slugify(None) == ""


def test_a_member_is_named_as_the_api_names_them() -> None:
    found = new_slugs(
        [
            {"key": "a", "name": "Rob Jetten"},
            # a minister who never sat in parliament: the name Rijksoverheid gives
            {"key": "b", "name": None, "known_as": "Sophie Hermans"},
            {"key": "c", "government_name": "G. Moes"},
            {"key": "d"},  # no name: no slug
        ]
    )
    assert found == {"a": "rob-jetten", "b": "sophie-hermans", "c": "g-moes"}


def test_a_slug_once_given_stays_and_a_later_namesake_gets_the_year() -> None:
    found = new_slugs(
        [
            {"key": "old", "name": "Jan de Vries", "slug": "jan-de-vries"},
            {"key": "new", "name": "Jan de Vries", "birth_date": "1971-03-02"},
        ]
    )
    assert found == {"new": "jan-de-vries-1971"}


def test_namesakes_who_come_together_all_get_one() -> None:
    found = new_slugs(
        [
            {"key": "b", "name": "Jan de Vries", "birth_date": "1980-01-01"},
            {"key": "a", "name": "Jan de Vries", "birth_date": "1950-01-01"},
            # the same year: the number of the Tweede Kamer, else a number of its own
            {
                "key": "c",
                "name": "Jan de Vries",
                "birth_date": "1950-06-01",
                "number": "123",
            },
            {"key": "d", "name": "Jan de Vries", "birth_date": "1950-07-01"},
        ]
    )
    assert found == {
        "a": "jan-de-vries-1950",
        "c": "jan-de-vries-123",
        "d": "jan-de-vries-2",
        "b": "jan-de-vries-1980",
    }
    assert len(set(found.values())) == 4
