"""What the TK parliament normalizers write: which edges, between what, and how.

The expectations name endpoints and meta, not the calls that produce them, and
the last group pins that the cost of a build does not grow with the number of
items.
"""

from __future__ import annotations

import inspect
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
    RELATION_ACCOMPANIES,
    RELATION_ANSWERS,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    RELATION_MADE_IN,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_VOTED,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.core.relations import BY_NAME
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.normalize import bwb as normalize_bwb
from lawgraph.db.queries.normalize import edges as normalize_edges
from lawgraph.db.queries.normalize import rechtspraak as normalize_rechtspraak
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize import _tk_members as tk_members
from lawgraph.pipelines.normalize import _tk_votes as tk_votes
from tests.fakes import RawSourcesFake

SOURCE = "test"


class _Store(RawSourcesFake):
    """The slice of GraphStore the normalizers use, recorded in memory."""

    def __init__(self, existing: dict[str, set[str]] | None = None) -> None:
        self.existing = existing or {}
        self.edge_meta: dict[tuple[str, str, str], dict | None] = {}
        self.written_nodes: dict[tuple[str, str], dict] = {}
        self.existence_calls = 0
        self.bulk_edge_calls = 0
        self.bulk_node_calls = 0

    def existing_keys(self, collection: str, keys: Any) -> set[str]:
        self.existence_calls += 1
        return set(keys) & self.existing.get(collection, set())

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


@pytest.fixture(autouse=True)
def _no_stale_votes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``link_votes`` removes the VOTED edges it did not write: there are none here."""
    monkeypatch.setattr(
        normalize_edges, "remove_edges_into_except", lambda *_a, **_kw: 0
    )


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
        (RELATION_MADE_IN, COLLECTION_DOCUMENTS, {COLLECTION_ACTIVITIES}),
        (RELATION_ANSWERS, COLLECTION_DOCUMENTS, {COLLECTION_COMMITMENTS}),
        (RELATION_MADE_IN, COLLECTION_DECISIONS, {COLLECTION_ACTIVITIES}),
        (RELATION_AUTHORED, COLLECTION_MEMBERS, {COLLECTION_COMMITMENTS}),
        (RELATION_ACCOMPANIES, COLLECTION_DOCUMENTS, {COLLECTION_DOCUMENTS}),
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


def test_cases_are_part_of_the_dossiers_they_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"id": f"{COLLECTION_CASES}/z1", "dossier_numbers": ["36000", "99999"]},
        {"id": f"{COLLECTION_CASES}/z2", "dossier_numbers": []},
    ]
    monkeypatch.setattr(normalize_tk, "case_dossier_numbers", lambda store: iter(rows))
    store = _Store(existing={COLLECTION_DOSSIERS: {"36000"}})

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


def test_a_commitment_of_a_moved_activity_is_about_the_dossiers_of_its_replacement() -> (
    None
):
    # 2026A04251 (Wetgevingsoverleg 36835, Verplaatst) kept no agenda; the Kamer replaced
    # it by 2026A06208 (VervangenDoor), whose agenda holds the cases of 36835
    store = _Store(existing={COLLECTION_DOSSIERS: {"36835"}})
    activities = {
        "moved": _node(
            COLLECTION_ACTIVITIES,
            NodeType.ACTIVITY,
            "moved",
            number="2026A04251",
            dossier_numbers=[],
            replaced_by=["2026A06208"],
        ),
        "held": _node(
            COLLECTION_ACTIVITIES,
            NodeType.ACTIVITY,
            "held",
            number="2026A06208",
            dossier_numbers=["36835"],
            replaced_by=[],
        ),
        # replaced by each other: no endless walk
        "loop": _node(
            COLLECTION_ACTIVITIES,
            NodeType.ACTIVITY,
            "loop",
            number="L1",
            replaced_by=["L1"],
        ),
    }
    commitments = {
        "t1": _node(
            COLLECTION_COMMITMENTS,
            NodeType.COMMITMENT,
            "t1",
            activity_number="2026A04251",
        ),
        "t2": _node(
            COLLECTION_COMMITMENTS, NodeType.COMMITMENT, "t2", activity_number="L1"
        ),
    }

    tk_cases.link_commitments(store, commitments, activities, source=SOURCE)

    assert set(store.edge_meta) == {
        # made in the activity it names, about what the replacement discussed
        (
            f"{COLLECTION_COMMITMENTS}/t1",
            RELATION_MADE_IN,
            f"{COLLECTION_ACTIVITIES}/moved",
        ),
        (
            f"{COLLECTION_COMMITMENTS}/t1",
            RELATION_ABOUT,
            f"{COLLECTION_DOSSIERS}/36835",
        ),
        (
            f"{COLLECTION_COMMITMENTS}/t2",
            RELATION_MADE_IN,
            f"{COLLECTION_ACTIVITIES}/loop",
        ),
    }


# ── authorship ───────────────────────────────────────────────────────────────


def test_only_people_author_a_document_and_their_role_and_capacity_are_kept() -> None:
    store = _Store(existing={COLLECTION_MEMBERS: {"p1"}})
    documents = {
        "d1": _document(
            "d1",
            actors=[
                {
                    "role": "Eerste ondertekenaar",
                    "person_id": "p1",
                    "faction": "VVD",
                    "function": "Tweede Kamerlid",
                    "capacity": "kamerlid",
                },
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
        ): {
            "role": "Eerste ondertekenaar",
            "function": "Tweede Kamerlid",
            "capacity": "kamerlid",
        }
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
                        ],
                        # a substitute's seat, later: the member's open seat represents
                        "CommissieZetelVervangerPersoon": [
                            {
                                "Persoon_Id": "p1",
                                "Van": "2023-01-01",
                                "TotEnMet": None,
                                "Functie": "Plv. lid",
                            }
                        ],
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
        ): {
            "from_date": "2022-01-01",
            "periods": [
                {"from_date": "2020-01-01", "to_date": "2021-01-01"},
                {"from_date": "2022-01-01"},
                {"from_date": "2023-01-01", "role": "Plv. lid", "substitute": True},
            ],
        },
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
                "Id": "s1",
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
        ): {
            "from_date": "2020-01-01",
            "to_date": None,
            "role": "Lid",
            "record_ids": ["s1"],
        }
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


def test_a_member_who_rejoined_has_one_edge_with_the_latest_period_in_any_order() -> (
    None
):
    """Two periods of one member in one faction share an edge key: the edge carries the
    latest, whatever order the seat records are read in (D4), and the ids of both."""
    faction = _node(
        COLLECTION_FACTIONS, NodeType.FACTION, "sp", name="SP", abbreviation="SP"
    )
    member = _node(COLLECTION_MEMBERS, NodeType.MEMBER, "p1", name="Jan")
    first = {
        "Id": "s1",
        "Persoon_Id": "p1",
        "FractieZetel": {"Fractie_Id": "f-sp"},
        "Van": "2006-11-30",
        "TotEnMet": "2010-03-04",
        "Functie": "Lid",
    }
    second = {
        "Id": "s2",
        "Persoon_Id": "p1",
        "FractieZetel": {"Fractie_Id": "f-sp"},
        "Van": "2010-03-05",
        "TotEnMet": "2017-12-12",
        "Functie": "Fractievoorzitter",
    }
    metas = []
    for order in ([first, second], [second, first]):
        store = _Store()
        tk_members.link_members_to_factions(
            store,
            [_raw(payload) for payload in order],
            {"p1": member},
            {"f-sp": faction},
            source=SOURCE,
        )
        metas.append(store.edge_meta)
    assert (
        metas[0]
        == metas[1]
        == {
            (
                f"{COLLECTION_MEMBERS}/p1",
                RELATION_MEMBER_OF,
                f"{COLLECTION_FACTIONS}/sp",
            ): {
                "from_date": "2010-03-05",
                "to_date": "2017-12-12",
                "role": "Fractievoorzitter",
                "record_ids": ["s1", "s2"],
            }
        }
    )


def test_of_two_periods_starting_the_same_day_the_open_one_is_the_latest() -> None:
    assert tk_members._recency({"from_date": "2020-01-01", "to_date": None}, "a") > (
        tk_members._recency({"from_date": "2020-01-01", "to_date": "2021-01-01"}, "z")
    )


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
        _vote_raw(Id="v-1"),
        _vote_raw(Id="v-2", Soort="Tegen", FractieGrootte=9, Fractie_Id="f-d66"),
        _vote_raw(Id="v-3", Soort="Onthouden", FractieGrootte=1, Fractie_Id="f-x"),
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
            "record_ids": ["v-1"],
        },
        (f"{COLLECTION_FACTIONS}/d66", RELATION_VOTED, decision_id): {
            "choice": "Tegen",
            "seats": 9,
            "record_ids": ["v-2"],
        },
    }


def test_a_roll_call_is_cast_by_the_members() -> None:
    store = _Store(existing={COLLECTION_MEMBERS: {"p_1"}})
    raws = [
        _vote_raw(
            Id="v-1",
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
        ): {"choice": "Voor", "seats": 1, "record_ids": ["v-1"]}  # one seat
    }


def test_members_voting_apart_from_their_faction_vote_beside_it() -> None:
    """A faction vote in which members voted apart: the faction votes with its seats
    without them, each of them from their member node with one seat."""
    store = _Store(existing={COLLECTION_MEMBERS: {"p_3", "p_4"}})
    raws = [
        _vote_raw(Id="v-1", Soort="Tegen", FractieGrootte=7),
        _vote_raw(Id="v-3", Soort="Voor", FractieGrootte=7, Persoon_Id="p-3"),
        _vote_raw(Id="v-4", Soort="Voor", FractieGrootte=7, Persoon_Id="p-4"),
    ]
    votes = tk_votes.read_votes(raws)
    decisions = tk_votes.normalize_decisions(store, votes)
    factions = {"f-vvd": _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd")}

    tk_votes.link_votes(store, votes.by_decision, decisions, factions, source=SOURCE)

    decision = decisions["b-1"]
    assert decision.props["vote_kind"] == "faction"
    target = f"{COLLECTION_DECISIONS}/{decision.key}"
    assert store.edge_meta == {
        (f"{COLLECTION_FACTIONS}/vvd", RELATION_VOTED, target): {
            "choice": "Tegen",
            "seats": 5,
            "record_ids": ["v-1"],
        },
        (f"{COLLECTION_MEMBERS}/p_3", RELATION_VOTED, target): {
            "choice": "Voor",
            "seats": 1,
            "record_ids": ["v-3"],
        },
        (f"{COLLECTION_MEMBERS}/p_4", RELATION_VOTED, target): {
            "choice": "Voor",
            "seats": 1,
            "record_ids": ["v-4"],
        },
    }


def test_a_deleted_vote_and_the_votes_on_a_deleted_besluit_are_no_votes() -> None:
    raws = [
        _vote_raw(Id="v-1"),
        _raw({"Id": "v-2", "Besluit_Id": None, "Verwijderd": True}),
        _vote_raw(Id="v-3", Besluit_Id="b-2", Besluit={"Id": "b-2"}),
        _vote_raw(
            Id="v-4", Besluit_Id="b-2", Besluit={"Id": "b-2", "Verwijderd": True}
        ),
    ]
    votes = tk_votes.read_votes(raws)
    assert list(votes.by_decision) == ["b-1"]
    assert votes.deleted.ids == {"v-2"}
    assert votes.struck.ids == {"b-2"}


# ── cost: a build must not grow a lookup per item ────────────────────────────


def _count_queries(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every query function of ``db/queries/normalize/``, replaced by one that records
    its name: the names of the queries a test ran."""
    ran: list[str] = []

    def recorder(name: str) -> Any:
        def recorded(*_args: Any, **_kw: Any) -> Any:
            ran.append(name)
            return iter([])

        return recorded

    for module in (normalize_bwb, normalize_edges, normalize_rechtspraak, normalize_tk):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ == module.__name__:
                monkeypatch.setattr(module, name, recorder(name))
    return ran


def test_linking_does_not_look_items_up_one_by_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran = _count_queries(monkeypatch)
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
    assert ran == []
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
    assert nodes["act1"].node_id == f"{COLLECTION_ACTIVITIES}/act1"
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
    assert nodes["doc1"].node_id == f"{COLLECTION_DOCUMENTS}/doc1"


def test_the_raw_records_are_streamed_per_kind_not_loaded_as_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.pipelines.normalize.tk_dossiers import (
        RAW_KINDS,
        TKDossiersNormalizePipeline,
    )

    asked: list[tuple[list[str], int]] = []

    def iter_raw_records(store: Any, *, kinds: list[str], batch_size: int, **_kw: Any):
        asked.append((kinds, batch_size))
        return iter([])

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)
    monkeypatch.setattr(raw_queries, "count_raw_records", lambda *_a: 0)

    raw = TKDossiersNormalizePipeline(store=_Store()).fetch_raw()
    assert asked == []  # nothing is read before it is walked
    assert set(raw) == set(RAW_KINDS) and not isinstance(raw[RAW_KINDS[0]], list)
    assert list(raw[RAW_KINDS[0]]) == [] and list(raw[RAW_KINDS[0]]) == []
    assert asked == [([RAW_KINDS[0]], 1000)] * 2  # every walk streams again


# ── dossiers a window touches ────────────────────────────────────────────────


def test_a_window_refreshes_the_dossiers_its_records_belong_to(monkeypatch) -> None:
    """In one read of the dossiers, not one per dossier."""
    from types import SimpleNamespace

    from lawgraph.config.constants import COLLECTION_DOSSIERS
    from lawgraph.db.queries.normalize import tk as normalize_tk
    from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline

    stored = {"36000", "37020_xv"}
    asked: list[list[str]] = []

    def dossiers_by_key(store: Any, keys: list[str]) -> Any:
        asked.append(keys)
        return iter(
            {"id": f"{COLLECTION_DOSSIERS}/{key}", "key": key, "type": "dossier",
             "labels": [], "props": {"title": key}}
            for key in keys
            if key in stored
        )  # fmt: skip

    monkeypatch.setattr(normalize_tk, "dossiers_by_key", dossiers_by_key)
    own = _node(COLLECTION_DOSSIERS, NodeType.DOSSIER, "36500")
    normalized = {
        "dossiers": {"36500": own, "guid-36500": own},
        "documents": {"d": _document("d", dossier_numbers=["36000", "36500"])},
        "activities": {
            "a": _node(
                COLLECTION_ACTIVITIES,
                NodeType.ACTIVITY,
                "a",
                dossier_numbers=["37020-XV", "99999"],
            )
        },
        "decisions": {},
    }
    window = SimpleNamespace(_incremental=True, store=object())
    touched = TKDossiersNormalizePipeline._touched_dossiers(window, normalized)  # type: ignore[arg-type]
    # the window's own dossier is refreshed anyway; one no record holds is passed over
    assert {label: node.key for label, node in touched.items()} == {
        "36000": "36000",
        "37020-XV": "37020_xv",
    }
    assert asked == [["36000", "37020_xv", "99999"]]  # one read
    # a run over everything holds every dossier already
    whole = SimpleNamespace(_incremental=False, store=None)
    assert TKDossiersNormalizePipeline._touched_dossiers(whole, normalized) == {}  # type: ignore[arg-type]


# ── links of a document: the activity it records, attachments and letters ─────

# The stenogram of the Tweede Kamer of 28 March 2023 (2023D18976): no case, no dossier,
# only the debate it is the record of (Document.Activiteit, 2023A00493).
STENOGRAM = "9cd4c32c-77fb-4713-821d-faf5ebd49b61"
DEBATE = "a76eec4d-9cde-48de-aefa-6385e69dd0e1"


def test_a_stenogram_is_made_in_its_debate_and_an_attachment_accompanies_its_letter() -> (
    None
):
    store = _Store(
        existing={
            COLLECTION_DOCUMENTS: {
                "9cd4c32c_77fb_4713_821d_faf5ebd49b61",
                "letter",
                "memo",
                "report",
            },
            COLLECTION_ACTIVITIES: {"a76eec4d_9cde_48de_aefa_6385e69dd0e1"},
        }
    )
    links = [
        (STENOGRAM, {"activity_ids": [DEBATE, "gone"]}),
        # the letter names its attachments; the report names its letter (a run that
        # read only the report makes the same edge); a paper not stored makes none
        ("letter", {"attachment_ids": ["memo", "absent"]}),
        ("report", {"attached_to_ids": ["letter"]}),
        ("memo", {"attached_to_ids": ["letter"]}),  # the same edge as the letter's
    ]
    tk_cases.link_documents(store, links, source=SOURCE)
    assert set(store.edge_meta) == {
        (
            "documents/9cd4c32c_77fb_4713_821d_faf5ebd49b61",
            RELATION_MADE_IN,
            "activities/a76eec4d_9cde_48de_aefa_6385e69dd0e1",
        ),
        ("documents/memo", RELATION_ACCOMPANIES, "documents/letter"),
        ("documents/report", RELATION_ACCOMPANIES, "documents/letter"),
    }
    # one lookup per collection, whatever the number of documents
    assert store.existence_calls == 2


def test_a_letter_answers_the_commitment_it_fulfils_when_it_is_stored() -> None:
    store = _Store(existing={COLLECTION_DOCUMENTS: {"letter"}})
    commitment = _node(
        COLLECTION_COMMITMENTS,
        NodeType.COMMITMENT,
        "tz1",
        letter_ids=["LETTER", "absent"],
    )
    tk_cases.link_letters_to_commitments(store, [commitment], source=SOURCE)
    assert set(store.edge_meta) == {
        ("documents/letter", RELATION_ANSWERS, "commitments/tz1")
    }


def test_a_decision_is_made_in_the_activity_of_its_agenda_item() -> None:
    store = _Store(existing={COLLECTION_ACTIVITIES: {"act_1"}})
    decisions = [
        _node(COLLECTION_DECISIONS, NodeType.DECISION, "b1", activity_id="ACT-1"),
        _node(COLLECTION_DECISIONS, NodeType.DECISION, "b2", activity_id="gone"),
        _node(COLLECTION_DECISIONS, NodeType.DECISION, "b3"),
    ]
    tk_cases.link_decisions_to_activities(store, decisions, source=SOURCE)
    assert set(store.edge_meta) == {
        ("decisions/b1", RELATION_MADE_IN, "activities/act_1")
    }
