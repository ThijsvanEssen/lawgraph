"""The feed queries on a real PostgreSQL, through ``GET /api/feed``, its summary and
``feed.atom`` on a small graph that has one event of every kind (what each item shows, every
filter, the facets under the other filters, pages that neither repeat nor skip), and through
``get_feed`` and ``get_feed_summary`` on the edges of their order, types and shapes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
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
from lawgraph.config.settings import SITE_URL
from lawgraph.core.feed import FeedCursor
from lawgraph.core.models import Node, NodeType
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter
from lawgraph.db.queries.feed import (
    FeedFilters,
    feed_query,
    get_feed,
    get_feed_summary,
)

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
            kind="Motie",
            decision_kind="Stemmen - aangenomen",
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


def _seed(store: GraphStore) -> None:
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
    """A client of the API (the suite's rate limit is set high in ``tests/conftest.py``)."""
    return TestClient(app)


def _serve(store: GraphStore) -> None:
    """The routes on *store* (``data_as_of`` is cached per database, and every test has a
    database of its own)."""
    app.dependency_overrides[get_store] = lambda: store


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    _seed(store)
    _serve(store)
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
        "chamber": "TK",
        "passed": True,
        "outcome": "aangenomen",
        "vote_kind": "faction",
        "tally": {"Voor": 80, "Tegen": 70},
        # how it was decided, as the Kamer writes it
        "method": None,
        "decision_kind": "Stemmen - aangenomen",
    }
    assert vote["subkind"] == "Motie"
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
    following_page = following["next"] or ""
    assert "kind=Motie%2Cstemming" in following_page
    assert "cursor=" in following_page
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
    store: GraphStore, facets: bool
) -> None:
    """Pages end inside a day and inside a kind; each event is on one page, in the order of
    the feed: the day, newest first, then the kind (a vote before a commitment before a
    publication), then the id."""
    with NodeWriter(store) as writer:
        writer.add_all(_busy_days())
    _serve(store)
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
        {"chamber": "TK", "subkind": "Motie", "outcome": "aangenomen", "count": 1}
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


def test_a_bill_goes_by_the_name_official_data_give_it(store: GraphStore) -> None:
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
    _serve(store)
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


def test_a_page_after_a_cursor_counts_the_whole_window(client: TestClient) -> None:
    """The facets and the total are those of every event under the filters, also on the
    pages after the first; the items continue after the cursor."""
    first = _feed(client, limit=2)
    second = _feed(client, limit=2, cursor=first["next_cursor"])
    assert _ids(second) == ALL[2:4]
    assert second["total"] == first["total"] == len(ALL)
    assert second["facets"] == first["facets"]


def test_q_is_matched_as_lower_case_words(client: TestClient) -> None:
    expected = ["documents/amendment_004", "commitments/commitment_1"]
    assert _ids(_feed(client, q="  Grens ")) == expected


@pytest.mark.parametrize(
    "params",
    [
        {"kind": "Motie,stemming"},
        {"kind": "Motie", "q": "binnenlandse"},
        {"member": BAKKER_KEY, "cabinet": "jetten"},
    ],
)
def test_a_summary_counts_what_the_feed_lists_under_the_same_filters(
    client: TestClient, params: dict[str, str]
) -> None:
    window = {"since": "2026-05-01", "until": "2026-05-12"}
    listed = _feed(client, **window, **params)
    response = client.get(
        "/api/feed/summary", params={"until": "2026-05-12", "days": 12, **params}
    )
    assert response.status_code == 200, response.text
    counted = sum(day["total"] for day in response.json()["days"])
    assert counted == len(listed["items"]) > 0


# ── get_feed and get_feed_summary: order, types and shapes ───────────────────


def _raw(key: str, labels: list[str] | None = None, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": labels or [], "props": props}


def _raw_edge(source: str, target: str, relation: str) -> dict[str, Any]:
    key = f"{source}_{relation}_{target}".replace("/", "_")
    return {"_key": key, "_from": source, "_to": target, "relation": relation}


def _load(store: GraphStore, nodes: dict[str, list[dict[str, Any]]]) -> None:
    for collection, docs in nodes.items():
        store.bulk_insert_or_update_nodes(collection, docs)


ITEM_KEYS = [
    "kind",
    "id",
    "date",
    "ministry",
    "cabinet",
    "dossier",
    "props",
    "text",
    "persons",
    "instrument",
    "changed_articles",
    "changed_instruments",
]


def test_the_answer_and_its_items_keep_their_keys_in_order(store: GraphStore) -> None:
    _seed(store)
    raw = get_feed(store, FeedFilters())
    assert list(raw) == ["items", "total", "facets"]
    assert isinstance(raw["total"], int) and raw["total"] == len(ALL)
    assert list(raw["facets"]) == ["kind", "ministry", "faction", "cabinet", "chamber"]
    for facet in raw["facets"].values():
        for row in facet:
            assert list(row) == ["value", "count"]
            assert isinstance(row["count"], int)
    assert [item["id"] for item in raw["items"]] == ALL
    items = {item["kind"]: item for item in raw["items"]}
    for item in raw["items"]:
        assert list(item) == ITEM_KEYS
        assert isinstance(item["changed_articles"], int)
    assert list(items["Amendement"]["dossier"]) == [
        "key",
        "number",
        "title",
        "official_short",
    ]
    # the props the item shows, in the byte order of their names (as KEEP gave them)
    assert list(items["stemming"]["props"]) == [
        "decision_kind",
        "decision_text",
        "kind",
        "passed",
        "subject",
        "tally",
        "vote_kind",
    ]
    assert list(items["stemming"]["props"]["tally"]) == ["Voor", "Tegen"]
    commencement = items["inwerkingtreding"]
    assert commencement["changed_articles"] == 2
    assert list(commencement["instrument"]) == [
        "key",
        "title",
        "bwb_id",
        "article_count",
    ]
    assert commencement["instrument"]["article_count"] == 12
    assert list(items["publicatie"]["changed_instruments"][0]) == [
        "key",
        "title",
        "bwb_id",
    ]
    person = items["Amendement"]["persons"][0]
    assert {"member_key", "member_name", "faction"} <= set(person)
    assert person["faction"] == {"key": "vvd", "short": "VVD"}
    assert items["toezegging"]["text"].startswith("De minister")
    assert items["Motie"]["text"] is None

    without = get_feed(store, FeedFilters(), facets=False)
    assert list(without) == ["items", "total", "facets"]
    assert (without["total"], without["facets"]) == (None, None)
    assert without["items"] == raw["items"]


def test_a_summary_keeps_its_keys_in_order(store: GraphStore) -> None:
    _seed(store)
    summary = get_feed_summary(
        store, FeedFilters(since="2026-03-01", until="2026-05-12")
    )
    assert list(summary) == ["days", "dossiers", "items"]
    assert [day["date"] for day in summary["days"]] == [
        "2026-05-12",
        "2026-05-01",
        "2026-04-01",
        "2026-03-01",
    ]
    for day in summary["days"]:
        assert list(day) == ["date", "total", "kinds", "dossiers", "votes"]
        assert isinstance(day["total"], int)
        for row in day["dossiers"]:
            assert list(row) == ["kind", "number", "count"]
        for row in day["votes"]:
            assert list(row) == ["chamber", "subkind", "passed", "count"]
    assert [d["number"] for d in summary["dossiers"]] == ["37000", "37001-VII"]
    for row in summary["dossiers"]:
        assert list(row) == ["number", "key", "title", "official_short"]
    for item in summary["items"]:
        assert list(item) == ITEM_KEYS


def test_an_empty_graph_has_no_events(store: GraphStore) -> None:
    raw = get_feed(store, FeedFilters())
    assert raw == {
        "items": [],
        "total": 0,
        "facets": {
            "kind": [],
            "ministry": [],
            "faction": [],
            "cabinet": [],
            "chamber": [],
        },
    }
    assert get_feed(store, FeedFilters(), facets=False) == {
        "items": [],
        "total": None,
        "facets": None,
    }
    assert get_feed_summary(store, FeedFilters(since="2026-01-01")) == {
        "days": [],
        "dossiers": [],
        "items": [],
    }
    # a filter no kind can meet reads no kind at all
    nothing = get_feed(
        store, FeedFilters(kinds=("toezegging",), faction="x"), facets=False
    )
    assert nothing["items"] == []


def _same_day(store: GraphStore) -> None:
    _load(
        store,
        {
            COLLECTION_DOCUMENTS: [
                _raw(key, ["TK"], kind="Motie", date="2026-05-01", subject=key)
                for key in ("motion_C", "Motion_b", "motion_a")
            ]
            + [_raw("bill", ["TK"], kind="Voorstel van wet", date="2026-05-01")],
        },
    )


@pytest.mark.parametrize("facets", [True, False])
def test_events_of_a_day_and_kind_go_by_id_in_the_collation(
    store: GraphStore, facets: bool
) -> None:
    """The ids of one day and kind sort as ArangoDB sorted them, case after letter, and a
    cursor between two of them goes on with the next."""
    _same_day(store)
    expected = [
        "documents/bill",
        "documents/motion_a",
        "documents/Motion_b",
        "documents/motion_C",
    ]
    assert _ids(get_feed(store, FeedFilters(), facets=facets)) == expected
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        raw = get_feed(store, FeedFilters(), cursor=cursor, limit=1, facets=facets)
        seen.append(raw["items"][0]["id"])
        if len(raw["items"]) == 1:
            break
        last = raw["items"][0]
        cursor = FeedCursor(date=last["date"], kind=last["kind"], id=last["id"])
    assert seen == expected


def test_a_page_as_long_as_the_events_has_no_next(store: GraphStore) -> None:
    _same_day(store)
    assert len(get_feed(store, FeedFilters(), limit=4)["items"]) == 4
    assert len(get_feed(store, FeedFilters(), limit=3)["items"]) == 4
    assert len(get_feed(store, FeedFilters(), limit=3, facets=False)["items"]) == 4


def test_one_statement_reads_a_page_whatever_its_size(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store)
    statements: list[str] = []
    query = store.query

    def counted(sql: Any, params: Any = None, **kwargs: Any) -> Any:
        statements.append(sql)
        return query(sql, params, **kwargs)

    monkeypatch.setattr(store, "query", counted)
    for limit in (1, 50):
        for facets in (True, False):
            get_feed(store, FeedFilters(), limit=limit, facets=facets)
    get_feed_summary(store, FeedFilters(since="2026-01-01"))
    feed = [s for s in statements if "lg_data_version" not in str(s)]
    # a page each (4), the total and facets once (kept for the second page with facets,
    # whatever its size), the summary
    assert len(feed) == 6


def test_props_of_another_type_are_no_event_or_no_dossier(store: GraphStore) -> None:
    """A decision whose ``passed`` is no boolean is no vote; dossier numbers that are no
    list give no dossier; a commitment's first dossier is the one whose label sorts first,
    a dossier without a label before all (null sorts first)."""
    _load(
        store,
        {
            COLLECTION_DECISIONS: [
                _raw("vote_str", date="2026-05-01", passed="true"),
                _raw("vote", date="2026-05-01", passed=False, dossier_numbers="37000"),
            ],
            COLLECTION_DOSSIERS: [
                _raw("37000", label="37000", ministry="fin"),
                _raw("unlabelled", ministry="bzk"),
            ],
            COLLECTION_COMMITMENTS: [_raw("c1", made_on="2026-05-01", text="t")],
        },
    )
    store.bulk_insert_or_update_edges(
        [
            _raw_edge("commitments/c1", "dossiers/37000", RELATION_ABOUT),
            _raw_edge("commitments/c1", "dossiers/unlabelled", RELATION_ABOUT),
        ]
    )
    raw = get_feed(store, FeedFilters())
    assert _ids(raw) == ["decisions/vote", "commitments/c1"]
    assert [item["dossier"] for item in raw["items"]] == [None, None]
    # the dossier filter reads every label, not only the first
    assert _ids(get_feed(store, FeedFilters(dossier="37000"))) == ["commitments/c1"]


def test_a_cabinet_starts_on_its_day_the_later_key_first(store: GraphStore) -> None:
    _load(
        store,
        {
            COLLECTION_CABINETS: [
                _raw("a", from_date="2024-07-02"),
                _raw("b", from_date="2024-07-02"),
                _raw("undated"),
            ],
            COLLECTION_COMMITMENTS: [
                _raw("before", made_on="2024-07-01", text="t"),
                _raw("on", made_on="2024-07-02", text="t"),
            ],
        },
    )
    raw = get_feed(store, FeedFilters())
    assert [item["cabinet"] for item in raw["items"]] == ["b", None]
    assert raw["facets"]["cabinet"] == [
        {"value": None, "count": 1},
        {"value": "b", "count": 1},
    ]
    assert _ids(get_feed(store, FeedFilters(cabinet="a"))) == ["commitments/on"]
    assert _ids(get_feed(store, FeedFilters(cabinet="undated"))) == []


def test_an_id_two_factions_claim_goes_to_the_first_by_key(store: GraphStore) -> None:
    signer = {"person_id": "p", "faction_id": "f-shared", "capacity": "kamerlid"}
    _load(
        store,
        {
            COLLECTION_FACTIONS: [
                _raw("zeta", abbreviation="Z", external_id="f-shared"),
                _raw("alfa", abbreviation="", name="Alfa", external_ids=["f-shared"]),
            ],
            COLLECTION_DOCUMENTS: [
                _raw("m", ["TK"], kind="Motie", date="2026-05-01", actors=[signer]),
            ],
        },
    )
    raw = get_feed(store, FeedFilters())
    assert raw["items"][0]["persons"][0]["faction"] == {"key": "alfa", "short": "Alfa"}
    assert raw["facets"]["faction"] == [{"value": "alfa", "count": 1}]
    assert _ids(get_feed(store, FeedFilters(faction="zeta"), facets=False)) == []


def test_a_summary_orders_the_counts_of_a_day(store: GraphStore) -> None:
    day = "2026-05-12"
    _load(
        store,
        {
            COLLECTION_DECISIONS: [
                _raw("v1", date=day, passed=True, kind="Motie", dossier_numbers=["2"]),
                _raw("v2", date=day, passed=False, kind="Motie", dossier_numbers=["1"]),
                _raw("v3", date=day, passed=True, kind="Motie", dossier_numbers=["2"]),
                _raw("v4", date=day, passed=True, dossier_numbers=["1"]),
                _raw("v5", date=day, passed=True, chamber="EK", bill_decision=True),
            ],
            COLLECTION_DOCUMENTS: [
                _raw("m1", ["TK"], kind="Motie", date=day, dossier_numbers=["1"]),
            ],
        },
    )
    summary = get_feed_summary(store, FeedFilters(since=day, until=day), few=0)
    (counted,) = summary["days"]
    assert counted["kinds"] == [
        {"value": "stemming", "count": 5},
        {"value": "Motie", "count": 1},
    ]
    # by the rank of the kind, then the count, then the number
    assert counted["dossiers"] == [
        {"kind": "stemming", "number": "1", "count": 2},
        {"kind": "stemming", "number": "2", "count": 2},
        {"kind": "Motie", "number": "1", "count": 1},
    ]
    assert counted["votes"] == [
        {"chamber": "TK", "subkind": "Motie", "passed": True, "count": 2},
        {"chamber": "EK", "subkind": None, "passed": True, "count": 1},
        {"chamber": "TK", "subkind": None, "passed": True, "count": 1},
        {"chamber": "TK", "subkind": "Motie", "passed": False, "count": 1},
    ]
    # the vote of the Eerste Kamer and those decided by at most 10 seats (no tally: 0)
    assert [item["id"] for item in summary["items"]] == [
        "decisions/v1",
        "decisions/v2",
        "decisions/v3",
        "decisions/v4",
        "decisions/v5",
    ]


# ── a cursor in a busy day: the page is bounded and read through indexes ─────

BUSY_DAY = "2026-09-29"
FILLER = 10_000
# The tables a page must never read whole.
LARGE = (
    "documents",
    "edges",
    "decisions",
    "activities",
    "commitments",
    "dossiers",
    "judgments",
)


def _uuid_key(n: int) -> str:
    """A key as a TK GUID makes it: the same length and ``_`` at the same places, so that
    their order in Python is their order in the collation."""
    return f"{n:08x}_441c_42c2_b6c9_{n * 7919:012x}"


def _busy(store: GraphStore) -> None:
    """A busy day of motions (and a few of another ``Motie (…)``), votes and commitments
    among other days, and many rows of the tables that no page asks for."""
    motions = [
        _raw(
            _uuid_key(n),
            ["TK"],
            kind="Motie" if n % 10 else "Motie (gewijzigd/nader)",
            date=BUSY_DAY if n < 240 else f"2026-09-{1 + n % 28:02d}",
            dossier_numbers=["37000"],
            subject=f"Motie {n}",
        )
        for n in range(300)
    ]
    _load(
        store,
        {
            COLLECTION_DOCUMENTS: motions,
            COLLECTION_DECISIONS: [
                _raw(f"vote_{n:03d}", date=BUSY_DAY, passed=n % 2 == 0, kind="Motie")
                for n in range(40)
            ],
            COLLECTION_COMMITMENTS: [
                _raw(f"c_{n:03d}", made_on=BUSY_DAY, text="t") for n in range(20)
            ],
            COLLECTION_DOSSIERS: [_raw("37000", label="37000", ministry="fin")],
        },
    )
    day = "to_char(date '2000-01-01' + n % 9000, 'YYYY-MM-DD')"
    for table, props in (
        ("documents", f"json_build_object('kind', 'Verslag', 'date', {day})"),
        ("decisions", f"json_build_object('date', {day})"),
        ("commitments", "'{}'::json"),
        ("dossiers", "json_build_object('label', 'x' || n)"),
        ("activities", f"json_build_object('date', {day})"),
        ("instruments", "'{}'::json"),
        ("instrument_versions", "'{}'::json"),
        ("article_versions", "'{}'::json"),
    ):
        store.execute(
            f"INSERT INTO {table} (id, type, props)"
            f" SELECT '{table}/filler_' || n, 'filler', {props}"
            f" FROM generate_series(1, {FILLER}) n"
        )
    store.execute(
        "INSERT INTO edges (key, from_id, to_id, doc)"
        " SELECT 'filler_' || n, 'documents/filler_' || n % 9973,"
        " 'cases/filler_' || n % 9967, json_build_object('relation', 'PART_OF')"
        f" FROM generate_series(1, {FILLER * 5}) n"
    )
    store.vacuum_analyze()


def _crowd(store: GraphStore) -> None:
    """Many motions and votes of the days before: what a page after the cursor must not
    read whole."""
    day = "to_char(date '2000-01-01' + n % 9000, 'YYYY-MM-DD')"
    store.execute(
        "INSERT INTO documents (id, type, labels, props)"
        " SELECT 'documents/crowd_' || n, 'filler', '{TK}',"
        f" json_build_object('kind', 'Motie', 'date', {day})"
        f" FROM generate_series(1, {FILLER}) n"
    )
    store.execute(
        "INSERT INTO decisions (id, type, props)"
        " SELECT 'decisions/crowd_' || n, 'filler',"
        f" json_build_object('passed', true, 'date', {day})"
        f" FROM generate_series(1, {FILLER}) n"
    )
    # judgments of every feed tier and of a court the feed leaves out
    store.execute(
        "INSERT INTO judgments (id, type, props)"
        " SELECT 'judgments/crowd_' || n, 'filler', json_build_object('tier',"
        " (ARRAY['hoge_raad', 'raad_van_state', 'parket', 'rechtbank'])[n % 4 + 1],"
        f" 'published_on', {day})"
        f" FROM generate_series(1, {FILLER}) n"
    )
    store.vacuum_analyze()


def _walk(
    store: GraphStore, cursor: FeedCursor | None, facets: bool, limit: int = 50
) -> list[str]:
    seen: list[str] = []
    for _ in range(50):
        rows = get_feed(store, FeedFilters(), cursor=cursor, limit=limit, facets=facets)
        seen += [row["id"] for row in rows["items"][:limit]]
        if len(rows["items"]) <= limit:
            return seen
        last = rows["items"][limit - 1]
        cursor = FeedCursor(date=last["date"], kind=last["kind"], id=last["id"])
    raise AssertionError("the pages do not end")


@pytest.mark.parametrize("facets", [True, False])
def test_the_pages_of_a_busy_day_neither_repeat_nor_skip(
    store: GraphStore, facets: bool
) -> None:
    """The cursor ``["2026-09-29", "Motie", "documents/…"]`` of the request that hung on
    ArangoDB: the pages after it hold every later event once, in the order of the feed."""
    _busy(store)
    everything = _walk(store, None, facets, limit=1000)
    assert len(everything) == len(set(everything)) == 300 + 40 + 20
    # by day, then a vote before a commitment before a motion, then by id
    busy = everything[: 240 + 40 + 20]
    assert busy[:40] == [f"decisions/vote_{n:03d}" for n in range(40)]
    assert busy[40:60] == [f"commitments/c_{n:03d}" for n in range(20)]
    assert busy[60:] == sorted(busy[60:])
    assert _walk(store, None, facets) == everything
    middle = everything.index(f"documents/{_uuid_key(120)}")
    cursor = FeedCursor(date=BUSY_DAY, kind="Motie", id=everything[middle])
    assert _walk(store, cursor, facets) == everything[middle + 1 :]


def _plan(store: GraphStore, sql: str, bind: dict[str, Any]) -> dict[str, Any]:
    with store.pool.connection() as conn:
        (plan,) = conn.execute(f"EXPLAIN (FORMAT JSON) {sql}", bind).fetchone()  # type: ignore[misc]
    return cast(dict[str, Any], plan[0]["Plan"])


def _plan_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


def _seq_scans(plan: dict[str, Any]) -> list[str]:
    return [
        node["Relation Name"]
        for node in _plan_nodes(plan)
        if node["Node Type"] == "Seq Scan" and node["Relation Name"] in LARGE
    ]


_INDEX_SCANS = ("Index Scan", "Index Only Scan", "Index Scan Backward")


def _limit_over_index(plan: dict[str, Any], table: str) -> bool:
    """A limit whose input reads *table* in the order of an index: no sort, no bitmap
    between them, so the scan stops after the page."""

    def ordered(node: dict[str, Any]) -> bool:
        if node["Node Type"] in _INDEX_SCANS:
            return bool(node.get("Relation Name") == table)
        # an incremental sort orders what the index gives in date order, by id within a
        # day: it reads one day at a time
        if node["Node Type"] in ("Sort", "Bitmap Heap Scan", "Hash", "Aggregate"):
            return False
        return any(ordered(child) for child in node.get("Plans", []))

    return any(
        node["Node Type"] == "Limit" and ordered(node) for node in _plan_nodes(plan)
    )


@pytest.mark.parametrize("facets", [False, True])
def test_a_cursor_page_of_a_busy_day_reads_through_indexes(
    store: GraphStore, facets: bool
) -> None:
    """The planner as it is (no ``enable_seqscan`` off). Without facets (the Atom feed,
    ``facets=false``) no large table is read whole: each kind reads its page in the order
    of an index on its date and stops (``Limit`` above the scan). With facets every event
    is read for the counts; its dossier and signatures are looked up by index."""
    _busy(store)
    _crowd(store)
    cursor = FeedCursor(date=BUSY_DAY, kind="Motie", id=f"documents/{_uuid_key(120)}")
    sql, bind = feed_query(FeedFilters(), cursor=cursor, limit=50, facets=facets)
    plan = _plan(store, sql, bind)
    if facets:
        # the facets count every event, so every event is read (the rows of a kind whole
        # where they are most of a table); what each row looks up goes by index
        assert [t for t in _seq_scans(plan) if t in ("edges", "dossiers")] == []
    else:
        assert _seq_scans(plan) == []
        assert _limit_over_index(plan, "documents")
        assert _limit_over_index(plan, "decisions")
        # the judgments only when asked for, a page per tier
        sql, bind = feed_query(
            FeedFilters(kinds=("uitspraak",)), cursor=cursor, limit=50, facets=False
        )
        judgments = _plan(store, sql, bind)
        assert _seq_scans(judgments) == []
        assert _limit_over_index(judgments, "judgments")


def test_one_reading_counts_the_feed_and_every_kind_alike(store: GraphStore) -> None:
    """The total and the facets of the feed without a kind and of each kind on its own,
    from one reading of the events, are what each counts on its own, in the same order."""
    from lawgraph.core.feed import DEFAULT_KINDS, FEED_KINDS
    from lawgraph.db.queries import feed

    _seed(store)
    for since in (None, "2026-01-01"):
        shared = feed._counts_per_kind(store, FeedFilters(since=since))
        assert shared[DEFAULT_KINDS] == feed._counts(store, FeedFilters(since=since))
        for kind in FEED_KINDS:
            alone = feed._counts(store, FeedFilters(kinds=(kind,), since=since))
            assert shared[(kind,)] == alone, (kind, since)


def test_the_kinds_of_the_feed_are_counted_once_for_all(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lawgraph.core.feed import FEED_KINDS
    from lawgraph.db.queries import feed

    _seed(store)
    readings: list[FeedFilters] = []
    real = feed._counts_per_kind

    def counted(store_: GraphStore, filters: FeedFilters) -> Any:
        readings.append(filters)
        return real(store_, filters)

    monkeypatch.setattr(feed, "_counts_per_kind", counted)
    feed.feed_counts(store, FeedFilters())
    for kind in FEED_KINDS:
        feed.feed_counts(store, FeedFilters(kinds=(kind,)))
    assert readings == [FeedFilters()]
    # a filter on more than the kind is counted on its own
    assert feed._shared_kinds(FeedFilters(kinds=(FEED_KINDS[0],), q=("wet",))) is None
    assert feed._shared_kinds(FeedFilters(kinds=FEED_KINDS[:2])) is None


def test_a_page_whose_counts_take_long_comes_without_them_and_they_follow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under a filter not counted before (an ``until``: a minute or more on the full
    graph, cold), the page answers within ``COUNTS_BUDGET`` without its total and facets,
    ``partial``; they are counted on, and the next request has them."""
    import time

    from lawgraph.db import version_cache
    from lawgraph.db.queries import feed as feed_queries

    version_cache.clear()
    expected = _feed(client, until="2026-12-31")
    assert expected["partial"] is False and expected["total"]
    version_cache.clear()
    counts = feed_queries._counts_per_kind

    def slow(store: GraphStore, filters: Any) -> Any:
        time.sleep(2)
        return counts(store, filters)

    monkeypatch.setattr(feed_queries, "_counts_per_kind", slow)
    monkeypatch.setattr(feed_queries, "COUNTS_BUDGET", 0.3)
    started = time.monotonic()
    first = _feed(client, until="2026-12-31")
    assert time.monotonic() - started < 1.5
    assert first["partial"] is True
    assert first["total"] is None and first["facets"] is None
    assert _ids(first) == _ids(expected)
    time.sleep(2.5)
    again = _feed(client, until="2026-12-31")
    assert again["partial"] is False
    assert again["total"] == expected["total"]
    assert again["facets"] == expected["facets"]


def _ago(days: int) -> str:
    import datetime as dt

    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


# one Motie on stikstof in each window of ``WORDS_WINDOWS`` and one before them all, and
# one on another subject
WORDS_AGO = [10, 200, 800, 3000]


def _words_over_the_years(store: GraphStore) -> None:
    _load(
        store,
        {
            COLLECTION_DOCUMENTS: [
                _raw(f"m{n}", ["TK"], kind="Motie", date=_ago(n), subject="Stikstof")
                for n in WORDS_AGO
            ]
            + [_raw("other", ["TK"], kind="Motie", date=_ago(5), subject="Wonen")],
        },
    )


@pytest.mark.parametrize("limit", [1, 2, 4, 50])
def test_words_without_a_first_day_are_searched_back_window_by_window(
    store: GraphStore, limit: int
) -> None:
    """``q`` without ``since``: the windows back from today find, page by page, what one
    reading of every day finds, the oldest too, and say no day was left unsearched."""
    _words_over_the_years(store)
    every = FeedFilters(q=("stikstof",), since="1900-01-01")
    expected = _ids(get_feed(store, every, facets=False))
    assert expected == [f"documents/m{n}" for n in WORDS_AGO]
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        raw = get_feed(store, FeedFilters(q=("stikstof",)), cursor=cursor, limit=limit)
        assert "searched_from" not in raw and "partial" not in raw
        seen += _ids(raw)[:limit]
        if len(raw["items"]) <= limit:
            break
        last = raw["items"][limit - 1]
        cursor = FeedCursor(date=last["date"], kind=last["kind"], id=last["id"])
    assert seen == expected
    assert _ids(get_feed(store, FeedFilters(q=("stikstof",), until=_ago(100)))) == [
        f"documents/m{n}" for n in WORDS_AGO[1:]
    ]


def test_words_searched_past_their_budget_answer_what_was_found(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the budget ends the search in a window, the page has what the windows before
    found, ``partial``, and the first day searched; asked again with ``until`` the day
    before, it goes on from there. With no budget at all nothing was searched."""
    from lawgraph.db.queries import feed as feed_queries
    from lawgraph.db.store import ReadTimedOut

    _words_over_the_years(store)
    rows = feed_queries._rows
    calls: list[FeedFilters] = []

    def timed_out_in_the_second(
        store: GraphStore, filters: FeedFilters, *a: Any
    ) -> Any:
        calls.append(filters)
        if len(calls) == 2:
            raise ReadTimedOut("budget spent")
        return rows(store, filters, *a)

    monkeypatch.setattr(feed_queries, "_rows", timed_out_in_the_second)
    raw = get_feed(store, FeedFilters(q=("stikstof",)), facets=False)
    assert _ids(raw) == ["documents/m10"]
    assert raw["partial"] is True and raw["searched_from"] == _ago(90)
    assert calls[1].until == _ago(91) and calls[1].since == _ago(365)
    monkeypatch.setattr(feed_queries, "_rows", rows)

    on = get_feed(store, FeedFilters(q=("stikstof",), until=_ago(91)), facets=False)
    assert _ids(on) == [f"documents/m{n}" for n in WORDS_AGO[1:]]

    monkeypatch.setattr(feed_queries, "WORDS_BUDGET", 0.0)
    none = get_feed(store, FeedFilters(q=("stikstof",)))
    assert none["items"] == [] and none["partial"] is True
    assert none["searched_from"] == _ago(-1)
    # a first day, or no words, reads as before: one reading under the filters
    assert _ids(get_feed(store, FeedFilters(q=("stikstof",), since=_ago(365)))) == [
        "documents/m10",
        "documents/m200",
    ]
    assert len(get_feed(store, FeedFilters())["items"]) == 5


def test_a_feed_searched_past_its_budget_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/api/feed`` has ``searched_from`` (null when every day was searched)."""
    from lawgraph.db.queries import feed as feed_queries

    assert _feed(client, q="grens")["searched_from"] is None
    monkeypatch.setattr(feed_queries, "WORDS_BUDGET", 0.0)
    raw = _feed(client, q="grens", facets="false")
    assert raw["partial"] is True and raw["items"] == []
    assert raw["searched_from"] == _ago(-1)


# ── words: whole words and their candidates by index ─────────────────────────


def _words(store: GraphStore) -> None:
    """Papers whose subject holds ``ai`` or ``stikstof`` as a word, or as a part of one; a
    vote and a commitment with a word in their title; a motion whose dossier has it in
    its."""
    subjects = {
        "w1": "Motie over de AI-verordening",
        "w2": "Regels voor AI",
        "w3": "Universitaire opleidingen",
        "w4": "Airport Schiphol",
        "w5": "Stikstofbank en natuurstikstof",
    }
    _load(
        store,
        {
            COLLECTION_DOCUMENTS: [
                _raw(key, ["TK"], kind="Motie", date=f"2026-05-0{n + 1}", subject=subject,
                     dossier_numbers=["36001"])
                for n, (key, subject) in enumerate(subjects.items())
            ]
            + [_raw("w6", ["TK"], kind="Motie", date="2026-05-07", subject="Motie Bakker",
                    dossier_numbers=["36002"]),
               _raw("w7", ["TK"], kind="Motie", date="2026-05-08", subject="Natuurstikstof",
                    dossier_numbers=["36001"])],
            COLLECTION_DOSSIERS: [
                _raw("36001", label="36001", title="Onderwijs"),
                _raw("36002", label="36002", title="Wet op de AI-toezichthouder"),
            ],
            COLLECTION_DECISIONS: [
                _raw("v1", date="2026-05-02", passed=True, kind="Motie",
                     subject="Stemming over AI in de zorg"),
                _raw("v2", date="2026-05-02", passed=False, kind="Motie",
                     subject="Stemming over dairy"),
            ],
            COLLECTION_COMMITMENTS: [
                _raw("c1", made_on="2026-05-03", text="De minister stuurt een brief over AI"),
            ],
        },
    )  # fmt: skip


WORDS_WINDOW = {"since": "2026-05-01", "until": "2026-05-12"}


def test_a_short_word_is_a_whole_word_on_the_page_the_counts_summary_and_atom(
    client: TestClient, store: GraphStore
) -> None:
    """``ai`` (at most four letters) is a whole word: the AI-verordening, AI in the title of
    the dossier, not universitaire, Airport or dairy; alike in the page, its total, the
    summary and the Atom feed."""
    _words(store)
    expected = {
        "documents/w1",
        "documents/w2",
        "documents/w6",
        "decisions/v1",
        "commitments/c1",
    }
    page = _feed(client, q="AI", **WORDS_WINDOW)
    assert set(_ids(page)) == expected
    assert page["total"] == len(expected)
    response = client.get(
        "/api/feed/summary", params={"until": "2026-05-12", "days": 12, "q": "AI"}
    )
    assert response.status_code == 200, response.text
    assert sum(day["total"] for day in response.json()["days"]) == len(expected)
    atom = client.get("/api/feed.atom", params={"q": "ai", **WORDS_WINDOW})
    ns = {"a": "http://www.w3.org/2005/Atom"}
    ids = {
        (entry.find("a:id", ns).text or "").split(":", 2)[2]  # type: ignore[union-attr]
        for entry in ElementTree.fromstring(atom.content).findall("a:entry", ns)
    }
    assert ids == expected
    # a word of five letters or more from the start of a word: Stikstofbank, not
    # Natuurstikstof
    assert set(_ids(_feed(client, q="stikstof", **WORDS_WINDOW))) == {"documents/w5"}


WORDS = ["AI", "ai-ver", "stikstof", "natuurstikstof", "grens", "wet voorbeeld",
         "binnenlandse", "onderwijs", "toezicht", "x", "%", "a_b"]  # fmt: skip


@pytest.mark.parametrize("q", WORDS)
@pytest.mark.parametrize("facets", [False, True])
def test_the_candidates_by_index_keep_every_event_the_words_keep(
    client: TestClient,
    store: GraphStore,
    monkeypatch: pytest.MonkeyPatch,
    q: str,
    facets: bool,
) -> None:
    """Read from the rows the indexes find, or from every row: the same events and the same
    counts, of every kind."""
    from lawgraph.db import version_cache
    from lawgraph.db.queries import feed as feed_queries

    _words(store)
    filters = FeedFilters(q=(q,), since="1900-01-01")
    by_index = get_feed(store, filters, facets=facets)
    version_cache.clear()
    monkeypatch.setattr(feed_queries._Kind, "candidates", lambda self: None)
    every = get_feed(store, filters, facets=facets)
    assert _ids(by_index) == _ids(every)
    assert by_index.get("total") == every.get("total")
    assert by_index.get("facets") == every.get("facets")


def test_words_are_found_by_index_not_by_reading_every_day(store: GraphStore) -> None:
    """Many papers, votes and judgments over the years and a word few of them hold: each
    kind reads the rows its trigram index finds (and the dossiers whose title holds the
    word), not every row in date order; no large table is read whole."""
    _busy(store)
    _crowd(store)
    _words(store)
    store.vacuum_analyze()
    sql, bind = feed_query(
        FeedFilters(q=("toezichthouder",), kinds=("Motie", "stemming", "uitspraak")),
        limit=50,
        facets=False,
    )
    plan = _plan(store, sql, bind)
    assert _seq_scans(plan) == []
    for table in ("documents", "decisions", "judgments"):
        assert not _limit_over_index(plan, table), table
    used = {node.get("Index Name") for node in _plan_nodes(plan)}
    assert {
        "documents_feed_title_g",
        "documents_dossier_numbers",
        "decisions_search_words",
        "judgments_s_display_name_g",
    } <= used, used


def test_words_are_found_before_the_index_is_built(store: GraphStore) -> None:
    """A deploy before ``documents_feed_title_g`` (and ``instruments_dossier_numbers``) is
    built answers the same events, by reading the rows of the papers instead."""
    from lawgraph.db import schema, version_cache

    _words(store)
    filters = FeedFilters(q=("toezichthouder",), since="1900-01-01")
    with_index = get_feed(store, filters)
    built = [
        statement
        for collection in ("documents", "instruments")
        for statement in schema._LIST_INDEXES[collection]
        if "feed_title_g" in statement or "instruments_dossier_numbers" in statement
    ]
    assert len(built) == 2
    store.execute("DROP INDEX documents_feed_title_g, instruments_dossier_numbers")
    try:
        version_cache.clear()  # the counts too, not those kept
        assert get_feed(store, filters) == with_index
        assert _ids(with_index) == ["documents/w6"]
    finally:
        for statement in built:
            store.execute(statement)


def test_several_words_find_the_events_that_hold_any_of_them(
    client: TestClient, store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``q`` repeated: any of the words, each event once; alike in the page, its total, the
    summary and the Atom feed; by index the same events as from every row."""
    from lawgraph.db import version_cache
    from lawgraph.db.queries import feed as feed_queries

    _words(store)
    both = {
        "documents/w1",
        "documents/w2",
        "documents/w5",
        "documents/w6",
        "decisions/v1",
        "commitments/c1",
    }
    page = _feed(client, q=["AI", "stikstof", "AI", " "], **WORDS_WINDOW)
    assert set(_ids(page)) == both and len(_ids(page)) == len(both)
    assert page["total"] == len(both)
    response = client.get(
        "/api/feed/summary",
        params={"until": "2026-05-12", "days": 12, "q": ["AI", "stikstof"]},
    )
    assert sum(day["total"] for day in response.json()["days"]) == len(both)
    atom = client.get(
        "/api/feed.atom", params={"q": ["ai", "stikstof"], **WORDS_WINDOW}
    )
    root = ElementTree.fromstring(atom.content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    assert len(root.findall("a:entry", ns)) == len(both)
    assert "‘ai’ of ‘stikstof’" in (root.find("a:title", ns).text or "")  # type: ignore[union-attr]

    filters = FeedFilters(q=("toezicht", "stikstof"), since="1900-01-01")
    by_index = get_feed(store, filters)
    version_cache.clear()
    monkeypatch.setattr(feed_queries._Kind, "candidates", lambda self: None)
    assert get_feed(store, filters) == by_index
    assert _ids(by_index) == ["documents/w6", "documents/w5"]


def test_too_many_or_too_long_words_are_422(client: TestClient) -> None:
    assert client.get("/api/feed", params={"q": ["w"] * 11}).status_code == 422
    assert client.get("/api/feed", params={"q": ["w" * 201]}).status_code == 422
