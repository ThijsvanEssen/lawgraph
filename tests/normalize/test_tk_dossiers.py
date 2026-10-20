"""What the TK parliament normalizers write: which edges, between what, and how.

The expectations name endpoints and meta, not the calls that produce them, and
the last group pins that the cost of a build does not grow with the number of
items.
"""

from __future__ import annotations

import inspect
from typing import Any, cast

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
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.props import FactionProps, MemberProps
from lawgraph.core.relations import BY_NAME
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries import removals
from lawgraph.db.queries.normalize import bwb as normalize_bwb
from lawgraph.db.queries.normalize import rechtspraak as normalize_rechtspraak
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.base import PipelineBase
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize import _tk_members as tk_members
from lawgraph.pipelines.normalize import _tk_votes as tk_votes
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from tests.fakes import InMemoryStore, count_calls
from tests.optional import present

SOURCE = "test"


def _store(existing: dict[str, set[str]] | None = None) -> InMemoryStore:
    """A store holding the nodes of *existing* (collection -> keys)."""
    return InMemoryStore(
        {
            collection: [{"key": key, "props": {}} for key in keys]
            for collection, keys in (existing or {}).items()
        }
    )


def _edge_meta(store: InMemoryStore) -> dict[tuple[str, str, str], dict | None]:
    """The meta of every stored edge, by its endpoints and relation."""
    return {
        (edge["from_id"], edge["relation"], edge["to_id"]): edge.get("meta") or None
        for edge in store.edges.values()
    }


@pytest.fixture(autouse=True)
def _removals(edge_removals: None) -> None:
    """The edges a run no longer derives go from the ``edges`` of the store."""


@pytest.fixture(autouse=True)
def _no_stale_votes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``link_votes`` removes the VOTED edges it did not write: there are none here."""
    monkeypatch.setattr(removals, "remove_edges_into_except", lambda *_a, **_kw: 0)


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node.skeleton(collection, key, props)


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
    store = _store(existing={COLLECTION_DOSSIERS: {"36000"}, COLLECTION_CASES: {"z_1"}})
    documents = [
        _document(
            "a", case_ids=["z-1", "z-unknown"], dossier_numbers=["36000", "99999"]
        ),
        _document("b"),
    ]

    tk_cases.link_subjects(store, documents, RELATION_PART_OF, source=SOURCE)

    assert set(_edge_meta(store)) == {
        (f"{COLLECTION_DOCUMENTS}/a", RELATION_PART_OF, f"{COLLECTION_CASES}/z_1"),
        (f"{COLLECTION_DOCUMENTS}/a", RELATION_PART_OF, f"{COLLECTION_DOSSIERS}/36000"),
    }


def test_activities_and_decisions_are_about_their_subjects() -> None:
    store = _store(existing={COLLECTION_DOSSIERS: {"36000"}})
    activity = _node(
        COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a1", dossier_numbers=["36000"]
    )
    decision = _node(
        COLLECTION_DECISIONS, NodeType.DECISION, "s1", dossier_numbers=["36000"]
    )

    tk_cases.link_subjects(store, [activity], RELATION_ABOUT, source=SOURCE)
    tk_cases.link_subjects(store, [decision], RELATION_ABOUT, source=SOURCE)

    assert set(_edge_meta(store)) == {
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
    store = _store(existing={COLLECTION_DOSSIERS: {"36000"}})

    tk_cases.link_cases_to_dossiers(store, source=SOURCE)

    assert set(_edge_meta(store)) == {
        (f"{COLLECTION_CASES}/z1", RELATION_PART_OF, f"{COLLECTION_DOSSIERS}/36000")
    }


def test_an_activity_is_led_by_its_lead_committee_only() -> None:
    store = _store(existing={COLLECTION_COMMITTEES: {"c1"}})
    activities = {
        "a1": _node(COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a1", committee_id="c1"),
        # A plenary activity has none.
        "a2": _node(COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a2", committee_id=None),
        "a3": _node(
            COLLECTION_ACTIVITIES, NodeType.ACTIVITY, "a3", committee_id="unknown"
        ),
    }

    tk_cases.link_activities_to_committees(store, activities, source=SOURCE)

    assert set(_edge_meta(store)) == {
        (f"{COLLECTION_ACTIVITIES}/a1", RELATION_LED_BY, f"{COLLECTION_COMMITTEES}/c1")
    }


# ── commitments ──────────────────────────────────────────────────────────────


def test_a_commitment_is_made_in_an_activity_and_about_its_dossiers() -> None:
    store = _store(existing={COLLECTION_DOSSIERS: {"36000"}})
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

    assert set(_edge_meta(store)) == {
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
    store = _store(existing={COLLECTION_DOSSIERS: {"36835"}})
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

    # as the run keeps them after the write (``link_node``)
    written = {key: tk_cases.link_node(node) for key, node in activities.items()}

    tk_cases.link_commitments(store, commitments, written, source=SOURCE)

    assert set(_edge_meta(store)) == {
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
    store = _store(existing={COLLECTION_MEMBERS: {"p1"}})
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

    assert _edge_meta(store) == {
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
    store = _store(
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
        _raw({"Id": "c-empty", "CommissieZetel": []}),
        _raw(
            {
                "Id": "c-missing",
                "CommissieZetel": [
                    {"CommissieZetelVastPersoon": [{"Persoon_Id": "p1", "Van": None}]}
                ],
            }
        ),
    ]

    pipeline = PipelineBase(store)
    tk_members.link_members_to_committees(pipeline, raws, source=SOURCE)

    assert pipeline.progress.skips == {
        "member not in the graph": 1,
        "committee not in the graph": 1,
    }

    assert _edge_meta(store) == {
        (
            f"{COLLECTION_MEMBERS}/p1",
            RELATION_MEMBER_OF,
            f"{COLLECTION_COMMITTEES}/c1",
        ): {
            "from_date": "2022-01-01",
            "periods": [
                {"from_date": "2020-01-01", "to_date": "2021-01-01"},
                {"from_date": "2022-01-01"},
                {"from_date": "2023-01-01", "role": "PlvLid", "substitute": True},
            ],
        },
        (
            f"{COLLECTION_MEMBERS}/p2",
            RELATION_MEMBER_OF,
            f"{COLLECTION_COMMITTEES}/c1",
        ): {"from_date": "2019-01-01", "to_date": "2020-01-01"},
    }


def test_faction_membership_writes_an_edge_and_the_member_timeline() -> None:
    store = _store()
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
        PipelineBase(store),
        raws,
        {"p1": member},
        {"f-vvd": faction},
        source=SOURCE,
    )

    assert _edge_meta(store) == {
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
    written = store.nodes[COLLECTION_MEMBERS]["p1"]["props"]
    MemberProps.model_validate(written)
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
        store = _store()
        tk_members.link_members_to_factions(
            PipelineBase(store),
            [_raw(payload) for payload in order],
            {"p1": member},
            {"f-sp": faction},
            source=SOURCE,
        )
        metas.append(_edge_meta(store))
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
    store = _store()
    raws = [
        _vote_raw(Id="v-1"),
        _vote_raw(Id="v-2", Soort="Tegen", FractieGrootte=9, Fractie_Id="f-d66"),
        _vote_raw(Id="v-3", Soort="Onthouden", FractieGrootte=1, Fractie_Id="f-x"),
    ]
    votes = tk_votes.read_votes(PipelineBase(store), raws)
    decisions = tk_votes.normalize_decisions(store, votes)
    factions = {
        "f-vvd": _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd"),
        "f-d66": _node(COLLECTION_FACTIONS, NodeType.FACTION, "d66"),
    }

    tk_votes.link_votes(store, votes.by_decision, decisions, factions, source=SOURCE)

    decision_id = f"{COLLECTION_DECISIONS}/{decisions['b-1'].key}"
    assert _edge_meta(store) == {
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
    store = _store(existing={COLLECTION_MEMBERS: {"p_1"}})
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
    votes = tk_votes.read_votes(PipelineBase(store), raws)
    decisions = tk_votes.normalize_decisions(store, votes)
    factions = {"f-vvd": _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd")}

    tk_votes.link_votes(store, votes.by_decision, decisions, factions, source=SOURCE)

    decision = decisions["b-1"]
    written = store.nodes[COLLECTION_DECISIONS][present(decision.key)]["props"]
    assert written["vote_kind"] == "member"
    assert _edge_meta(store) == {
        (
            f"{COLLECTION_MEMBERS}/p_1",
            RELATION_VOTED,
            f"{COLLECTION_DECISIONS}/{decision.key}",
        ): {"choice": "Voor", "seats": 1, "record_ids": ["v-1"]}  # one seat
    }


def test_members_voting_apart_from_their_faction_vote_beside_it() -> None:
    """A faction vote in which members voted apart: the faction votes with its seats
    without them, each of them from their member node with one seat."""
    store = _store(existing={COLLECTION_MEMBERS: {"p_3", "p_4"}})
    raws = [
        _vote_raw(Id="v-1", Soort="Tegen", FractieGrootte=7),
        _vote_raw(Id="v-3", Soort="Voor", FractieGrootte=7, Persoon_Id="p-3"),
        _vote_raw(Id="v-4", Soort="Voor", FractieGrootte=7, Persoon_Id="p-4"),
    ]
    votes = tk_votes.read_votes(PipelineBase(store), raws)
    decisions = tk_votes.normalize_decisions(store, votes)
    factions = {"f-vvd": _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd")}

    tk_votes.link_votes(store, votes.by_decision, decisions, factions, source=SOURCE)

    decision = decisions["b-1"]
    written = store.nodes[COLLECTION_DECISIONS][present(decision.key)]["props"]
    assert written["vote_kind"] == "faction"
    target = f"{COLLECTION_DECISIONS}/{decision.key}"
    assert _edge_meta(store) == {
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
    votes = tk_votes.read_votes(PipelineBase(_store()), raws)
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

    for module in (normalize_bwb, removals, normalize_rechtspraak, normalize_tk):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ == module.__name__:
                monkeypatch.setattr(module, name, recorder(name))
    return ran


def test_linking_does_not_look_items_up_one_by_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran = _count_queries(monkeypatch)
    n = 2000
    store = _store(
        existing={
            COLLECTION_DOSSIERS: {str(i) for i in range(n)},
            COLLECTION_MEMBERS: {f"p{i}" for i in range(n)},
        }
    )
    lookups = count_calls(store, "existing_keys")
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

    assert len(_edge_meta(store)) == 2 * n
    assert ran == []
    # One existence lookup for the dossiers, one for the signatories.
    assert lookups["existing_keys"] == 2


def test_normalizing_activities_writes_nodes_in_bulk() -> None:
    store = _store()
    writes = count_calls(store, "bulk_insert_or_update_nodes")
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

    nodes = tk_cases.normalize_activities(PipelineBase(store), raws)

    assert len(nodes) == 700
    assert nodes["act1"].node_id == f"{COLLECTION_ACTIVITIES}/act1"
    assert nodes["act1"].props["dossier_numbers"] == ["36000"]
    assert (
        writes["bulk_insert_or_update_nodes"] == 2
    )  # 500 + 200, not 700 single upserts


def test_a_written_node_keeps_only_what_the_edges_need() -> None:
    """130K documents with their API payload are over a gigabyte; the edges read a few props."""
    store = _store()
    raws = (  # a generator: the records are walked once, as they stream in
        _raw({"Id": f"doc{i}", "Soort": "Motie", "Titel": "Motie " * 50})
        for i in range(3)
    )

    nodes = tk_cases.normalize_documents(PipelineBase(store), raws)

    written = store.nodes[COLLECTION_DOCUMENTS]["doc1"]["props"]
    assert written["title"].startswith("Motie") and "raw" in written
    assert set(nodes) == {"doc0", "doc1", "doc2"}
    assert set(nodes["doc1"].props) <= set(tk_cases.LINK_PROPS)
    assert nodes["doc1"].node_id == f"{COLLECTION_DOCUMENTS}/doc1"


def test_the_raw_records_are_streamed_per_kind_not_loaded_as_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.pipelines.normalize.tk_dossiers import (
        RAW_KINDS,
    )

    asked: list[tuple[list[str], int]] = []

    def iter_raw_records(store: Any, *, kinds: list[str], batch_size: int, **_kw: Any):
        asked.append((kinds, batch_size))
        return iter([])

    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)
    monkeypatch.setattr(raw_queries, "count_raw_records", lambda *_a: 0)

    raw = TKDossiersNormalizePipeline(store=InMemoryStore()).fetch_raw().records
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
    from lawgraph.pipelines.normalize.tk_dossiers import (
        Written,
    )

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
    written = Written(
        members={},
        factions={},
        dossiers={"36500": own, "guid-36500": own},
        activities={
            "a": _node(
                COLLECTION_ACTIVITIES,
                NodeType.ACTIVITY,
                "a",
                dossier_numbers=["37020-XV", "99999"],
            )
        },
        commitments={},
        documents={"d": _document("d", dossier_numbers=["36000", "36500"])},
        decisions={},
        votes={},
    )
    pipeline = SimpleNamespace(store=object())
    touched = TKDossiersNormalizePipeline._touched_dossiers(
        cast(TKDossiersNormalizePipeline, pipeline), written, True
    )
    # the window's own dossier is refreshed anyway; one no record holds is passed over
    assert {label: node.key for label, node in touched.items()} == {
        "36000": "36000",
        "37020-XV": "37020_xv",
    }
    assert asked == [["36000", "37020_xv", "99999"]]  # one read
    # a run over everything holds every dossier already
    assert (
        TKDossiersNormalizePipeline._touched_dossiers(
            cast(TKDossiersNormalizePipeline, pipeline), written, False
        )
        == {}
    )


# ── links of a document: the activity it records, attachments and letters ─────

# The stenogram of the Tweede Kamer of 28 March 2023 (2023D18976): no case, no dossier,
# only the debate it is the record of (Document.Activiteit, 2023A00493).
STENOGRAM = "9cd4c32c-77fb-4713-821d-faf5ebd49b61"
DEBATE = "a76eec4d-9cde-48de-aefa-6385e69dd0e1"


def test_a_stenogram_is_made_in_its_debate_and_an_attachment_accompanies_its_letter() -> (
    None
):
    store = _store(
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
    lookups = count_calls(store, "existing_keys")
    tk_cases.link_documents(store, links, source=SOURCE)
    assert set(_edge_meta(store)) == {
        (
            "documents/9cd4c32c_77fb_4713_821d_faf5ebd49b61",
            RELATION_MADE_IN,
            "activities/a76eec4d_9cde_48de_aefa_6385e69dd0e1",
        ),
        ("documents/memo", RELATION_ACCOMPANIES, "documents/letter"),
        ("documents/report", RELATION_ACCOMPANIES, "documents/letter"),
    }
    # one lookup per collection, whatever the number of documents
    assert lookups["existing_keys"] == 2


def test_a_letter_answers_the_commitment_it_fulfils_when_it_is_stored() -> None:
    store = _store(existing={COLLECTION_DOCUMENTS: {"letter"}})
    commitment = _node(
        COLLECTION_COMMITMENTS,
        NodeType.COMMITMENT,
        "tz1",
        letter_ids=["LETTER", "absent"],
    )
    tk_cases.link_letters_to_commitments(store, [commitment], source=SOURCE)
    assert set(_edge_meta(store)) == {
        ("documents/letter", RELATION_ANSWERS, "commitments/tz1")
    }


def test_a_decision_is_made_in_the_activity_of_its_agenda_item() -> None:
    store = _store(existing={COLLECTION_ACTIVITIES: {"act_1"}})
    decisions = [
        _node(COLLECTION_DECISIONS, NodeType.DECISION, "b1", activity_id="ACT-1"),
        _node(COLLECTION_DECISIONS, NodeType.DECISION, "b2", activity_id="gone"),
        _node(COLLECTION_DECISIONS, NodeType.DECISION, "b3"),
    ]
    tk_cases.link_decisions_to_activities(store, decisions, source=SOURCE)
    assert set(_edge_meta(store)) == {
        ("decisions/b1", RELATION_MADE_IN, "activities/act_1")
    }


# ── a record that gives nothing says why ─────────────────────────────────────

_GONE = {"Id": "gone", "Verwijderd": True}


@pytest.fixture
def _no_removals(monkeypatch: pytest.MonkeyPatch) -> None:
    """What an earlier run made of a deleted record: nothing here."""
    monkeypatch.setattr(removals, "remove_nodes", lambda *_a: 0)
    monkeypatch.setattr(removals, "remove_nodes_of_records", lambda *_a: 0)


@pytest.mark.usefixtures("_no_removals")
def test_a_deleted_or_nameless_document_is_skipped_with_its_reason() -> None:
    from lawgraph.pipelines.normalize._tk_deleted import DELETED

    pipeline = PipelineBase(_store())
    raws = [_raw(_GONE), {"key": "k-1", "payload_json": {"Soort": "Motie"}}]

    nodes = tk_cases.normalize_documents(pipeline, [*raws, _raw({"Id": "doc1"})])

    assert set(nodes) == {"doc1"}
    assert pipeline.progress.skips == {DELETED: 1, "no Id": 1}


@pytest.mark.usefixtures("_no_removals")
def test_a_deleted_or_nameless_case_or_dossier_is_skipped_with_its_reason() -> None:
    from lawgraph.pipelines.normalize._tk_deleted import DELETED
    from lawgraph.pipelines.normalize.tk import TKNormalizePipeline

    nameless = {"key": "k-1", "payload_json": {"Soort": "Motie"}}
    cases = TKNormalizePipeline(store=_store())
    cases.write([_raw(_GONE), nameless], PipelineResult())
    dossiers = TKDossiersNormalizePipeline(store=_store())
    nodes = dossiers._normalize_dossiers([_raw(_GONE), nameless])

    assert (cases.store.writes.created, nodes) == (0, {})
    assert cases.progress.skips == {DELETED: 1, "no Zaak identifier": 1}
    assert dossiers.progress.skips == {DELETED: 1, "no Id or number": 1}


@pytest.mark.parametrize("module", ["tk_document_links", "tk_case_actors"])
def test_a_deleted_or_nameless_link_record_is_skipped_with_its_reason(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    from lawgraph.pipelines.normalize._tk_deleted import DELETED

    links = importlib.import_module(f"lawgraph.pipelines.normalize.{module}")
    written: list[Any] = []
    kind = getattr(
        links,
        {
            "tk_document_links": "TKDocumentLinksNormalizePipeline",
            "tk_case_actors": "TKCaseActorsNormalizePipeline",
        }[module],
    )

    def link(_s: object, rows: list[Any], **_: object) -> int:
        written.extend(rows)
        return 0

    monkeypatch.setattr(kind, "link", link)
    pipeline = kind(store=_store())
    result = PipelineResult()

    pipeline.write(
        [_raw(_GONE), {"key": "k-1", "payload_json": {}}, _raw({"Id": "doc1"})],
        result,
    )
    pipeline.add_outcomes(result)

    assert [row[0] for row in written] == ["doc1"]
    assert pipeline.progress.skips == {DELETED: 1, "no Id": 1}
    assert result.skipped == 2


@pytest.fixture
def _no_edge_removals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(removals, "remove_edges_of_records", lambda *_a: 0)


@pytest.mark.usefixtures("_no_removals")
def test_a_deleted_or_nameless_committee_member_or_faction_is_skipped_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.pipelines.normalize._tk_deleted import DELETED

    monkeypatch.setattr(raw_queries, "vote_labels_of_factions", lambda *_a: [])
    pipeline = PipelineBase(_store())
    committees = tk_members.normalize_committees(
        pipeline,
        [_raw(_GONE), _raw({"Id": "c-nameless"}), _raw({"Id": "c1", "NaamNL": "Fin"})],
    )
    members = tk_members.normalize_members(
        pipeline, [_raw(_GONE), {"key": "k-1", "payload_json": {}}, _raw({"Id": "p1"})]
    )
    factions = tk_members.normalize_factions(
        pipeline,
        [_raw(_GONE), _raw({"Id": "f-nameless"}), _raw({"Id": "f1", "Afkorting": "X"})],
        [],
    )

    assert (set(committees), set(members), set(factions)) == ({"c1"}, {"p1"}, {"f1"})
    assert pipeline.progress.skips == {
        DELETED: 3,
        "no Id or name": 1,
        "no Id": 1,
        "no abbreviation or name": 1,
    }


@pytest.mark.usefixtures("_no_edge_removals")
def test_a_seat_left_out_is_skipped_with_its_reason() -> None:
    from lawgraph.pipelines.normalize._tk_deleted import DELETED

    store = _store()
    pipeline = PipelineBase(store)
    faction = _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd", abbreviation="VVD")
    member = _node(COLLECTION_MEMBERS, NodeType.MEMBER, "p1", name="Jan")
    seat = {"Persoon_Id": "p1", "FractieZetel": {"Fractie_Id": "f-vvd"}}

    tk_members.link_members_to_factions(
        pipeline,
        [
            _raw(_GONE),
            _raw({"Id": "s-0", "Persoon_Id": "p1"}),
            _raw({**seat, "Id": "s-1", "Persoon_Id": "nobody"}),
            _raw({**seat, "Id": "s-2", "Van": "2020-01-01"}),
        ],
        {"p1": member},
        {"f-vvd": faction},
        source=SOURCE,
    )

    assert len(_edge_meta(store)) == 1
    assert pipeline.progress.skips == {
        DELETED: 1,
        "no person or faction": 1,
        "member or faction not in the graph": 1,
    }


def test_a_vacancy_left_out_is_skipped_with_its_reason() -> None:
    from lawgraph.pipelines.normalize._tk_deleted import DELETED

    store = _store()
    pipeline = PipelineBase(store)
    faction = _node(COLLECTION_FACTIONS, NodeType.FACTION, "vvd", abbreviation="VVD")
    seat = {"FractieZetel": {"Fractie_Id": "f-vvd", "Id": "z1"}}

    tk_members.keep_faction_vacancies(
        pipeline,
        [
            _raw(_GONE),
            _raw({"Id": "v-0", "FractieZetel": {}}),
            _raw({**seat, "Id": "v-1", "Van": "2021-01-01", "TotEnMet": "2020-01-01"}),
            _raw({**seat, "Id": "v-2", "Van": "2021-01-01", "FractieZetel": {}}),
            _raw(
                {"Id": "v-3", "Van": "2021-01-01", "FractieZetel": {"Fractie_Id": "x"}}
            ),
            _raw({**seat, "Id": "v-4", "Van": "2021-01-01"}),
        ],
        [
            _raw(
                {
                    "Id": "h-1",
                    "FractieZetel": {"Id": "z1"},
                    "Van": "2015-01-01",
                    "TotEnMet": "2020-12-31",
                }
            )
        ],
        {"f-vvd": faction},
    )

    assert faction.props["vacancies"]
    FactionProps.model_validate(faction.props)
    assert pipeline.progress.skips == {
        DELETED: 1,
        "no faction or start, or an end before the start": 3,
        "faction not in the graph": 1,
    }


def test_a_vote_left_out_is_skipped_with_its_reason() -> None:
    from lawgraph.pipelines.normalize._tk_deleted import DELETED

    pipeline = PipelineBase(_store())
    struck = {"Id": "b-gone", "Verwijderd": True}

    votes = tk_votes.read_votes(
        pipeline,
        [
            _raw(_GONE),
            _vote_raw(Id="v-1", Besluit_Id="b-gone", Besluit=struck),
            _vote_raw(Id="v-2", Besluit_Id=None),
            _vote_raw(Id="v-3"),
        ],
    )

    assert set(votes.by_decision) == {"b-1"}
    assert pipeline.progress.skips == {
        DELETED: 1,
        "on a decision the Kamer deleted": 1,
        "no Besluit_Id": 1,
    }


def test_a_deleted_or_nameless_besluit_is_skipped_with_its_reason() -> None:
    from lawgraph.pipelines.normalize._tk_deleted import DELETED

    pipeline = TKDossiersNormalizePipeline(store=_store())
    votes = tk_votes.Votes()

    pipeline._add_bill_decisions(
        votes,
        [_raw({"Id": "b-gone", "Verwijderd": True}), _raw({}), _raw({"Id": "b-1"})],
        incremental=False,
    )

    assert set(votes.by_decision) == {"b-1"}
    assert pipeline.progress.skips == {DELETED: 1, "no Id": 1}


def _fail(*args: Any, **_: Any) -> dict[str, Any]:
    """A step that cannot read one record."""
    pipeline = next(arg for arg in args if isinstance(arg, PipelineBase))
    pipeline.progress.fail("not readable", "r-1")
    return {}


@pytest.mark.parametrize(
    ("mode", "step"),
    [
        ("persons", "normalize_members"),
        ("factions", "normalize_factions"),
        ("committees", "normalize_committees"),
        ("seats", "link_members_to_factions"),
        ("mixed_votes", "read_votes"),
    ],
)
def test_a_mode_of_one_kind_reports_what_it_left_out(
    mode: str, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.setattr(normalize_tk, "nodes_by_external_id", lambda *_a: [])
    monkeypatch.setattr(normalize_tk, "mixed_vote_decisions", lambda *_a: ["b-1"])
    monkeypatch.setattr(raw_queries, "vote_rows_of_decisions", lambda *_a: [])
    monkeypatch.setattr(
        tk_members, "link_members_to_committees", lambda *_a, **_k: None
    )
    module = tk_votes if step == "read_votes" else tk_members
    monkeypatch.setattr(
        module,
        step,
        (lambda *a, **k: _fail(*a, **k) or tk_votes.Votes())
        if step == "read_votes"
        else _fail,
    )
    pipeline = TKDossiersNormalizePipeline(store=_store(), **{mode: True})

    result = pipeline.run()

    assert result.skipped == 1
    assert result.errors == ["1 x not readable (first: r-1)"]
