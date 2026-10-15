"""The graph of the feed: papers, decisions, judgments and publications of a few days, the
members who signed them and the dossiers they belong to."""

from __future__ import annotations

from typing import Any

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
from lawgraph.core.models import Node, NodeType
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter

AALDERS = "11111111-1111-1111-1111-111111111111"
BAKKER = "22222222-2222-2222-2222-222222222222"
HEINEN = "33333333-3333-3333-3333-333333333333"
MOTION_CASE = "44444444-4444-4444-4444-444444444444"
AALDERS_KEY = AALDERS.replace("-", "_")
BAKKER_KEY = BAKKER.replace("-", "_")
HEINEN_KEY = HEINEN.replace("-", "_")
FIRST = "Eerste ondertekenaar"
CO = "Mede ondertekenaar"


def feed_node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    labels = props.pop("labels", ["TK"])
    return Node(collection=collection, key=key, labels=labels, props=props)


def feed_actor(person: str, faction: str | None, role: str, capacity: str) -> dict:
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


def feed_document(key: str, kind: str, date: str, dossier: str, **props: Any) -> Node:
    return feed_node(
        COLLECTION_DOCUMENTS,
        NodeType.DOCUMENT,
        key,
        kind=kind,
        date=date,
        dossier_numbers=[dossier],
        document_number=f"2026D{key[-3:]}",
        **props,
    )


def feed_nodes() -> list[Node]:
    return [
        feed_node(
            COLLECTION_CABINETS, NodeType.CABINET, "schoof", from_date="2024-07-02"
        ),
        feed_node(
            COLLECTION_CABINETS, NodeType.CABINET, "jetten", from_date="2026-02-23"
        ),
        feed_node(
            COLLECTION_FACTIONS,
            NodeType.FACTION,
            "vvd",
            abbreviation="VVD",
            external_id="f-vvd",
            external_ids=["f-vvd"],
        ),
        feed_node(
            COLLECTION_FACTIONS,
            NodeType.FACTION,
            "d66",
            abbreviation="D66",
            external_id="f-d66",
            external_ids=["f-d66-old", "f-d66"],
        ),
        feed_node(
            COLLECTION_MEMBERS,
            NodeType.MEMBER,
            AALDERS_KEY,
            name="Anna Aalders",
            external_id=AALDERS,
        ),
        feed_node(
            COLLECTION_MEMBERS,
            NodeType.MEMBER,
            BAKKER_KEY,
            name="Bram Bakker",
            external_id=BAKKER,
        ),
        feed_node(
            COLLECTION_MEMBERS,
            NodeType.MEMBER,
            HEINEN_KEY,
            name="Eelco Heinen",
            external_id=HEINEN,
        ),
        feed_node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "37000",
            number="37000",
            label="37000",
            title="Wijziging van de Wet voorbeeld (Wet beter voorbeeld)",
            ministry="fin",
        ),
        feed_node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "37001_vii",
            number="37001",
            suffix="VII",
            label="37001-VII",
            title="Begroting Binnenlandse Zaken 2027",
            ministry="bzk",
        ),
        feed_document(
            "bill_001",
            "Voorstel van wet",
            "2026-03-01",
            "37000",
            title="Voorstel van wet ",
        ),
        # the source signs the memorandum, not the voorstel: its signatories submitted it
        feed_document(
            "memorandum_008",
            "Memorie van toelichting",
            "2026-03-01",
            "37000",
            actors=[feed_actor(HEINEN, None, FIRST, "bewindspersoon")],
        ),
        # the bill as the Eerste Kamer received it is not submitted again
        feed_document(
            "ek_bill_002",
            "Voorstel van wet",
            "2026-06-15",
            "37000",
            labels=["EersteKamer", "EK"],
        ),
        feed_document("note_003", "Nota van wijziging", "2026-04-01", "37000"),
        feed_document(
            "amendment_004",
            "Amendement",
            "2026-05-01",
            "37000",
            subject="Amendement van het lid Aalders over de grens",
            actors=[
                feed_actor(AALDERS, "f-vvd", FIRST, "kamerlid"),
                feed_actor(BAKKER, "f-d66-old", CO, "kamerlid"),
            ],
        ),
        feed_document(
            "motion_005",
            "Motie (gewijzigd/nader)",
            "2026-05-01",
            "37001-VII",
            subject="Gewijzigde motie van het lid Bakker over gemeenten",
            text="De Kamer, gehoord de beraadslaging, verzoekt de regering de gemeenten te "
            "steunen, en gaat over tot de orde van de dag.",
            dictum="verzoekt de regering de gemeenten te steunen",
            case_ids=[MOTION_CASE],
            actors=[
                feed_actor(BAKKER, "f-d66", FIRST, "kamerlid"),
                feed_actor("griffier", None, CO, "overig"),
            ],
        ),
        feed_document(
            "letter_006",
            "Brief regering",
            "2026-06-01",
            "37001-VII",
            subject="Stand van zaken gemeentefonds",
            actors=[feed_actor(HEINEN, None, FIRST, "bewindspersoon")],
        ),
        # a paper of another kind is no event
        feed_document("report_007", "Verslag", "2026-06-02", "37000"),
        feed_node(
            COLLECTION_CASES, NodeType.CASE, MOTION_CASE.replace("-", "_"), kind="Motie"
        ),
        feed_node(
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
        feed_node(
            COLLECTION_DECISIONS,
            NodeType.DECISION,
            "stemming_2",
            date="2026-05-12",
            subject="Uitstel",
            dossier_numbers=["37001-VII"],
        ),
        feed_node(
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
        feed_node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "bwbr0000001",
            bwb_id="BWBR0000001",
            citation_title="Wet voorbeeld",
            article_count=12,
        ),
        feed_node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0000001_1",
            bwb_id="BWBR0000001",
            article_number="1",
            labels=["BWB"],
        ),
        feed_node(
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
        feed_node(
            COLLECTION_INSTRUMENT_VERSIONS,
            NodeType.INSTRUMENT_VERSION,
            "bwbr0000001_2026_08_01",
            bwb_id="BWBR0000001",
            valid_from="2026-08-01",
            labels=["BWB", "Version"],
        ),
        *(
            feed_node(
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


def seed_feed(store: GraphStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(feed_nodes())
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


# TK GUIDs: a member's key is its GUID made a node key.
