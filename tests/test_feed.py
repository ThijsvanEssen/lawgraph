"""The news feed without a database: its cursor, the roles of its people, and the items and
Atom document made of its rows. What the queries read is in tests/integration/test_feed.py."""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
from xml.etree import ElementTree

import pytest

from lawgraph.api.routes.feed import feed_title, site_query
from lawgraph.api.schemas.feed import (
    FeedItemDTO,
    FeedResponse,
    FeedSummaryResponse,
    _subject,
    _surname,
    atom_feed,
)
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.feed import (
    DAY_ORDER,
    DOCUMENT_EVENTS,
    FEED_KINDS,
    FeedCursor,
    person_role,
)
from lawgraph.db.queries.feed import _SOURCES, FeedFilters


def test_a_cursor_survives_its_token() -> None:
    cursor = FeedCursor(date="2026-05-01", kind="Motie", id="documents/motion_005")
    token = cursor.encode()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert FeedCursor.decode(token) == cursor


def _token(value: object) -> str:
    raw = json.dumps(value).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize(
    "token",
    [
        "nonsense!",
        "e30",
        "",
        _token(["2026-05-01", "documents/x"]),  # no kind
        _token(["2026-05-01", "roddel", "documents/x"]),
    ],
)
def test_a_token_this_api_did_not_hand_out_is_refused(token: str) -> None:
    with pytest.raises(ValueError, match="not a feed cursor"):
        FeedCursor.decode(token)


@pytest.mark.parametrize(
    ("role", "capacity", "kind", "expected"),
    [
        ("Eerste ondertekenaar", "kamerlid", "Motie", "indiener"),
        ("Mede ondertekenaar", "kamerlid", "Motie", "medeindiener"),
        ("Eerste ondertekenaar", "bewindspersoon", "Brief regering", "bewindspersoon"),
        ("Mede namens", "bewindspersoon", "toezegging", "bewindspersoon"),
        # a bill and a note of change are submitted by who signs them
        ("Eerste ondertekenaar", "bewindspersoon", "Voorstel van wet", "indiener"),
        ("Mede namens", "bewindspersoon", "Nota van wijziging", "medeindiener"),
        ("Eerste ondertekenaar", "overig", "Voorstel van wet", None),
        (None, None, None, None),
    ],
)
def test_a_signature_has_its_role(
    role: str | None, capacity: str | None, kind: str | None, expected: str | None
) -> None:
    assert person_role(role, capacity, kind) == expected


def test_a_day_orders_its_kinds() -> None:
    assert DAY_ORDER[:3] == ("Voorstel van wet", "stemming", "toezegging")
    assert set(DAY_ORDER) == set(FEED_KINDS)


def test_every_kind_is_read_from_a_source() -> None:
    assert set(_SOURCES) == set(FEED_KINDS)
    assert set(DOCUMENT_EVENTS) < set(FEED_KINDS)


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
        "kind": "Motie",
    },
    "text": None,
    "persons": [
        {
            "person_id": "22222222-2222-2222-2222-222222222222",
            "member_key": "22222222_2222_2222_2222_222222222222",
            "member_name": "Bram Bakker",
            "name": "B. Bakker",
            "role": "Eerste ondertekenaar",
            "capacity": "kamerlid",
            "faction_id": "f-d66",
            "faction": {"key": "d66", "short": "D66", "path": "/fracties/d66"},
        },
        {"name": "griffier", "role": "Mede ondertekenaar", "capacity": "overig"},
    ],
    "instrument": None,
    "changed_articles": 0,
    "changed_instruments": [],
}


def test_a_vote_is_an_item() -> None:
    item = FeedItemDTO.from_row(VOTE_ROW)
    assert item.title == "Motie van het lid Bakker"
    assert item.summary == "Verworpen."
    assert item.subkind == "Motie"
    assert item.node.model_dump() == {"collection": "decisions", "key": "stemming_1"}
    assert item.vote is not None
    assert (item.vote.passed, item.vote.outcome) == (False, "verworpen")
    assert [p.model_dump() for p in item.persons] == [
        {
            "key": "22222222_2222_2222_2222_222222222222",
            "name": "Bram Bakker",
            "surname": "Bakker",
            "function": None,
            "role": "indiener",
            "faction": {"key": "d66", "short": "D66", "path": "/fracties/d66"},
            # no slug in the row: no address
            "path": None,
        }
    ]
    assert item.dossier is not None and item.dossier.short_title is None
    assert item.commitment is None and item.publication is None
    assert item.tk_url is None and item.official_url is None


def test_a_vote_has_the_parts_of_its_headline() -> None:
    item = FeedItemDTO.from_row(VOTE_ROW)
    assert item.headline.model_dump() == {
        "surname": "Bakker",
        "subject": None,
        "short_title": None,
    }


@pytest.mark.parametrize(
    ("title", "subject"),
    [
        ("Motie van het lid Van der Plas over de mestregels", "de mestregels"),
        ("Gewijzigde motie van de leden A en B over X over Y", "X over Y"),
        ("Brief over", None),
        ("Stand van zaken gemeentefonds", None),
        (None, None),
    ],
)
def test_the_subject_is_what_comes_after_over(
    title: str | None, subject: str | None
) -> None:
    assert _subject(title) == subject


@pytest.mark.parametrize(
    ("signature", "surname"),
    [
        ({"name": "C.A.M. van der Plas"}, "van der Plas"),
        ({"name": "Th.J.A.M. de Bruijn"}, "de Bruijn"),
        ({"name": "Vijlbrief, J.A.", "member_name": "Hans Vijlbrief"}, "Vijlbrief"),
        ({"name": None, "member_name": "Hanneke Steen"}, "Steen"),
        ({"name": None, "member_name": None}, None),
    ],
)
def test_a_surname_keeps_its_prefix(signature: dict, surname: str | None) -> None:
    assert _surname(signature) == surname


def test_a_commitment_without_a_due_date_says_none() -> None:
    item = FeedItemDTO.from_row(
        {
            "kind": "toezegging",
            "id": "commitments/c1",
            "date": "2026-09-22",
            "props": {
                "display_name": "De minister…",
                "status": "Openstaand",
                "expected_resolution": "0001-01-01",
            },
            "text": "De minister stuurt een brief.",
            "persons": [
                {
                    "member_key": "m1",
                    "member_name": "Hans Vijlbrief",
                    "name": "Vijlbrief, J.A.",
                    "function": "Minister van Sociale Zaken en Werkgelegenheid",
                    "role": "Eerste ondertekenaar",
                    "capacity": "bewindspersoon",
                }
            ],
        }
    )
    assert item.commitment is not None
    assert item.commitment.model_dump() == {
        "status": "Openstaand",
        "expected_resolution": None,
    }
    assert [(p.key, p.name, p.surname, p.function, p.role) for p in item.persons] == [
        (
            "m1",
            "Hans Vijlbrief",
            "Vijlbrief",
            "Minister van Sociale Zaken en Werkgelegenheid",
            "bewindspersoon",
        )
    ]


def test_a_bill_is_named_by_its_dossier() -> None:
    item = FeedItemDTO.from_row(
        {
            "kind": "Voorstel van wet",
            "id": "documents/b1",
            "date": "2026-09-15",
            "dossier": {
                "key": "37035_xv",
                "number": "37035-XV",
                "title": "Wijziging van de begrotingsstaten van het Ministerie van Sociale "
                "Zaken en Werkgelegenheid (XV) voor het jaar 2026 (wijziging "
                "samenhangende met de Miljoenennota)",
            },
            "props": {"kind": "Voorstel van wet", "title": "Voorstel van wet "},
        }
    )
    assert item.title is not None and item.title.startswith(
        "Wijziging van de begroting"
    )
    assert item.dossier is not None
    assert item.dossier.short_title == (
        "Suppletoire begroting Sociale Zaken en Werkgelegenheid 2026 (Miljoenennota)"
    )


def test_a_paper_has_its_number_and_a_vote_none() -> None:
    letter = FeedItemDTO.from_row(
        {
            "kind": "Brief regering",
            "id": "documents/l1",
            "date": "2026-09-15",
            "props": {
                "kind": "Brief regering",
                "title": "Brief over de huurwet",
                "sequence": 12,
            },
        }
    )
    assert letter.number == "12"
    assert FeedItemDTO.from_row(VOTE_ROW).number is None


def test_a_page_is_an_atom_feed() -> None:
    page = FeedResponse(items=[FeedItemDTO.from_row(VOTE_ROW)], next_cursor="abc")
    body = atom_feed(
        page,
        title="Concordans: stemmingen",
        self_url="http://x/api/feed.atom?kind=stemming",
        next_url="http://x/api/feed.atom?kind=stemming&cursor=abc",
        page_url="https://site/actueel?soort=stemming",
        site_url="https://site",
    )
    root = ElementTree.fromstring(body)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    assert root.find("a:title", ns).text == "Concordans: stemmingen"  # type: ignore[union-attr]
    assert root.find("a:updated", ns).text == "2026-05-12T00:00:00Z"  # type: ignore[union-attr]
    links = {link.get("rel"): link.get("href") for link in root.findall("a:link", ns)}
    assert links["next"].endswith("cursor=abc")
    assert links["alternate"] == "https://site/actueel?soort=stemming"
    entry = root.find("a:entry", ns)
    assert entry is not None
    assert entry.find("a:title", ns).text == "Motie van het lid Bakker"  # type: ignore[union-attr]
    entry_links = {
        link.get("rel"): link.get("href") for link in entry.findall("a:link", ns)
    }
    assert entry_links == {
        "alternate": "https://site/explore?focus=decisions/stemming_1"
    }
    assert entry.find("a:category", ns).get("term") == "stemming"  # type: ignore[union-attr]
    assert entry.find("a:summary", ns).text == "Verworpen.\n37001-VII Begroting"  # type: ignore[union-attr]


def test_the_feed_title_and_page_say_the_filters() -> None:
    filters = FeedFilters(
        kinds=("Motie", "stemming"), dossier="36600", ministry="fin", faction="d66"
    )
    page = FeedResponse(items=[FeedItemDTO.from_row(VOTE_ROW)])
    assert feed_title(filters, page) == (
        "Concordans: moties en stemmingen, dossier 36600, Financiën, D66"
    )
    assert feed_title(FeedFilters(), page) == "Concordans"
    assert site_query(filters) == {
        "soort": "Motie,stemming",
        "ministerie": "fin",
        "dossier": "36600",
        "fractie": "d66",
    }


@pytest.mark.parametrize(
    ("title", "short"),
    [
        (
            "Vaststelling van de begrotingsstaten van het Ministerie van Defensie (X) voor "
            "het jaar 2027",
            "Begroting Defensie 2027",
        ),
        (
            "Wijziging van de begrotingsstaat van het gemeentefonds voor het jaar 2026 "
            "(wijziging samenhangende met de Voorjaarsnota)",
            "Suppletoire begroting gemeentefonds 2026 (Voorjaarsnota)",
        ),
        (
            "Vaststelling van de begrotingsstaten van Koninkrijksrelaties (IV) en het "
            "BES-fonds (H) voor het jaar 2027",
            "Begroting Koninkrijksrelaties 2027",
        ),
        (
            "Jaarverslag en slotwet Ministerie van Defensie 2025 ",
            "Slotwet Defensie 2025",
        ),
        ("Wijziging van de Wet X (Wet beter voorbeeld)", "Wet beter voorbeeld"),
        ("Toekomst pensioenstelsel", None),
        (None, None),
    ],
)
def test_a_dossier_has_the_short_title_it_goes_by(
    title: str | None, short: str | None
) -> None:
    assert short_title(title) == short


def test_a_summary_has_every_day_of_its_window() -> None:
    summary = FeedSummaryResponse.from_raw(
        {
            "days": [
                {
                    "date": "2026-05-02",
                    "total": 1,
                    "kinds": [],
                    "votes": [{"subkind": "Wetgeving", "passed": False, "count": 1}],
                    "dossiers": [{"kind": "Motie", "number": "36600-VII", "count": 1}],
                }
            ],
            "dossiers": [
                {"number": "36600-VII", "key": "36600_vii", "title": "T (Wet x)"}
            ],
            "items": [VOTE_ROW, VOTE_ROW],
        },
        since=dt.date(2026, 5, 1),
        until=dt.date(2026, 5, 3),
        margin=10,
        limit=1,
    )
    assert [d.date for d in summary.days] == ["2026-05-03", "2026-05-02", "2026-05-01"]
    assert summary.days[1].votes[0].outcome == "verworpen"
    assert summary.days[1].dossiers[0].short_title == "Wet x"
    assert len(summary.items) == 1 and summary.items_truncated


def test_a_person_the_paper_lists_twice_is_one_person() -> None:
    """Heerma signs a letter as first and as co-signatory with one function."""
    heerma = {
        "person_id": "cf4c4d24-798d-4bbe-bf06-23ca674f0d28",
        "member_key": "cf4c4d24_798d_4bbe_bf06_23ca674f0d28",
        "member_name": "Pieter Heerma",
        "name": "P.E. Heerma",
        "function": "minister van Binnenlandse Zaken en Koninkrijksrelaties",
        "capacity": "bewindspersoon",
    }
    row = {
        **VOTE_ROW,
        "persons": [
            {**heerma, "role": "Eerste ondertekenaar"},
            {**heerma, "role": "Mede ondertekenaar"},
        ],
    }
    item = FeedItemDTO.from_row(row)
    assert [p.key for p in item.persons] == ["cf4c4d24_798d_4bbe_bf06_23ca674f0d28"]


def test_a_vote_says_how_it_was_decided_as_the_kamer_writes_it() -> None:
    hamer = FeedItemDTO.from_row(
        {
            **VOTE_ROW,
            "props": {
                **VOTE_ROW["props"],
                "decision_kind": "Stemmen - zonder stemming aannemen",
                "vote_kind": None,
                "tally": {},
            },
        }
    )
    assert hamer.vote is not None
    assert hamer.vote.decision_kind == "Stemmen - zonder stemming aannemen"
    assert hamer.vote.method is None
    ek = FeedItemDTO.from_row(
        {
            **VOTE_ROW,
            "props": {
                **VOTE_ROW["props"],
                "chamber": "EK",
                "method": "Stemming bij zitten en opstaan, aangenomen",
            },
        }
    )
    assert ek.vote is not None
    assert ek.vote.method == "Stemming bij zitten en opstaan, aangenomen"
