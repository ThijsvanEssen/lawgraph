"""A judgment found by the persons it names, on a real PostgreSQL: ``lg_judgment_persons``
kept by the trigger on every write of a judgment's props, and read by the search, full and
while typing (ECLI:NL:RVS:2007:BB0782: "R. van Gelder", its appellants' advocaat)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import search as search_queries

BB0782 = "judgments/ecli_nl_rvs_2007_bb0782"


def _person(
    name: str, role: str, place: str | None = None, capacity: str | None = None
) -> dict[str, Any]:
    return {"name": name, "role": role, "place": place, "capacity": capacity}


def _party(
    name: str, role: str, side: str, *representatives: dict[str, Any], **more: Any
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "roles": [role],
        "role_stated": True,
        "side": side,
        "alias": None,
        "representatives": list(representatives),
        **more,
    }


PARTIES = [
    _party(
        "[appellanten]",
        "Appellant",
        "first",
        _person("mr. drs. R. van Gelder", "advocaat", "Voorschoten"),
    ),
    _party(
        "het college van gedeputeerde staten van Zuid-Holland",
        "Verweerder",
        "second",
        _person(
            "mr. I.T.F. Vermeulen",
            "gemachtigde",
            capacity="ambtenaar in dienst van de provincie",
        ),
    ),
    _party(
        "de gemeenteraad van Nieuwerkerk aan den IJssel",
        "Partij",
        "other",
        _person("mr. R. van der Meulen MPM", "gemachtigde"),
        alias="de gemeenteraad",
    ),
]


def _judgment(key: str, date: str, parties: list[dict[str, Any]], **props: Any) -> dict:
    return {
        "_key": key,
        "type": "judgment",
        "labels": [],
        "props": {
            "ecli": key.upper().replace("_", ":"),
            "display_name": f"Raad van State, {date} / 200604968/1",
            "summary": "Bestemmingsplan Esse Zoom.",
            "date_eff": date,
            "parties": parties,
            **props,
        },
    }


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment("ecli_nl_rvs_2007_bb0782", "2007-08-01", PARTIES),
            # an advocaat of the same surname, other initials; and one Gelderen
            _judgment(
                "ecli_nl_rvs_2010_1",
                "2010-01-01",
                [
                    _party(
                        "[appellant]",
                        "Appellant",
                        "first",
                        _person("mr. P. van Gelder", "advocaat"),
                    ),
                    _party(
                        "het college van gedeputeerde staten van Gelderland",
                        "Verweerder",
                        "second",
                    ),
                ],
            ),
            # a word of a party's name in a judgment that names no such person
            _judgment(
                "ecli_nl_rvs_2011_1",
                "2011-01-01",
                [],
                summary="Het college van gedeputeerde staten besluit.",
            ),
        ],
    )
    return store


def _rows(store: GraphStore) -> list[tuple[str, str, str | None, str]]:
    return [
        (row["name"], row["role"], row["party"], row["words"])
        for row in store.query(
            "SELECT name, role, party, words FROM lg_judgment_persons"
            " WHERE id = %(id)s ORDER BY n",
            {"id": BB0782},
        )
    ]


def test_the_persons_a_judgment_names_are_kept_with_every_write(
    graph: GraphStore,
) -> None:
    assert _rows(graph) == [
        # an anonymised party names no one
        (
            "mr. drs. R. van Gelder",
            "advocaat",
            "[appellanten]",
            " mr drs r van gelder ",
        ),
        (
            "het college van gedeputeerde staten van Zuid-Holland",
            "Verweerder",
            None,
            " het college van gedeputeerde staten van zuid holland ",
        ),
        (
            "mr. I.T.F. Vermeulen",
            "gemachtigde",
            PARTIES[1]["name"],
            " mr i t f vermeulen ",
        ),
        (
            "de gemeenteraad van Nieuwerkerk aan den IJssel",
            "Partij",
            None,
            " de gemeenteraad van nieuwerkerk aan den ijssel ",
        ),
        (
            "mr. R. van der Meulen MPM",
            "gemachtigde",
            "de gemeenteraad",
            " mr r van der meulen mpm ",
        ),
    ]

    graph.bulk_insert_or_update_nodes(
        "judgments", [_judgment("ecli_nl_rvs_2007_bb0782", "2007-08-01", PARTIES[:1])]
    )
    assert [name for name, *_ in _rows(graph)] == ["mr. drs. R. van Gelder"]

    graph.execute("DELETE FROM judgments WHERE id = %(id)s", {"id": BB0782})
    assert _rows(graph) == []


def _judgments(found: dict[str, list[dict[str, Any]]]) -> list[tuple[str, Any]]:
    return [
        (hit["id"], (hit["extra"].get("person") or {}).get("name"))
        for hit in found["judgments"]
    ]


@pytest.mark.parametrize(
    "q", ["R. van Gelder", "mr. drs. R. van Gelder", "r van gelder", "Van Gelder"]
)
def test_a_judgment_is_found_by_its_advocaat(graph: GraphStore, q: str) -> None:
    found = search_queries.search_all(graph, q=q, types=["judgments"])

    hits = _judgments(found)
    assert (BB0782, "mr. drs. R. van Gelder") in hits
    bb0782 = next(h for h in found["judgments"] if h["id"] == BB0782)
    assert bb0782["extra"]["person"] == {
        "name": "mr. drs. R. van Gelder",
        "role": "advocaat",
        "party": "[appellanten]",
    }
    assert bb0782["score"] == search_queries.SCORE_CONTAINS
    if "R." in q:
        # the initials tell the other Van Gelder apart (a bare "r" is no word of a query);
        # "gelder" is no word of Gelderland
        assert hits == [(BB0782, "mr. drs. R. van Gelder")]


def test_a_judgment_is_found_by_a_gemachtigde_and_a_party(graph: GraphStore) -> None:
    for q, person in (
        ("Vermeulen", "mr. I.T.F. Vermeulen"),
        ("R. van der Meulen", "mr. R. van der Meulen MPM"),
        (
            "college van gedeputeerde staten van Zuid-Holland",
            "het college van gedeputeerde staten van Zuid-Holland",
        ),
    ):
        found = search_queries.search_all(graph, q=q, types=["judgments"])
        assert _judgments(found)[0] == (BB0782, person), q


def test_a_word_of_a_name_alone_comes_after_the_words_of_a_text(
    graph: GraphStore,
) -> None:
    found = search_queries.search_all(
        graph, q="college gedeputeerde staten", types=["judgments"]
    )

    hits = found["judgments"]
    # in the summary of one; a word of the names of the other two
    assert hits[0]["id"] == "judgments/ecli_nl_rvs_2011_1"
    assert {h["score"] for h in hits} == {search_queries.SCORE_WORDS}


def test_while_typing_the_last_word_is_the_start_of_one(graph: GraphStore) -> None:
    for q in ("R. van Geld", "Vermeul"):
        hits, partial = search_queries.search_live(graph, q=q, types=["judgments"])
        assert not partial
        assert [h["id"] for h in hits["judgments"]] == [BB0782], q
    # the full search takes every word whole
    found = search_queries.search_all(graph, q="Vermeul", types=["judgments"])
    assert found["judgments"] == []


def test_a_period_keeps_the_persons_to_it(graph: GraphStore) -> None:
    period = search_queries.Period("2009-01-01", None)
    found = search_queries.search_all(
        graph, q="Van Gelder", types=["judgments"], period=period
    )

    assert _judgments(found) == [("judgments/ecli_nl_rvs_2010_1", "mr. P. van Gelder")]
