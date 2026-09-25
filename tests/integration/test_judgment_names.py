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
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries.search import SCORE_IDENTIFIER, search_all
from tests.integration.seed import wait_for_views

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


@pytest.fixture()
def client(database: str, cli: Any) -> Iterator[TestClient]:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        for ecli, name in JUDGMENTS.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=(FIXTURES / name).read_text(),
                    meta={"ecli": ecli},
                )
            )
    store.ensure_stub_node(
        COLLECTION_JUDGMENTS,
        make_node_key(LINDENBAUM),
        "judgment",
        props={"ecli": LINDENBAUM},
    )
    cli("normalize", "rechtspraak")
    cli("semantic", "graph-list-stats")
    wait_for_views(store, {"search_judgments": len(JUDGMENTS) + 1})
    # the names graph-list-stats gave the stub: an update the view commits later
    list(store.query("FOR d IN search_judgments OPTIONS {waitForSync: true} RETURN 1"))
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _judgment(client: TestClient, ecli: str) -> dict[str, Any]:
    response = client.get(f"/api/judgments/{ecli}")
    assert response.status_code == 200, response.text
    judgment: dict[str, Any] = response.json()["judgment"]
    return judgment


def test_the_translation_shows_the_dutch_summary_and_keeps_the_english_apart(
    client: TestClient,
) -> None:
    english = _judgment(client, URGENDA_EN)
    dutch = _judgment(client, URGENDA)

    assert english["summary"].startswith("Klimaatzaak Urgenda. Mensenrechten.")
    assert english["summary_en"].startswith("Climate case Urgenda. Human rights.")
    assert english["translation_of"] == URGENDA
    assert dutch["summary"] == english["summary"]
    assert dutch["summary_en"] == english["summary_en"]
    assert dutch["translation_of"] is None


def test_a_second_run_changes_nothing(client: TestClient, cli: Any) -> None:
    before = _judgment(client, URGENDA_EN)
    done = cli("normalize", "rechtspraak")

    assert _judgment(client, URGENDA_EN) == before
    assert "Done in" in done.stderr
    assert f": {len(JUDGMENTS)} unchanged." in done.stderr, done.stderr[-500:]


def test_the_names_of_landmark_judgments_and_of_a_stub(client: TestClient) -> None:
    assert _judgment(client, URGENDA)["names"] == ["Urgenda"]
    assert _judgment(client, URGENDA_EN)["names"] == ["Urgenda"]
    assert _judgment(client, "ECLI:NL:HR:1965:AB7079")["names"] == ["Kelderluik"]
    assert _judgment(client, "ECLI:NL:RVS:2026:5668")["names"] == []

    stub = ArangoStore().get_node(COLLECTION_JUDGMENTS, make_node_key(LINDENBAUM))
    assert stub is not None
    assert stub.props["names"] == ["Lindenbaum/Cohen"]
    assert stub.props["decision_kind"] == "arrest"


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
def test_the_kind_of_each_decision(client: TestClient, ecli: str, kind: str) -> None:
    assert _judgment(client, ecli)["decision_kind"] == kind


def test_the_list_carries_names_and_kind(client: TestClient) -> None:
    items = client.get("/api/judgments", params={"q": "Kelderluik"}).json()["items"]

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
    client: TestClient, q: str, first: set[str]
) -> None:
    hits = search_all(ArangoStore(), q=q, types=["judgments"])["judgments"]

    top = [h for h in hits if h["score"] == SCORE_IDENTIFIER]
    assert {h["extra"]["ecli"] for h in top} == first
    assert hits[: len(top)] == top


def test_the_dutch_judgment_comes_before_its_translation(client: TestClient) -> None:
    hits = search_all(ArangoStore(), q="Urgenda", types=["judgments"])["judgments"]

    assert [h["extra"]["ecli"] for h in hits[:2]] == [URGENDA, URGENDA_EN]


def test_part_of_a_name_finds_it_too(client: TestClient) -> None:
    body = client.get("/api/search", params={"q": "Lindenbaum", "types": "judgments"})

    hits = body.json()["results"]["judgments"]
    assert hits[0]["extra"]["ecli"] == LINDENBAUM
    assert hits[0]["extra"]["names"] == ["Lindenbaum/Cohen"]


def test_a_translation_alone_has_no_summary_but_its_english_one(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=URGENDA_EN,
                payload_text=(FIXTURES / JUDGMENTS[URGENDA_EN]).read_text(),
                meta={"ecli": URGENDA_EN},
            )
        )
    cli("normalize", "rechtspraak")

    node = store.get_node(COLLECTION_JUDGMENTS, make_node_key(URGENDA_EN))
    assert node is not None
    assert node.props.get("summary") is None
    assert node.props.get("translation_of") is None
    assert node.props["summary_en"].startswith("Climate case Urgenda.")
