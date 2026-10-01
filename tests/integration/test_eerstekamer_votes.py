"""The outcome of a bill in the Eerste Kamer, from its list of votes and its list of rejected
bills (pages of eerstekamer.nl as served on 2026-09-30), on a real database.

* 36791 was adopted after a vote (29 September 2026); 36880 by hamerslag that day.
* 36855 (a novelle) was rejected on 21 April 2026: the list of rejected bills says so, and
  no page of votes read here holds that day.
* 37999 has no vote in the Eerste Kamer and stays open.
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
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    RAW_KIND_EK_REJECTED,
    RAW_KIND_EK_VOTES_DAY,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import eerstekamer_votes as ev
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, NodeWriter, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NUMBERS = ("36791", "36880", "36855", "37999")


def _dossier(number: str) -> Node:
    return Node(
        collection=COLLECTION_DOSSIERS,
        type=NodeType.DOSSIER,
        key=number,
        labels=["TK"],
        props={
            "number": number,
            "label": number,
            "title": f"Wet {number}",
            "kind": "Wetgeving",
        },
    )


@pytest.fixture()
def store(database: str, cli: Any) -> Iterator[ArangoStore]:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(_dossier(n) for n in NUMBERS)
        writer.add(
            Node(
                collection=COLLECTION_FACTIONS,
                type=NodeType.FACTION,
                key="ek_boerburgerbeweging",
                labels=["EK"],
                props={"chamber": "EK", "name": "BBB-fractie", "abbreviation": "BBB"},
            )
        )
    page = (FIXTURES / "ek_votes_page_1.html").read_text()
    day, _, fragment = ev.days(page)[0]
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_VOTES_DAY,
                external_id=day,
                payload_text=fragment,
                meta={"url": "https://www.eerstekamer.nl/x", "read_on": "2026-09-30"},
            )
        )
        writer.add(
            raw_source_doc(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_REJECTED,
                external_id="verworpen_in_de_eerste_kamer",
                payload_text=(FIXTURES / "ek_rejected_page_1.html").read_text(),
                meta={
                    "url": "https://www.eerstekamer.nl/verworpen_in_de_eerste_kamer",
                    "read_on": "2026-09-30",
                },
            )
        )
    cli("normalize", "eerstekamer-votes")
    cli("semantic", "tk-dossier-outcomes")
    yield store


def _props(store: ArangoStore, number: str) -> dict[str, Any]:
    return store.get_document(COLLECTION_DOSSIERS, number)["props"]


def test_the_eerste_kamer_decides_the_bill(store: ArangoStore, cli: Any) -> None:
    rent = _props(store, "36791")
    assert (rent["closed"], rent["outcome"], rent["closed_on"]) == (
        True,
        "aangenomen",
        "2026-09-29",
    )
    assert rent["ek_outcome"] == {
        "outcome": "Aangenomen",
        "date": "2026-09-29",
        "method": "Stemming bij zitten en opstaan, aangenomen",
        "source_url": "https://www.eerstekamer.nl/verslagdeel/20260929/wet_toekomstbestendige",
        "retrieved_on": "2026-09-30",
    }
    assert _props(store, "36880")["ek_outcome"]["method"] == "Hamerstuk"
    novelle = _props(store, "36855")
    assert (novelle["outcome"], novelle["closed_on"]) == ("verworpen", "2026-04-21")
    assert novelle["ek_outcome"]["method"] is None
    assert novelle["ek_outcome"]["source_url"].endswith("verworpen_in_de_eerste_kamer")
    assert not _props(store, "37999").get("closed")

    decisions = list(
        store.query(
            "FOR d IN decisions FILTER d.props.chamber == 'EK' "
            "RETURN [d.props.dossier_numbers[0], d.props.bill_decision]"
        )
    )
    assert len(decisions) == 5  # the votes of 29 September 2026
    assert ["36791", True] in decisions

    # a second run changes nothing
    done = cli("semantic", "tk-dossier-outcomes")
    assert "0 changed" in done.stderr + done.stdout


def test_the_api_shows_the_eerste_kamer(store: ArangoStore) -> None:
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        dossier = client.get("/api/dossiers/36791").json()
        assert dossier["ek_outcome"]["outcome"] == "Aangenomen"
        assert dossier["ek_outcome"]["attribution"].startswith("Eerste Kamer")
        votes = client.get("/api/decisions", params={"chamber": "EK"}).json()
        assert votes["total"] == 5
        rent = next(v for v in votes["items"] if v["dossier_numbers"] == ["36791"])
        # the vote that decided the bill has the kind of its dossier
        assert rent["kind"] == "Wetgeving"
        bbb = client.get("/api/factions/ek_boerburgerbeweging/votes").json()
        mine = next(v for v in bbb["items"] if v["dossier_numbers"] == ["36791"])
        assert (mine["choice"], mine["result"], mine["bill_decision"]) == (
            "tegen",
            "Aangenomen",
            True,
        )
        assert bbb["counts"]["tegen"] >= 1 and bbb["total"] == sum(
            bbb["counts"].values()
        )
        assert client.get("/api/factions/nope/votes").status_code == 404
        assert (rent["result"], rent["bill_decision"]) == ("Aangenomen", True)
        detail = client.get(f"/api/decisions/{rent['key']}").json()
        assert detail["factions_against"] == ["BBB", "FVD"]
        feed = client.get(
            "/api/feed", params={"chamber": "EK", "since": "2026-09-01"}
        ).json()
        assert {i["kind"] for i in feed["items"]} == {"stemming"}
        assert {i["vote"]["chamber"] for i in feed["items"]} == {"EK"}
        # only the votes that decided a bill the graph holds: 36791 and 36880
        assert len(feed["items"]) == 2
        assert {f["value"]: f["count"] for f in feed["facets"]["chamber"]} == {"EK": 2}
        timeline = client.get("/api/dossiers/36791/timeline").json()["entries"]
        vote = next(e for e in timeline if e["node_type"] == "decision")
        assert (vote["body"]["chamber"], vote["body"]["result"]) == ("EK", "Aangenomen")
        assert vote["body"]["method"] == "Stemming bij zitten en opstaan, aangenomen"
    finally:
        app.dependency_overrides.pop(get_store, None)
