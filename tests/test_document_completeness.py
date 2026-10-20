"""The ``text``, ``paragraphs`` and ``tables`` of a Kamerstuk: what ``retrieve tk-content``
and ``normalize tk-content`` wrote of it (``core/document_completeness.py``)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.core.document_completeness import XmlRetrieval, document_text_parts

TODAY = dt.date(2026, 10, 21)
NUMBERED = {"dossier_number": "37020", "dossier_suffix": "X", "sequence": 53}
FRESH = {**NUMBERED, "date": "2026-10-19"}
OLD = {**NUMBERED, "date": "2019-03-01"}
FETCHED = "2026-10-20T03:10:00+00:00"
NORMALIZED = "2026-10-20T05:00:00+00:00"


def _parts(
    props: dict[str, Any],
    retrieval: XmlRetrieval | None = None,
    labels: tuple[str, ...] = ("TK",),
) -> dict[str, Any] | None:
    return document_text_parts(props, list(labels), retrieval, today=TODAY)


def _same(state: str, as_of: str | None = None) -> dict[str, Any]:
    part: dict[str, Any] = {"state": state}
    if as_of is not None:
        part["as_of"] = as_of
    return {"text": part, "paragraphs": part, "tables": part}


def test_a_paper_read_with_paragraphs_and_tables_is_done() -> None:
    props = {
        **NUMBERED,
        "text": "Brief\nTabel",
        "paragraphs": [{"id": "p1"}],
        "tables": [{"start": 6, "end": 11}],
    }
    assert _parts(props) == _same("done")


def test_a_paper_read_without_tables_has_none() -> None:
    props = {**NUMBERED, "text": "Brief", "paragraphs": [{"id": "p1"}], "tables": None}
    parts = _parts(props)
    assert parts is not None
    assert parts["tables"] == {"state": "none"}
    assert parts["paragraphs"] == {"state": "done"}


def test_a_paper_read_before_its_paragraphs_and_tables_were_kept_waits_for_them() -> (
    None
):
    assert _parts({**NUMBERED, "text": "Brief"}) == {
        "text": {"state": "done"},
        "paragraphs": {"state": "pending"},
        "tables": {"state": "pending"},
    }


def test_a_paper_read_without_lines_has_no_paragraphs() -> None:
    props = {**NUMBERED, "text": "Brief", "paragraphs": [], "tables": None}
    parts = _parts(props)
    assert parts is not None
    assert parts["paragraphs"] == {"state": "none"}


def test_a_numbered_paper_not_fetched_yet_is_pending() -> None:
    assert _parts(OLD, XmlRetrieval()) == _same("pending")


def test_a_fresh_paper_the_repository_has_no_xml_of_yet_is_pending() -> None:
    """A new paper is a PDF only ("Onopgemaakt") until its XML follows: asked again."""
    assert _parts(FRESH, XmlRetrieval(missing=FETCHED)) == _same("pending", FETCHED)


def test_an_old_paper_the_repository_has_no_xml_of_is_not_in_the_source() -> None:
    assert _parts(OLD, XmlRetrieval(missing=FETCHED)) == _same("not_in_source", FETCHED)


def test_xml_fetched_after_the_last_complete_normalize_is_pending() -> None:
    retrieval = XmlRetrieval(stored=FETCHED, normalized_until="2026-10-19T05:00:00Z")
    assert _parts(OLD, retrieval) == _same("pending", FETCHED)


def test_xml_read_by_normalize_without_text_has_none() -> None:
    """``normalize tk-content`` read it and wrote nothing: the XML does not read, or holds
    no text."""
    retrieval = XmlRetrieval(stored=FETCHED, normalized_until=NORMALIZED)
    assert _parts(OLD, retrieval) == _same("none", FETCHED)


def test_stored_xml_wins_over_an_earlier_answer_of_404() -> None:
    retrieval = XmlRetrieval(stored=FETCHED, missing="2026-10-01T03:00:00+00:00")
    assert _parts(OLD, retrieval) == _same("pending", FETCHED)


@pytest.mark.parametrize(
    "props",
    [
        {"kind": "Agenda"},  # no dossier
        {"dossier_number": "37020", "kind": "Verslag"},  # no number in it
        {"dossier_number": "Kamerstuk", "sequence": 3},  # no address in the repository
    ],
)
def test_a_paper_that_is_no_kamerstuk_is_not_in_the_source(
    props: dict[str, Any],
) -> None:
    assert _parts(props, XmlRetrieval()) == _same("not_in_source")


def test_a_paper_of_another_chamber_says_nothing() -> None:
    assert _parts(NUMBERED, XmlRetrieval(), labels=("EK",)) is None
