"""What the TK parliament normalizers write: which edges, between what, and how.

The expectations name endpoints and meta, not the calls that produce them, and
the last group pins that the cost of a build does not grow with the number of
items.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    RELATION_MADE_IN,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_VOTED,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.core.relations import BY_NAME
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize import _tk_members as tk_members
from lawgraph.pipelines.normalize import _tk_votes as tk_votes
from tests.fakes import RawSourcesFake

SOURCE = "test"


class _Store(RawSourcesFake):
    """The slice of ArangoStore the normalizers use, recorded in memory."""

    def __init__(
        self,
        existing: dict[str, set[str]] | None = None,
        query_handler: Any = None,
    ) -> None:
        self.existing = existing or {}
        self.query_handler = query_handler or (lambda aql, bind: [])
        self.edge_meta: dict[tuple[str, str, str], dict | None] = {}
        self.written_nodes: dict[tuple[str, str], dict] = {}
        self.query_calls = 0
        self.existence_calls = 0
        self.bulk_edge_calls = 0
        self.bulk_node_calls = 0

    def existing_keys(self, collection: str, keys: Any) -> set[str]:
        self.existence_calls += 1
        return set(keys) & self.existing.get(collection, set())

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict]:
        self.query_calls += 1
        return list(self.query_handler(aql, bind_vars or {}))

    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        self.bulk_edge_calls += 1
        for doc in docs:
            self.edge_meta[(doc["_from"], doc["relation"], doc["_to"])] = (
                doc.get("meta") or None
            )
        return len(docs), 0

    def bulk_insert_or_update_nodes(
        self, collection: str, docs: list[dict]
    ) -> tuple[int, int]:
        self.bulk_node_calls += 1
        for doc in docs:
            self.written_nodes[(collection, doc["_key"])] = dict(doc["props"])
        return len(docs), 0


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(
        collection=collection,
        type=node_type,
        key=key,
        props=props,
        _skip_validation=True,
    )


def _document(key: str, **props: Any) -> Node:
    return _node(COLLECTION_DOCUMENTS, NodeType.DOCUMENT, key, **props)


def _raw(payload: dict[str, Any]) -> dict[str, Any]:
    return {"payload_json": payload}


# ── the catalogue is what the writers are allowed to write ───────────────────


@pytest.mark.parametrize(
    ("relation", "source_collection", "target_collections"),
    [
        (
            RELATION_PART_OF,
            COLLECTION_DOCUMENTS,
            {COLLECTION_CASES, COLLECTION_DOSSIERS},
        ),
        (RELATION_PART_OF, COLLECTION_CASES, {COLLECTION_DOSSIERS}),
        (
            RELATION_ABOUT,
            COLLECTION_ACTIVITIES,
            {COLLECTION_CASES, COLLECTION_DOSSIERS},
        ),
        (RELATION_ABOUT, COLLECTION_DECISIONS, {COLLECTION_CASES, COLLECTION_DOSSIERS}),
        (RELATION_ABOUT, COLLECTION_COMMITMENTS, {COLLECTION_DOSSIERS}),
        (RELATION_LED_BY, COLLECTION_ACTIVITIES, {COLLECTION_COMMITTEES}),
        (RELATION_MADE_IN, COLLECTION_COMMITMENTS, {COLLECTION_ACTIVITIES}),
        (
            RELATION_MEMBER_OF,
            COLLECTION_MEMBERS,
            {COLLECTION_COMMITTEES, COLLECTION_FACTIONS},
        ),
        (RELATION_AUTHORED, COLLECTION_MEMBERS, {COLLECTION_DOCUMENTS}),
        (RELATION_VOTED, COLLECTION_MEMBERS, {COLLECTION_DECISIONS}),
        (RELATION_VOTED, COLLECTION_FACTIONS, {COLLECTION_DECISIONS}),
    ],
)
def test_every_edge_this_pipeline_writes_is_in_the_catalogue(
    relation: str, source_collection: str, target_collections: set[str]
) -> None:
    spec = BY_NAME[relation]
    assert source_collection in spec.sources
    assert target_collections <= set(spec.targets)


# ── subjects: documents, activities and decisions → cases and dossiers ───────


def test_documents_are_part_of_their_cases_and_dossiers() -> None:
    store = _Store(existing={COLLECTION_DOSSIERS: {"36000"}, COLLECTION_CASES: {"z_1"}})
    documents = [
        _document(
            "a", case_ids=["z-1", "z-unknown"], dossier_numbers=["36000", "99999"]
        ),
        _document("b"),
    ]

    tk_cases.link_subjects(store, documents, RELATION_PART_OF, source=SOURCE)

    assert set(store.edge_meta) == {
        (f"{COLLECTION_DOCUMENTS}/a", RELATION_PART_OF, f"{COLLECTION_CASES}/z_1"),
        (f"{COLLECTION_DOCUMENTS}/a", RELATION_PART_OF, f"{COLLECTION_DOSSIERS}/36000"),
    }


def test_activities_and_decisions_are_about_their_subjects() -> None:
    store = _Store(existing={COLLECTION_DOSSIERS: {"36000"}})
    activity = _node(
        COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a1", dossier_numbers=["36000"]
    )
    decision = _node(
        COLLECTION_DECISIONS, NodeType.DECISION, "s1", dossier_numbers=["36000"]
    )

    tk_cases.link_subjects(store, [activity], RELATION_ABOUT, source=SOURCE)
    tk_cases.link_subjects(store, [decision], RELATION_ABOUT, source=SOURCE)

    assert set(store.edge_meta) == {
        (f"{COLLECTION_ACTIVITIES}/a1", RELATION_ABOUT, f"{COLLECTION_DOSSIERS}/36000"),
        (f"{COLLECTION_DECISIONS}/s1", RELATION_ABOUT, f"{COLLECTION_DOSSIERS}/36000"),
    }


def test_cases_are_part_of_the_dossiers_they_name() -> None:
    rows = [
        {"id": f"{COLLECTION_CASES}/z1", "dossier_numbers": ["36000", "99999"]},
        {"id": f"{COLLECTION_CASES}/z2", "dossier_numbers": []},
    ]
    store = _Store(
        existing={COLLECTION_DOSSIERS: {"36000"}},
        query_handler=lambda aql, bind: rows,
    )

    tk_cases.link_cases_to_dossiers(store, source=SOURCE)

    assert set(store.edge_meta) == {
        (f"{COLLECTION_CASES}/z1", RELATION_PART_OF, f"{COLLECTION_DOSSIERS}/36000")
    }


def test_an_activity_is_led_by_its_lead_committee_only() -> None:
    store = _Store(existing={COLLECTION_COMMITTEES: {"c1"}})
    activities = {
        "a1": _node(COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a1", committee_id="c1"),
        # A plenary activity has none.
        "a2": _node(COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a2", committee_id=None),
        "a3": _node(
            COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a3", committee_id="unknown"
        ),
    }

    tk_cases.link_activities_to_committees(store, activities, source=SOURCE)

    assert set(store.edge_meta) == {
        (f"{COLLECTION_ACTIVITIES}/a1", RELATION_LED_BY, f"{COLLECTION_COMMITTEES}/c1")
    }


# ── commitments ──────────────────────────────────────────────────────────────


def test_a_commitment_is_made_in_an_activity_and_about_its_dossiers() -> None:
    store = _Store(existing={COLLECTION_DOSSIERS: {"36000"}})
    activities = {
        "a1": _node(
            COLLECTION_ACTIVITIES,
            NodeType.ACTIVITY,
            "a1",
            number="2024A05766",
            dossier_numbers=["36000"],
        )
    }
    commitments = {
        "t1": _node(
            COLLECTION_COMMITMENTS,
            NodeType.COMMITMENT,
            "t1",
            activity_number="2024A05766",
        ),
        "t2": _node(
            COLLECTION_COMMITMENTS, NodeType.COMMITMENT, "t2", activity_number="ZZ"
        ),
    }

    tk_cases.link_commitments(store, commitments, activities, source=SOURCE)

    assert set(store.edge_meta) == {
        (
            f"{COLLECTION_COMMITMENTS}/t1",
            RELATION_MADE_IN,
            f"{COLLECTION_ACTIVITIES}/a1",
        ),
        (
            f"{COLLECTION_COMMITMENTS}/t1",
            RELATION_ABOUT,
            f"{COLLECTION_DOSSIERS}/36000",
        ),
    }


# ── authorship ───────────────────────────────────────────────────────────────


def test_only_people_author_a_document_and_the_role_is_kept() -> None:
    store = _Store(existing={COLLECTION_MEMBERS: {"p1"}})
    documents = {
        "d1": _document(
            "d1",
            actors=[
                {"role": "Eerste ondertekenaar", "person_id": "p1", "faction": "VVD"},
                {"role": "Mede ondertekenaar", "person_id": "p-missing"},
                # A faction-only signatory writes nothing: who signed for a
                # party follows from that person's faction membership.
                {"role": "Indiener", "person_id": None, "faction": "CDA"},
            ],
        )
    }

    tk_cases.link_authors(store, documents, source=SOURCE)

    assert store.edge_meta == {
        (
            f"{COLLECTION_MEMBERS}/p1",
            RELATION_AUTHORED,
            f"{COLLECTION_DOCUMENTS}/d1",
        ): {"role": "Eerste ondertekenaar"}
    }


# ── membership ───────────────────────────────────────────────────────────────


def test_a_committee_seat_carries_one_representative_period() -> None:
    store = _Store(
        existing={COLLECTION_COMMITTEES: {"c1"}, COLLECTION_MEMBERS: {"p1", "p2"}}
    )
    raws = [
        _raw(
            {
                "Id": "c1",
                "CommissieZetel": [
                    {
                        "CommissieZetelVastPersoon": [
                            {
                                "Persoon_Id": "p1",
                                "Van": "2020-01-01",
                                "TotEnMet": "2021-01-01",
                            },
                            {"Persoon_Id": "p1", "Van": "2022-01-01", "TotEnMet": None},
                            {
                                "Persoon_Id": "p2",
                                "Van": "2019-01-01",
                                "TotEnMet": "2020-01-01",
                            },
                            {"Persoon_Id": "p-missing", "Van": "2019-01-01"},
                        ]
                    }
                ],
            }
        ),
        _raw({"Id": "c-missing", "CommissieZetel": []}),
    ]

    tk_members.link_members_to_committees(store, raws, source=SOURCE)

    assert store.edge_meta == {
        (
            f"{COLLECTION_MEMBERS}/p1",
            RELATION_MEMBER_OF,
            f"{COLLECTION_COMMITTEES}/c1",
        ): {"from_date": "2022-01-01"},
        (
            f"{COLLECTION_MEMBERS}/p2",
            RELATION_MEMBER_OF,
            f"{COLLECTION_COMMITTEES}/c1",
        ): {"from_date": "2019-01-01", "to_date": "2020-01-01"},
    }


def test_faction_membership_writes_an_edge_and_the_member_timeline() -> None:
    store = _Store()
    faction = _node(
        COLLECTION_FACTIONS,
        NodeType.FACTION,
        "vvd",
        name="VVD",
        abbreviation="VVD",
        aliases=[],
    )
    member = _node(COLLECTION_MEMBERS, NodeType.MEMBER, "p1", name="Jan")
    raws = [
        _raw(
            {
                "Persoon_Id": "p1",
                "FractieZetel": {"Fractie_Id": "f-vvd"},
                "Van": "2020-01-01",
                "TotEnMet": None,
                "Functie": "Lid",
            }
        ),
        _raw({"Persoon_Id": "nobody", "FractieZetel": {"Fractie_Id": "f-vvd"}}),
    ]

    tk_members.link_members_to_factions(
        store, raws, {"p1": member}, {"f-vvd": faction}, source=SOURCE
    )

    assert store.edge_meta == {
        (
            f"{COLLECTION_MEMBERS}/p1",
            RELATION_MEMBER_OF,
            f"{COLLECTION_FACTIONS}/vvd",
        ): {"from_date": "2020-01-01", "to_date": None, "role": "Lid"}
    }
    written = store.written_nodes[(COLLECTION_MEMBERS, "p1")]
    assert written["party"] == "VVD"
    assert written["display_name"] == "Jan (VVD)"
    assert written["faction_memberships"] == [
        {
            "faction_id": f"{COLLECTION_FACTIONS}/vvd",
            "faction_key": "vvd",
            "name": "VVD",
            "abbreviation": "VVD",
            "aliases": [],
            "from_date": "2020-01-01",
            "to_date": None,
            "role": "Lid",
        }
    ]


# ── votes ────────────────────────────────────────────────────────────────────


def _vote_raw(**overrides: Any) -> dict[str, Any]:
    payload = {
        "Besluit_Id": "b-1",
        "Soort": "Voor",
        "FractieGrootte": 24,
        "ActorFractie": "VVD",
        "Fractie_Id": "f-vvd",
        "Persoon_Id": None,
        "GewijzigdOp": "2024-10-16T11:34:18.673+02:00",
        "Besluit": {"BesluitSoort": "Stemmen - aangenomen"},
    }
    payload.update(overrides)
    return _raw(payload)


def test_an_ordinary_vote_is_cast_by_the_faction() -> None:
    store = _Store()
    raws = [
        _vote_raw(),
        _vote_raw(Soort="Tegen", FractieGrootte=9, Fractie_Id="f-d66"),
        _vote_raw(Soort="Onthouden", FractieGrootte=1, Fractie_Id="f-unknown"),
    ]
    votes = tk_votes.read_votes(raws)
    decisions = tk_votes.normalize_decisions(store, votes)
    factions = {
        "f-vvd": _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd"),
        "f-d66": _node(COLLECTION_FACTIONS, NodeType.FACTION, "d66"),
    }

    tk_votes.link_votes(store, votes.by_decision, decisions, factions, source=SOURCE)

    decision_id = f"{COLLECTION_DECISIONS}/{decisions['b-1'].key}"
    assert store.edge_meta == {
        (f"{COLLECTION_FACTIONS}/vvd", RELATION_VOTED, decision_id): {
            "choice": "Voor",
            "seats": 24,
        },
        (f"{COLLECTION_FACTIONS}/d66", RELATION_VOTED, decision_id): {
            "choice": "Tegen",
            "seats": 9,
        },
    }


def test_a_roll_call_is_cast_by_the_members() -> None:
    store = _Store(existing={COLLECTION_MEMBERS: {"p_1"}})
    raws = [
        _vote_raw(
            Persoon_Id="p-1",
            Besluit={
                "StemmingsSoort": "Hoofdelijk",
                "BesluitSoort": "Stemmen - verworpen",
            },
        ),
        _vote_raw(
            Soort="Tegen",
            Persoon_Id="p-missing",
            Besluit={"StemmingsSoort": "Hoofdelijk"},
        ),
    ]
    votes = tk_votes.read_votes(raws)
    decisions = tk_votes.normalize_decisions(store, votes)
    factions = {"f-vvd": _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd")}

    tk_votes.link_votes(store, votes.by_decision, decisions, factions, source=SOURCE)

    decision = decisions["b-1"]
    assert decision.props["vote_kind"] == "member"
    assert store.edge_meta == {
        (
            f"{COLLECTION_MEMBERS}/p_1",
            RELATION_VOTED,
            f"{COLLECTION_DECISIONS}/{decision.key}",
        ): {"choice": "Voor", "seats": 24}
    }


# ── cost: a build must not grow a lookup per item ────────────────────────────


def test_linking_does_not_look_items_up_one_by_one() -> None:
    n = 2000
    store = _Store(
        existing={
            COLLECTION_DOSSIERS: {str(i) for i in range(n)},
            COLLECTION_MEMBERS: {f"p{i}" for i in range(n)},
        }
    )
    documents = {
        f"d{i}": _document(
            f"d{i}",
            dossier_numbers=[str(i)],
            actors=[{"role": "Indiener", "person_id": f"p{i}"}],
        )
        for i in range(n)
    }

    tk_cases.link_subjects(store, documents.values(), RELATION_PART_OF, source=SOURCE)
    tk_cases.link_authors(store, documents, source=SOURCE)

    assert len(store.edge_meta) == 2 * n
    assert store.query_calls == 0
    # One existence lookup for the dossiers, one for the signatories.
    assert store.existence_calls == 2


def test_normalizing_activities_writes_nodes_in_bulk() -> None:
    store = _Store()
    raws = [
        _raw(
            {
                "Id": f"act{i}",
                "Datum": "2024-01-02T00:00:00",
                "Soort": "Commissiedebat",
                "Voortouwcommissie_Id": "comm1",
                "Agendapunt": [
                    {
                        "Zaak": [
                            {
                                "Id": "z-1",
                                "Soort": "Wetgeving",
                                "Kamerstukdossier": [{"Nummer": 36000}],
                            }
                        ]
                    }
                ],
            }
        )
        for i in range(700)
    ]

    nodes = tk_cases.normalize_activities(store, raws)

    assert len(nodes) == 700
    assert nodes["act1"].arango_id == f"{COLLECTION_ACTIVITIES}/act1"
    assert nodes["act1"].props["dossier_numbers"] == ["36000"]
    assert store.bulk_node_calls == 2  # 500 + 200, not 700 single upserts


def test_a_written_node_keeps_only_what_the_edges_need() -> None:
    """130K documents with their API payload are over a gigabyte; the edges read a few props."""
    store = _Store()
    raws = (  # a generator: the records are walked once, as they stream in
        _raw({"Id": f"doc{i}", "Soort": "Motie", "Titel": "Motie " * 50})
        for i in range(3)
    )

    nodes = tk_cases.normalize_documents(store, raws)

    written = store.written_nodes[(COLLECTION_DOCUMENTS, "doc1")]
    assert written["title"].startswith("Motie") and "raw" in written
    assert set(nodes) == {"doc0", "doc1", "doc2"}
    assert set(nodes["doc1"].props) <= set(tk_cases.LINK_PROPS)
    assert nodes["doc1"].arango_id == f"{COLLECTION_DOCUMENTS}/doc1"


def test_the_raw_records_are_streamed_per_kind_not_loaded_as_lists() -> None:
    from lawgraph.pipelines.normalize.tk_dossiers import (
        RAW_KINDS,
        TKDossiersNormalizePipeline,
    )

    asked: list[tuple[list[str], int | None]] = []

    class Streaming(_Store):
        def query(self, aql, bind_vars=None, *, batch_size=None):  # type: ignore[override]
            asked.append(((bind_vars or {}).get("kinds"), batch_size))
            return iter([])

    raw = TKDossiersNormalizePipeline(store=Streaming()).fetch_raw()
    assert asked == []  # nothing is read before it is walked
    assert set(raw) == set(RAW_KINDS) and not isinstance(raw[RAW_KINDS[0]], list)
    assert list(raw[RAW_KINDS[0]]) == [] and list(raw[RAW_KINDS[0]]) == []
    reads = [call for call in asked if call[1] is not None]  # without the counts
    assert reads == [([RAW_KINDS[0]], 1000)] * 2  # every walk streams again


def test_the_dossier_signals_query_builds_no_list_of_whole_documents() -> None:
    """``RETURN doc`` in a subquery keeps every document of 500 dossiers, text and payload,
    in the memory of the server until the outer RETURN projects it (measured on the test
    server, 40,000 documents without text: a peak of 143 MB, 12 MB with the projection)."""
    import re

    from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline

    seen: list[str] = []

    class Store:
        def query(self, aql: str, bind_vars: dict | None = None, **_kw: object):
            seen.append(aql)
            return iter([])

    pipeline = TKDossiersNormalizePipeline.__new__(TKDossiersNormalizePipeline)
    pipeline.store = Store()  # type: ignore[assignment]
    pipeline._dossier_signals(["dossiers/36000"])
    assert seen and not re.search(r"RETURN\s+(doc|node)\s*\n", seen[0])
