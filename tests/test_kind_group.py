"""What a paper or case of the Kamer is, by its Soort (``kind_group``)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.api.schemas.documents import DocumentListItemDTO
from lawgraph.api.schemas.feed import FeedItemDTO
from lawgraph.api.schemas.nodes import BaseNodeDTO
from lawgraph.core.tk_records.kinds import kind_group


@pytest.mark.parametrize(
    ("kind", "group"),
    [
        ("Motie", "motie"),
        ("Motie (gewijzigd/nader)", "motie"),
        ("Amendement", "amendement"),
        ("Amendement (gewijzigd/nader/vervangend)", "amendement"),
        ("Voorstel van wet", "wetsvoorstel"),
        ("Voorstel van wet (initiatiefvoorstel)", "wetsvoorstel"),
        ("Wetgeving", "wetsvoorstel"),
        ("Initiatiefwetgeving", "wetsvoorstel"),
        ("Brief regering", "brief"),
        ("Brief commissie aan bewindspersoon", "brief"),
        ("Geleidende brief", "overig"),
        ("Memorie van toelichting", "overig"),
        ("Stenogram", "overig"),
        (None, None),
        ("", None),
    ],
)
def test_a_soort_has_its_group(kind: str | None, group: str | None) -> None:
    assert kind_group(kind) == group


def test_a_paper_row_carries_its_group() -> None:
    schema = DocumentListItemDTO.model_json_schema(mode="serialization")
    assert "kind_group" in schema["properties"]


_COLLECTION = {"document": "documents", "case": "cases", "instrument": "instruments"}


def _node(type_: str, kind: str) -> dict[str, Any]:
    return BaseNodeDTO.from_document(
        {
            "id": f"{_COLLECTION[type_]}/k",
            "key": "k",
            "type": type_,
            "props": {"kind": kind},
        }
    ).model_dump()


def test_a_node_of_a_paper_or_case_carries_its_group_and_no_other_does() -> None:
    assert _node("document", "Motie (gewijzigd/nader)")["kind_group"] == "motie"
    assert _node("case", "Wetgeving")["kind_group"] == "wetsvoorstel"
    assert "kind_group" not in _node("instrument", "wet")


def test_the_props_of_a_node_of_a_paper_or_case_carry_its_group() -> None:
    assert _node("document", "Amendement (vervangend)")["props"]["kind_group"] == (
        "amendement"
    )
    assert _node("case", "Brief regering")["props"]["kind_group"] == "brief"
    assert "kind_group" not in _node("instrument", "wet")["props"]


def test_a_feed_item_and_a_link_of_a_paper_carry_its_group() -> None:
    item = FeedItemDTO.from_row(
        {
            "kind": "Brief regering",
            "id": "documents/letter",
            "date": "2026-06-24",
            "props": {"kind": "Brief regering", "subject": "Uitvoering van moties"},
            "answers": [
                {
                    "id": "documents/motion",
                    "props": {"kind": "Motie (gewijzigd/nader)"},
                },
                {"id": "commitments/tz", "props": {"number": "TZ202606-001"}},
            ],
        }
    ).model_dump()
    assert item["kind_group"] == "brief"
    assert [a["kind_group"] for a in item["answers"]] == ["motie", None]


def test_a_feed_item_of_a_vote_carries_the_group_of_what_was_voted_on() -> None:
    vote = {"kind": "stemming", "id": "decisions/d", "date": "2026-06-24"}
    assert (
        FeedItemDTO.from_row({**vote, "props": {"kind": "Wetgeving"}}).kind_group
        == "wetsvoorstel"
    )
    publication = {"kind": "publicatie", "id": "instruments/stb_2026_1", "date": "2026"}
    assert FeedItemDTO.from_row({**publication, "props": {}}).kind_group is None
