"""What a document says about itself: its chamber, and whether it explains a law."""

from __future__ import annotations

import pytest

from lawgraph.core.documents import chamber_of, is_explanatory


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
    from lawgraph.db.queries.semantic import MEMORANDUM_TARGETS_AQL

    assert "'toelichting'" in MEMORANDUM_TARGETS_AQL
