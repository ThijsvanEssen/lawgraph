"""What a document says about itself: its chamber, whether it explains a law, its sender."""

from __future__ import annotations

import pytest

from lawgraph.core.documents import chamber_of, document_sender, is_explanatory


@pytest.mark.parametrize(
    ("labels", "chamber"),
    [
        (["TK"], "TK"),
        (["TK", "Kamerstuk"], "TK"),
        (["EersteKamer", "EK"], "EK"),
        (["Staatsblad", "NvT"], None),
        ([], None),
        (None, None),
    ],
)
def test_the_chamber_is_read_from_the_labels(labels, chamber) -> None:
    assert chamber_of(labels) == chamber


@pytest.mark.parametrize(
    ("kind", "explanatory"),
    [
        ("Memorie van toelichting", True),
        ("Nota van toelichting", True),
        ("MEMORIE VAN TOELICHTING", True),
        ("Motie", False),
        ("Nota naar aanleiding van het verslag", False),
        ("", False),
        (None, False),
    ],
)
def test_an_explanatory_kind_contains_toelichting(kind, explanatory) -> None:
    assert is_explanatory(kind) is explanatory


def test_the_tk_mvt_pipeline_selects_with_the_same_marker() -> None:
    from lawgraph.db.queries.semantic.tk import MEMORANDUM_TARGETS_SQL

    assert "'toelichting'" in MEMORANDUM_TARGETS_SQL


_MINISTER = {
    "person_id": "p-9",
    "name": "E. Heinen",
    "faction": "",
    "role": "Eerste ondertekenaar",
    "function": "minister van Financiën",
    "capacity": "bewindspersoon",
}
_GRIFFIER = {
    "name": "Griffier",
    "faction": "",
    "role": "Afzender",
    "capacity": "overig",
}


def test_a_letter_of_the_government_is_sent_by_its_minister_and_ministry() -> None:
    assert document_sender([_GRIFFIER, _MINISTER], "2026-01-05") == {
        "name": "E. Heinen",
        "function": "minister van Financiën",
        "faction": None,
        "capacity": "bewindspersoon",
        "member_key": "p_9",
        "ministry": "fin",
    }


def test_without_a_first_signatory_the_sender_is_the_one_the_source_names() -> None:
    sender = document_sender([_GRIFFIER])
    assert sender is not None
    assert (sender["name"], sender["capacity"], sender["ministry"]) == (
        "Griffier",
        "overig",
        None,
    )


def test_a_member_names_no_ministry_and_a_paper_without_signatures_no_sender() -> None:
    member = {
        "name": "M. Faber",
        "faction": "PVV",
        "role": "Eerste ondertekenaar",
        "function": "Tweede Kamerlid",
        "capacity": "kamerlid",
    }
    sender = document_sender([member])
    assert sender is not None and sender["faction"] == "PVV"
    assert sender["ministry"] is None and sender["member_key"] is None
    co_signer = {"name": "I. Ellian", "role": "Mede ondertekenaar"}
    assert document_sender([co_signer]) is None
    assert document_sender(None) is None
