"""What an item of the feed says of the sources it is tied to, on a real PostgreSQL, through
``GET /api/feed``: the laws a publication enacts and changes, what a new version puts in force
and is issued under, the motions and commitments a letter answers, the paper a changed motion
replaces, the articles of an amendment and of a judgment; where an item holds the words of
``q`` (``matched``), a publication by the names of its laws too; and the events of one law
(``instrument``, ``article``), each with how it is tied to it (``via``).

The graph is the Cyberbeveiligingswet (Cbw) as it is on prod: Stb. 2026, 187 enacts it and
amends the Telecommunicatiewet, its articles come into force on 15 August 2026, the
Cyberbeveiligingsbesluit is an AMvB on grounds of art. 3 and 16 Cbw."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_ANSWERS,
    RELATION_BASED_ON,
    RELATION_LEGISLATED_IN,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
    RELATION_REVISES,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter
from lawgraph.db.queries import feed_events
from lawgraph.db.queries.feed import feed_query
from lawgraph.db.queries.feed_sql import FeedFilters
from tests.asserts import assert_status
from tests.pg.planned_graph import fill
from tests.pg.plans import explain, plan_faults, plan_nodes

CBW, TW, BESLUIT = "BWBR0052872", "BWBR0009950", "BWBR0052875"
PUBLICATION = f"{COLLECTION_INSTRUMENTS}/stb_2026_187"
KATHMANN = "44444444-4444-4444-4444-444444444444"


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    labels = props.pop("labels", ["TK"])
    return Node(collection=collection, key=key, labels=labels, props=props)


def _article(bwb: str, number: str, position: int, law: str, short: str) -> Node:
    return _node(
        COLLECTION_ARTICLES,
        NodeType.ARTICLE,
        f"{bwb.lower()}_{number.replace('.', '_')}",
        bwb_id=bwb,
        article_number=number,
        position=position,
        instrument_citation_title=law,
        instrument_abbreviation=short,
        labels=["BWB"],
    )


def _version(bwb: str, number: str, position: int) -> Node:
    origin = {
        "id": "stb-2026-187",
        "kind": "Stb",
        "year": 2026,
        "number": "187",
        "effect": "nieuwe-regeling",
    }
    return _node(
        COLLECTION_ARTICLE_VERSIONS,
        NodeType.ARTICLE_VERSION,
        f"{bwb.lower()}_av_{number}_1",
        bwb_id=bwb,
        article_number=number,
        position=position,
        valid_from="2026-08-15",
        origin_publication=origin,
        labels=["BWB"],
    )


def _document(key: str, kind: str, date: str, sequence: int, **props: Any) -> Node:
    return _node(
        COLLECTION_DOCUMENTS,
        NodeType.DOCUMENT,
        key,
        kind=kind,
        date=date,
        dossier_numbers=["36764"],
        dossier_number="36764",
        sequence=sequence,
        document_number=f"2026D{sequence:05d}",
        **props,
    )


def _nodes() -> list[Node]:
    return [
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "36764",
            number="36764",
            label="36764",
            title="Regels ter implementatie van Richtlijn (EU) 2022/2555 betreffende "
            "maatregelen voor een hoog gezamenlijk niveau van cyberbeveiliging in de Unie "
            "(Cyberbeveiligingswet)",
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            CBW.lower(),
            bwb_id=CBW,
            kind="wet",
            title="Cyberbeveiligingswet",
            citation_title="Cyberbeveiligingswet",
            official_title="Wet van 8 juli 2026, houdende regels ter implementatie van "
            "Richtlijn (EU) 2022/2555 (Cyberbeveiligingswet)",
            enacted_publication="stb-2026-187",
            date_in_force="2026-08-15",
            article_count=3,
            dossier_numbers=["36764"],
            labels=["BWB"],
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            TW.lower(),
            bwb_id=TW,
            kind="wet",
            title="Telecommunicatiewet",
            citation_title="Telecommunicatiewet",
            enacted_publication="stb-1998-610",
            date_in_force="1998-12-15",
            labels=["BWB"],
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            BESLUIT.lower(),
            bwb_id=BESLUIT,
            kind="AMvB",
            title="Cyberbeveiligingsbesluit",
            citation_title="Cyberbeveiligingsbesluit",
            date_in_force="2026-08-15",
            article_count=36,
            labels=["BWB"],
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "stb_2026_187",
            kind="publicatie",
            citation_title="Stb. 2026, 187",
            official_id="stb-2026-187",
            publication_kind="Stb",
            publication_year=2026,
            publication_number="187",
            date_published="2026-07-10",
            dossier_numbers=["36764"],
            labels=["BWB", "Publication"],
        ),
        # a publication that only amends: no law names it as its enactment
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "stb_2026_200",
            kind="publicatie",
            citation_title="Stb. 2026, 200",
            official_id="stb-2026-200",
            publication_kind="Stb",
            publication_year=2026,
            publication_number="200",
            date_published="2026-07-20",
            labels=["BWB", "Publication"],
        ),
        _article(CBW, "1", 1, "Cyberbeveiligingswet", "Cbw"),
        _article(CBW, "3", 3, "Cyberbeveiligingswet", "Cbw"),
        _article(CBW, "16", 16, "Cyberbeveiligingswet", "Cbw"),
        _article(TW, "11a.1", 234, "Telecommunicatiewet", "Tw"),
        _article(TW, "11a.2", 235, "Telecommunicatiewet", "Tw"),
        _article(TW, "15.1", 300, "Telecommunicatiewet", "Tw"),
        _version(CBW, "16", 16),
        _version(CBW, "1", 1),
        _version(CBW, "3", 3),
        _node(
            COLLECTION_INSTRUMENT_VERSIONS,
            NodeType.INSTRUMENT_VERSION,
            "bwbr0052872_2026_08_15",
            bwb_id=CBW,
            valid_from="2026-08-15",
            labels=["BWB", "Version"],
        ),
        _node(
            COLLECTION_INSTRUMENT_VERSIONS,
            NodeType.INSTRUMENT_VERSION,
            "bwbr0052875_2026_08_15",
            bwb_id=BESLUIT,
            valid_from="2026-08-15",
            labels=["BWB", "Version"],
        ),
        _node(
            COLLECTION_INSTRUMENT_VERSIONS,
            NodeType.INSTRUMENT_VERSION,
            "bwbr0009950_2026_08_15",
            bwb_id=TW,
            valid_from="2026-08-15",
            labels=["BWB", "Version"],
        ),
        _document(
            "motion_19",
            "Motie",
            "2026-06-02",
            19,
            subject="Motie van het lid Kathmann over meldplicht",
        ),
        _document(
            "motion_31",
            "Motie (gewijzigd/nader)",
            "2026-06-04",
            31,
            subject="Gewijzigde motie van het lid Kathmann over meldplicht "
            "(t.v.v. 36764-19)",
            actors=[
                {
                    "person_id": KATHMANN,
                    "name": "B. Kathmann",
                    "role": "Eerste ondertekenaar",
                    "capacity": "kamerlid",
                },
            ],
        ),
        _document(
            "amendment_20",
            "Amendement",
            "2026-06-03",
            20,
            subject="Amendement over de zorgplicht",
        ),
        _document(
            "letter_40",
            "Brief regering",
            "2026-06-24",
            40,
            subject="Uitvoering van de aangenomen moties en toezeggingen",
        ),
        _node(
            COLLECTION_COMMITMENTS,
            NodeType.COMMITMENT,
            "tz_1",
            number="TZ202606-001",
            text="De minister stuurt een brief over de meldplicht.",
            display_name="De minister stuurt een brief over de meldplicht.",
            made_on="2026-06-10",
            status="Voldaan",
        ),
        _node(
            COLLECTION_DECISIONS,
            NodeType.DECISION,
            "vote_31",
            date="2026-06-09",
            subject="Gewijzigde motie van het lid Kathmann over meldplicht",
            dossier_numbers=["36764"],
            kind="Motie",
            passed=True,
            tally={"Voor": 100, "Tegen": 50},
        ),
        _node(
            COLLECTION_JUDGMENTS,
            NodeType.JUDGMENT,
            "ecli_nl_rvs_2026_9",
            ecli="ECLI:NL:RVS:2026:9",
            display_name="ABRvS 1 oktober 2026, meldplicht",
            tier="raad_van_state",
            court_code="RVS",
            published_on="2026-10-01",
            source="rechtspraak",
            labels=["Rechtspraak"],
        ),
    ]


def _seed(store: GraphStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(_nodes())

    def article(bwb: str, number: str) -> str:
        return f"{COLLECTION_ARTICLES}/{bwb.lower()}_{number.replace('.', '_')}"

    papers = COLLECTION_DOCUMENTS
    with EdgeWriter(store, what=None) as edges:
        for target, relation in (
            (article(TW, "11a.1"), RELATION_AMENDS),
            (article(TW, "15.1"), RELATION_AMENDS),
            (article(TW, "11a.2"), RELATION_REPEALS),
        ):
            edges.add(PUBLICATION, target, relation, source="t")
        edges.add(
            f"{COLLECTION_INSTRUMENTS}/stb_2026_200",
            article(TW, "15.1"),
            RELATION_AMENDS,
            source="t",
        )
        for source in (PUBLICATION, f"{COLLECTION_INSTRUMENTS}/{CBW.lower()}"):
            edges.add(
                source,
                f"{COLLECTION_DOSSIERS}/36764",
                RELATION_LEGISLATED_IN,
                source="t",
            )
        for number in ("3", "16"):
            edges.add(
                f"{COLLECTION_INSTRUMENTS}/{BESLUIT.lower()}",
                article(CBW, number),
                RELATION_BASED_ON,
                source="t",
            )
            edges.add(
                f"{papers}/amendment_20",
                article(CBW, number),
                RELATION_AMENDS,
                source="t",
                status="voorgesteld",
            )
        edges.add(
            f"{papers}/letter_40", f"{papers}/motion_31", RELATION_ANSWERS, source="t"
        )
        edges.add(
            f"{papers}/letter_40",
            f"{COLLECTION_COMMITMENTS}/tz_1",
            RELATION_ANSWERS,
            source="t",
        )
        edges.add(
            f"{papers}/motion_31",
            f"{papers}/motion_19",
            RELATION_REVISES,
            source="t",
            meta={"rule": "vervanging"},
        )
        edges.add(
            f"{COLLECTION_COMMITMENTS}/tz_1",
            f"{COLLECTION_DOSSIERS}/36764",
            RELATION_ABOUT,
            source="t",
        )
        for number, mentions in (("1", 1), ("16", 3)):
            edges.add(
                f"{COLLECTION_JUDGMENTS}/ecli_nl_rvs_2026_9",
                article(CBW, number),
                RELATION_REFERS_TO,
                source="t",
                meta={"mention_count": mentions},
            )


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _feed(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/api/feed", params={"facets": "false", **params})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _item(items: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    return next(item for item in items if item["id"] == node_id)


def test_a_publication_names_the_law_it_enacts_and_what_it_does_to_each(
    client: TestClient,
) -> None:
    publication = _item(_feed(client, kind="publicatie"), PUBLICATION)["publication"]
    assert [
        (i["title"], i["effect"], i["article_count"])
        for i in publication["instruments"]
    ] == [
        ("Cyberbeveiligingswet", "establishes", 3),
        # two articles amended, one repealed: it amends the law
        ("Telecommunicatiewet", "amends", 3),
    ]


def test_a_new_version_says_its_articles_publication_and_basis(
    client: TestClient,
) -> None:
    items = _feed(client, kind="inwerkingtreding")
    cbw = _item(items, f"{COLLECTION_INSTRUMENT_VERSIONS}/bwbr0052872_2026_08_15")
    commenced = cbw["commencement"]
    assert commenced["articles"] == ["1", "3", "16"]
    assert commenced["new"] is True
    assert commenced["publication"] == {
        "key": "stb_2026_187",
        "series": "stb",
        "year": 2026,
        "number": "187",
        "citation": "Stb. 2026, 187",
        "path": "/stb/2026/187",
    }
    assert commenced["based_on"] is None

    besluit = _item(items, f"{COLLECTION_INSTRUMENT_VERSIONS}/bwbr0052875_2026_08_15")
    assert besluit["commencement"]["new"] is True
    assert besluit["commencement"]["based_on"] == {
        "instrument": {
            "key": "bwbr0052872",
            "title": "Cyberbeveiligingswet",
            "official_url": "https://wetten.overheid.nl/BWBR0052872",
        },
        "kind": "amvb",
        "articles": ["3", "16"],
    }
    # a version of a law in force since long: not new, no articles that day
    tw = _item(items, f"{COLLECTION_INSTRUMENT_VERSIONS}/bwbr0009950_2026_08_15")
    assert tw["commencement"]["new"] is False
    assert tw["commencement"]["publication"] is None


def test_papers_name_what_they_answer_replace_and_amend(client: TestClient) -> None:
    items = _feed(client)
    letter = _item(items, f"{COLLECTION_DOCUMENTS}/letter_40")
    assert [
        (a["kind"], a["number"], a["dossier"], a["surname"], a["path"])
        for a in letter["answers"]
    ] == [
        ("toezegging", "TZ202606-001", None, None, "/toezeggingen/TZ202606-001"),
        (
            "Motie (gewijzigd/nader)",
            "31",
            "36764",
            "Kathmann",
            "/kamerstukken/36764/31",
        ),
    ]
    commitment = _item(items, f"{COLLECTION_COMMITMENTS}/tz_1")
    assert [a["id"] for a in commitment["answered_by"]] == [
        f"{COLLECTION_DOCUMENTS}/letter_40"
    ]
    motion = _item(items, f"{COLLECTION_DOCUMENTS}/motion_31")
    assert (motion["replaces"]["number"], motion["replaces"]["path"]) == (
        "19",
        "/kamerstukken/36764/19",
    )
    amendment = _item(items, f"{COLLECTION_DOCUMENTS}/amendment_20")
    assert [
        (a["number"], a["law_short"], a["effect"], a["path"])
        for a in amendment["amends_articles"]
    ] == [
        ("3", "Cbw", "amends", "/wetten/BWBR0052872/artikel/3"),
        ("16", "Cbw", "amends", "/wetten/BWBR0052872/artikel/16"),
    ]
    # what a kind does not have, it does not name
    assert letter["replaces"] is None and letter["cites"] == []
    assert motion["answers"] == [] and motion["amends_articles"] == []


def test_a_judgment_names_the_articles_it_cites_most_mentioned_first(
    client: TestClient,
) -> None:
    judgment = _feed(client, kind="uitspraak")[0]
    assert [(a["number"], a["law_short"]) for a in judgment["cites"]] == [
        ("16", "Cbw"),
        ("1", "Cbw"),
    ]


def test_matched_says_where_each_word_is(client: TestClient) -> None:
    items = _feed(client, q=["meldplicht", "Cyberbeveiliging"])
    motion = _item(items, f"{COLLECTION_DOCUMENTS}/motion_31")
    assert motion["matched"] == [
        {"term": "meldplicht", "field": "title"},
        {"term": "Cyberbeveiliging", "field": "dossier_title"},
    ]
    assert _feed(client)[0]["matched"] == []


def test_a_publication_is_found_by_the_names_of_its_laws(
    client: TestClient, store: GraphStore
) -> None:
    # by the title ``lawgraph feed-events`` writes: before, by its citation alone
    assert _feed(client, q="telecommunicatiewet", kind="publicatie") == []
    feed_events.write_all(store)
    items = _feed(client, q="telecommunicatiewet", kind="publicatie")
    assert [(i["id"], i["matched"]) for i in items] == [
        (
            f"{COLLECTION_INSTRUMENTS}/stb_2026_200",
            [{"term": "telecommunicatiewet", "field": "laws"}],
        ),
        (PUBLICATION, [{"term": "telecommunicatiewet", "field": "laws"}]),
    ]
    # the official title of the law it enacts is its title too
    items = _feed(client, q="implementatie", kind="publicatie")
    assert [i["id"] for i in items] == [PUBLICATION]
    # and the counts of the feed count it as the page finds it
    response = client.get(
        "/api/feed", params={"q": "telecommunicatiewet", "kind": "publicatie"}
    )
    assert response.json()["total"] == 2


def _via(items: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    return {item["id"]: item["via"] for item in items}


def test_the_events_of_a_law_say_how_they_are_tied_to_it(
    client: TestClient,
) -> None:
    items = _feed(client, instrument=CBW.lower())
    assert _via(items) == {
        f"{COLLECTION_INSTRUMENT_VERSIONS}/bwbr0052872_2026_08_15": {
            "relation": "version_of",
            "article": None,
            "dossier": None,
        },
        f"{COLLECTION_INSTRUMENT_VERSIONS}/bwbr0052875_2026_08_15": {
            "relation": "based_on",
            "article": "3",
            "dossier": None,
        },
        PUBLICATION: {"relation": "establishes", "article": None, "dossier": None},
        f"{COLLECTION_DOCUMENTS}/letter_40": {
            "relation": "legislated_in",
            "article": None,
            "dossier": "36764",
        },
        f"{COLLECTION_COMMITMENTS}/tz_1": {
            "relation": "legislated_in",
            "article": None,
            "dossier": "36764",
        },
        f"{COLLECTION_DECISIONS}/vote_31": {
            "relation": "legislated_in",
            "article": None,
            "dossier": "36764",
        },
        f"{COLLECTION_DOCUMENTS}/motion_31": {
            "relation": "legislated_in",
            "article": None,
            "dossier": "36764",
        },
        f"{COLLECTION_DOCUMENTS}/amendment_20": {
            "relation": "proposes",
            "article": "3",
            "dossier": None,
        },
        f"{COLLECTION_DOCUMENTS}/motion_19": {
            "relation": "legislated_in",
            "article": None,
            "dossier": "36764",
        },
    }
    judgments = _feed(client, instrument=CBW, kind="uitspraak")
    assert _via(judgments) == {
        f"{COLLECTION_JUDGMENTS}/ecli_nl_rvs_2026_9": {
            "relation": "refers_to",
            "article": "1",
            "dossier": None,
        }
    }


def test_the_events_of_an_article(client: TestClient) -> None:
    items = _feed(
        client,
        instrument=CBW,
        article="16",
        kind="uitspraak,inwerkingtreding,Amendement",
    )
    assert _via(items) == {
        f"{COLLECTION_INSTRUMENT_VERSIONS}/bwbr0052872_2026_08_15": {
            "relation": "version_of",
            "article": None,
            "dossier": None,
        },
        f"{COLLECTION_INSTRUMENT_VERSIONS}/bwbr0052875_2026_08_15": {
            "relation": "based_on",
            "article": "16",
            "dossier": None,
        },
        f"{COLLECTION_DOCUMENTS}/amendment_20": {
            "relation": "proposes",
            "article": "16",
            "dossier": None,
        },
        f"{COLLECTION_JUDGMENTS}/ecli_nl_rvs_2026_9": {
            "relation": "refers_to",
            "article": "16",
            "dossier": None,
        },
    }
    # an article of another law: the publications that changed it, and the events of the
    # dossier one of them was legislated in
    via = _via(_feed(client, instrument=TW, article="15.1"))
    assert via.pop(f"{COLLECTION_INSTRUMENTS}/stb_2026_200") == {
        "relation": "amends",
        "article": "15.1",
        "dossier": None,
    }
    assert via.pop(PUBLICATION) == {
        "relation": "amends",
        "article": "15.1",
        "dossier": None,
    }
    assert set(via) == {
        f"{COLLECTION_DOCUMENTS}/letter_40",
        f"{COLLECTION_COMMITMENTS}/tz_1",
        f"{COLLECTION_DECISIONS}/vote_31",
        f"{COLLECTION_DOCUMENTS}/motion_31",
        f"{COLLECTION_DOCUMENTS}/amendment_20",
        f"{COLLECTION_DOCUMENTS}/motion_19",
    }
    assert {(v or {}).get("relation") for v in via.values()} == {"legislated_in"}
    response = client.get("/api/feed", params={"article": "3"})
    assert_status(response, 422)


def test_the_judgments_of_a_widely_cited_law_are_the_same_read_in_date_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A law many judgments cite has its judgments read in date order, each tested for
    a citation; a law few cite, from its citations: the same events either way."""
    from lawgraph.db.queries import feed

    looked_up = _feed(client, instrument=CBW, kind="uitspraak")
    monkeypatch.setattr(feed, "WIDELY_CITED", 1)
    walked = _feed(client, instrument=CBW, kind="uitspraak")
    assert walked == looked_up and len(walked) == 1
    one = _feed(client, instrument=CBW, article="16", kind="uitspraak")
    assert [i["via"]["article"] for i in one] == ["16"]
    assert _feed(client, instrument=CBW, article="3", kind="uitspraak") == []


# What every feed statement reads whole, at most a few dozen rows: its preamble's factions
# and cabinets (``feed._PREAMBLE``).
_PREAMBLE_TABLES = ("factions", "cabinets")


@pytest.mark.parametrize(
    "filters",
    [
        FeedFilters(instrument=CBW),
        FeedFilters(instrument=CBW, kinds=("uitspraak", "Amendement")),
        FeedFilters(instrument=TW, article="15.1"),
        FeedFilters(
            q=("telecommunicatiewet",), kinds=("publicatie",), since="2000-01-01"
        ),
    ],
)
def test_the_events_of_a_law_and_their_ties_are_read_through_indexes(
    client: TestClient, store: GraphStore, filters: FeedFilters
) -> None:
    """Planned with sequential scans and joins by hash or merge off, as the plan test of
    the routes does: no table but the preamble's is read whole. The edges of a law are
    probed per article, not read by their relation; each item's ties by its own edges."""
    fill(store)  # on tables of a few rows the planner reads them whole whatever it may
    feed_events.write_all(store)
    store.vacuum_analyze()
    statement, bind = feed_query(filters, facets=False)
    plan = explain(store, statement, bind, disable=("seqscan", "hashjoin", "mergejoin"))
    faults = [
        fault
        for fault in plan_faults(plan)
        if not any(f" {table}" in fault for table in _PREAMBLE_TABLES)
    ]
    assert faults == [], "\n".join(faults)


def _removed(node: dict[str, Any], table: str) -> int:
    """The rows of *table* the plan *node* read and threw away (``Rows Removed``)."""
    return sum(
        int(n.get("Rows Removed by Filter", 0)) * int(n.get("Actual Loops", 1))
        for n in plan_nodes(node)
        if n.get("Relation Name") == table
    )


def test_a_law_with_few_events_has_them_looked_up_not_every_paper_read(
    client: TestClient, store: GraphStore
) -> None:
    """Papers by the thousand that are not the law's, newer than its events: its page reads
    its own papers by their ids, it does not read every paper in date order and throw away
    those that are not (seconds per kind on prod)."""
    store.execute(
        "INSERT INTO documents (id, type, labels, props)"
        " SELECT 'documents/other_' || n, 'document', '{TK}', json_build_object("
        "'kind', 'Motie', 'date', '2026-09-01', 'dossier_numbers', json_build_array('36000'))"
        " FROM generate_series(1, 3000) n"
    )
    store.vacuum_analyze()
    statement, bind = feed_query(FeedFilters(instrument=TW), facets=False)
    plan = explain(store, statement, bind, analyze=True)
    assert _removed(plan, "documents") < 100
