"""The news feed without a database: its cursor, the roles of its people, the AQL and bind
variables it builds, and the items and Atom document made of its rows."""

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
    DOCUMENT_KINDS,
    FEED_KINDS,
    FeedCursor,
    person_role,
)
from lawgraph.db.queries.feed import _SOURCES, FeedFilters, feed_query, summary_query


def test_a_cursor_survives_its_token() -> None:
    cursor = FeedCursor(date="2026-05-01", kind="motie", id="documents/motion_005")
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
        ("Eerste ondertekenaar", "kamerlid", "motie", "indiener"),
        ("Mede ondertekenaar", "kamerlid", "motie", "medeindiener"),
        ("Eerste ondertekenaar", "bewindspersoon", "brief_regering", "bewindspersoon"),
        ("Mede namens", "bewindspersoon", "toezegging", "bewindspersoon"),
        # a bill and a note of change are submitted by who signs them
        ("Eerste ondertekenaar", "bewindspersoon", "wetsvoorstel", "indiener"),
        ("Mede namens", "bewindspersoon", "nota_van_wijziging", "medeindiener"),
        ("Eerste ondertekenaar", "overig", "wetsvoorstel", None),
        (None, None, None, None),
    ],
)
def test_a_signature_has_its_role(
    role: str | None, capacity: str | None, kind: str | None, expected: str | None
) -> None:
    assert person_role(role, capacity, kind) == expected


def test_a_day_orders_its_kinds() -> None:
    assert DAY_ORDER[:3] == ("wetsvoorstel", "stemming", "toezegging")
    assert set(DAY_ORDER) == set(FEED_KINDS)


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
@pytest.mark.parametrize(
    "cursor", [None, FeedCursor("2026-05-01", "motie", "documents/x")]
)
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


def test_a_kind_reads_the_cursor_s_day_by_its_rank() -> None:
    cursor = FeedCursor("2026-05-01", "toezegging", "commitments/c1")
    aql, bind = feed_query(FeedFilters(), cursor=cursor, facets=False)
    rows = {
        block.split('kind: "')[1].split('"')[0]: block
        for block in aql.split("LET rows_")[1:]
    }
    assert "== @cursor_date ? false : true" in rows["wetsvoorstel"]
    assert "== @cursor_date ? n._id > @cursor_id : true" in rows["toezegging"]
    assert "== @cursor_date ? true : true" in rows["motie"]
    assert "cursor_rank" not in bind  # only the page with facets reads it
    _, bind = feed_query(FeedFilters(), cursor=cursor, facets=True)
    assert bind["cursor_rank"] == 2


def test_a_cursor_reads_nothing_after_its_day_from_the_index() -> None:
    _, bind = feed_query(
        FeedFilters(until="2026-12-31"),
        cursor=FeedCursor("2026-05-01", "motie", "documents/x"),
        facets=False,
    )
    assert bind["until"] == "2026-05-01"
    _, bind = feed_query(
        FeedFilters(until="2026-12-31"),
        cursor=FeedCursor("2026-05-01", "motie", "documents/x"),
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
            "member_key": "22222222_2222_2222_2222_222222222222",
            "member_name": "Bram Bakker",
            "name": "B. Bakker",
            "role": "Eerste ondertekenaar",
            "capacity": "kamerlid",
            "faction_id": "f-d66",
            "faction": {"key": "d66", "short": "D66"},
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
    assert item.subkind == "motie"
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
            "faction": {"key": "d66", "short": "D66"},
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
                "status": "rumoured",
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
    assert item.commitment.model_dump() == {"status": None, "expected_resolution": None}
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
            "kind": "wetsvoorstel",
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
        kinds=("motie", "stemming"), dossier="36600", ministry="fin", faction="d66"
    )
    page = FeedResponse(items=[FeedItemDTO.from_row(VOTE_ROW)])
    assert feed_title(filters, page) == (
        "Concordans: moties en stemmingen, dossier 36600, Financiën, D66"
    )
    assert feed_title(FeedFilters(), page) == "Concordans"
    assert site_query(filters) == {
        "soort": "motie,stemming",
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


@pytest.mark.parametrize(
    "filters",
    [
        FeedFilters(since="2026-05-01", until="2026-05-03"),
        FeedFilters(since="2026-05-01", until="2026-05-03", kinds=("motie",), q="x"),
        FeedFilters(since="2026-05-01", until="2026-05-03", member="m1", cabinet="c"),
    ],
)
def test_a_summary_binds_what_it_reads(filters: FeedFilters) -> None:
    aql, bind = summary_query(filters, margin=7, limit=20)
    assert _bind_names(aql) == set(bind)
    assert (bind["margin"], bind["page_size"]) == (7, 21)


def test_a_summary_has_every_day_of_its_window() -> None:
    summary = FeedSummaryResponse.from_raw(
        {
            "days": [
                {
                    "date": "2026-05-02",
                    "total": 1,
                    "kinds": [],
                    "votes": [{"subkind": "wetsvoorstel", "passed": False, "count": 1}],
                    "dossiers": [{"number": "36600-VII", "count": 1}],
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
