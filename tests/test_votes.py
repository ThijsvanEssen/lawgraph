"""The choice of a vote and the outcome of a decision, written once (``core/votes.py``)."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import BaseModel

from lawgraph.api.schemas.decisions import CoalitionFactionDTO
from lawgraph.api.schemas.documents import PaperOutcomeFields
from lawgraph.api.schemas.feed import FeedVoteDTO
from lawgraph.core.tk_records.commitments import NO_DUE_DATE, due_date
from lawgraph.core.votes import (
    DECISION_KIND_WITHDRAWN,
    OUTCOMES,
    DocumentOutcome,
    VoteChoice,
    VoteOutcome,
    decision_outcome,
    vote_outcome,
)


def test_the_outcomes_are_those_of_the_literal() -> None:
    assert OUTCOMES == get_args(DocumentOutcome)
    assert OUTCOMES[:2] == get_args(VoteOutcome) == ("aangenomen", "verworpen")


def test_vote_outcome() -> None:
    assert vote_outcome(True) == "aangenomen"
    assert vote_outcome(False) == "verworpen"
    assert vote_outcome(None) is None
    assert vote_outcome(1) is None


def test_a_decision_that_is_no_vote_says_its_kind() -> None:
    assert DECISION_KIND_WITHDRAWN == "Stemmen - ingetrokken"
    assert decision_outcome(None, DECISION_KIND_WITHDRAWN, None) == "ingetrokken"
    assert decision_outcome(None, "Stemmen - aangehouden", None) == "aangehouden"
    assert decision_outcome(None, None, "Vervallen") == "vervallen"
    assert decision_outcome(None, "Stemmen - uitstellen", None) is None
    assert decision_outcome(True, DECISION_KIND_WITHDRAWN, None) == "aangenomen"


@pytest.mark.parametrize(
    ("value", "due"),
    [
        (NO_DUE_DATE, None),
        ("0001-01-01", None),
        (None, None),
        ("", None),
        ("2026-12-01", "2026-12-01"),
    ],
)
def test_due_date(value: str | None, due: str | None) -> None:
    assert due_date(value) == due


@pytest.mark.parametrize(
    ("model", "field", "words"),
    [
        (CoalitionFactionDTO, "choice", get_args(VoteChoice)),
        (FeedVoteDTO, "outcome", get_args(VoteOutcome)),
        (PaperOutcomeFields, "outcome", OUTCOMES),
    ],
)
def test_the_api_answers_the_words_of_core(
    model: type[BaseModel], field: str, words: tuple
) -> None:
    assert _words(model.model_fields[field].annotation) == set(words)


def _words(annotation: object) -> set[str]:
    """The strings a (possibly optional, possibly nested) ``Literal`` allows."""
    found: set[str] = set()
    for arg in get_args(annotation):
        if isinstance(arg, str):
            found.add(arg)
        else:
            found |= _words(arg)
    return found
