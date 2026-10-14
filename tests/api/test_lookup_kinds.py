"""``GET /api/lookup`` without a database: each kind has its finder, and the kind of an
answer is the type of its collection."""

from __future__ import annotations

from typing import get_args

import pytest

from lawgraph.api.routes.lookup import FINDERS
from lawgraph.api.schemas.lookup import LookupKind
from lawgraph.api.schemas.nodes import node_type_of


def test_every_kind_has_a_finder() -> None:
    assert set(FINDERS) == set(get_args(LookupKind))


@pytest.mark.parametrize(
    ("collection", "kind"),
    [
        ("documents", "document"),
        ("dossiers", "dossier"),
        ("articles", "article"),
        ("annexes", "annex"),
        ("cases", "case"),
        ("activities", "activity"),
        ("instruments", "instrument"),
        ("judgments", "judgment"),
        ("commitments", "commitment"),
        ("factions", "faction"),
        ("committees", "committee"),
        ("cabinets", "cabinet"),
        ("members", "member"),
    ],
)
def test_the_kind_of_an_answer_is_the_type_of_its_collection(
    collection: str, kind: str
) -> None:
    assert node_type_of(collection) == kind
