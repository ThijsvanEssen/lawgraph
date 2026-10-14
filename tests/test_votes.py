"""The choice of a vote and the outcome of a decision, written once (``core/votes.py``)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from lawgraph.api.schemas.decisions import CoalitionFactionDTO
from lawgraph.api.schemas.documents import PaperOutcomeFields
from lawgraph.api.schemas.feed import FeedVoteDTO
from lawgraph.core.tk_records import NO_DUE_DATE, due_date
from lawgraph.core.votes import (
    DECISION_KIND_WITHDRAWN,
    OUTCOMES,
    PaperOutcome,
    VoteChoice,
    VoteOutcome,
    decision_outcome,
    vote_outcome,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "lawgraph"


def test_the_outcomes_are_those_of_the_literal() -> None:
    assert OUTCOMES == get_args(PaperOutcome)
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
    model: type, field: str, words: tuple
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


# A vote choice or an outcome of a decision written out instead of named from core.votes.
_SPELLED_OUT = re.compile(
    r"""["'](?:aangenomen|verworpen|ingetrokken|aangehouden|vervangen|Voor|Tegen|"""
    r"""Aantekening gevraagd|Stemmen - [a-z ]+)["']"""
)
# Their own vocabularies: a judgment is also ``verworpen`` (``core/judgment_outcome.py``).
_OWN = {"core/votes.py", "core/judgment_outcome.py"}
# A Literal cannot name a constant: the one outcome a pending amendment can have.
_LITERAL = 'outcome: Literal["aangenomen"] | None = Field('


def test_no_vote_word_spelled_out() -> None:
    found = [
        f"{path.relative_to(SRC)}:{number}: {line.strip()}"
        for path in sorted(SRC.rglob("*.py"))
        if str(path.relative_to(SRC)) not in _OWN
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _SPELLED_OUT.search(line) and "``" not in line and _LITERAL not in line
    ]
    assert found == []
