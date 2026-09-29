"""``GET /api/feed`` on a small graph that has one event of every kind: what each item shows,
every filter, the facets under the other filters, and pages that neither repeat nor skip."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_PART_OF,
)
from lawgraph.config.settings import API_ALLOWED_ORIGINS, SITE_URL
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter

# TK GUIDs: a member's key is its GUID made a node key.
AALDERS = "11111111-1111-1111-1111-111111111111"
BAKKER = "22222222-2222-2222-2222-222222222222"
HEINEN = "33333333-3333-3333-3333-333333333333"
MOTION_CASE = "44444444-4444-4444-4444-444444444444"
AALDERS_KEY = AALDERS.replace("-", "_")
BAKKER_KEY = BAKKER.replace("-", "_")
HEINEN_KEY = HEINEN.replace("-", "_")


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    labels = props.pop("labels", ["TK"])
    return Node(
        collection=collection, type=node_type, key=key, labels=labels, props=props
    )


def _actor(person: str, faction: str | None, role: str, capacity: str) -> dict:
    return {
        "person_id": person,
        "faction_id": faction,
        "name": {AALDERS: "A. Aalders", BAKKER: "B. Bakker", HEINEN: "E. Heinen"}.get(
            person, "griffier"
        ),
        "role": role,
        "function": "Tweede Kamerlid" if capacity == "kamerlid" else "minister",
        "capacity": capacity,
    }


FIRST = "Eerste ondertekenaar"
CO = "Mede ondertekenaar"


def _document(key: str, kind: str, date: str, dossier: str, **props: Any) -> Node:
    return _node(
        COLLECTION_DOCUMENTS,
        NodeType.DOCUMENT,
        key,
        kind=kind,
        date=date,
        dossier_numbers=[dossier],
        document_number=f"2026D{key[-3:]}",
        **props,
    )


def _nodes() -> list[Node]:
    return [
        _node(COLLECTION_CABINETS, NodeType.CABINET, "schoof", from_date="2024-07-02"),
        _node(COLLECTION_CABINETS, NodeType.CABINET, "jetten", from_date="2026-02-23"),
        _node(
            COLLECTION_FACTIONS,
            NodeType.FACTION,
            "vvd",
            abbreviation="VVD",
            external_id="f-vvd",
            external_ids=["f-vvd"],
        ),
        _node(
            COLLECTION_FACTIONS,
            NodeType.FACTION,
            "d66",
            abbreviation="D66",
            external_id="f-d66",
            external_ids=["f-d66-old", "f-d66"],
        ),
        _node(
            COLLECTION_MEMBERS,
            NodeType.MEMBER,
            AALDERS_KEY,
            name="Anna Aalders",
            external_id=AALDERS,
        ),
        _node(
            COLLECTION_MEMBERS,
            NodeType.MEMBER,
            BAKKER_KEY,
            name="Bram Bakker",
            external_id=BAKKER,
        ),
        _node(
            COLLECTION_MEMBERS,
            NodeType.MEMBER,
            HEINEN_KEY,
            name="Eelco Heinen",
            external_id=HEINEN,
        ),
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "37000",
            number="37000",
            label="37000",
            title="Wijziging van de Wet voorbeeld (Wet beter voorbeeld)",
            ministry="fin",
        ),
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "37001_vii",
            number="37001",
            suffix="VII",
            label="37001-VII",
            title="Begroting Binnenlandse Zaken 2027",
            ministry="bzk",
        ),
        _document(
            "bill_001",
            "Voorstel van wet",
            "2026-03-01",
            "37000",
            title="Voorstel van wet ",
        ),
        # the source signs the memorandum, not the voorstel: its signatories submitted it
        _document(
            "memorandum_008",
            "Memorie van toelichting",
            "2026-03-01",
            "37000",
            actors=[_actor(HEINEN, None, FIRST, "bewindspersoon")],
        ),
        # the bill as the Eerste Kamer received it is not submitted again
        _document(
            "ek_bill_002",
            "Voorstel van wet",
            "2026-06-15",
            "37000",
            labels=["EersteKamer", "EK"],
        ),
        _document("note_003", "Nota van wijziging", "2026-04-01", "37000"),
        _document(
            "amendment_004",
            "Amendement",
            "2026-05-01",
            "37000",
            subject="Amendement van het lid Aalders over de grens",
            actors=[
                _actor(AALDERS, "f-vvd", FIRST, "kamerlid"),
                _actor(BAKKER, "f-d66-old", CO, "kamerlid"),
            ],
        ),
        _document(
            "motion_005",
            "Motie (gewijzigd/nader)",
            "2026-05-01",
            "37001-VII",
            subject="Gewijzigde motie van het lid Bakker over gemeenten",
            case_ids=[MOTION_CASE],
            actors=[
                _actor(BAKKER, "f-d66", FIRST, "kamerlid"),
                _actor("griffier", None, CO, "overig"),
            ],
        ),
        _document(
            "letter_006",
            "Brief regering",
            "2026-06-01",
            "37001-VII",
            subject="Stand van zaken gemeentefonds",
            actors=[_actor(HEINEN, None, FIRST, "bewindspersoon")],
        ),
        # a paper of another kind is no event
        _document("report_007", "Verslag", "2026-06-02", "37000"),
        _node(
            COLLECTION_CASES, NodeType.CASE, MOTION_CASE.replace("-", "_"), kind="Motie"
        ),
        _node(
            COLLECTION_DECISIONS,
            NodeType.DECISION,
            "stemming_1",
            date="2026-05-12",
            subject="Gewijzigde motie van het lid Bakker over gemeenten",
            decision_text="Aangenomen.",
            primary_case_id=MOTION_CASE,
            dossier_numbers=["37001-VII"],
            kind="motie",
            vote_kind="faction",
            tally={"Voor": 80, "Tegen": 70},
            passed=True,
        ),
        # a decision without an outcome is no vote
        _node(
            COLLECTION_DECISIONS,
            NodeType.DECISION,
            "stemming_2",
            date="2026-05-12",
            subject="Uitstel",
            dossier_numbers=["37001-VII"],
        ),
        _node(
            COLLECTION_COMMITMENTS,
            NodeType.COMMITMENT,
            "commitment_1",
            text="De minister stuurt voor de zomer een brief over de grens.",
            display_name="De minister stuurt voor de zomer een brief…",
            minister_name="Heinen, E.",
            minister_role="Minister van Financiën",
            made_on="2024-09-01",
            expected_resolution="2025-06-01",
            status="Openstaand",
            member_key=HEINEN_KEY,
            ministry="fin",
            cabinet="schoof",
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "bwbr0000001",
            bwb_id="BWBR0000001",
            citation_title="Wet voorbeeld",
            article_count=12,
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0000001_1",
            bwb_id="BWBR0000001",
            article_number="1",
            labels=["BWB"],
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "stb_2026_10",
            kind="publicatie",
            citation_title="Stb. 2026, 10",
            publication_kind="Stb",
            publication_year=2026,
            publication_number="10",
            date_published="2026-07-01",
            dossier_numbers=["37000"],
            labels=["BWB", "Publication"],
        ),
        _node(
            COLLECTION_INSTRUMENT_VERSIONS,
            NodeType.INSTRUMENT_VERSION,
            "bwbr0000001_2026_08_01",
            bwb_id="BWBR0000001",
            valid_from="2026-08-01",
            labels=["BWB", "Version"],
        ),
        *(
            _node(
                COLLECTION_ARTICLE_VERSIONS,
                NodeType.ARTICLE_VERSION,
                f"bwbr0000001_av_{n}_1",
                bwb_id="BWBR0000001",
                valid_from="2026-08-01",
                labels=["BWB"],
            )
            for n in (1, 2)
        ),
    ]


def _seed(store: ArangoStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(_nodes())
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            f"{COLLECTION_COMMITMENTS}/commitment_1",
            f"{COLLECTION_DOSSIERS}/37000",
            RELATION_ABOUT,
            source="t",
        )
        edges.add(
            f"{COLLECTION_DOCUMENTS}/motion_005",
            f"{COLLECTION_CASES}/{MOTION_CASE.replace('-', '_')}",
            RELATION_PART_OF,
            source="t",
        )
        edges.add(
            f"{COLLECTION_INSTRUMENTS}/stb_2026_10",
            f"{COLLECTION_ARTICLES}/bwbr0000001_1",
            RELATION_AMENDS,
            source="t",
        )


def _test_client() -> TestClient:
    """A client of the front end, whose origin the rate limit lets through: these tests ask
    more than the limit allows one address, and the tests after them would get 429."""
    return TestClient(app, headers={"Origin": API_ALLOWED_ORIGINS[0]})


@pytest.fixture()
def client(database: str) -> Iterator[TestClient]:
    store = ArangoStore()
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield _test_client()
    finally:
        app.dependency_overrides.pop(get_store, None)


def _feed(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/feed", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(answer: dict[str, Any]) -> list[str]:
    return [item["id"] for item in answer["items"]]


def _counts(facet: list[dict[str, Any]]) -> dict[str | None, int]:
    return {row["value"]: row["count"] for row in facet}


ALL = [
    "instrument_versions/bwbr0000001_2026_08_01",
    "instruments/stb_2026_10",
    "documents/letter_006",
    "decisions/stemming_1",
    # two papers of one day: by kind, an amendment before a motion
    "documents/amendment_004",
    "documents/motion_005",
    "documents/note_003",
    "documents/bill_001",
    "commitments/commitment_1",
]


def test_every_kind_is_an_event_newest_first(client: TestClient) -> None:
    answer = _feed(client)
    assert _ids(answer) == ALL
    assert answer["total"] == 9
    assert answer["next_cursor"] is None
    items = {item["kind"]: item for item in answer["items"]}
    assert set(items) == {
        "toezegging",
        "Voorstel van wet",
        "Nota van wijziging",
        "Amendement",
        "Motie",
        "stemming",
        "publicatie",
        "inwerkingtreding",
        "Brief regering",
    }

    commitment = items["toezegging"]
    assert commitment["title"] == "De minister stuurt voor de zomer een brief…"
    assert commitment["summary"].startswith("De minister stuurt")
    assert commitment["commitment"] == {
        "status": "Openstaand",
        "expected_resolution": "2025-06-01",
    }
    assert commitment["persons"] == [
        {
            "key": HEINEN_KEY,
            "name": "Eelco Heinen",
            "surname": "Heinen",
            "function": "Minister van Financiën",
            "role": "bewindspersoon",
            "faction": None,
        }
    ]
    assert (commitment["ministry"], commitment["cabinet"]) == ("fin", "schoof")
    assert commitment["dossier"] == {
        "key": "37000",
        "number": "37000",
        "title": "Wijziging van de Wet voorbeeld (Wet beter voorbeeld)",
        "short_title": "Wet beter voorbeeld",
        "short_title_basis": "title",
    }

    amendment = items["Amendement"]
    assert amendment["title"] == "Amendement van het lid Aalders over de grens"
    assert amendment["subkind"] == "Amendement"
    assert amendment["node"] == {"collection": "documents", "key": "amendment_004"}
    assert amendment["tk_url"].endswith("2026D004")
    assert amendment["ministry"] == "fin"  # of its dossier
    assert amendment["cabinet"] == "jetten"
    assert amendment["persons"] == [
        {
            "key": AALDERS_KEY,
            "name": "Anna Aalders",
            "surname": "Aalders",
            "function": "Tweede Kamerlid",
            "role": "indiener",
            "faction": {"key": "vvd", "short": "VVD"},
        },
        {
            "key": BAKKER_KEY,
            "name": "Bram Bakker",
            "surname": "Bakker",
            "function": "Tweede Kamerlid",
            "role": "medeindiener",
            # an older Fractie record of the faction
            "faction": {"key": "d66", "short": "D66"},
        },
    ]

    assert amendment["headline"] == {
        "surname": "Aalders",
        "subject": "de grens",
        "short_title": "Wet beter voorbeeld",
    }
    # the griffier signs, but is no person of the event
    assert [p["key"] for p in items["Motie"]["persons"]] == [BAKKER_KEY]
    assert items["Motie"]["subkind"] == "Motie (gewijzigd/nader)"
    # named as the member routes name them, whatever the paper writes
    assert items["Brief regering"]["persons"][0]["name"] == "Eelco Heinen"
    bill = items["Voorstel van wet"]
    assert bill["title"] == "Wijziging van de Wet voorbeeld (Wet beter voorbeeld)"
    assert bill["persons"] == [
        {
            "key": HEINEN_KEY,
            "name": "Eelco Heinen",
            "surname": "Heinen",
            "function": "minister",
            "role": "indiener",
            "faction": None,
        }
    ]

    assert bill["headline"]["short_title"] == "Wet beter voorbeeld"

    vote = items["stemming"]
    assert vote["headline"] == {
        "surname": "Bakker",
        "subject": "gemeenten",
        "short_title": None,
    }
    assert vote["vote"] == {
        "passed": True,
        "outcome": "aangenomen",
        "vote_kind": "faction",
        "tally": {"Voor": 80, "Tegen": 70},
    }
    assert vote["subkind"] == "motie"
    assert vote["summary"] == "Aangenomen."
    # the signatures of the motion it decided
    assert [p["key"] for p in vote["persons"]] == [BAKKER_KEY]
    assert vote["ministry"] == "bzk"

    publication = items["publicatie"]
    assert publication["title"] == "Stb. 2026, 10"
    assert publication["publication"] == {
        "series": "stb",
        "year": 2026,
        "number": "10",
        "instruments": [
            {
                "key": "bwbr0000001",
                "title": "Wet voorbeeld",
                "official_url": "https://wetten.overheid.nl/BWBR0000001",
            }
        ],
    }
    assert publication["official_url"].endswith("stb-2026-10.html")
    assert publication["dossier"]["number"] == "37000"

    commencement = items["inwerkingtreding"]
    assert commencement["title"] == "Wet voorbeeld"
    assert commencement["official_url"] == (
        "https://wetten.overheid.nl/BWBR0000001/2026-08-01"
    )
    assert commencement["commencement"] == {
        "instrument": {
            "key": "bwbr0000001",
            "title": "Wet voorbeeld",
            "official_url": "https://wetten.overheid.nl/BWBR0000001",
        },
        "article_count": 12,
        "changed_articles": 2,
    }
    assert commencement["dossier"] is None


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"kind": "Motie,stemming"}, ["decisions/stemming_1", "documents/motion_005"]),
        ({"since": "2026-05-01", "until": "2026-05-31"}, ALL[3:6]),
        ({"cabinet": "schoof"}, ["commitments/commitment_1"]),
        ({"cabinet": "nobody"}, []),
        (
            {"ministry": "fin"},
            [
                "instruments/stb_2026_10",
                "documents/amendment_004",
                "documents/note_003",
                "documents/bill_001",
                "commitments/commitment_1",
            ],
        ),
        (
            {"dossier": "37001"},
            ["documents/letter_006", "decisions/stemming_1", "documents/motion_005"],
        ),
        (
            {"dossier": "37001-VII"},
            ["documents/letter_006", "decisions/stemming_1", "documents/motion_005"],
        ),
        ({"dossier": "3700"}, ALL[1:]),
        (
            {"member": BAKKER_KEY},
            [
                "decisions/stemming_1",
                "documents/amendment_004",
                "documents/motion_005",
            ],
        ),
        (
            {"member": HEINEN_KEY},
            [
                "documents/letter_006",
                "documents/bill_001",
                "commitments/commitment_1",
            ],
        ),
        ({"member": "nobody"}, []),
        ({"faction": "vvd"}, ["documents/amendment_004"]),
        (
            {"faction": "d66"},
            [
                "decisions/stemming_1",
                "documents/amendment_004",
                "documents/motion_005",
            ],
        ),
        # the title, or the title of the dossier
        ({"q": "GRENS"}, ["documents/amendment_004", "commitments/commitment_1"]),
        (
            {"q": "binnenlandse"},
            ["documents/letter_006", "decisions/stemming_1", "documents/motion_005"],
        ),
        ({"q": "wet voorbeeld", "kind": "inwerkingtreding"}, ALL[:1]),
    ],
)
@pytest.mark.parametrize("facets", [True, False])
def test_a_filter_keeps_its_events(
    client: TestClient, params: dict[str, str], expected: list[str], facets: bool
) -> None:
    answer = _feed(client, facets=facets, **params)
    assert _ids(answer) == expected
    if facets:
        assert answer["total"] == len(expected)
    else:
        assert answer["total"] is None and answer["facets"] is None


def test_each_facet_is_counted_under_the_other_filters(client: TestClient) -> None:
    answer = _feed(client, kind="Motie", ministry="bzk")
    facets = answer["facets"]
    assert answer["total"] == 1
    # every kind of dossier 37001-VII (the ministry bzk), whatever the kind asked for
    assert _counts(facets["kind"]) == {"Brief regering": 1, "stemming": 1, "Motie": 1}
    # the motions of every ministry
    assert _counts(facets["ministry"]) == {"bzk": 1}
    assert _counts(facets["faction"]) == {"d66": 1}
    assert _counts(facets["cabinet"]) == {"jetten": 1}

    everything = _feed(client)["facets"]
    assert _counts(everything["ministry"]) == {"fin": 5, "bzk": 3, None: 1}
    assert _counts(everything["cabinet"]) == {"jetten": 8, "schoof": 1}
    # the amendment counts for both its factions
    assert _counts(everything["faction"]) == {None: 6, "d66": 3, "vvd": 1}
    assert _counts(_feed(client, cabinet="schoof")["facets"]["cabinet"]) == {
        "jetten": 8,
        "schoof": 1,
    }


@pytest.mark.parametrize("limit", [1, 2, 3])
@pytest.mark.parametrize("facets", [True, False])
def test_the_pages_neither_repeat_nor_skip(
    client: TestClient, facets: bool, limit: int
) -> None:
    """A page may end inside a day (the motion and the amendment of 1 May)."""
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params: dict[str, Any] = {"limit": limit, "facets": facets}
        if cursor:
            params["cursor"] = cursor
        answer = _feed(client, **params)
        seen += _ids(answer)
        cursor = answer["next_cursor"]
        if cursor is None:
            break
    assert seen == ALL


def test_the_feed_as_atom_has_the_same_events(client: TestClient) -> None:
    response = client.get(
        "/api/feed.atom", params={"kind": "Motie,stemming", "limit": 1}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/atom+xml")
    root = ElementTree.fromstring(response.content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    assert [e.find("a:id", ns).text for e in entries] == [  # type: ignore[union-attr]
        "tag:lawgraph,2026:decisions/stemming_1"
    ]
    assert root.find("a:title", ns).text == "Concordans: moties en stemmingen"  # type: ignore[union-attr]
    following = {
        link.get("rel"): link.get("href") for link in root.findall("a:link", ns)
    }
    assert "kind=Motie%2Cstemming" in following["next"]
    assert "cursor=" in following["next"]
    assert following["alternate"] == f"{SITE_URL}/actueel?soort=Motie%2Cstemming"
    entry = {
        link.get("rel"): link.get("href") for link in entries[0].findall("a:link", ns)
    }
    assert entry == {"alternate": f"{SITE_URL}/explore?focus=decisions/stemming_1"}


def test_the_feed_and_its_atom_are_sent_compressed(client: TestClient) -> None:
    gzip = {"Accept-Encoding": "gzip"}
    for path in ("/api/feed", "/api/feed.atom"):
        response = client.get(path, headers=gzip)
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip", path


def test_a_cursor_or_kind_that_is_none_is_422(client: TestClient) -> None:
    assert client.get("/api/feed?cursor=nonsense").status_code == 422
    assert client.get("/api/feed?kind=Motie,roddel").status_code == 422
    assert client.get("/api/feed?dossier=abc").status_code == 422


def _busy_days() -> list[Node]:
    """Publications, votes and commitments, many of each kind on each of a few days."""
    day = ["2026-07-01", "2026-06-30", "2026-06-29"]
    return [
        *(
            _node(
                COLLECTION_INSTRUMENTS,
                NodeType.INSTRUMENT,
                f"stb_2026_{n}",
                kind="publicatie",
                citation_title=f"Stb. 2026, {n}",
                date_published=day[n % 3],
                labels=["BWB", "Publication"],
            )
            for n in range(1, 151)
        ),
        *(
            _node(
                COLLECTION_DECISIONS,
                NodeType.DECISION,
                f"stemming_{n}",
                date=day[n % 3],
                subject=f"Motie {n}",
                passed=n % 2 == 0,
            )
            for n in range(1, 91)
        ),
        *(
            _node(
                COLLECTION_COMMITMENTS,
                NodeType.COMMITMENT,
                f"commitment_{n}",
                text=f"Toezegging {n}",
                made_on=day[n % 3],
            )
            for n in range(1, 61)
        ),
    ]


@pytest.mark.parametrize("facets", [False, True])
def test_busy_days_are_paged_whole_by_day_kind_and_id(
    database: str, facets: bool
) -> None:
    """Pages end inside a day and inside a kind; each event is on one page, in the order of
    the feed: the day, newest first, then the kind (a vote before a commitment before a
    publication), then the id."""
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(_busy_days())
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = _test_client()
        seen: list[dict[str, Any]] = []
        cursor = None
        for _ in range(60):
            params: dict[str, Any] = {"limit": 7, "facets": facets}
            if cursor:
                params["cursor"] = cursor
            answer = _feed(client, **params)
            seen += answer["items"]
            cursor = answer["next_cursor"]
            if cursor is None:
                break
    finally:
        app.dependency_overrides.pop(get_store, None)
    ids = [item["id"] for item in seen]
    assert len(ids) == len(set(ids)) == 300
    rank = {"stemming": 1, "toezegging": 2, "publicatie": 4}
    order = sorted(seen, key=lambda item: item["id"])
    order.sort(key=lambda item: rank[item["kind"]])
    order.sort(key=lambda item: item["date"], reverse=True)
    assert ids == [item["id"] for item in order]


def test_a_summary_counts_the_days_and_shows_what_matters(client: TestClient) -> None:
    response = client.get(
        "/api/feed/summary", params={"until": "2026-05-12", "days": 12}
    )
    assert response.status_code == 200, response.text
    summary = response.json()
    assert (summary["since"], summary["until"], summary["margin"]) == (
        "2026-05-01",
        "2026-05-12",
        10,
    )
    days = {day["date"]: day for day in summary["days"]}
    assert len(summary["days"]) == 12
    assert summary["days"][0]["date"] == "2026-05-12"
    assert days["2026-05-05"] == {
        "date": "2026-05-05",
        "total": 0,
        "kinds": [],
        "dossiers": [],
        "votes": [],
    }
    assert days["2026-05-12"]["votes"] == [
        {"subkind": "motie", "outcome": "aangenomen", "count": 1}
    ]
    may_first = days["2026-05-01"]
    assert may_first["total"] == 2
    assert {k["value"]: k["count"] for k in may_first["kinds"]} == {
        "Amendement": 1,
        "Motie": 1,
    }
    assert [
        (d["kind"], d["number"], d["short_title"], d["count"])
        for d in may_first["dossiers"]
    ] == [
        ("Amendement", "37000", "Wet beter voorbeeld", 1),
        ("Motie", "37001-VII", None, 1),
    ]
    assert isinstance(summary["data_as_of"], dict)
    # the vote is decided by 10 seats: close enough by default
    assert [item["id"] for item in summary["items"]] == ["decisions/stemming_1"]
    assert summary["items"][0]["headline"]["surname"] == "Bakker"

    # a closer margin, and no day is quiet enough to show all its votes
    closer = client.get(
        "/api/feed/summary",
        params={"until": "2026-05-12", "days": 12, "margin": 5, "few": 0},
    ).json()
    assert closer["items"] == []
    # the only vote of its day is shown, whatever its margin
    quiet = client.get(
        "/api/feed/summary", params={"until": "2026-05-12", "days": 12, "margin": 5}
    ).json()
    assert [item["id"] for item in quiet["items"]] == ["decisions/stemming_1"]
    bill_day = client.get(
        "/api/feed/summary", params={"until": "2026-03-01", "days": 1}
    ).json()
    assert [item["id"] for item in bill_day["items"]] == ["documents/bill_001"]
    by_member = client.get(
        "/api/feed/summary",
        params={"until": "2026-05-12", "days": 12, "member": AALDERS_KEY},
    ).json()
    assert sum(day["total"] for day in by_member["days"]) == 1
    assert client.get("/api/feed/summary?days=0").status_code == 422


def test_a_bill_goes_by_the_name_official_data_give_it(database: str) -> None:
    """The citation title in the bill itself, else of its case, else of the one Dutch law
    it changes; nothing when there is none of them (a law of the EU is no name)."""
    case = "55555555-5555-5555-5555-555555555555"
    nodes = [
        *(
            _node(
                COLLECTION_DOSSIERS,
                NodeType.DOSSIER,
                number,
                number=number,
                label=number,
                title="Wijziging van enige wetten",
            )
            for number in ("38001", "38002", "38003", "38004")
        ),
        _document(
            "bill_101",
            "Voorstel van wet",
            "2026-06-01",
            "38001",
            text="Artikel III\nDeze wet wordt aangehaald als: Wet sterkere archieven.",
        ),
        _document(
            "bill_102", "Voorstel van wet", "2026-06-02", "38002", case_ids=[case]
        ),
        _document("bill_103", "Voorstel van wet", "2026-06-03", "38003"),
        _document("bill_104", "Voorstel van wet", "2026-06-04", "38004"),
        _node(
            COLLECTION_CASES,
            NodeType.CASE,
            case.replace("-", "_"),
            citation_title="Wet open overheid",
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "bwbr0007376",
            bwb_id="BWBR0007376",
            citation_title="Archiefwet 1995",
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "32019l1937",
            celex="32019L1937",
            citation_title="Richtlijn 2019/1937/EU",
            labels=["EU"],
        ),
    ]
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(nodes)
    with EdgeWriter(store, what=None) as edges:
        for paper, law in (("bill_103", "bwbr0007376"), ("bill_104", "32019l1937")):
            edges.add(
                f"{COLLECTION_DOCUMENTS}/{paper}",
                f"{COLLECTION_INSTRUMENTS}/{law}",
                RELATION_AMENDS,
                source="t",
                status="voorgesteld",
            )
    app.dependency_overrides[get_store] = lambda: store
    try:
        items = _feed(_test_client(), kind="Voorstel van wet")["items"]
    finally:
        app.dependency_overrides.pop(get_store, None)
    names = {
        item["dossier"]["number"]: (
            item["dossier"]["short_title"],
            item["dossier"]["short_title_basis"],
            item["headline"]["short_title"],
        )
        for item in items
    }
    assert names == {
        "38001": ("Wet sterkere archieven", "citation", "Wet sterkere archieven"),
        "38002": ("Wet open overheid", "case", "Wet open overheid"),
        "38003": ("Archiefwet 1995", "amended_law", "Archiefwet 1995"),
        "38004": (None, None, None),
    }
