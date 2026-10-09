"""A faction vote in which members voted apart, normalized again on a real database
(``normalize tk-dossiers --mixed-votes``): read before as a roll call of those members
alone, it becomes a faction vote, each faction with its seats without them and each of
them with one seat from their member node. The rows have the fields the API sends."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RAW_KIND_TK_STEMMING, SOURCE_TK
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db import GraphStore, NodeWriter, RawSourceWriter, raw_source_doc
from lawgraph.db.queries.normalize import tk as normalize_tk

BESLUIT = "2a67b884-e78e-4ccb-a21f-b97df9801d99"
CASE = {"Id": "z-faber", "Soort": "Motie", "Onderwerp": "Motie van het lid Faber"}


def _row(n: int, choice: str, size: int, faction: str, person: str | None) -> dict:
    return {
        "Id": f"s-{n}",
        "Besluit_Id": BESLUIT,
        "Soort": choice,
        "FractieGrootte": size,
        "ActorFractie": faction,
        "Fractie_Id": f"f-{faction.lower()}",
        "Persoon_Id": person,
        "ActorNaam": person,
        "GewijzigdOp": "2026-05-12T16:00:00+02:00",
        "Verwijderd": False,
        "Besluit": {
            "Id": BESLUIT,
            "BesluitSoort": "Stemmen - verworpen",
            "StemmingsSoort": "Met handopsteken",
            "Zaak": [CASE],
            "Agendapunt": {
                "Onderwerp": CASE["Onderwerp"],
                "Activiteit": {"Soort": "Stemmingen", "Datum": "2026-05-12T15:00:00"},
                "Zaak": [CASE],
            },
        },
    }


# Groep Markuszower (7) against but for two of its members; the VVD (22) for, D66 (26)
# against.
ROWS = [
    _row(1, "Voor", 22, "VVD", None),
    _row(2, "Tegen", 7, "GM", None),
    _row(3, "Voor", 7, "GM", "p-3"),
    _row(4, "Voor", 7, "GM", "p-4"),
    _row(5, "Tegen", 26, "D66", None),
]


def _seed(store: GraphStore) -> str:
    with RawSourceWriter(store) as writer:
        for row in ROWS:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_STEMMING,
                    external_id=row["Id"],
                    payload_json=row,
                )
            )
    key = make_node_key("decision", BESLUIT)
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                *(
                    Node(collection="factions", type=NodeType.FACTION, key=f,
                         labels=["TK"], props={"external_id": f"f-{f}", "name": f})
                    for f in ("vvd", "gm", "d66")
                ),
                *(
                    Node(collection="members", type=NodeType.MEMBER, key=p,
                         labels=["TK"], props={"name": p})
                    for p in ("p_3", "p_4")
                ),
                # as it was read: a roll call of the two members alone
                Node(collection="decisions", type=NodeType.DECISION, key=key,
                     labels=["TK"], props={"decision_id": BESLUIT, "vote_kind": "member",
                                           "tally": {"Voor": 2}}),
            ]
        )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            {"_key": f"old-{p}", "_from": f"members/{p}", "_to": f"decisions/{key}",
             "relation": "VOTED", "source": "tk-dossiers",
             "meta": {"choice": "Voor", "seats": 1}}
            for p in ("p_3", "p_4")
        ]
    )  # fmt: skip
    return f"decisions/{key}"


def test_a_mixed_vote_is_normalized_again_as_a_faction_vote(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    decision = _seed(store)
    assert normalize_tk.mixed_vote_decisions(store) == [BESLUIT]

    cli("normalize", "tk-dossiers", "--mixed-votes", "--limit", "10")

    (props,) = store.query(
        "SELECT props FROM decisions WHERE id = %(id)s", {"id": decision}
    )
    assert props["vote_kind"] == "faction"
    assert props["tally"] == {"Voor": 24, "Tegen": 31}
    votes = {
        row["from_id"]: (row["choice"], row["seats"])
        for row in store.query(
            "SELECT json_build_object('from_id', from_id,"
            " 'choice', lg_str(doc -> 'meta' -> 'choice'),"
            " 'seats', lg_num(doc -> 'meta' -> 'seats')) FROM edges"
            " WHERE to_id = %(id)s AND relation = 'VOTED'",
            {"id": decision},
        )
    }
    assert votes == {
        "factions/vvd": ("Voor", 22),
        "factions/gm": ("Tegen", 5),
        "factions/d66": ("Tegen", 26),
        "members/p_3": ("Voor", 1),
        "members/p_4": ("Voor", 1),
    }
    # a faction vote now: the next slice finds nothing
    assert normalize_tk.mixed_vote_decisions(store) == []
