"""The ``references`` part of a record: how many references its step could not link and how
many it linked to a stub (``core.completeness.references_part``)."""

from __future__ import annotations

from lawgraph.core.completeness import ReferenceCounts, references_part


def test_a_record_no_step_read_has_no_part() -> None:
    assert references_part(None) is None


def test_every_reference_linked_to_a_loaded_target_is_done() -> None:
    assert references_part(ReferenceCounts(0, 0)) == {"state": "done"}


def test_references_not_linked_are_missing() -> None:
    assert references_part(ReferenceCounts(2)) == {"state": "partial", "missing": 2}


def test_references_linked_to_a_stub_are_missing_for_that_reason() -> None:
    assert references_part(ReferenceCounts(0, 3)) == {
        "state": "partial",
        "missing": 3,
        "reason": "target_not_loaded",
    }


def test_both_are_missing_without_a_reason() -> None:
    assert references_part(ReferenceCounts(1, 3)) == {"state": "partial", "missing": 4}
