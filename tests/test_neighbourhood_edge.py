"""An edge of a neighbourhood or a path carries its ``meta``, its passages apart."""

from __future__ import annotations

from lawgraph.api.schemas.nodes import NodeNeighborhoodEdge

_PASSAGE = {
    "paragraph_id": "rov-5.3",
    "paragraph_number": "5.3",
    "footnote": None,
    "snippet": "op grond van artikel 6:162 BW",
    "text": "artikel 6:162 BW",
    "start": 11,
    "end": 27,
}


def _edge(meta: dict[str, object] | None) -> dict[str, object]:
    return NodeNeighborhoodEdge.from_doc(
        {
            "id": "edges/e",
            "from_id": "members/m",
            "to_id": "factions/f",
            "relation": "MEMBER_OF",
            "meta": meta,
        }
    ).model_dump()


def test_the_period_of_a_membership_is_on_its_edge() -> None:
    edge = _edge({"from_date": "2023-12-06", "to_date": None})
    assert edge["meta"] == {"from_date": "2023-12-06", "to_date": None}


def test_the_passages_stay_their_own_field() -> None:
    edge = _edge({"lid": "2", "passages": [_PASSAGE]})
    assert edge["meta"] == {"lid": "2"}
    assert edge["passages"] == [_PASSAGE]


def test_an_edge_without_meta_has_none() -> None:
    assert _edge(None)["meta"] is None
    assert _edge({})["meta"] is None
    assert _edge({"passages": [_PASSAGE]})["meta"] is None
