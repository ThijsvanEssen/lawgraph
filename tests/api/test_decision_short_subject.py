"""The card of a vote names what was voted on by its short name (``short_subject``)."""

from __future__ import annotations

from typing import Any

from lawgraph.api.schemas.nodes import BaseNodeDTO


def _props(subject: str) -> dict[str, Any]:
    node = BaseNodeDTO.from_document(
        {
            "id": "decisions/d",
            "key": "d",
            "type": "decision",
            "props": {"subject": subject},
        }
    )
    return node.props or {}


def test_a_vote_has_the_short_name_of_its_subject() -> None:
    bill = "Regels over het toezicht op AI-systemen (Wet AI-toezicht)"
    assert _props(bill)["short_subject"] == "Wet AI-toezicht"
    budget = (
        "Vaststelling van de begrotingsstaten van het Ministerie van Defensie (X) voor "
        "het jaar 2027"
    )
    assert _props(budget)["short_subject"] == "Begroting Defensie 2027"
    # a motion has no short name: its subject is its name
    assert (
        _props("Motie van het lid Bolhuis over een AI-killswitch")["short_subject"]
        is None
    )
