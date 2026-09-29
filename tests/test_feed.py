"""The news feed without a database: its cursor, the roles of its people, the AQL and bind
variables it builds, and the items and Atom document made of its rows."""

from __future__ import annotations

import re
from xml.etree import ElementTree

import pytest

from lawgraph.api.schemas.feed import FeedItemDTO, FeedResponse, atom_feed
from lawgraph.core.feed import (
    DOCUMENT_KINDS,
    FEED_KINDS,
    FeedCursor,
    person_role,
)
from lawgraph.db.queries.feed import _SOURCES, FeedFilters, feed_query


def test_a_cursor_survives_its_token() -> None:
    cursor = FeedCursor(date="2026-05-01", id="documents/motion_005")
    token = cursor.encode()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert FeedCursor.decode(token) == cursor


@pytest.mark.parametrize("token", ["nonsense!", "WyIyMDI2Il0", "e30", ""])
def test_a_token_this_api_did_not_hand_out_is_refused(token: str) -> None:
    with pytest.raises(ValueError, match="not a feed cursor"):
        FeedCursor.decode(token)


@pytest.mark.parametrize(
    ("role", "capacity", "expected"),
    [
        ("Eerste ondertekenaar", "kamerlid", "indiener"),
        ("Mede ondertekenaar", "kamerlid", "medeindiener"),
        ("Eerste ondertekenaar", "bewindspersoon", "bewindspersoon"),
        ("Mede namens", "bewindspersoon", "bewindspersoon"),
        ("Eerste ondertekenaar", "overig", None),
        (None, None, None),
    ],
)
def test_a_signature_has_its_role(
    role: str | None, capacity: str | None, expected: str | None
) -> None:
    assert person_role(role, capacity) == expected


def test_every_kind_is_read_from_a_source() -> None:
    assert set(_SOURCES) == set(FEED_KINDS)
    assert set(DOCUMENT_KINDS) < set(FEED_KINDS)


def _bind_names(aql: str) -> set[str]:
    return set(re.findall(r"(?<![@\w])@(\w+)", aql))


@pytest.mark.parametrize(
    "filters",
    [
        FeedFilters(),
        FeedFilters(
            kinds=("motie", "stemming"), since="2026-01-01", until="2026-12-31"
        ),
        FeedFilters(cabinet="jetten", ministry="fin", faction="vvd"),
        FeedFilters(dossier="36600", member="m1", q="Pensioen "),
    ],
)
@pytest.mark.parametrize("facets", [True, False])
@pytest.mark.parametrize("cursor", [None, FeedCursor("2026-05-01", "documents/x")])
def test_every_bind_variable_is_used_and_every_used_one_is_bound(
    filters: FeedFilters, facets: bool, cursor: FeedCursor | None
) -> None:
    """ArangoDB refuses a query with a bind variable it does not use."""
    aql, bind = feed_query(filters, cursor=cursor, limit=20, facets=facets)
    assert _bind_names(aql) == set(bind)
    assert bind["page_size"] == 21


def test_without_facets_only_the_kinds_asked_for_are_read() -> None:
    aql, bind = feed_query(FeedFilters(kinds=("motie",)), facets=False)
    assert aql.count("LET rows_") == 1
    assert "kinds" not in bind
    assert "facets = null" in aql


def test_the_facets_count_every_kind() -> None:
    aql, bind = feed_query(FeedFilters(kinds=("motie",)), facets=True)
    assert aql.count("LET rows_") == len(FEED_KINDS)
    assert bind["kinds"] == ["motie"]
    for name in ("kind", "ministry", "faction", "cabinet"):
        assert f"{name}: (" in aql


def test_a_member_or_faction_leaves_out_the_kinds_nobody_signs() -> None:
    by_member, _ = feed_query(FeedFilters(member="m1"), facets=True)
    assert by_member.count("LET rows_") == len(FEED_KINDS) - 2
    by_faction, _ = feed_query(FeedFilters(faction="vvd"), facets=True)
    # nor a commitment: a bewindspersoon signs for no faction
    assert by_faction.count("LET rows_") == len(FEED_KINDS) - 3


def test_a_page_without_filters_is_cut_before_anything_is_looked_up() -> None:
    aql, _ = feed_query(FeedFilters(), facets=False)
    rows = aql.split("LET rows_1 = (")[1].split("LET rows_2")[0]
    assert rows.index("LIMIT @page_size") < rows.index("LET labels")
    filtered, _ = feed_query(FeedFilters(ministry="fin"), facets=False)
    rows = filtered.split("LET rows_1 = (")[1].split("LET rows_2")[0]
    assert rows.index("LET labels") < rows.index("LIMIT @page_size")


def test_a_cursor_reads_nothing_after_its_day_from_the_index() -> None:
    _, bind = feed_query(
        FeedFilters(until="2026-12-31"),
        cursor=FeedCursor("2026-05-01", "documents/x"),
        facets=False,
    )
    assert bind["until"] == "2026-05-01"
    _, bind = feed_query(
        FeedFilters(until="2026-12-31"),
        cursor=FeedCursor("2026-05-01", "documents/x"),
        facets=True,
    )
    assert bind["until"] == "2026-12-31"


def test_q_is_lower_case_words() -> None:
    _, bind = feed_query(FeedFilters(q="  Pensioen "))
    assert bind["q"] == "pensioen"


VOTE_ROW = {
    "kind": "stemming",
    "id": "decisions/stemming_1",
    "date": "2026-05-12",
    "ministry": "bzk",
    "cabinet": "jetten",
    "dossier": {"key": "37001_vii", "number": "37001-VII", "title": "Begroting"},
    "props": {
        "subject": "Motie van het lid Bakker",
        "decision_text": "Verworpen.",
        "passed": False,
        "tally": {"Voor": 70, "Tegen": 80},
        "vote_kind": "faction",
        "kind": "motie",
    },
    "text": None,
    "persons": [
        {
            "person_id": "22222222-2222-2222-2222-222222222222",
            "name": "B. Bakker",
            "role": "Eerste ondertekenaar",
            "capacity": "kamerlid",
            "faction_id": "f-d66",
            "faction": {"key": "d66", "short": "D66"},
        },
        {"name": "griffier", "role": "Mede ondertekenaar", "capacity": "overig"},
    ],
    "member": None,
    "instrument": None,
    "changed_articles": 0,
    "changed_instruments": [],
}


def test_a_vote_is_an_item() -> None:
    item = FeedItemDTO.from_row(VOTE_ROW)
    assert item.title == "Motie van het lid Bakker"
    assert item.summary == "Verworpen."
    assert item.subkind == "motie"
    assert item.node.model_dump() == {"collection": "decisions", "key": "stemming_1"}
    assert item.vote is not None
    assert (item.vote.passed, item.vote.outcome) == (False, "verworpen")
    assert [p.model_dump() for p in item.persons] == [
        {
            "key": "22222222_2222_2222_2222_222222222222",
            "name": "B. Bakker",
            "role": "indiener",
            "faction": {"key": "d66", "short": "D66"},
        }
    ]
    assert item.dossier is not None and item.dossier.short_title is None
    assert item.commitment is None and item.publication is None
    assert item.tk_url is None and item.official_url is None


def test_a_commitment_without_a_due_date_says_none() -> None:
    item = FeedItemDTO.from_row(
        {
            "kind": "toezegging",
            "id": "commitments/c1",
            "date": "2026-09-22",
            "props": {
                "display_name": "De minister…",
                "status": "rumoured",
                "expected_resolution": "0001-01-01",
            },
            "text": "De minister stuurt een brief.",
            "persons": [
                {
                    "member_key": "m1",
                    "name": "Vijlbrief, J.A.",
                    "role": "Eerste ondertekenaar",
                    "capacity": "bewindspersoon",
                }
            ],
            "member": {"key": "m1", "name": "Hans Vijlbrief"},
        }
    )
    assert item.commitment is not None
    assert item.commitment.model_dump() == {"status": None, "expected_resolution": None}
    assert [(p.key, p.name, p.role) for p in item.persons] == [
        ("m1", "Hans Vijlbrief", "bewindspersoon")
    ]


def test_a_page_is_an_atom_feed() -> None:
    page = FeedResponse(items=[FeedItemDTO.from_row(VOTE_ROW)], next_cursor="abc")
    body = atom_feed(
        page,
        self_url="http://x/api/feed.atom?kind=stemming",
        next_url="http://x/api/feed.atom?kind=stemming&cursor=abc",
        node_url="http://x/api/nodes/{collection}/{key}",
    )
    root = ElementTree.fromstring(body)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    assert root.find("a:updated", ns).text == "2026-05-12T00:00:00Z"  # type: ignore[union-attr]
    links = {link.get("rel"): link.get("href") for link in root.findall("a:link", ns)}
    assert links["next"].endswith("cursor=abc")
    entry = root.find("a:entry", ns)
    assert entry is not None
    assert entry.find("a:title", ns).text == "Motie van het lid Bakker"  # type: ignore[union-attr]
    assert entry.find("a:link", ns).get("href") == (  # type: ignore[union-attr]
        "http://x/api/nodes/decisions/stemming_1"
    )
    assert entry.find("a:category", ns).get("term") == "stemming"  # type: ignore[union-attr]
    assert entry.find("a:summary", ns).text == "Verworpen.\n37001-VII Begroting"  # type: ignore[union-attr]
