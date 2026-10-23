"""The warm API routes read through indexes: no table scan, no sort of a whole table.

Every statement the routes below run is planned with sequential scans, sorts and joins
by hash or merge turned off. The planner then still uses one only where no
index can do the work, and marks that node ``Disabled``. So the check does not depend on
the size of the data: on the small graph seeded here it finds what would read every row of
the full database. Two things fail it:

* a table read whole (a disabled ``Seq Scan``, or a scan in the order of an index that a
  filter picks the rows from);
* a sort of the rows of a whole table (a disabled ``Sort`` above a scan without a
  condition that narrows it): a page cut from it sorts the list first.

A sort that groups (``GROUP BY``, the facets) or orders what a narrowing condition found
(the hits of a search, the citations of one article) is not such a sort. What a route reads
whole on purpose, at most once a minute, is listed in ``_WHOLE_BY_DESIGN``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql

from lawgraph.db import GraphStore
from lawgraph.db.queries.overlay import HEAT_MAX_LIMIT, store_heat
from lawgraph.db.store import _query, statement_text
from tests.asserts import show_items
from tests.databases import module_database, opened_store, serving
from tests.optional import present
from tests.pg.planned_graph import BWB, CELEX, ECLI, seed
from tests.pg.plans import explain, plan_faults, plan_nodes, recorded

# The graph is seeded and every route run once for the whole module (``planned``), and
# its tests run on one worker (``--dist loadgroup`` in CI): the seed is the slow part.
pytestmark = pytest.mark.xdist_group("query_plans")


# The routes of the front end that are read most, with the parameters they take.
URLS = [
    "/api/search?q=wet",
    "/api/search?q=Burgerlijk+Wetboek+Boek+6",
    "/api/search?q=6:162",
    f"/api/search?q={ECLI}",
    "/api/search?q=Hoge+Raad&types=judgments",
    "/api/search?q=kabinet+schoof&types=cabinets",
    "/api/search?q=statusbrief&types=commitments",
    "/api/search?q=stemming+abortus&types=decisions",
    "/api/resolve?q=art.+1+BWBR0001",
    "/api/resolve?q=A.+Lid",
    # a paper by its dossier and ondernummer: by the index of its light row
    "/api/resolve?q=36000-3",
    "/api/search?q=art.+1+BWBR0001&resolve=true",
    "/api/search?q=wet&mode=live",
    # the counts and facets of every hit of a type, and a page deeper in: the rows that hold
    # the words from their indexes, capped (``search.counts``); with a period, a kind, a law's
    # abbreviation and a term
    "/api/search?q=wet&facets=true&offset=20",
    "/api/search?q=Hoge+Raad&facets=true&types=judgments&types=instruments",
    "/api/search?q=wet&facets=true&from=2019-01-01&to=2019-12-31",
    "/api/search?q=daad+pw&facets=true&types=articles&types=dossiers",
    "/api/search?q=noodweer&facets=true&types=articles",
    "/api/search?q=motie+vvd&facets=true&types=documents&kind=motie",
    # a period: each type by a date of its own, inside its lookup
    "/api/search?q=wet&from=2019-01-01&to=2019-12-31",
    "/api/search?q=wet&mode=live&from=2019-01-01&to=2019-12-31",
    f"/api/search?q={ECLI}&from=2019-01-01",
    "/api/search?q=Hoge+Raad&types=judgments&mode=live&to=2020-12-31",
    # an article by what its case law calls it (``lg_article_terms``), full and live
    "/api/search?q=noodweer&types=articles",
    "/api/search?q=noodweer&types=articles&mode=live",
    # a word and the abbreviation of a law: its laws by the index of their aliases, their
    # articles by the index of their law
    "/api/search?q=daad+pw&types=articles",
    "/api/search?q=daad+pw&types=articles&mode=live",
    # the abbreviation of a law: the dossiers it was legislated in by the edges of its laws
    "/api/search?q=pw+dossier&types=dossiers",
    "/api/search?q=pw+dossier&types=dossiers&mode=live",
    "/api/search?q=stik+wetb&mode=live&types=articles&types=documents&types=instruments",
    # a judgment by a person it names: by the trigram index of lg_judgment_persons
    # the articles of a search of the papers too, the best tier first (art. 6:162 BW)
    "/api/search?q=onrechtmatige+daad&types=articles&types=documents&limit=6",
    "/api/search?q=onrechtmatige+daad&types=articles&types=documents&limit=6&mode=live",
    # the papers and the votes signed for a faction the query names
    "/api/search?q=motie+vvd&types=decisions&types=documents",
    "/api/search?q=motie+vvd&types=decisions&types=documents&mode=live",
    "/api/search?q=R.+van+Gelder&types=judgments",
    "/api/search?q=R.+van+Geld&types=judgments&mode=live",
    # a judgment by its LJN: the trigrams of the end of its ECLI
    "/api/search?q=LJN+AU3313&resolve=true",
    "/api/search?q=AU3313&types=judgments&mode=live",
    # the motions of a kind by its name, and kept to a kind; a stem of a word of a vote
    "/api/search?q=motie+van+wantrouwen&types=decisions&types=documents",
    "/api/search?q=wantrouwen&types=decisions&types=documents&mode=live",
    "/api/search?q=motie&types=decisions&types=documents&motion_kind=no_confidence",
    "/api/search?q=toezeggingen+pensioenen&types=commitments",
    # no hit of every word: the hits of one at least
    "/api/search?q=wat+is+de+opzegtermijn+van+mijn+huurcontract",
    f"/api/lookup?kind=judgment&ecli={ECLI}",
    # a paper by its number: by the index on lg_document_light, not the props of every
    # paper of the dossier (a budget dossier holds thousands)
    "/api/lookup?kind=document&dossier=36000&number=3",
    "/api/judgments",
    "/api/judgments?sort=date_asc",
    "/api/judgments?sort=citation_count",
    "/api/judgments?court=HR",
    "/api/judgments?tier=hoge_raad&from=2000-01-01",
    "/api/judgments?tier=hoge_raad&tier=raad_van_state",
    "/api/judgments?subject=Strafrecht",
    "/api/judgments?subject_area=Strafrecht",
    "/api/judgments?procedure=Cassatie",
    "/api/judgments?q=onrechtmatige+daad",
    f"/api/judgments/{ECLI}",
    "/api/instruments",
    "/api/instruments?sort=article_count",
    "/api/instruments?jurisdiction=nl",
    "/api/instruments?q=wet",
    # a period: the day an instrument came into force, or was published
    "/api/instruments?from=2015-01-01&to=2020-12-31",
    "/api/instruments?published_from=2015-01-01",
    "/api/commitments?from=2024-01-01&to=2024-12-31",
    f"/api/instruments/{BWB}",
    # a law of the Staatsblad and an article of it: the edges of its articles to a stub,
    # its articles by the index of the law they belong to
    "/api/instruments/wet_stb_2026_1",
    "/api/articles/STB-2026-1/1",
    f"/api/instruments/{BWB}/articles",
    f"/api/instruments/{BWB}/articles/at/2020-01-01",
    # with the references and citations of its current articles: the articles by key, the
    # edges out of them by their index, the targets by key
    f"/api/instruments/{BWB}/articles/at/2020-01-01?include=references",
    # one division of the law: the breadcrumbs of its articles by the index of the law,
    # then the page by id
    f"/api/instruments/{BWB}/articles?division=deel-hoofdstuk-1",
    f"/api/instruments/{BWB}/articles/at/2020-01-01?division=deel-hoofdstuk-1",
    f"/api/instruments/{BWB}/amended-by",
    f"/api/instruments/{BWB}/eu-links",
    f"/api/instruments/{BWB}/eu-links?sort=importance",
    # the connections ranked (``sort=importance``): each by a measure of fields it reads anyway
    f"/api/instruments/{BWB}/amended-by?sort=importance",
    f"/api/instruments/{BWB}/dossiers?sort=importance",
    f"/api/instruments/{BWB}/judgments",
    f"/api/instruments/{BWB}/judgments?sort=cited&offset=1",
    f"/api/instruments/{BWB}/judgments?year=2020",
    f"/api/instruments/{BWB}/judgments?sort=citation_count&tier=hoge_raad",
    f"/api/instruments/{BWB}/dossiers",
    f"/api/instruments/{BWB}/related-instruments",
    # the regulations issued under the law: its articles, then their BASED_ON edges
    f"/api/instruments/{BWB}/delegated",
    # the basis of a regulation: its edges, then the articles of it that refer to each
    f"/api/instruments/{BWB}/basis",
    # the references between the articles of two laws: those of each, by its edges
    f"/api/instruments/{BWB}/references/BWBR0002",
    f"/api/instruments/{BWB}/versions",
    f"/api/articles/{BWB}/1",
    f"/api/articles/{BWB}/1/cited-by",
    f"/api/articles/{BWB}/1/cited-by?tier=hoge_raad",
    f"/api/articles/{BWB}/1/cited-by?tier=hoge_raad&tier=rechtbank&year=2020",
    f"/api/articles/{BWB}/1/cited-by?sort=citation_count",
    f"/api/articles/{BWB}/1/cited-by?lid=1&court=HR",
    f"/api/articles/{BWB}/1/explained-by",
    f"/api/articles/{BWB}/1/explained-by?sort=importance",
    # the passages, with the names of the dossiers (once per data version of them)
    f"/api/articles/{BWB}/1/explanations",
    f"/api/articles/{BWB}/1/delegated",
    f"/api/articles/{BWB}/1/history",
    f"/api/articles/{BWB}/1/history/av1",
    f"/api/articles/{BWB}/1/legislative-history",
    "/api/relationships/search",
    f"/api/relationships/search?law={BWB}",
    "/api/relationships/search?type=conditional_requirement",
    f"/api/nodes/articles/{BWB.lower()}_1",
    f"/api/nodes/articles/{BWB.lower()}_1?props=canvas",
    f"/api/nodes/articles/{BWB.lower()}_1/neighborhood",
    f"/api/nodes/articles/{BWB.lower()}_1/neighborhood?depth=2",
    # a law: its buckets and its neighbourhood without the outcomes of the old articles
    # (``lg_transposition_outcome``), from the edges' covering index still
    f"/api/nodes/instruments/{BWB.lower()}?limit=1",
    # the buckets ranked (``sort=importance``): an instrument's, a document's, a member's
    f"/api/nodes/instruments/{BWB.lower()}?sort=importance",
    "/api/nodes/documents/d1?sort=importance",
    "/api/nodes/members/m1?sort=importance",
    f"/api/nodes/instruments/{BWB.lower()}/neighborhood?depth=2&props=canvas",
    # a walk that reaches the members, factions, committees and cabinets but goes through
    # none of them
    "/api/nodes/documents/d1/neighborhood?depth=3&stop_at=members,factions,committees,cabinets",
    f"/api/paths?ids=articles/{BWB.lower()}_1,instruments/{BWB.lower()}",
    f"/api/paths?ids=articles/{BWB.lower()}_1,documents/d1&relations=EXPLAINS,PART_OF",
    "/api/nodes/heat",
    "/api/nodes/in-flux",
    "/api/annexes/a1",
    # a paper: its dossiers by its PART_OF edges, each by its id; the same for the paper
    # of a vote
    "/api/documents/d1",
    "/api/documents/d1/passages?bwb_id=BWBR0001&article=1",
    "/api/documents",
    "/api/documents?dossier=36000",
    # the motions of censure and of no confidence: by the partial index on their light row
    "/api/documents?motion_kind=censure,no_confidence",
    "/api/decisions?facets=false",
    "/api/decisions/b1",
    "/api/decisions/b1/document",
    "/api/dossiers/36000",
    "/api/dossiers/36000?sort=importance",
    # the documents behind the decisions of a page, by their cases (not every paper of it)
    "/api/dossiers/36000/timeline",
    "/api/dossiers/36000/amendments",
    "/api/dossiers/36000/documents",
    "/api/dossiers/36000/mutations",
    # the server HTML of a page (``/render``): a judgment, a dossier, a paper (the law of
    # this graph has no BWB id of seven figures, so no readable address)
    f"/render/uitspraken/{ECLI}",
    "/render/dossiers/36000",
    "/render/kamerstukken/36000/3",
    "/render/leden/a-lid",
    "/render/fracties/f1",
    "/render/kabinetten/k1",
    "/render/commissies/c1",
    "/render/stb/2025/263",
    "/render/toezeggingen/TZ202609-124",
    "/render/stemmingen/b1",
    "/render/activiteiten/2026A01323",
    # an EU act by its CELEX number: its articles by the index of its CELEX number; an
    # article of it, its act and the articles before and after it by the same
    f"/render/wetten/{CELEX}",
    f"/render/wetten/{CELEX}/artikel/21",
    # a debate, and what was made in it: by the edges into it, a paper by its light row
    "/api/activities/act1",
    "/api/activities/act1/records",
    "/api/activities/act1/records?sort=importance",
    # a committee: the dossiers it leads and its activities, held before planned
    "/api/committees/c1",
    "/api/committees/c1?sort=importance",
    "/api/committees/c1/activities",
    "/api/committees/c1/activities?sort=importance",
    "/api/commitments/tz1",
    # the events per month of a topic, by the index on their words
    "/api/feed/periods?q=proef&chamber=TK",
    # the votes of a faction: those of its rows of lg_faction_votes
    "/api/feed/periods?party=f1&vote=tegen",
    "/api/dossiers/36000/changed-articles",
    # a member: their votes (by roll-call and through their faction), dossiers, node, and
    # a path from their faction through its members
    "/api/members/m1/votes",
    "/api/members/m1/documents?limit=3",
    "/api/members/m1/dossiers",
    "/api/members/m1/touched-instruments",
    "/api/members/m1/dossiers?sort=importance",
    "/api/factions/f1/dossiers",
    "/api/factions/f1/dossiers?sort=importance",
    "/api/nodes/members/m1",
    f"/api/paths?ids=factions/f1,instruments/{BWB.lower()}&expand=members",
]

# Statements that read a table whole on purpose, each kept for a minute: the statistics
# BM25 weighs a search with, and the names and abbreviations of every law that a search, a
# citation or the title of a dossier is resolved against.
_WHOLE_BY_DESIGN = (
    re.compile(r"SELECT count\(\*\)::float AS n, avg\("),
    re.compile(r"FROM instruments\s+WHERE coalesce\(bwb_id, celex\) IS NOT NULL"),
    re.compile(r"FROM instruments\s+WHERE bwb_id IS NOT NULL OR celex IS NOT NULL"),
    re.compile(
        r"FROM instruments i\s+JOIN lg_instrument_names n ON n.id = i.id\s+"
        r"WHERE i.stub IS DISTINCT FROM TRUE\s+ORDER BY i.key"
    ),
    # the names of the dossiers, once per data version of them (``load_dossier_names``)
    re.compile(r"SELECT DISTINCT ON \(label\) label, lg_str\(pj_title\) AS title"),
    # the slugs of the members, once per data version of them (``load_member_slugs``)
    re.compile(r"SELECT key, lg_str\(props -> 'slug'\) AS slug FROM members"),
    # the names of the factions and of the members a search may name, once per data
    # version of them (``search.signers``)
    re.compile(r"lg_str\(props -> 'chamber'\) AS chamber\s+FROM factions"),
    re.compile(r"SELECT lg_fold\(name\) FROM members WHERE name IS NOT NULL"),
)

# The statements a route ran with ``indexes_only`` (``store.query``).
INDEXES_ONLY: set[str] = set()


@pytest.fixture(scope="module")
def planned(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """The store on a database of its own with the seeded graph, for every test here: they
    only plan statements on it, and set what they change for their own transaction."""
    with module_database(tmp_path_factory), opened_store() as store:
        seed(store)
        yield store


@pytest.fixture(scope="module")
def statements(planned: GraphStore) -> list[tuple[str, Any, Any]]:
    """``(url, statement, params)`` of every read the routes run."""
    store = planned
    # the heat of the whole graph as ``semantic graph-heat`` keeps it: the routes read it
    store_heat(store, HEAT_MAX_LIMIT)
    captured: list[tuple[str, Any, Any]] = []
    with serving(store) as client, pytest.MonkeyPatch.context() as monkeypatch:
        calls = recorded(store, monkeypatch)
        for url in URLS:
            start = len(calls)
            response = client.get(url)  # the /render pages answer HTML
            assert response.status_code == 200, (url, response.text[:300])
            captured += [(url, c.statement, c.params) for c in calls[start:]]
    INDEXES_ONLY.update(c.text for c in calls if c.options.get("indexes_only"))
    return captured


def _outline(node: dict[str, Any], depth: int = 0) -> list[str]:
    """The plan as lines: each node with its table and its conditions."""
    detail = " ".join(
        str(node[k])
        for k in ("Relation Name", "Index Name", "Index Cond", "Recheck Cond", "Filter")
        if k in node
    )
    flag = " (disabled)" if node.get("Disabled") else ""
    lines = [f"{'  ' * depth}{node['Node Type']}{flag} {detail[:120]}"]
    for child in node.get("Plans", []):
        lines += _outline(child, depth + 1)
    return lines


def test_the_routes_read_through_indexes(
    planned: GraphStore, statements: list[tuple[str, Any, Any]]
) -> None:
    assert len(statements) > 60  # the routes ran their queries
    faults = []
    with planned.pool.connection() as conn:
        # Joins by hash or merge read both sides whole: off too, so that what a nested
        # loop over an index can join is joined that way. For this transaction only: the
        # connection goes back to the pool the next test plans with.
        for setting in ("seqscan", "hashjoin", "mergejoin"):
            conn.execute(f"SET LOCAL enable_{setting} = off")
        partial = frozenset(
            name
            for (name,) in conn.execute(
                "SELECT indexrelid::regclass::text FROM pg_index WHERE indpred IS NOT NULL"
            )
        )
        # the first column of every index on a column (not on an expression)
        leading: dict[str, str] = dict(
            conn.execute(
                "SELECT i.indexrelid::regclass::text, a.attname FROM pg_index i"
                " JOIN pg_attribute a"
                "   ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]"
                " WHERE i.indkey[0] <> 0"
            ).fetchall()
        )
        for url, statement, params in statements:
            text = statement_text(statement)
            if any(pattern.search(text) for pattern in _WHOLE_BY_DESIGN):
                continue
            explain = sql.SQL("EXPLAIN (FORMAT JSON) ") + _query(statement)
            try:
                (plan,) = present(conn.execute(explain, params).fetchone())
            except psycopg.Error as exc:
                pytest.fail(f"{url}: {exc}\n{text}")
            found = plan_faults(plan[0]["Plan"], partial, leading=leading)
            if found:
                outline = "\n      ".join(_outline(plan[0]["Plan"]))
                faults.append(
                    f"{url}: {'; '.join(found)}\n    {' '.join(text.split())[:200]}"
                    f"\n      {outline}"
                )
    assert not faults, "\n".join(sorted(set(faults)))


def test_the_search_ranks_and_counts_with_indexes_only(
    statements: list[tuple[str, Any, Any]],
) -> None:
    """The planner does not count detoasting (``store.query``): without ``indexes_only``
    it scans every article's words for a common one. This test runs on the seeded graph
    with sequential scans allowed only through that option, so the option itself is
    what keeps the ranking of the search and its document frequencies on the indexes."""
    ranking = [
        text
        for _, statement, _ in statements
        if re.search(r"OFFSET 0\) r\b", text := statement_text(statement))
        or re.search(r"^SELECT \(SELECT count\(\*\) .*\) AS d0\b", text.strip())
    ]
    assert ranking  # the searches ranked and counted
    assert [text for text in ranking if text not in INDEXES_ONLY] == []


def test_the_live_search_reads_the_trigrams_of_a_field_once_per_word(
    planned: GraphStore, statements: list[tuple[str, Any, Any]]
) -> None:
    """A word typed is found at the start of a value of a name or title, or of a word in
    it: one lookup in the trigram index of the field. Its trigrams are those of the word
    wherever it starts, so a lookup per place reads the same posting lists again (prod,
    14 Oct: "kamer" in 727,000 papers, each past the 250 ms of the live search)."""
    read_again = []
    for url, statement, params in statements:
        if "mode=live" not in url:
            continue
        plan = explain(planned, statement, params, disable=["seqscan"])
        for node in plan_nodes(plan):
            if node["Node Type"] != "BitmapOr":
                continue
            names = [child.get("Index Name", "") for child in node["Plans"]]
            again = sorted(
                {n for n in names if n.endswith("_g") and names.count(n) > 1}
            )
            if again:
                read_again.append(f"{url}: {', '.join(again)}")
    assert not read_again, "\n".join(sorted(set(read_again)))


def test_a_page_read_whole_is_found() -> None:
    scan = {
        "Node Type": "Index Scan",
        "Relation Name": "judgments",
        "Index Cond": "(same_as IS NULL)",
    }
    sorted_page = {
        "Node Type": "Limit",
        "Plans": [{"Node Type": "Sort", "Plans": [scan]}],
    }
    assert plan_faults(sorted_page) == ["Index Scan on judgments read whole"]
    # read in the order of an index, the limit stops the scan
    assert plan_faults({"Node Type": "Limit", "Plans": [scan]}) == []
    # unless a filter picks the rows: then it may read every row for them
    picked = {**scan, "Filter": "(s_names_n @> '{wet}'::text[])"}
    assert plan_faults({"Node Type": "Limit", "Plans": [picked]}) == [
        "Index Scan on judgments read whole, filtered by (s_names_n @> '{wet}'::text[])"
    ]
    # narrowed by a condition that finds rows, it is no whole read
    narrowed = {**scan, "Index Cond": "(court_code = 'HR'::text)"}
    assert plan_faults({"Node Type": "Sort", "Plans": [narrowed]}) == []
    # and so it is by the condition of a partial index
    on_partial = {"Node Type": "Index Scan", "Index Name": "edges_semantic_type"}
    sorted_partial = {"Node Type": "Sort", "Plans": [on_partial]}
    assert plan_faults(sorted_partial, frozenset({"edges_semantic_type"})) == []


def _shape(node: dict[str, Any]) -> list[str]:
    """The plan as its nodes, their tables and indexes, without costs."""
    own = " ".join(
        str(node[k]) for k in ("Node Type", "Relation Name", "Index Name") if k in node
    )
    return [own] + [line for child in node.get("Plans", []) for line in _shape(child)]


def test_a_cursor_is_planned_as_the_query_it_reads(
    planned: GraphStore, statements: list[tuple[str, Any, Any]]
) -> None:
    """``store.query`` reads every statement through a server-side cursor; planned for its
    first tenth (the default ``cursor_tuple_fraction``), a statement with ``ORDER BY …
    LIMIT`` may walk a table in index order. The connections of the pool plan a cursor
    for all its rows: as the statement itself."""
    differ = []
    with planned.pool.connection() as conn:
        assert conn.execute("SHOW cursor_tuple_fraction").fetchone() == ("1",)
        for url, statement, params in statements:
            query = _query(statement)
            plain = sql.SQL("EXPLAIN (FORMAT JSON) ") + query
            cursor = (
                sql.SQL("EXPLAIN (FORMAT JSON) DECLARE plan_check CURSOR FOR ") + query
            )
            (as_query,) = present(conn.execute(plain, params).fetchone())
            (as_cursor,) = present(conn.execute(cursor, params).fetchone())
            if _shape(as_query[0]["Plan"]) != _shape(as_cursor[0]["Plan"]):
                differ.append(
                    f"{url}: {' '.join(statement_text(statement).split())[:200]}"
                )
            conn.rollback()
    assert not differ, "\n".join(sorted(set(differ)))


def test_a_zaak_a_member_and_an_activity_are_found_by_their_index_without_statistics(
    planned: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An expression index made after the last ANALYZE has no statistics: the planner then
    guesses many rows per number, and with ``ORDER BY key LIMIT 1`` beside the condition it
    walks the key index until a row holds it (prod, 1.4 s on 258,638 zaken). The lookups
    find the rows by the expression index whatever the statistics."""
    from lawgraph.db.queries import lookup

    found = []
    original = planned.query

    def explained(statement: Any, params: Any = None, **options: Any) -> Any:
        with planned.pool.connection() as conn:
            for index, table, expression in (
                ("cases_number", "cases", "public.lg_str(props -> 'number')"),
                ("members_slug", "members", "public.lg_str(props -> 'slug')"),
                ("activities_number", "activities", "public.lg_str(props -> 'number')"),
            ):
                # made again in this transaction: no statistics, as a new index has
                conn.execute(f"DROP INDEX {index}")
                conn.execute(f"CREATE INDEX {index} ON {table} ({expression})")
            query = sql.SQL("EXPLAIN (FORMAT JSON) ") + _query(statement)
            (plan,) = present(conn.execute(query, params).fetchone())
            found.append(_shape(plan[0]["Plan"]))
            conn.rollback()
        return original(statement, params, **options)

    monkeypatch.setattr(planned, "query", explained)
    lookup.find_case(planned, "2025Z15468")
    lookup.find_member(planned, "a-lid")
    lookup.find_activity(planned, "2026A01323")
    case, member, activity = found
    assert any("cases_number" in line for line in case), case
    assert any("members_slug" in line for line in member), member
    assert any("activities_number" in line for line in activity), activity
    found_2 = [
        line
        for line in case + member + activity
        if line.endswith(("cases_key", "members_key", "activities_key"))
    ]
    assert not found_2, show_items(found_2)


def test_an_article_reads_the_definitions_its_regulation_takes(
    statements: list[tuple[str, Any, Any]],
) -> None:
    """The article route reads the regulations its regulation is issued under (two levels
    of ``BASED_ON``) for the definitions it takes: planned above with the rest."""
    from lawgraph.db.queries.definitions import _BASES_SQL

    assert any(
        url == f"/api/articles/{BWB}/1"
        and statement_text(statement) == statement_text(_BASES_SQL)
        for url, statement, _ in statements
    ), show_items(statements)


def test_a_detail_reads_its_unlinked_references_by_its_id(
    statements: list[tuple[str, Any, Any]],
) -> None:
    """The article and the judgment route read how many references of the record were not
    linked (``lg_unlinked_references``, one row by its key): planned above with the rest."""
    from lawgraph.db.queries.unlinked_references import _COUNT_SQL

    read = {
        url
        for url, statement, _ in statements
        if statement_text(statement) == statement_text(_COUNT_SQL)
    }
    assert {f"/api/articles/{BWB}/1", f"/api/judgments/{ECLI}"} <= read, show_items(
        statements
    )


def test_a_law_of_the_staatsblad_reads_its_counts_in_one_statement(
    statements: list[tuple[str, Any, Any]],
) -> None:
    """A law of the Staatsblad and an article of it read what the step could not link and
    their edges to a stub in one statement each: planned above with the rest."""
    from lawgraph.db.queries.unlinked_references import (
        _LAW_ARTICLE_COUNT_SQL,
        _LAW_COUNT_SQL,
    )

    read = {
        (url, statement_text(statement))
        for url, statement, _ in statements
        if statement_text(statement)
        in {statement_text(_LAW_COUNT_SQL), statement_text(_LAW_ARTICLE_COUNT_SQL)}
    }
    assert read == {
        ("/api/instruments/wet_stb_2026_1", statement_text(_LAW_COUNT_SQL)),
        ("/api/articles/STB-2026-1/1", statement_text(_LAW_ARTICLE_COUNT_SQL)),
    }, show_items(statements)


def test_the_passages_name_their_dossiers_without_a_read_per_paper(
    statements: list[tuple[str, Any, Any]],
) -> None:
    """The passages of an article put the name of its dossier next to each paper from the
    names of the dossiers kept per data version (``load_dossier_names``): no statement of
    the route reads the dossiers by number."""
    url = f"/api/articles/{BWB}/1/explanations"
    texts = [statement_text(s) for u, s, _ in statements if u == url]
    assert texts, show_items(statements)
    assert not [t for t in texts if "FROM dossiers" in t and "DISTINCT ON" not in t]


def test_the_votes_of_a_rare_word_are_found_by_its_trigrams(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A word that the newest votes seldom hold is found by the trigram index of the
    words of the votes, not by testing every vote newest first: the planner counts on the
    votes of long ago that hold it (prod, 16 Oct: 21,601 votes read for the 20 of
    "huurverhoging"). The hits are the newest that hold every word, whichever way they
    were found."""
    from lawgraph.db.queries.search.dispatch import search_all
    from lawgraph.db.queries.search.types import DECISIONS_RECENT

    count = 3 * DECISIONS_RECENT
    votes: list[dict[str, Any]] = [
        {"key": f"v{n:05d}", "type": "decision", "labels": [],
         "props": {"date": f"{2000 + n * 25 // count}-{1 + n % 12:02d}-{1 + n % 28:02d}",
                   "kind": "Motie" if n % 2 else "Amendement",
                   # held by the oldest tenth of the votes and by every 997th
                   "subject": f"Over de begroting {n}"
                   + (" en de huurverhoging" if n < count // 10 or n % 997 == 0 else "")}}
        for n in range(count)
    ]  # fmt: skip
    store.bulk_insert_or_update_nodes("decisions", votes)
    with store.pool.connection() as conn:
        conn.execute("ANALYZE decisions")

    def newest(*words: str) -> list[str]:
        held = [
            v for v in votes
            if all(w in f"{v['props']['subject']} {v['props']['kind']}".lower()
                   for w in words)
        ]  # fmt: skip
        held.sort(key=lambda v: v["key"])
        held.sort(key=lambda v: v["props"]["date"], reverse=True)
        return [v["key"] for v in held[:20]]

    calls = recorded(store, monkeypatch)
    faults = []
    for q, words in (
        ("huurverhoging", ["huurverhoging"]),
        ("motie huurverhoging", ["motie", "huurverhoging"]),
        ("motie", ["motie"]),
    ):
        start = len(calls)
        hits = search_all(store, q=q, types=["decisions"], limit=20)["decisions"]
        assert [h["key"] for h in hits] == newest(*words), q
        for call in calls[start:]:
            if any(pattern.search(call.text) for pattern in _WHOLE_BY_DESIGN):
                continue
            plan = explain(store, call.statement, call.params, disable=["seqscan"])
            faults += [f"{q}: {fault}" for fault in plan_faults(plan)]
    assert faults == []


def test_the_law_of_a_day_reads_the_references_of_its_articles_at_once(
    statements: list[tuple[str, Any, Any]],
) -> None:
    """``include=references`` reads the articles of the page and the edges out of them in
    a statement each, not one per article."""
    url = f"/api/instruments/{BWB}/articles/at/2020-01-01?include=references"
    texts = [" ".join(statement_text(s).split()) for u, s, _ in statements if u == url]
    assert sum("FROM articles WHERE key = ANY" in t for t in texts) == 1
    assert sum("e.from_id = ANY(%(ids)s)" in t for t in texts) == 1


@pytest.mark.parametrize("marked", [0, 3])
def test_the_motions_of_a_kind_are_found_by_their_index(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, marked: int
) -> None:
    """A motion of censure or of no confidence is rare (156 of some 600,000 papers): the
    papers and the votes of one kind are found by the partial index on ``motion_kind``,
    not by walking the list newest first and testing each row (prod, 0.80.0: the papers
    timed out after 30 s, with none marked yet). The oldest *marked* are of the kind."""
    from lawgraph.db.queries.decisions import DecisionFilters, get_decisions
    from lawgraph.db.queries.documents import list_documents

    count = 3_000

    def date(n: int) -> str:
        return f"{2026 - n * 20 // count}-{1 + n % 12:02d}-{1 + n % 28:02d}"

    def kind(n: int) -> dict[str, Any]:
        return {"motion_kind": "censure"} if n >= count - marked else {}

    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {"key": f"m{n:05d}", "type": "document", "labels": ["TK"],
             "props": {"kind": "Motie", "date": date(n), "title": f"Motie {n}", **kind(n)}}
            for n in range(count)
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            {"key": f"v{n:05d}", "type": "decision", "labels": ["TK"],
             "props": {"kind": "Motie", "date": date(n), "passed": n % 2 == 0,
                       "subject": f"Motie {n}", **kind(n)}}
            for n in range(count)
        ],
    )  # fmt: skip
    with store.pool.connection() as conn:
        for table in ("documents", "decisions"):
            conn.execute(f"ANALYZE {table}")

    calls = recorded(store, monkeypatch)
    papers = list_documents(store, motion_kinds=("censure",), facets=False)
    assert len(papers["items"]) == marked
    votes = get_decisions(
        store, DecisionFilters(motion_kinds=("censure",)), facets=False
    )
    assert len(votes["items"]) == marked

    def first_found(node: dict[str, Any]) -> bool:
        """Whether an InitPlan of *node* reads the motion_kind index: the ids of the
        kind are found once, before any row of the list is read."""
        return any(
            child.get("Parent Relationship") == "InitPlan"
            and any(
                str(n.get("Index Name", "")).endswith("motion_kind")
                for n in plan_nodes(child)
            )
            for n in plan_nodes(node)
            for child in n.get("Plans", [])
        )

    shapes = []
    for call in calls:
        if "motion_kind" not in call.text or "ANY(%(motion_kinds)s" not in call.text:
            continue
        plan = explain(store, call.statement, call.params, disable=["seqscan"])
        indexes = {node.get("Index Name") for node in plan_nodes(plan)}
        shapes.append((indexes, _outline(plan), first_found(plan)))
    assert len(shapes) == 2, show_items([c.text for c in calls])
    for indexes, outline, first in shapes:
        assert first, "\n".join(outline)
        assert indexes & {"lg_document_light_motion_kind", "decisions_motion_kind"}, (
            "\n".join(outline)
        )
        assert not indexes & {"documents_list_date", "decisions_list_date"}, "\n".join(
            outline
        )


def test_the_artikel_100_brieven_are_read_by_their_index(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An artikel 100-brief is rare (a few hundred of some 650,000 papers, the oldest of
    them from 2008): a page of them and their count read the partial index
    ``documents_article_100``, not every paper newest first with the subject of each
    tested."""
    from lawgraph.db.queries.documents import list_documents

    count, named = 3_000, 3

    def subject(n: int) -> str:
        return "Artikel 100-inzet" if n >= count - named else f"Brief {n}"

    store.bulk_insert_or_update_nodes(
        "documents",
        [
            {"key": f"b{n:05d}", "type": "document", "labels": ["TK"],
             "props": {"kind": "Brief regering", "subject": subject(n),
                       "date": f"{2026 - n * 20 // count}-{1 + n % 12:02d}-01"}}
            for n in range(count)
        ],
    )  # fmt: skip
    with store.pool.connection() as conn:
        conn.execute("ANALYZE documents")

    calls = recorded(store, monkeypatch)
    found = list_documents(store, letter_kind="article_100")
    assert (len(found["items"]), found["total"]) == (named, named)

    plans = [
        explain(store, call.statement, call.params, disable=["seqscan"])
        for call in calls
        if "~*" in call.text
    ]
    assert len(plans) == 2, show_items([c.text for c in calls])  # the page, the count
    for plan in plans:
        indexes = {node.get("Index Name") for node in plan_nodes(plan)}
        outline = "\n".join(_outline(plan))
        assert "documents_article_100" in indexes, outline
        assert "documents_list_date" not in indexes, outline
