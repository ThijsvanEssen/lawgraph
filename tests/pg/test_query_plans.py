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
from fastapi.testclient import TestClient
from psycopg import sql

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from lawgraph.db.queries.overlay import HEAT_MAX_LIMIT, store_heat
from lawgraph.db.schema import NODE_COLLECTIONS
from lawgraph.db.store import _query, _text

BWB = "BWBR0001"
FILLER = 10_000
ECLI = "ECLI:NL:HR:2020:1"

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
    "/api/search?q=art.+1+BWBR0001&resolve=true",
    "/api/search?q=wet&mode=live",
    "/api/search?q=stik+wetb&mode=live&types=articles&types=documents&types=instruments",
    f"/api/lookup?kind=judgment&ecli={ECLI}",
    "/api/judgments",
    "/api/judgments?sort=date_asc",
    "/api/judgments?sort=citation_count",
    "/api/judgments?court=HR",
    "/api/judgments?tier=hoge_raad&from=2000-01-01",
    "/api/judgments?subject=Strafrecht",
    "/api/judgments?subject_area=Strafrecht",
    "/api/judgments?procedure=Cassatie",
    "/api/judgments?q=onrechtmatige+daad",
    f"/api/judgments/{ECLI}",
    "/api/instruments",
    "/api/instruments?sort=article_count",
    "/api/instruments?jurisdiction=nl",
    "/api/instruments?q=wet",
    f"/api/instruments/{BWB}",
    f"/api/instruments/{BWB}/articles",
    f"/api/instruments/{BWB}/articles/at/2020-01-01",
    f"/api/instruments/{BWB}/amended-by",
    f"/api/instruments/{BWB}/judgments",
    f"/api/instruments/{BWB}/judgments?sort=cited&offset=1",
    f"/api/instruments/{BWB}/judgments?year=2020",
    f"/api/instruments/{BWB}/dossiers",
    f"/api/instruments/{BWB}/related-instruments",
    f"/api/instruments/{BWB}/versions",
    f"/api/articles/{BWB}/1",
    f"/api/articles/{BWB}/1/cited-by",
    f"/api/articles/{BWB}/1/cited-by?tier=hoge_raad",
    f"/api/articles/{BWB}/1/cited-by?sort=citation_count",
    f"/api/articles/{BWB}/1/explained-by",
    f"/api/articles/{BWB}/1/history",
    f"/api/articles/{BWB}/1/legislative-history",
    "/api/relationships/search",
    f"/api/relationships/search?law={BWB}",
    "/api/relationships/search?type=conditional_requirement",
    f"/api/nodes/articles/{BWB.lower()}_1",
    f"/api/nodes/articles/{BWB.lower()}_1?props=canvas",
    f"/api/nodes/articles/{BWB.lower()}_1/neighborhood",
    f"/api/nodes/articles/{BWB.lower()}_1/neighborhood?depth=2",
    f"/api/paths?ids=articles/{BWB.lower()}_1,instruments/{BWB.lower()}",
    f"/api/paths?ids=articles/{BWB.lower()}_1,documents/d1&relations=EXPLAINS,PART_OF",
    "/api/nodes/heat",
    "/api/nodes/in-flux",
    "/api/annexes/a1",
    "/api/dossiers/36000",
    "/api/dossiers/36000/changed-articles",
    # a member: their votes (by roll-call and through their faction), dossiers, node, and
    # a path from their faction through its members
    "/api/members/m1/votes",
    "/api/members/m1/dossiers",
    "/api/members/m1/touched-instruments",
    "/api/factions/f1/dossiers",
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
        r"FROM instruments i\s+WHERE i.stub IS DISTINCT FROM TRUE\s+ORDER BY i.key"
    ),
    # the names of the dossiers, once per data version of them (``load_dossier_names``)
    re.compile(r"SELECT DISTINCT ON \(label\) label, lg_str\(pj_title\) AS title"),
)

# The statements a route ran with ``indexes_only`` (``store.query``).
INDEXES_ONLY: set[str] = set()

_SCANS = ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan")
# The conditions of a whole list hold for nearly every row, they do not find rows: a test
# of a flag (``same_as IS NULL``, ``stub IS NOT TRUE``) and every instrument but the
# publications.
_LIST_TEST = re.compile(
    r"^(\w+\.)?\w+ IS (NOT )?(NULL|TRUE|FALSE)$"
    r"|^(\w+\.)?kind IS DISTINCT FROM 'publicatie'::text$"
)


def _flags_only(condition: str) -> bool:
    if not condition:
        return True
    parts = re.split(r"\s+AND\s+", condition)
    return all(_LIST_TEST.match(part.strip(" ()")) for part in parts)


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _edge(
    key: str, source: str, target: str, relation: str, **extra: Any
) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
        "created_at": "2026-09-01T00:00:00Z",
        **extra,
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "bwbr0001",
                "instrument",
                bwb_id=BWB,
                title="Wet op de proef",
                citation_title="Proefwet",
                short_title="Pw",
                jurisdiction="nl",
                kind="wet",
                article_count=2,
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                f"bwbr0001_{n}",
                "article",
                bwb_id=BWB,
                article_number=str(n),
                stam_id=f"s{n}",
                display_name=f"Artikel {n} Proefwet",
                heading="Onrechtmatige daad",
                text="Hij die jegens een ander een onrechtmatige daad pleegt.",
            )
            for n in (1, 2)
        ],
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _node(
                "av1",
                "article_version",
                bwb_id=BWB,
                article_number="1",
                stam_id="s1",
                valid_from="2010-01-01",
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instrument_versions",
        [_node("iv1", "instrument_version", bwb_id=BWB, valid_from="2010-01-01")],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "ecli_nl_hr_2020_1",
                "judgment",
                ecli=ECLI,
                source="rechtspraak",
                court_code="HR",
                court="Hoge Raad",
                tier="hoge_raad",
                date_eff="2020-01-01",
                display_name="HR 1 januari 2020, onrechtmatige daad",
                summary="Onrechtmatige daad.",
                subjects=["Strafrecht"],
                inbound_citation_count=1,
                stub=False,
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node("d1", "document", title="Memorie van toelichting", kind="memorie")],
    )
    store.bulk_insert_or_update_nodes(
        "annexes", [_node("a1", "annex", bwb_id=BWB, title="Bijlage")]
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node(
                "36000",
                "dossier",
                number="36000",
                label="36000",
                # a law the title names: the dossier looks it up (``get_laws_named``)
                title="Wijziging van de Wet op de proef",
            )
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "stb_2026_1", "instrument", kind="publicatie", official_id="stb-2026-1"
            )
        ],
    )
    membership = {
        "faction_id": "factions/f1",
        "faction_key": "f1",
        "abbreviation": "F",
        "from_date": "2010-01-01",
        "to_date": None,
    }
    store.bulk_insert_or_update_nodes(
        "members",
        [_node("m1", "member", name="A. Lid", faction_memberships=[membership])],
    )
    store.bulk_insert_or_update_nodes("factions", [_node("f1", "faction", name="F")])
    store.bulk_insert_or_update_nodes(
        "decisions",
        [_node(f"b{n}", "decision", date=f"2020-01-0{n}") for n in (1, 2)],
    )
    article = f"articles/{BWB.lower()}_1"
    store.bulk_insert_or_update_edges(
        [
            _edge("mf", "members/m1", "factions/f1", "MEMBER_OF"),
            _edge("ma", "members/m1", "documents/d1", "AUTHORED"),
            _edge(
                "fv", "factions/f1", "decisions/b1", "VOTED", meta={"choice": "Voor"}
            ),
            _edge(
                "mv", "members/m1", "decisions/b2", "VOTED", meta={"choice": "Tegen"}
            ),
        ]
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("p1", article, "instruments/bwbr0001", "PART_OF"),
            _edge("p2", f"articles/{BWB.lower()}_2", "instruments/bwbr0001", "PART_OF"),
            _edge(
                "r1",
                article,
                f"articles/{BWB.lower()}_2",
                "REFERS_TO",
                semantic_type="conditional_requirement",
            ),
            _edge(
                "r2",
                "judgments/ecli_nl_hr_2020_1",
                article,
                "REFERS_TO",
                meta={"paragraphs": [1]},
            ),
            _edge("x1", "documents/d1", article, "EXPLAINS"),
            _edge("s1", article, "annexes/a1", "SCOPED_BY"),
            # a bill: the publication that enacts it, and a paper that proposes a change
            _edge("l1", "instruments/stb_2026_1", "dossiers/36000", "LEGISLATED_IN"),
            _edge(
                "m1",
                "instruments/stb_2026_1",
                article,
                "AMENDS",
                meta={"effective_date": "2026-01-01"},
            ),
            _edge("d1p", "documents/d1", "dossiers/36000", "PART_OF"),
            _edge(
                "v1",
                "documents/d1",
                f"articles/{BWB.lower()}_2",
                "AMENDS",
                status="voorgesteld",
            ),
        ]
    )
    _fill(store)
    store.vacuum_analyze()


def _fill(store: GraphStore) -> None:
    """Rows that no route asks for: on tables of one or two rows the planner reads them
    whole whatever indexes there are; on a thousand, as on the real ones, it does not."""
    statements = [
        f"INSERT INTO {table} (id, type) SELECT '{table}/filler_' || n, 'filler'"
        f" FROM generate_series(1, {FILLER}) n"
        for table in NODE_COLLECTIONS
    ]
    statements.append(
        "INSERT INTO edges (key, from_id, to_id, doc)"
        " SELECT 'filler_' || n, 'judgments/filler_' || n % 9973,"
        " 'articles/filler_' || n % 9967, json_build_object('relation', 'FILLER',"
        # a moment of its own, as nearly every edge has: an index that starts with it is
        # no way to the edges of a node
        " 'created_at', '2020-01-01T00:00:00.' || lpad(n::text, 6, '0'))"
        f" FROM generate_series(1, {FILLER * 5}) n"
    )
    for statement in statements:
        store.execute(statement)


@pytest.fixture()
def statements(store: GraphStore) -> Iterator[list[tuple[str, Any, Any]]]:
    """``(url, statement, params)`` of every read the routes run."""
    _seed(store)
    # the heat of the whole graph as ``semantic graph-heat`` keeps it: the routes read it
    store_heat(store, HEAT_MAX_LIMIT)
    captured: list[tuple[str, Any, Any]] = []
    current = {"url": ""}
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        captured.append((current["url"], statement, params))
        if options.get("indexes_only"):
            INDEXES_ONLY.add(_text(statement))
        return query(statement, params, **options)

    store.query = recording  # type: ignore[method-assign]
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        for url in URLS:
            current["url"] = url
            response = client.get(url)
            assert response.status_code == 200, (url, response.text[:300])
        yield captured
    finally:
        app.dependency_overrides.pop(get_store, None)


def _narrowed(node: dict[str, Any], partial: frozenset[str]) -> bool:
    """Whether a condition of the scan, or the condition of the partial index it reads
    (``WHERE semantic_type IS NOT NULL``), finds its rows."""
    indexes = {node.get("Index Name")} | {
        child.get("Index Name") for child in node.get("Plans", [])
    }
    if indexes & partial:
        return True
    condition = node.get("Index Cond") or node.get("Recheck Cond")
    return bool(condition) and not _flags_only(condition)


def _skipped(
    node: dict[str, Any], leading: dict[str, str], partial: frozenset[str]
) -> bool:
    """Whether the scan's condition leaves out the first column of its index: a skip scan
    over every value of it (``to_id`` through ``(created_at, to_id)`` reads the whole index
    on the full database). A partial index holds only the rows of its condition."""
    if node.get("Index Name") in partial:
        return False
    column = leading.get(node.get("Index Name") or "")
    condition = node.get("Index Cond") or ""
    return (
        bool(column and condition)
        and not _flags_only(condition)
        and not re.search(rf"\b{column}\b", condition)
    )


# Nodes that read all of their input before they give a row: below them a limit above
# stops nothing early.
_READS_ALL = ("Sort", "Incremental Sort", "Hash", "Materialize", "Aggregate", "Unique")


def _faults(
    node: dict[str, Any],
    partial: frozenset[str] = frozenset(),
    limited: bool = False,
    grouped: bool = False,
    leading: dict[str, str] | None = None,
) -> list[str]:
    """The whole reads in the plan *node*: a sequential scan, and a scan that nothing
    narrows, unless it only tests flags and is either cut short by a limit (a page read
    in the order of an index) or counted (a total or the facets of a list)."""
    kind = node["Node Type"]
    if kind in _READS_ALL:
        limited = False
    if kind == "Limit":
        limited = True
    found = []
    if kind == "Seq Scan":
        found.append(f"Seq Scan on {node.get('Relation Name')}")
    elif kind in _SCANS and _skipped(node, leading or {}, partial):
        found.append(
            f"{kind} on {node.get('Relation Name')} skips the first column of"
            f" {node.get('Index Name')}"
        )
    elif kind in _SCANS and not _narrowed(node, partial):
        filtered = node.get("Filter", "")
        if not (_flags_only(filtered) and (limited or grouped)):
            found.append(
                f"{kind} on {node.get('Relation Name')} read whole"
                + (f", filtered by {filtered}" if filtered else "")
            )
    for child in node.get("Plans", []):
        found += _faults(
            child, partial, limited, grouped or kind == "Aggregate", leading
        )
    return found


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
    store: GraphStore, statements: list[tuple[str, Any, Any]]
) -> None:
    assert len(statements) > 60  # the routes ran their queries
    faults = []
    with store.pool.connection() as conn:
        # Joins by hash or merge read both sides whole: off too, so that what a nested
        # loop over an index can join is joined that way.
        for setting in ("seqscan", "hashjoin", "mergejoin"):
            conn.execute(f"SET enable_{setting} = off")
        partial = frozenset(
            name
            for (name,) in conn.execute(
                "SELECT indexrelid::regclass::text FROM pg_index WHERE indpred IS NOT NULL"
            )
        )
        # the first column of every index on a column (not on an expression)
        leading = dict(
            conn.execute(
                "SELECT i.indexrelid::regclass::text, a.attname FROM pg_index i"
                " JOIN pg_attribute a"
                "   ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]"
                " WHERE i.indkey[0] <> 0"
            ).fetchall()
        )
        for url, statement, params in statements:
            text = _text(statement)
            if any(pattern.search(text) for pattern in _WHOLE_BY_DESIGN):
                continue
            explain = sql.SQL("EXPLAIN (FORMAT JSON) ") + _query(statement)
            try:
                (plan,) = conn.execute(explain, params).fetchone()  # type: ignore[misc]
            except psycopg.Error as exc:
                pytest.fail(f"{url}: {exc}\n{text}")
            found = _faults(plan[0]["Plan"], partial, leading=leading)
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
        if "OFFSET 0) doc" in (text := _text(statement))
        or re.search(r"^SELECT \(SELECT count\(\*\) .*\) AS d0\b", text.strip())
    ]
    assert ranking  # the searches ranked and counted
    assert [text for text in ranking if text not in INDEXES_ONLY] == []


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
    assert _faults(sorted_page) == ["Index Scan on judgments read whole"]
    # read in the order of an index, the limit stops the scan
    assert _faults({"Node Type": "Limit", "Plans": [scan]}) == []
    # unless a filter picks the rows: then it may read every row for them
    picked = {**scan, "Filter": "(s_names_n @> '{wet}'::text[])"}
    assert _faults({"Node Type": "Limit", "Plans": [picked]}) == [
        "Index Scan on judgments read whole, filtered by (s_names_n @> '{wet}'::text[])"
    ]
    # narrowed by a condition that finds rows, it is no whole read
    narrowed = {**scan, "Index Cond": "(court_code = 'HR'::text)"}
    assert _faults({"Node Type": "Sort", "Plans": [narrowed]}) == []
    # and so it is by the condition of a partial index
    on_partial = {"Node Type": "Index Scan", "Index Name": "edges_semantic_type"}
    sorted_partial = {"Node Type": "Sort", "Plans": [on_partial]}
    assert _faults(sorted_partial, frozenset({"edges_semantic_type"})) == []


def _shape(node: dict[str, Any]) -> list[str]:
    """The plan as its nodes, their tables and indexes, without costs."""
    own = " ".join(
        str(node[k]) for k in ("Node Type", "Relation Name", "Index Name") if k in node
    )
    return [own] + [line for child in node.get("Plans", []) for line in _shape(child)]


def test_a_cursor_is_planned_as_the_query_it_reads(
    store: GraphStore, statements: list[tuple[str, Any, Any]]
) -> None:
    """``store.query`` reads every statement through a server-side cursor; planned for its
    first tenth (the default ``cursor_tuple_fraction``), a statement with ``ORDER BY …
    LIMIT`` may walk a table in index order. The connections of the pool plan a cursor
    for all its rows: as the statement itself."""
    differ = []
    with store.pool.connection() as conn:
        assert conn.execute("SHOW cursor_tuple_fraction").fetchone() == ("1",)
        for url, statement, params in statements:
            query = _query(statement)
            plain = sql.SQL("EXPLAIN (FORMAT JSON) ") + query
            cursor = (
                sql.SQL("EXPLAIN (FORMAT JSON) DECLARE plan_check CURSOR FOR ") + query
            )
            (as_query,) = conn.execute(plain, params).fetchone()  # type: ignore[misc]
            (as_cursor,) = conn.execute(cursor, params).fetchone()  # type: ignore[misc]
            if _shape(as_query[0]["Plan"]) != _shape(as_cursor[0]["Plan"]):
                differ.append(f"{url}: {' '.join(_text(statement).split())[:200]}")
            conn.rollback()
    assert not differ, "\n".join(sorted(set(differ)))
