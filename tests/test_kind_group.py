"""What a paper or case of the Kamer is, by its Soort (``kind_group``)."""

from __future__ import annotations

import pytest

from lawgraph.api.schemas.documents import DocumentListItemDTO
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


def _node(type_: str, kind: str) -> dict[str, object]:
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
