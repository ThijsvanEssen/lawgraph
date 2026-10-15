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
    COLLECTION_DOSSIERS,
    COLLECTION_JUDGMENTS,
    RELATION_LEGISLATED_IN,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import EdgeWriter, GraphStore
from lawgraph.db.queries.search.dispatch import search_all, search_live

BW7 = "BWBR0005290"


def _put(
    store: GraphStore,
    collection: str,
    key: str,
    labels: list[str] | None = None,
    **props: Any,
) -> None:
    doc = {
        "key": key,
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


def test_a_vote_is_found_by_its_subject(store: GraphStore) -> None:
    """BE-46: "stemming abortus" finds the votes on abortion; "stemming" names the type,
    not what was voted on."""
    _put(
        store,
        "decisions",
        "d_old",
        subject="Motie over de abortuswet en de beraadtermijn",
        kind="Motie",
        date="2023-02-14",
        passed=False,
    )
    _put(
        store,
        "decisions",
        "d_new",
        subject="Wijziging van de Wet afbreking zwangerschap (abortuswet)",
        kind="Wetgeving",
        date="2025-06-03",
        passed=True,
    )
    _put(store, "decisions", "d_other", subject="Wet huurcommissie", kind="Wetgeving")
    hits = search_all(store, q="stemming abortuswet", types=["decisions"])["decisions"]
    assert [h["key"] for h in hits] == ["d_new", "d_old"]  # newest first
    assert (hits[0]["extra"]["kind"], hits[0]["extra"]["passed"]) == ("Wetgeving", True)
    motie = search_all(store, q="motie abortuswet", types=["decisions"])["decisions"]
    assert [h["key"] for h in motie] == ["d_old"]
    assert search_all(store, q="stemming", types=["decisions"])["decisions"] == []


@pytest.mark.parametrize("mode", ["full", "live"])
def test_an_instrument_hit_has_its_kind_and_dates(store: GraphStore, mode: str) -> None:
    """Regulations of one title are told apart by their kind and dates, not by their BWB
    id alone (#53: six "Belastingen op milieugrondslag")."""
    for bwb_id, version in (
        ("BWBR0021767", "2007-04-27"),
        ("BWBR0034957", "2014-03-22"),
    ):
        _put(
            store,
            "instruments",
            bwb_id.lower(),
            bwb_id=bwb_id,
            title="Belastingen op milieugrondslag",
            citation_title="Belastingen op milieugrondslag",
            kind="beleidsregel",
            version_date_in_force=version,
        )
    hits = (
        search_all(store, q="milieugrondslag", types=["instruments"])
        if mode == "full"
        else search_live(store, q="milieugrondslag", types=["instruments"])[0]
    )
    assert {
        hit["key"]: (
            hit["extra"]["kind"],
            hit["extra"]["date_published"],
            hit["extra"]["date_in_force"],
            hit["extra"]["version_date_in_force"],
        )
        for hit in hits["instruments"]
    } == {
        "bwbr0021767": ("beleidsregel", None, None, "2007-04-27"),
        "bwbr0034957": ("beleidsregel", None, None, "2014-03-22"),
    }


@pytest.mark.parametrize("mode", ["full", "live"])
def test_a_word_and_the_abbreviation_of_a_law_find_its_article(
    store: GraphStore, mode: str
) -> None:
    """ "zorgplicht cbw" finds art. 21 of the Cyberbeveiligingswet, whose heading holds
    the word and whose law has the abbreviation (its short title from the WTI), as
    "zorgplicht cyberbeveiligingswet" does."""
    cbw = "BWBR0052872"
    _put(
        store,
        "instruments",
        cbw.lower(),
        bwb_id=cbw,
        title="Cyberbeveiligingswet",
        citation_title="Cyberbeveiligingswet",
        short_title="Cbw",
        aliases=["Cbw"],
    )
    _put(
        store,
        COLLECTION_ARTICLES,
        make_node_key(cbw, "21"),
        bwb_id=cbw,
        article_number="21",
        display_name="Artikel 21 Cyberbeveiligingswet",
        heading="(zorgplicht)",
        text="Een essentiële of belangrijke entiteit neemt passende maatregelen.",
    )
    search = search_all if mode == "full" else search_live
    for q in ("zorgplicht cbw", "Zorgplicht CBW", "zorgplicht cyberbeveiligingswet"):
        found = search(store, q=q, types=[COLLECTION_ARTICLES])
        hits = found[0] if isinstance(found, tuple) else found
        assert [h["key"] for h in hits[COLLECTION_ARTICLES]] == [
            make_node_key(cbw, "21")
        ]


@pytest.mark.parametrize("mode", ["full", "live"])
@pytest.mark.parametrize("q", ["cbw", "CBW", "cbw dossier", "Cbw dossiers"])
def test_the_abbreviation_of_a_law_finds_the_dossier_it_was_legislated_in(
    store: GraphStore, mode: str, q: str
) -> None:
    """ "cbw" finds dossier 36764, whose bill became the Cyberbeveiligingswet (the law is
    ``LEGISLATED_IN`` it, its short title from the WTI is Cbw), though its title holds the
    name only in full; "dossier" names the type and is left out. Another dossier does not
    match by the abbreviation."""
    cbw = "BWBR0052872"
    _put(
        store,
        "instruments",
        cbw.lower(),
        bwb_id=cbw,
        title="Cyberbeveiligingswet",
        citation_title="Cyberbeveiligingswet",
        short_title="Cbw",
        aliases=["Cbw"],
    )
    for number, title in (
        (
            "36764",
            "Regels ter implementatie van Richtlijn (EU) 2022/2555 (Cyberbeveiligingswet)",
        ),
        (
            "36765",
            "Wet weerbaarheid kritieke entiteiten",
        ),
    ):
        _put(
            store, COLLECTION_DOSSIERS, number, label=number, number=number, title=title
        )
    edges = EdgeWriter(store, what=None)
    edges.add(
        f"instruments/{cbw.lower()}",
        f"{COLLECTION_DOSSIERS}/36764",
        RELATION_LEGISLATED_IN,
        source="test",
    )
    edges.flush()
    search = search_all if mode == "full" else search_live
    found = search(store, q=q, types=[COLLECTION_DOSSIERS])
    hits = found[0] if isinstance(found, tuple) else found
    assert [h["key"] for h in hits[COLLECTION_DOSSIERS]] == ["36764"]
