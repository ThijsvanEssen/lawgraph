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
from lawgraph.db import GraphStore, NodeWriter, RawSourceWriter, raw_source_doc

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
def store(database: str, cli: Any) -> Iterator[GraphStore]:
    store = GraphStore()
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


def _props(store: GraphStore, number: str) -> dict[str, Any]:
    return store.get_document(COLLECTION_DOSSIERS, number)["props"]


def test_the_eerste_kamer_decides_the_bill(store: GraphStore, cli: Any) -> None:
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
            "SELECT json_build_array(props -> 'dossier_numbers' -> 0,"
            " props -> 'bill_decision') FROM decisions"
            " WHERE lg_str(props -> 'chamber') = 'EK'"
        )
    )
    assert len(decisions) == 5  # the votes of 29 September 2026
    assert ["36791", True] in decisions

    # a second run changes nothing
    done = cli("semantic", "tk-dossier-outcomes")
    assert "0 changed" in done.stderr + done.stdout

    # the votes of the BBB are edges; a second normalize keeps them as they are
    voted = "SELECT count(*) FROM edges WHERE relation = 'VOTED'"
    before = next(store.query(voted))
    assert before >= 1
    cli("normalize", "eerstekamer-votes")
    assert next(store.query(voted)) == before


def test_the_api_shows_the_eerste_kamer(store: GraphStore) -> None:
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
        # the factions the graph holds vote as edges; FVD has no faction node here
        assert [(v["voter_key"], v["choice"], v["seats"]) for v in detail["votes"]] == [
            ("ek_boerburgerbeweging", "Tegen", 0)
        ]
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


def test_a_vote_on_a_motion_is_its_own_decision_and_a_day_read_is_derived_in_full(
    database: str, cli: Any
) -> None:
    """The list of every vote (2026-10-06, as served on 2026-10-09): a vote on a motion is a
    decision of its own, on the motion's letter, about the motion (``Kamerstuk I 37020,
    M``) and its dossier. A decision of that day the list no longer gives (made when a
    motion counted as a vote on its bill) goes with its edges; one of a day not read stays.
    A vote on a motion decides no bill."""
    from lawgraph.config.constants import COLLECTION_DECISIONS, COLLECTION_DOCUMENTS

    store = GraphStore()
    stale = Node(
        collection=COLLECTION_DECISIONS,
        type=NodeType.DECISION,
        key="ek_2026_10_06_37020_2",
        labels=["EK"],
        props={"chamber": "EK", "date": "2026-10-06", "dossier_numbers": ["37020"]},
    )
    other_day = Node(
        collection=COLLECTION_DECISIONS,
        type=NodeType.DECISION,
        key="ek_2026_09_29_99999_1",
        labels=["EK"],
        props={"chamber": "EK", "date": "2026-09-29", "dossier_numbers": ["99999"]},
    )
    motion_m = Node(
        collection=COLLECTION_DOCUMENTS,
        type=NodeType.DOCUMENT,
        key="ek_kst_1000001",
        labels=["EersteKamer", "EK"],
        props={
            "number": "M",
            "kind": "Motie",
            "dossier_number": "37020",
            "dossier_numbers": ["37020"],
            "title": "Motie van het lid Beukering c.s.",
        },
    )
    with NodeWriter(store) as writer:
        writer.add_all([_dossier("37020"), stale, other_day, motion_m])
        writer.add(
            Node(
                collection=COLLECTION_FACTIONS,
                type=NodeType.FACTION,
                key="ek_boerburgerbeweging",
                labels=["EK"],
                props={"chamber": "EK", "name": "BBB-fractie", "abbreviation": "BBB"},
            )
        )
    store.execute(
        "INSERT INTO edges (key, from_id, to_id, doc) VALUES ('stale_vote',"
        " 'factions/ek_boerburgerbeweging', 'decisions/ek_2026_10_06_37020_2',"
        " json_build_object('relation', 'VOTED'))"
    )
    day, _, fragment = ev.days((FIXTURES / "ek_votes_alles_page_1.html").read_text())[0]
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_VOTES_DAY,
                external_id=day,
                payload_text=fragment,
                meta={"url": "https://www.eerstekamer.nl/x", "read_on": "2026-10-09"},
            )
        )
    cli("normalize", "eerstekamer-votes")
    cli("semantic", "tk-dossier-outcomes")

    keys = set(store.query("SELECT key FROM decisions ORDER BY key"))
    assert "ek_2026_10_06_37020_m" in keys and "ek_2026_10_06_36920_1" in keys
    assert "ek_2026_10_06_37020_2" not in keys  # no longer in the list: gone
    assert "ek_2026_09_29_99999_1" in keys  # a day not read stays
    assert len([k for k in keys if k.startswith("ek_2026_10_06_")]) == 14
    assert next(store.query("SELECT count(*) FROM edges WHERE key = 'stale_vote'")) == 0

    motion = store.get_document(COLLECTION_DECISIONS, "ek_2026_10_06_37020_m")["props"]
    assert (motion["kind"], motion["letter"], motion["result"]) == (
        "Motie",
        "M",
        "Verworpen",
    )
    assert motion["motion_url"].endswith(
        "/motiedossier/37020_m_motie_beukering_fractie"
    )
    about = set(
        store.query(
            "SELECT to_id FROM edges WHERE from_id = 'decisions/ek_2026_10_06_37020_m'"
            " AND relation = 'ABOUT' ORDER BY to_id"
        )
    )
    assert about == {"dossiers/37020", "documents/ek_kst_1000001"}
    voted = list(
        store.query(
            "SELECT doc -> 'meta' ->> 'choice' FROM edges WHERE relation = 'VOTED'"
            " AND to_id = 'decisions/ek_2026_10_06_37020_m'"
        )
    )
    assert voted == ["Voor"]  # BBB voted for
    # nine motions on the Algemene Politieke Beschouwingen decide no bill
    assert not _props(store, "37020").get("ek_outcome")
