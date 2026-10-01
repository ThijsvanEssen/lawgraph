"""Full-text search in Dutch, run for real on the small test server.

The texts are Dutch, so a word must find its other forms: the plural its singular and back
("uitspraken" finds "uitspraak", "wetten" finds "wet"). An English stemmer leaves Dutch
plurals as they are, and the search then finds only the form that was typed.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_JUDGMENTS,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.queries.search import search_all

BW7 = "BWBR0005290"


def _put(
    store: GraphStore,
    collection: str,
    key: str,
    labels: list[str] | None = None,
    **props: Any,
) -> None:
    doc = {
        "_key": key,
        "type": collection.rstrip("s"),
        "labels": labels or [],
        "props": props,
    }
    store.bulk_insert_or_update_nodes(collection, [doc])


@pytest.fixture()
def store(database: str) -> GraphStore:
    store = GraphStore()
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(BW7, "7:231"),
        bwb_id=BW7,
        article_number="7:231",
        display_name="Artikel 7:231",
        text="De rechter doet uitspraak over de vordering tot ontbinding van de huurovereenkomst.",
    )
    _put(
        store,
        COLLECTION_JUDGMENTS,
        "ecli_nl_hr_2021_1",
        ecli="ECLI:NL:HR:2021:1",
        display_name="ECLI:NL:HR:2021:1",
        summary="Ontslag op staande voet; de rechten van de werknemer uit de wetten.",
    )
    _put(
        store,
        COLLECTION_DOCUMENTS,
        "amendement_36000_12",
        labels=["TK"],
        title="Amendement van het lid Jansen over de huurovereenkomst",
        kind="Amendement",
        sequence=12,
        dossier_numbers=["36000"],
        date="2025-11-04",
    )
    return store


def _keys(store: GraphStore, q: str, kind: str) -> list[str]:
    return [hit["key"] for hit in search_all(store, q=q, types=[kind])[kind]]


@pytest.mark.parametrize(
    "q", ["uitspraken", "vorderingen", "huurovereenkomsten", "uitspraak vorderingen"]
)
def test_an_article_is_found_by_another_form_of_its_words(
    store: GraphStore, q: str
) -> None:
    assert _keys(store, q, "articles") == [make_node_key(BW7, "7:231")]


@pytest.mark.parametrize("q", ["ontslagen", "recht", "wet"])
def test_a_judgment_is_found_by_another_form_of_the_words_of_its_summary(
    store: GraphStore, q: str
) -> None:
    assert _keys(store, q, "judgments") == ["ecli_nl_hr_2021_1"]


def test_a_word_that_is_not_there_finds_nothing(store: GraphStore) -> None:
    assert _keys(store, "belastingen", "articles") == []


def test_a_document_hit_has_its_number_in_the_dossier(store: GraphStore) -> None:
    (hit,) = search_all(store, q="huurovereenkomst", types=["documents"])["documents"]
    assert (hit["extra"]["dossier_number"], hit["extra"]["sequence"]) == ("36000", 12)


def test_a_document_hit_has_its_date_and_chamber(store: GraphStore) -> None:
    """Four debates on one subject are told apart by their day (BE-1), and the chamber
    is read as /api/documents reads it (BE-39)."""
    (hit,) = search_all(store, q="huurovereenkomst", types=["documents"])["documents"]
    assert (hit["extra"]["date"], hit["extra"]["chamber"]) == ("2025-11-04", "TK")


def test_a_cabinet_is_found_by_the_words_of_its_name(store: GraphStore) -> None:
    """BE-35: the entry Kabinet of the start page."""
    for key, name, start in (
        ("schoof", "kabinet-Schoof", "2024-07-02"),
        ("rutte_iv", "kabinet-Rutte IV", "2022-01-10"),
        ("rutte_iii", "kabinet-Rutte III", "2017-10-26"),
    ):
        _put(store, "cabinets", key, name=name, from_date=start)
    hits = search_all(store, q="Rutte", types=["cabinets"])["cabinets"]
    assert [h["key"] for h in hits] == ["rutte_iv", "rutte_iii"]  # newest first
    (hit,) = search_all(store, q="kabinet schoof", types=["cabinets"])["cabinets"]
    assert (hit["display_name"], hit["extra"]["from_date"]) == (
        "kabinet-Schoof",
        "2024-07-02",
    )


def test_a_commitment_is_found_by_its_words_or_its_number(store: GraphStore) -> None:
    """BE-35: a commitment by what it promises, or by its number."""
    _put(
        store,
        "commitments",
        "tz1",
        number="TZ202609-011",
        text="De minister zegt toe de Kamer een statusbrief over stikstof te sturen.",
        display_name="De minister zegt toe de Kamer een statusbrief…",
        made_on="2026-09-08",
        status="Openstaand",
    )
    _put(store, "commitments", "tz2", number="TZ202501-001", text="Iets anders.")
    (hit,) = search_all(store, q="statusbrief stikstof", types=["commitments"])[
        "commitments"
    ]
    assert hit["key"] == "tz1"
    assert (hit["extra"]["number"], hit["extra"]["status"]) == (
        "TZ202609-011",
        "Openstaand",
    )
    by_number = search_all(store, q="tz202609-011", types=["commitments"])
    assert [h["key"] for h in by_number["commitments"]] == ["tz1"]
