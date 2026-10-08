"""Search and resolve on a real PostgreSQL: the hits ArangoSearch gave, in the same shape."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import resolve as resolve_queries
from lawgraph.db.queries import search as search_queries


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "bwbr0001854",
                "instrument",
                bwb_id="BWBR0001854",
                title="Wetboek van Strafrecht",
                citation_title="Wetboek van Strafrecht",
                short_title="Sr",
                aliases=["WvSr", "Sr"],
            ),
            _node(
                "bwbr0001903",
                "instrument",
                bwb_id="BWBR0001903",
                title="Wetboek van Strafvordering",
                citation_title="Wetboek van Strafvordering",
                short_title="Sv",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                "bwbr0001854_1",
                "article",
                bwb_id="BWBR0001854",
                article_number="1",
                display_name="Artikel 1 Wetboek van Strafrecht",
                text="Geen feit is strafbaar dan uit kracht van een daaraan voorafgegane "
                "wettelijke strafbepaling.",
                breadcrumb=[{"title": "Algemene bepalingen"}, {"label": "x"}],
                inbound_citation_count=5,
            ),
            _node(
                "bwbr0001903_1",
                "article",
                bwb_id="BWBR0001903",
                article_number="1",
                display_name="Artikel 1 Wetboek van Strafvordering",
                text="Strafvordering heeft alleen plaats op de wijze bij de wet voorzien.",
                inbound_citation_count=9,
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "ecli_nl_hr_1919_1",
                "judgment",
                ecli="ECLI:NL:HR:1919:1",
                display_name="Hoge Raad 1919 Lindenbaum/Cohen",
                names=["Lindenbaum/Cohen"],
                summary="Onrechtmatige daad.",
                date_eff="1919-01-31",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node(
                "m1",
                "member",
                name="Jan de Vries",
                party="VVD",
                active=True,
                faction_memberships=[{"abbreviation": "VVD", "name": "Volkspartij"}],
            ),
            _node("m2", "member", name="Piet de Vries", party="CDA", active=False),
        ],
    )
    return store


def _ids(hits: list[dict[str, Any]]) -> list[str]:
    return [h["id"] for h in hits]


def test_words_match_by_stem_prefix_identifier_or_part(graph: GraphStore) -> None:
    search = search_queries.search_all
    # stems: "strafbaar" and "strafbepaling" are words of the text
    assert _ids(search(graph, q="strafbaar", types=["articles"])["articles"]) == [
        "articles/bwbr0001854_1"
    ]
    # a part of a title of 3 to 12 characters, folded: "vordering" in "Strafvordering"
    assert _ids(search(graph, q="vordering", types=["instruments"])["instruments"]) == [
        "instruments/bwbr0001903"
    ]
    # an identifier in any case
    assert _ids(
        search(graph, q="bwbr0001854", types=["instruments"])["instruments"]
    ) == ["instruments/bwbr0001854"]
    # every word must match
    assert search(graph, q="strafbaar vordering", types=["articles"])["articles"] == []


def test_a_hit_has_the_shape_of_before(graph: GraphStore) -> None:
    hits = search_queries.search_all(graph, q="strafbaar", types=["articles"])[
        "articles"
    ]
    assert hits == [
        {
            "id": "articles/bwbr0001854_1",
            "key": "bwbr0001854_1",
            "collection": "articles",
            "type": "article",
            "display_name": "Artikel 1 Wetboek van Strafrecht",
            "snippet": "Geen feit is strafbaar dan uit kracht van een daaraan voorafgegane "
            "wettelijke strafbepaling.",
            "extra": {
                "bwb_id": "BWBR0001854",
                "celex": None,
                "article_number": "1",
                "heading": None,
                "division_titles": ["Algemene bepalingen"],
                "instrument_title": "Wetboek van Strafrecht",
                "citation_title": "Wetboek van Strafrecht",
                "short_title": "Sr",
            },
            "score": search_queries.SCORE_WORDS,
        }
    ]


def test_a_name_an_alias_and_an_ecli(graph: GraphStore) -> None:
    found = search_queries.search_all(graph, q="Lindenbaum/Cohen", types=["judgments"])
    assert _ids(found["judgments"]) == ["judgments/ecli_nl_hr_1919_1"]
    assert found["judgments"][0]["score"] == search_queries.SCORE_IDENTIFIER  # precise
    found = search_queries.search_all(graph, q="ECLI:NL:HR:1919:1", types=["judgments"])
    assert found["judgments"][0]["extra"] == {"ecli": "ECLI:NL:HR:1919:1"}
    found = search_queries.search_all(graph, q="wvsr", types=["instruments"])
    assert _ids(found["instruments"]) == ["instruments/bwbr0001854"]


def test_members_by_every_word_of_their_names(graph: GraphStore) -> None:
    found = search_queries.search_all(graph, q="de vries", types=["members"])["members"]
    assert _ids(found) == ["members/m1", "members/m2"]  # the active first
    found = search_queries.search_all(graph, q="volkspartij", types=["members"])[
        "members"
    ]
    assert _ids(found) == ["members/m1"]


def test_resolve_an_article_without_its_law(graph: GraphStore) -> None:
    answer = resolve_queries.resolve(graph, "art. 1")
    assert answer["kind"] == "article"
    # the most cited first
    assert [answer["match"]["id"], *(a["id"] for a in answer["alternatives"])] == [
        "articles/bwbr0001903_1",
        "articles/bwbr0001854_1",
    ]


def test_resolve_a_law_by_its_abbreviation(graph: GraphStore) -> None:
    answer = resolve_queries.resolve(graph, "Sr")
    assert answer["match"]["id"] == "instruments/bwbr0001854"
    assert answer["match"]["display_name"] == "Wetboek van Strafrecht"


def test_resolve_a_paper_of_a_dossier_directly_or_through_a_case(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("31746", "dossier", number="31746", title="Wet x")]
    )
    store.bulk_insert_or_update_nodes("cases", [_node("c1", "case")])
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node(
                "d11",
                "document",
                sequence=11,
                dossier_number="31746",
                title="Amendement",
            ),
            _node(
                "d12", "document", sequence=12, dossier_number="31746", title="Motie"
            ),
        ],
    )

    def part_of(key: str, source: str, target: str) -> dict[str, Any]:
        return {
            "_key": key,
            "_from": source,
            "_to": target,
            "relation": "PART_OF",
            "source": "test",
            "status": "canoniek",
            "confidence": None,
            "meta": {},
        }

    store.bulk_insert_or_update_edges(
        [
            part_of("p1", "documents/d11", "dossiers/31746"),
            part_of("p2", "cases/c1", "dossiers/31746"),
            part_of("p3", "documents/d12", "cases/c1"),
        ]
    )
    assert resolve_queries.resolve(store, "31746, nr. 11")["match"]["id"] == (
        "documents/d11"
    )
    # through the case
    assert resolve_queries.resolve(store, "31746, nr. 12")["match"]["id"] == (
        "documents/d12"
    )


def test_the_laws_are_read_once_per_data_version(
    graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parser of citations reads every instrument: once for every search until the
    data changes, not once a minute (``version_cache``)."""
    reads: list[int] = []
    names = search_queries._load_law_names

    def counted(store: GraphStore) -> dict[str, list[str]]:
        reads.append(1)
        return names(store)

    monkeypatch.setattr(search_queries, "_load_law_names", counted)
    first = search_queries.load_notation_parser(graph)
    assert search_queries.load_notation_parser(graph) is first
    assert reads == [1]

    graph.bulk_insert_or_update_nodes("instruments", [_node("x", "instrument")])
    assert search_queries.load_notation_parser(graph) is not first
    assert reads == [1, 1]


def _bw_article(book: str, number: str) -> dict[str, Any]:
    from lawgraph.core.code_families import CODE_FAMILIES

    law = CODE_FAMILIES["BW"][book]
    return _node(
        f"{law.lower()}_{number}",
        "article",
        bwb_id=law,
        article_number=number,
        display_name=f"Artikel {number} Burgerlijk Wetboek Boek {book}",
    )


def test_resolve_a_code_without_its_book_lists_its_books(store: GraphStore) -> None:
    """``artikel 3 BW``: no match, the article 3 of each book that has one, in the order of
    the books, and how many there are; one book with that article is the match."""
    from lawgraph.core.code_families import CODE_FAMILIES

    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _bw_article("6", "3"),
            _bw_article("1", "3"),
            _bw_article("3", "3"),
            _bw_article("6", "162"),
        ],
    )
    books = CODE_FAMILIES["BW"]
    answer = resolve_queries.resolve(store, "artikel 3 lid 2 BW")
    assert answer["match"] is None
    assert answer["kind"] == "article"
    assert answer["confidence"] <= resolve_queries.CONFIDENCE_AMBIGUOUS
    assert [a["key"] for a in answer["alternatives"]] == [
        f"{books[b].lower()}_3" for b in ("1", "3", "6")
    ]
    assert answer["alternatives_total"] == 3
    assert answer["qualifier"] == "lid 2"

    one = resolve_queries.resolve(store, "artikel 162 BW")
    assert one["match"]["key"] == f"{books['6'].lower()}_162"
    assert one["confidence"] == resolve_queries.CONFIDENCE_CITATION
    assert one["alternatives"] == [] and one["alternatives_total"] == 0

    for q in ("art. 6:162", "boek 6 art 162"):
        assert (
            resolve_queries.resolve(store, q)["match"]["key"]
            == f"{books['6'].lower()}_162"
        )


def test_resolve_a_number_without_law_lists_the_most_cited_first(
    store: GraphStore,
) -> None:
    """``art. 8:69``: Boek 8 BW article 69 and the Awb's own 8:69, the most cited first,
    whatever law it is; a choice, as neither is named."""
    from lawgraph.core.code_families import CODE_FAMILIES

    version_cache.clear()
    awb = _node(
        "bwbr0005537_8_69",
        "article",
        bwb_id="BWBR0005537",
        article_number="8:69",
        display_name="Artikel 8:69 Algemene wet bestuursrecht",
        inbound_citation_count=900,
    )
    store.bulk_insert_or_update_nodes("articles", [{**_bw_article("8", "69")}, awb])
    answer = resolve_queries.resolve(store, "art. 8:69")
    assert answer["match"] is None
    assert [a["key"] for a in answer["alternatives"]] == [
        "bwbr0005537_8_69",
        f"{CODE_FAMILIES['BW']['8'].lower()}_69",
    ]


def _live_judgments(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "ecli_nl_hr_2019_2007",
                "judgment",
                ecli="ECLI:NL:HR:2019:2007",
                display_name="Hoge Raad 2019-12-20 / 19/00135",
                names=["Urgenda"],
                summary="Klimaat.",
                inbound_citation_count=50,
            ),
            _node(
                "ecli_nl_rbams_2021_1",
                "judgment",
                ecli="ECLI:NL:RBAMS:2021:1",
                display_name="Rechtbank Amsterdam 2021-11-25 / 20/325",
                summary="Huurcommissie.",
                inbound_citation_count=1,
            ),
            _node(
                "ecli_nl_rbams_2021_2",
                "judgment",
                ecli="ECLI:NL:RBAMS:2021:2",
                display_name="Rechtbank Amsterdam 2021-12-01 / 21/1",
                summary="Huur.",
                inbound_citation_count=9,
            ),
        ],
    )


def test_a_live_search_finds_judgments_by_name_display_name_or_ecli(
    store: GraphStore,
) -> None:
    """While typing: no summary is ranked; a part of a name, of the display name (court,
    date, case number) or an ECLI, the most cited first."""
    version_cache.clear()
    _live_judgments(store)
    statements: list[str] = []
    query = store.query

    def recording(statement: Any, *args: Any, **kwargs: Any) -> Any:
        statements.append(" ".join(str(statement).split()))
        return query(statement, *args, **kwargs)

    store.query = recording  # type: ignore[method-assign]
    try:

        def live(q: str) -> list[str]:
            hits, partial = search_queries.search_live(store, q=q, types=["judgments"])
            assert partial == set()
            return [h["key"] for h in hits["judgments"]]

        assert live("urgen") == ["ecli_nl_hr_2019_2007"]
        assert live("rechtbank amsterdam") == [
            "ecli_nl_rbams_2021_2",
            "ecli_nl_rbams_2021_1",
        ]
        assert live("20/325") == ["ecli_nl_rbams_2021_1"]
        assert live("ECLI:NL:HR:2019:2007") == ["ecli_nl_hr_2019_2007"]
        assert live("hu") == []  # fewer than three characters
    finally:
        store.query = query  # type: ignore[method-assign]
    assert not any("AS rank" in s for s in statements)  # no BM25 while typing


def test_a_live_search_cuts_a_type_off_at_its_budget(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_cache.clear()
    _live_judgments(store)
    monkeypatch.setattr(search_queries, "LIVE_BUDGET", 0.0)
    hits, partial = search_queries.search_live(
        store, q="rechtbank", types=["judgments", "articles"]
    )
    assert partial == {"judgments", "articles"}
    assert hits == {"judgments": [], "articles": []}


def _live_names(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "bwbr0001854",
                "instrument",
                bwb_id="BWBR0001854",
                title="Wetboek van Strafrecht",
                citation_title="Wetboek van Strafrecht",
                article_count=10,
            ),
            _node(
                "bwbr0005753",
                "instrument",
                bwb_id="BWBR0005753",
                title="Wet strafrechtelijke handhaving",
                citation_title="Wet strafrechtelijke handhaving",
                article_count=900,
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                f"bwbr0047000_{n}",
                "article",
                bwb_id="BWBR0047000",
                article_number=str(n),
                display_name=f"Artikel {n} Omgevingswet",
                heading=heading,
                text="Regels over de omgeving.",
                inbound_citation_count=cited,
            )
            for n, heading, cited in [
                (1, "Regels voor stikstofdepositie", 2),
                (2, "Beëindiging van de stikstofruimte", 7),
                (3, "Vastikstofbinding", 40),  # "tikst" within a word only
                (4, "Geluid", 90),
            ]
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node(
                f"d{n}",
                "document",
                title=title,
                kind="Brief regering",
                date=date,
                external_id=f"2024D0000{n}",
            )
            for n, title, date in [
                (1, "Brief over stikstof", "2024-01-05"),
                (2, "Kamerbrief over de stikstofbank", "2024-03-01"),
                (3, "Woningbouw", "2024-06-01"),
                (4, "Stikstofbeleid", "2020-01-01"),
            ]
        ],
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node(
                "36001",
                "dossier",
                number="36001",
                title="Spoedwet stikstof",
                last_activity="2023-01-01",
            ),
            _node(
                "36002",
                "dossier",
                number="36002",
                title="Wet stikstofreductie",
                last_activity="2024-05-01",
            ),
        ],
    )


def test_a_live_search_finds_the_start_of_a_word_without_ranking(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While typing, a part of a word is the start of a word of a name or title (an index
    read each), never within one, and nothing is counted or ranked by its words: of hits
    that score alike (``rank_hits``), articles the most cited first, laws the largest,
    papers and dossiers the newest."""
    version_cache.clear()
    _live_names(store)
    statements: list[str] = []
    query = store.query

    def recording(statement: Any, *args: Any, **kwargs: Any) -> Any:
        statements.append(" ".join(str(statement).split()))
        return query(statement, *args, **kwargs)

    def live(q: str, kind: str) -> list[str]:
        hits, partial = search_queries.search_live(store, q=q, types=[kind])
        assert partial == set()
        return [h["key"] for h in hits[kind]]

    store.query = recording  # type: ignore[method-assign]
    try:
        assert live("stik", "articles") == ["bwbr0047000_2", "bwbr0047000_1"]
        assert live("beeindiging", "articles") == ["bwbr0047000_2"]  # accents folded
        assert live("tikst", "articles") == []
        assert live("stik", "documents") == ["d4", "d2", "d1"]
        assert live("2024D00003", "documents") == ["d3"]
        assert live("stik", "dossiers") == ["36002", "36001"]
        assert live("strafr", "instruments") == ["bwbr0005753", "bwbr0001854"]
        assert live("st", "articles") == []  # two characters: whole words only
    finally:
        store.query = query  # type: ignore[method-assign]
    assert statements
    assert not any("AS rank" in s or "lg_bm25" in s for s in statements)
    # the full search, after Enter, finds a part within a word too
    full = search_queries.search_all(store, q="tikst", types=["articles"])
    assert "bwbr0047000_3" in [h["key"] for h in full["articles"]]
    # of more than it keeps, the title that starts with the query before the newest
    hits, _ = search_queries.search_live(store, q="stik", types=["documents"], limit=1)
    assert [h["key"] for h in hits["documents"]] == ["d4"]
    # a common word: of the first rows found, those first in order
    monkeypatch.setattr(search_queries, "LIVE_CANDIDATES", 1)
    assert len(live("stik", "articles")) == 1


def test_a_full_search_past_its_budget_answers_its_live_hits(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A type whose ranking takes longer than ``FULL_BUDGET`` answers what its live
    search finds, and is named in ``partial``, instead of the request answering 503."""
    import time

    version_cache.clear()
    _live_judgments(store)
    hits, partial = search_queries.search_full(
        store, q="rechtbank amsterdam", types=["judgments", "articles"]
    )
    assert partial == set()
    assert hits == search_queries.search_all(
        store, q="rechtbank amsterdam", types=["judgments", "articles"]
    )

    def slow(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return list(store.query("SELECT pg_sleep(5)"))

    monkeypatch.setattr(search_queries, "_search_judgments", slow)
    monkeypatch.setattr(search_queries, "FULL_BUDGET", 0.5)
    started = time.monotonic()
    hits, partial = search_queries.search_full(
        store, q="rechtbank amsterdam", types=["judgments", "articles"]
    )
    assert time.monotonic() - started < 2
    assert partial == {"judgments"}
    assert [h["key"] for h in hits["judgments"]] == [
        "ecli_nl_rbams_2021_2",
        "ecli_nl_rbams_2021_1",
    ]


def test_a_live_word_of_several_stems_holds_them_all(store: GraphStore) -> None:
    """``20/325`` is the words 20 and 325 (``lg_tokens``): while typing a paper holds them
    both, not one of them (every paper with a 20); a token of no word (``--``) finds
    nothing by it, not every paper."""
    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node(
                "d1", "document", title="Twintig jaar: 20 besluiten", date="2024-02-01"
            ),
            _node("d2", "document", title="Zaak 20/325 besluit", date="2024-01-01"),
            _node("d3", "document", title="De 325 regels", date="2024-03-01"),
        ],
    )

    def live(q: str) -> list[str]:
        hits, partial = search_queries.search_live(store, q=q, types=["documents"])
        assert partial == set()
        return [h["key"] for h in hits["documents"]]

    assert live("20/325") == ["d2"]
    assert live("--") == []


def test_the_types_of_a_live_search_share_one_budget(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Types that find no free thread run one after another: together they keep to
    ``LIVE_BUDGET``, a type that starts late has what is left and is cut off."""
    import time

    version_cache.clear()

    def slow(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        list(store.query("SELECT pg_sleep(0.2)"))
        return []

    monkeypatch.setattr(search_queries, "_search_articles", slow)
    monkeypatch.setattr(search_queries, "_search_documents", slow)
    monkeypatch.setattr(search_queries, "_search_dossiers", slow)
    # no thread free: every type in the thread of the request
    monkeypatch.setattr(
        search_queries, "side_by_side", lambda pool, calls: [call() for call in calls]
    )
    monkeypatch.setattr(search_queries, "LIVE_BUDGET", 0.3)
    started = time.monotonic()
    _, partial = search_queries.search_live(
        store, q="wet", types=["articles", "documents", "dossiers"]
    )
    assert time.monotonic() - started < 0.6
    assert partial == {"documents", "dossiers"}
