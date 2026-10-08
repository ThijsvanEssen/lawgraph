"""The names of a dossier next to its bare number (``load_dossier_names``): ``dossiers``
of the decisions, the papers of a list, the votes of an Eerste Kamer faction and the
activities of a committee, ``dossier_short_title`` of a neighbour, ``short_title`` of a
dossier a commitment or a publication names."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.schemas.common import DossierRefDTO
from lawgraph.api.schemas.decisions import DecisionDTO
from lawgraph.api.schemas.documents import DocumentListItemDTO
from lawgraph.api.schemas.government import CommitmentDTO
from lawgraph.api.schemas.nodes import NeighborDTO

from .conftest import DOSSIER_NAMES

client = TestClient(app)

NAMED = {
    "number": "36000",
    "short_title": "Wet beter voorbeeld",
    "title": "Wijziging van de Wet X (Wet beter voorbeeld)",
}
UNKNOWN = {"number": "99999", "short_title": None, "title": None}


def test_a_decision_in_the_list_names_its_dossiers(monkeypatch) -> None:
    """Each number once, in its order; a number no dossier has gets null names."""
    row = {
        "id": "decisions/d1",
        "key": "d1",
        "dossier_numbers": ["36000", "99999", "36000"],
    }
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_decisions",
        lambda store, filters, **kwargs: {"total": 1, "items": [row]},
    )
    item = client.get("/api/decisions").json()["items"][0]
    assert item["dossier_numbers"] == ["36000", "99999", "36000"]
    assert item["dossiers"] == [NAMED, UNKNOWN]


def test_a_decision_names_its_dossiers() -> None:
    doc = {"_id": "decisions/d1", "_key": "d1", "props": {"dossier_numbers": ["36000"]}}
    assert DecisionDTO.from_document(doc, DOSSIER_NAMES).model_dump()["dossiers"] == [
        NAMED
    ]


def test_a_paper_in_the_list_names_its_dossiers_or_its_own() -> None:
    """By ``dossier_numbers``; without them by ``dossier_number``; neither: none."""
    row: dict[str, Any] = {"id": "documents/p1", "key": "p1"}
    by_labels = DocumentListItemDTO.from_row(
        {**row, "dossier_numbers": ["99999", "36000"]}, DOSSIER_NAMES
    )
    assert [d.model_dump() for d in by_labels.dossiers] == [UNKNOWN, NAMED]
    own = DocumentListItemDTO.from_row(
        {**row, "dossier_number": "36000"}, DOSSIER_NAMES
    )
    assert [d.model_dump() for d in own.dossiers] == [NAMED]
    assert DocumentListItemDTO.from_row(row, DOSSIER_NAMES).dossiers == []


def _neighbor(collection: str, props: dict[str, Any]) -> NeighborDTO:
    return NeighborDTO.from_entry(
        doc={
            "_id": f"{collection}/n1",
            "_key": "n1",
            "type": "x",
            "labels": [],
            "props": props,
        },
        edge={"_key": "e1", "relation": "ABOUT"},
        direction="outbound",
        confidence=None,
        names=DOSSIER_NAMES,
    )


def test_a_neighbour_says_the_name_of_its_first_dossier() -> None:
    """A paper, an activity or a decision: the short title of its first dossier (null when
    it has none, or none is known); another node: nothing; the kept props unchanged."""
    props = {"dossier_numbers": ["36000", "99999"]}
    paper = _neighbor("documents", props)
    assert paper.props == {**props, "dossier_short_title": "Wet beter voorbeeld"}
    assert props == {"dossier_numbers": ["36000", "99999"]}  # not the kept dict
    assert _neighbor("decisions", {"dossier_numbers": ["99999"]}).props == {
        "dossier_numbers": ["99999"],
        "dossier_short_title": None,
    }
    activity = _neighbor("activities", {"kind": "Commissiedebat"})
    assert (activity.props or {})["dossier_short_title"] is None
    assert "dossier_short_title" not in (_neighbor("articles", props).props or {})


def test_the_dossier_of_a_commitment_or_a_publication_has_its_short_title() -> None:
    ref = DossierRefDTO.from_number(
        "36000", {"36000": "Wijziging van de Wet X (Wet beter voorbeeld)"}
    )
    assert ref.short_title == "Wet beter voorbeeld"
    assert DossierRefDTO.from_number("99999").short_title is None
    commitment = CommitmentDTO.from_row(
        {
            "commitment": {"_key": "c1", "props": {}},
            "dossiers": [
                {"key": "36000", "number": "36000", "title": NAMED["title"]},
                {"key": "99999", "number": "99999", "title": None},
            ],
        }
    )
    assert [d.short_title for d in commitment.dossiers] == ["Wet beter voorbeeld", None]
