"""Cabinets with their bewindspersonen, dossiers, signed papers and commitments, written for
the cabinet and commitment queries and shared by their test modules."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore


def node(key: str, labels: list[str] | None = None, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": "t", "labels": labels or [], "props": props}


def edge(key: str, source: str, target: str, relation: str, **meta: Any) -> dict:
    doc = {
        "key": key,
        "from_id": source,
        "to_id": target,
        "relation": relation,
        "source": "test",
    }
    return {**doc, "meta": meta} if meta else doc


def government_graph(store: GraphStore) -> None:
    """Four cabinets, their bewindspersonen and what one of them signed, four dossiers
    and four commitments."""
    nodes = {
        "members": [
            node("m1", name="Eelco Heinen", slug="eelco-heinen"),
            # no name: the name it is known as, else the one Rijksoverheid gives
            node("m2", name="", known_as="Bert"),
            node(
                "m3",
                ["Rijksoverheid"],
                name=None,
                known_as="",
                government_name="C. de Vries",
            ),
            node("m4", name="Dirk"),
        ],
        "cabinets": [
            node("jetten", from_date="2026-02-23", to_date=None, prime_minister="m1"),
            node(
                "schoof",
                from_date="2024-07-02",
                to_date="2026-02-23",
                prime_minister="m2",
            ),
            # the same first day as schoof: the key settles it
            node("tie", from_date="2024-07-02", prime_minister="ghost"),
            node("old"),
        ],
        "dossiers": [
            node(
                "d1",
                label="36000",
                number="36000",
                title="T1",
                kind="Wetgeving",
                initiative=False,
                cabinet="jetten",
            ),
            node(
                "d2",
                label="36000-VII",
                number="36000",
                title="T2",
                kind="Wetgeving",
                initiative=True,
                cabinet="jetten",
            ),
            node("d3", label=None, kind="Overig", initiative=False, cabinet="jetten"),
            node(
                "d4",
                label="36001",
                number="36001",
                kind="Wetgeving",
                initiative=False,
                cabinet="schoof",
            ),
        ],
        "cases": [node("c1")],
        "documents": [
            node("signed", date="2026-03-01"),
            node("via_case", date="2026-03-02"),
            node("before", date="2025-01-01"),
            node("as_member", date="2026-03-03"),
            node("undated"),
            node("elsewhere", date="2026-03-04"),
        ],
        "activities": [
            node("a1", date="2026-04-01", number="2026A01"),
            node("a2", date="2026-04-02", number="2026A02"),
        ],
        "commitments": [
            node(
                "k1",
                member_key="m1",
                cabinet="jetten",
                ministry="fin",
                status="Openstaand",
                made_on="2026-04-01",
                expected_resolution="2020-05-01",
                text="Een brief over Box 3",
            ),
            node(
                "k2",
                member_key="m1",
                cabinet="jetten",
                ministry="fin",
                status="Openstaand",
                made_on="2026-04-02",
                expected_resolution="0001-01-01",
            ),
            node(
                "k3",
                member_key="nobody",
                cabinet="schoof",
                status="Afgedaan",
                made_on="2026-04-01",
                expected_resolution="2025-01-01",
                text="Over de ÉCOLE",
            ),
            node("k4", cabinet="jetten", status="Openstaand", made_on=None),
        ],
    }
    for collection, docs in nodes.items():
        store.bulk_insert_or_update_nodes(collection, docs)
    bewindspersoon = {"capacity": "bewindspersoon"}
    store.bulk_insert_or_update_edges(
        [
            edge(
                "s0", "members/ghost", "cabinets/jetten", "SERVED_IN", posts=[{"p": 1}]
            ),
            edge("s1", "members/m4", "cabinets/jetten", "SERVED_IN", posts=None),
            edge(
                "s2",
                "members/m1",
                "cabinets/jetten",
                "SERVED_IN",
                posts=[{"post": "minister", "ministry": "fin"}],
            ),
            edge(
                "s5",
                "members/m3",
                "cabinets/jetten",
                "SERVED_IN",
                posts=[{"z": 1, "a": 2}],
            ),
            edge(
                "s3",
                "members/m2",
                "cabinets/schoof",
                "SERVED_IN",
                posts=[{"post": "minister"}],
            ),
            edge(
                "s4",
                "members/m1",
                "cabinets/schoof",
                "SERVED_IN",
                posts=[{"member": "x", "seat": "y"}],
            ),
            # what m1 signed as a bewindspersoon: directly, through a case into two
            # dossiers, before jetten, as a Kamerlid, undated, and into a dossier gone
            edge("a1", "members/m1", "documents/signed", "AUTHORED", **bewindspersoon),
            edge(
                "a2", "members/m1", "documents/via_case", "AUTHORED", **bewindspersoon
            ),
            edge("a3", "members/m1", "documents/before", "AUTHORED", **bewindspersoon),
            edge(
                "a4",
                "members/m1",
                "documents/as_member",
                "AUTHORED",
                capacity="kamerlid",
            ),
            edge("a5", "members/m1", "documents/undated", "AUTHORED", **bewindspersoon),
            edge(
                "a6", "members/m1", "documents/elsewhere", "AUTHORED", **bewindspersoon
            ),
            edge("p1", "documents/signed", "dossiers/d1", "PART_OF"),
            edge("p2", "documents/via_case", "cases/c1", "PART_OF"),
            edge("p3", "cases/c1", "dossiers/d1", "PART_OF"),
            edge("p4", "cases/c1", "dossiers/d2", "PART_OF"),
            edge("p5", "documents/before", "dossiers/d3", "PART_OF"),
            edge("p6", "documents/as_member", "dossiers/d3", "PART_OF"),
            edge("p7", "documents/undated", "dossiers/d3", "PART_OF"),
            edge("p8", "documents/elsewhere", "dossiers/gone", "PART_OF"),
            # k1 discussed in a debate on two dossiers, k3 fulfilled by a letter in d2
            edge("b1", "commitments/k1", "dossiers/d1", "ABOUT", basis="agenda"),
            edge("b2", "commitments/k1", "dossiers/d3", "ABOUT", basis="agenda"),
            edge("b3", "commitments/k3", "dossiers/d2", "ABOUT", basis="nakoming"),
            edge("b4", "commitments/k4", "dossiers/d4", "ABOUT"),
            edge("i1", "commitments/k1", "activities/a2", "MADE_IN"),
            edge("i2", "commitments/k1", "activities/a1", "MADE_IN"),
            edge("i3", "commitments/k1", "activities/a0", "MADE_IN"),
        ]
    )
