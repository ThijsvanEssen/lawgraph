"""The names, the kind and the Dutch summary of judgments: the real ``normalize rechtspraak``
and ``semantic graph-list-stats`` on the test server, then the API and the search.

On the real data the Urgenda judgment of the Hoge Raad (ECLI:NL:HR:2019:2007) showed an
English summary, and a search for "Urgenda" did not put it on top: ECLI:NL:HR:2019:2007 is
the English translation the Rechtspraak publishes beside the Dutch ECLI:NL:HR:2019:2006.
Every judgment was labelled "Arrest", also a criminal judgment of a gerechtshof whose kop
opens with "Uitspraak : 10 augustus 2026".
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.queries.search.dispatch import search_all
from lawgraph.db.queries.search.ranking import SCORE_IDENTIFIER
from tests.databases import Api, module_store, opened_store, serving
from tests.integration.seed import write_judgments

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
URGENDA = "ECLI:NL:HR:2019:2006"
URGENDA_EN = "ECLI:NL:HR:2019:2007"
JUDGMENTS = {
    URGENDA: "rechtspraak_hr_2019_2006.xml",
    URGENDA_EN: "rechtspraak_hr_2019_2007.xml",
    "ECLI:NL:HR:1965:AB7079": "rechtspraak_hr_1965_ab7079.xml",
    "ECLI:NL:GHSHE:2026:2210": "rechtspraak_ghshe_2026_2210.xml",
    "ECLI:NL:RVS:2026:5668": "rechtspraak_rvs_2026_5668.xml",
    "ECLI:NL:RBAMS:2024:81": "rechtspraak_rbams_2024_81.xml",
}
# cited, not loaded: a stub
LINDENBAUM = "ECLI:NL:HR:1919:AG1776"


# The tests read one database built for them all (``store``), on the worker that built it;
# the ones that run a pipeline again have a database of their own (``database``).
pytestmark = pytest.mark.xdist_group("judgment_names")


def _build(store: GraphStore, cli: Any) -> None:
    write_judgments(
        store, {ecli: (FIXTURES / name).read_text() for ecli, name in JUDGMENTS.items()}
    )
    store.ensure_stub_node(
        COLLECTION_JUDGMENTS,
        make_node_key(LINDENBAUM),
        props={"ecli": LINDENBAUM},
    )
    cli("normalize", "rechtspraak")
    cli("semantic", "graph-list-stats")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests that only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _build(store, cli)
        yield store


def _judgment(api: Api, ecli: str) -> dict[str, Any]:
    judgment: dict[str, Any] = api.get_json(f"/api/judgments/{ecli}")["judgment"]
    return judgment


def test_the_translation_shows_the_dutch_summary_and_keeps_the_english_apart(
    api: Api,
) -> None:
    english = _judgment(api, URGENDA_EN)
    dutch = _judgment(api, URGENDA)

    assert english["summary"].startswith("Klimaatzaak Urgenda. Mensenrechten.")
    assert english["summary_en"].startswith("Climate case Urgenda. Human rights.")
    assert english["translation_of"] == URGENDA
    assert dutch["summary"] == english["summary"]
    assert dutch["summary_en"] == english["summary_en"]
    assert dutch["translation_of"] is None


def test_a_second_run_changes_nothing(database: str, cli: Any) -> None:
    _build(GraphStore(), cli)
    with opened_store() as store, serving(store) as api:
        before = _judgment(api, URGENDA_EN)
        done = cli("normalize", "rechtspraak")

        assert _judgment(api, URGENDA_EN) == before
    assert "Done in" in done.stderr
    assert f": {len(JUDGMENTS)} unchanged." in done.stderr, done.stderr[-500:]


def test_the_names_of_landmark_judgments_and_of_a_stub(
    api: Api, store: GraphStore
) -> None:
    assert _judgment(api, URGENDA)["names"] == ["Urgenda"]
    assert _judgment(api, URGENDA_EN)["names"] == ["Urgenda"]
    assert _judgment(api, "ECLI:NL:HR:1965:AB7079")["names"] == ["Kelderluik"]
    assert _judgment(api, "ECLI:NL:RVS:2026:5668")["names"] == []

    stub = store.get_node(COLLECTION_JUDGMENTS, make_node_key(LINDENBAUM))
    assert stub is not None
    assert stub.props["names"] == ["Lindenbaum/Cohen"]
    assert stub.props["decision_kind"] == "arrest"
    # graph-list-stats gives a stub its tier and kind of court from the court table
    assert (stub.props["tier"], stub.props["court_kind"]) == ("hoge_raad", "hoge_raad")


@pytest.mark.parametrize(
    ("ecli", "kind"),
    [
        (URGENDA, "arrest"),
        (URGENDA_EN, "arrest"),
        ("ECLI:NL:HR:1965:AB7079", "arrest"),
        ("ECLI:NL:GHSHE:2026:2210", "arrest"),
        ("ECLI:NL:RVS:2026:5668", "uitspraak"),
        ("ECLI:NL:RBAMS:2024:81", "vonnis"),
    ],
)
def test_the_kind_of_each_decision(api: Api, ecli: str, kind: str) -> None:
    assert _judgment(api, ecli)["decision_kind"] == kind


def test_the_list_carries_names_and_kind(api: Api) -> None:
    items = api.get_json("/api/judgments", q="Kelderluik")["items"]

    assert [(i["ecli"], i["names"], i["decision_kind"]) for i in items] == [
        ("ECLI:NL:HR:1965:AB7079", ["Kelderluik"], "arrest")
    ]


@pytest.mark.parametrize(
    ("q", "first"),
    [
        ("Urgenda", {URGENDA, URGENDA_EN}),
        ("urgenda", {URGENDA, URGENDA_EN}),
        ("Lindenbaum/Cohen", {LINDENBAUM}),
        ("Kelderluik", {"ECLI:NL:HR:1965:AB7079"}),
    ],
)
def test_a_judgment_is_found_first_by_its_name(
    store: GraphStore, q: str, first: set[str]
) -> None:
    hits = search_all(store, q=q, types=["judgments"])["judgments"]

    top = [h for h in hits if h["score"] == SCORE_IDENTIFIER]
    assert {h["extra"]["ecli"] for h in top} == first
    assert hits[: len(top)] == top


def test_the_dutch_judgment_comes_before_its_translation(store: GraphStore) -> None:
    hits = search_all(store, q="Urgenda", types=["judgments"])["judgments"]

    assert [h["extra"]["ecli"] for h in hits[:2]] == [URGENDA, URGENDA_EN]


def test_part_of_a_name_finds_it_too(api: Api) -> None:
    body = api.get_json("/api/search", q="Lindenbaum", types="judgments")

    hits = body["results"]["judgments"]
    assert hits[0]["extra"]["ecli"] == LINDENBAUM
    assert hits[0]["extra"]["names"] == ["Lindenbaum/Cohen"]


def test_a_translation_alone_has_no_summary_but_its_english_one(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    write_judgments(store, {URGENDA_EN: (FIXTURES / JUDGMENTS[URGENDA_EN]).read_text()})
    cli("normalize", "rechtspraak")

    node = store.get_node(COLLECTION_JUDGMENTS, make_node_key(URGENDA_EN))
    assert node is not None
    assert node.props.get("summary") is None
    assert node.props.get("translation_of") is None
    assert node.props["summary_en"].startswith("Climate case Urgenda.")
