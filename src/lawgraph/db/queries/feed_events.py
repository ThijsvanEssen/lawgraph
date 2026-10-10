"""The events of the feed in a table of their own (``lg_feed_events``), and what ``GET
/api/feed/periods`` counts in it per month or day.

The rows are written from the reading of every kind of event the feed itself makes
(``queries/feed.py``: each kind's table, its condition, its first dossier, its signatures),
so a period counts what the feed's facets count under the same filters. Each row keeps what
those filters read: its kind, date, chamber, ministry, factions and dossier labels, and the
texts the feed matches ``q`` against, its title and that of its first dossier, in lower
case. ``words`` (their tokens of letters and digits) finds the rows that may hold ``q`` by
index; the feed's own pattern then decides, on those texts.

``lawgraph feed-events`` writes them: all of them into a new table that then takes the
place of the old one, or (``since``) those dated from a day on, in place.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any

import psycopg

from lawgraph.config.constants import RELATION_REVISES
from lawgraph.core.feed import FEED_KINDS
from lawgraph.db import GraphStore
from lawgraph.db.queries import _words
from lawgraph.db.queries.feed import (
    _CABINET_PERIOD,
    _IN_PERIOD,
    _PREAMBLE,
    FeedFilters,
    _elements,
    _Kind,
    _kinds_to_read,
    _lit,
    _Plan,
    _text,
    _words_of,
)
from lawgraph.db.schema import (
    FEED_EVENTS_COLUMNS,
    FEED_EVENTS_INDEXES,
    FEED_EVENTS_TABLE,
)
from lawgraph.db.version_cache import lasting

# The columns written, in the order of each kind's SELECT.
COLUMNS = (
    "kind",
    "id",
    "date",
    "chamber",
    "ministry",
    "factions",
    "labels",
    "title",
    "dossier_title",
    "words",
)

# A plan that reads every kind for the facets (the factions of a row), with the title of
# a row and of its first dossier (a word of ``q`` makes a kind read them).
_PLAN = _Plan(
    filters=FeedFilters(q=("x",)),
    facets=True,
    shared=[],
    dimensions={},
    cursor=None,
)
_LABELS = (
    f"ARRAY(SELECT x.v #>> '{{}}' FROM {_elements('l.labels')}"
    " WHERE json_typeof(x.v) IN ('string', 'number', 'boolean'))"
)


def _rows_of_kind(kind: _Kind) -> str:
    """SQL: the rows of one kind (``COLUMNS``), dated from ``%(since)s``."""
    source = kind.source
    title = f"lower({_text('t.title')})"
    dossier_title = f"lower({_text('fd.title')})" if kind.first_dossier else "NULL"
    values = (
        _lit(source.kind),
        "n.id",
        f"n.{source.date}",
        f"({source.chamber})::text",
        f"({kind.ministry})::text",
        kind.factions,
        _LABELS,
        title,
        dossier_title,
        f"lg_alnum_tokens(concat_ws(' ', {title}, {dossier_title}))",
    )
    select = ",\n            ".join(
        f"{value} AS {name}" for value, name in zip(values, COLUMNS, strict=True)
    )
    return f"""(
        SELECT {select}
        FROM {source.collection} n{kind.laterals()}
        WHERE n.{source.date} >= %(since)s AND {source.condition}
    )"""


def insert_query(table: str) -> str:
    """SQL: insert into *table* every event of the feed dated from ``%(since)s``."""
    sources = _kinds_to_read(FeedFilters(), facets=True)
    union = "\n    UNION ALL ".join(_rows_of_kind(_Kind(s, _PLAN)) for s in sources)
    return (
        f"WITH {_PREAMBLE}\n"
        f"INSERT INTO {table} ({', '.join(COLUMNS)})\n"
        f"SELECT * FROM ({union}\n) events"
    )


_NEW = f"{FEED_EVENTS_TABLE}_new"
_STATE = """
INSERT INTO lg_feed_events_state (id, written_at, since) VALUES (true, now(), %(since)s)
ON CONFLICT (id) DO UPDATE SET written_at = excluded.written_at, since = excluded.since
"""


# The chains of the amendments, as the front end's timetable of a dossier draws them
# (``dienstregeling``, ``kiesBesluit`` in lawgraph-explorer): written again whole with the
# events.
# - an amendment is a paper whose case is one (``case_kinds`` holds ``Amendement``);
# - a paper REVISES the one it replaces; a chain ends at a paper no other replaces, and
#   holds every paper that one replaces, the papers it replaced, and so on: chains that
#   meet in one last paper are one amendment (merged);
# - its day is that of its oldest paper (by date, then number);
# - its outcome that of its last paper: of its cases in their order the first with a
#   decision that singles it out (``primary_case_id``), of those the latest with an outcome
#   (``passed``), else the latest; ``aangenomen``, ``verworpen``, else ``other``
#   (withdrawn, held, postponed, lapsed, not voted yet).
CHAINS = """
WITH RECURSIVE papers AS (
    SELECT l.id, lg_str(l.props -> 'date') AS date, lg_num(l.props -> 'sequence') AS number
    FROM lg_document_light l
    WHERE json_typeof(l.props -> 'case_kinds') = 'array'
      AND EXISTS (SELECT 1 FROM json_array_elements_text(l.props -> 'case_kinds') k
                  WHERE k = 'Amendement')
),
revises AS (
    SELECT DISTINCT e.from_id AS newer, e.to_id AS older
    FROM edges e
    JOIN papers n ON n.id = e.from_id
    JOIN papers o ON o.id = e.to_id
    WHERE e.relation = %(revises)s
),
chain (chain_id, paper_id) AS (
    SELECT p.id, p.id FROM papers p
    WHERE NOT EXISTS (SELECT 1 FROM revises r WHERE r.older = p.id)
    UNION
    SELECT c.chain_id, r.older FROM chain c JOIN revises r ON r.newer = c.paper_id
),
first AS (
    SELECT c.chain_id,
           (array_agg(p.date ORDER BY p.date ASC NULLS LAST, p.number ASC NULLS LAST))[1]
               AS first_date
    FROM chain c JOIN papers p ON p.id = c.paper_id
    GROUP BY c.chain_id
),
chosen AS (
    SELECT DISTINCT ON (lg_str(d.props -> 'primary_case_id'))
           lg_str(d.props -> 'primary_case_id') AS case_id, d.passed
    FROM decisions d
    WHERE lg_str(d.props -> 'primary_case_id') IS NOT NULL
    ORDER BY lg_str(d.props -> 'primary_case_id') ASC NULLS LAST,
             (d.passed IS NOT NULL) DESC, d.date DESC NULLS LAST, d.key DESC
),
outcome AS (
    SELECT DISTINCT ON (f.chain_id) f.chain_id,
           CASE ch.passed WHEN true THEN 'aangenomen' WHEN false THEN 'verworpen'
                ELSE 'other' END AS outcome
    FROM first f
    JOIN documents doc ON doc.id = f.chain_id
    CROSS JOIN LATERAL json_array_elements_text(
        CASE WHEN json_typeof(doc.props -> 'case_ids') = 'array'
             THEN doc.props -> 'case_ids' ELSE '[]' END) WITH ORDINALITY AS k(case_id, n)
    JOIN chosen ch ON ch.case_id = k.case_id
    ORDER BY f.chain_id ASC NULLS LAST, k.n ASC
)
INSERT INTO lg_amendment_chains (chain_id, paper_id, first_date, outcome)
SELECT c.chain_id, c.paper_id, f.first_date, coalesce(o.outcome, 'other')
FROM chain c
JOIN first f ON f.chain_id = c.chain_id
LEFT JOIN outcome o ON o.chain_id = c.chain_id
"""


def _write_chains(conn: psycopg.Connection) -> int:
    """Write the chains of the amendments again, whole."""
    conn.execute("DELETE FROM lg_amendment_chains")
    written = _execute(conn, CHAINS, {"revises": RELATION_REVISES})
    conn.execute("ANALYZE lg_amendment_chains")
    return written


def write_all(store: GraphStore) -> int:
    """Write every event into a new table with its indexes, which then takes the place of
    the old one in one transaction: a reader sees the old rows or the new, never none."""
    with store.pool.connection() as conn, conn.transaction():
        conn.execute(f"DROP TABLE IF EXISTS {_NEW}")
        conn.execute(f"CREATE TABLE {_NEW} ({FEED_EVENTS_COLUMNS})")
        written = _execute(conn, insert_query(_NEW), {"since": "0"})
        for name, definition in FEED_EVENTS_INDEXES.items():
            conn.execute(definition.format(name=f"{name}_new", table=_NEW))
        conn.execute(f"DROP TABLE IF EXISTS {FEED_EVENTS_TABLE}")
        conn.execute(f"ALTER TABLE {_NEW} RENAME TO {FEED_EVENTS_TABLE}")
        conn.execute(f"ALTER INDEX {_NEW}_pkey RENAME TO {FEED_EVENTS_TABLE}_pkey")
        for name in FEED_EVENTS_INDEXES:
            conn.execute(f"ALTER INDEX {name}_new RENAME TO {name}")
        conn.execute(f"ANALYZE {FEED_EVENTS_TABLE}")
        _write_chains(conn)
        conn.execute(_STATE, {"since": None})
    return written


def write_since(store: GraphStore, since: str) -> int:
    """Write the events dated from *since* again, in place: those of the days a poll
    changes, between two writes of all of them."""
    with store.pool.connection() as conn, conn.transaction():
        conn.execute(
            f"DELETE FROM {FEED_EVENTS_TABLE} WHERE date >= %(since)s", {"since": since}
        )
        written = _execute(conn, insert_query(FEED_EVENTS_TABLE), {"since": since})
        _write_chains(conn)
        conn.execute(_STATE, {"since": since})
    return written


def _execute(conn: psycopg.Connection, statement: str, bind: dict[str, Any]) -> int:
    cursor = conn.execute(statement.encode(), bind)
    return cursor.rowcount


# ── the periods ───────────────────────────────────────────────────────────────

PERIODS = ("month", "day")
# The days a request ``per=day`` may span.
MAX_DAYS = 400


def _period(per: str) -> str:
    """SQL: the first day of the period of a row's date."""
    return "left(e.date, 7) || '-01'" if per == "month" else "left(e.date, 10)"


def word_queries(store: GraphStore, filters: FeedFilters) -> list[str | None]:
    """Per word of ``q`` the ``tsquery`` of the rows that may hold it (``lg_word_query``,
    by the character classes of the database); None for a word without a letter or digit."""
    words = _words_of(filters)
    if not words:
        return []
    statement = ", ".join(
        f"lg_word_query(%(q_{n})s, %(w_{n})s)::text" for n in range(len(words))
    )
    bind: dict[str, Any] = {}
    for n, word in enumerate(words):
        bind[f"q_{n}"] = word
        bind[f"w_{n}"] = _whole(word)
    with store.pool.connection() as conn:
        row = conn.execute(f"SELECT {statement}", bind).fetchone()
    return list(row or ())


def _whole(word: str) -> bool:
    """Whether the feed matches *word* as a whole word (``_words.word_pattern``)."""
    return len(word) <= _words.WHOLE_WORD_MAX and word[-1:].isalnum()


def _words_filter(
    filters: FeedFilters, queries: list[str | None], bind: dict[str, Any]
) -> str | None:
    """SQL: the rows that hold any word of ``q`` in their title or that of their first
    dossier, as the feed matches it (``_words.holds``): found by ``words`` when every word
    has a query (*queries*), else tested row by row."""
    words = _words_of(filters)
    if not words:
        return None
    holds = []
    for n, word in enumerate(words):
        bind[f"q_word_{n}"] = _words.word_pattern(word)
        holds.append(f"e.title ~ %(q_word_{n})s OR e.dossier_title ~ %(q_word_{n})s")
    exact = " OR ".join(holds)
    if len(queries) != len(words) or any(q is None for q in queries):
        return f"({exact})"
    bind["words"] = " | ".join(f"({q})" for q in queries)
    return f"e.words @@ %(words)s::tsquery AND ({exact})"


def _matching(
    filters: FeedFilters, queries: list[str | None] | None
) -> tuple[str, list[str], dict[str, Any]]:
    """The CTEs, conditions (on ``e``) and parameters of the rows of ``lg_feed_events``
    under *filters*: every kind unless ``kinds`` names some."""
    bind: dict[str, Any] = {"since": filters.since or "0"}
    where = ["e.date >= %(since)s"]
    ctes = ""
    if filters.until:
        # as the feed bounds a kind's dates
        where.append("e.date <= %(until)s")
        bind["until"] = filters.until
    if filters.kinds:
        where.append("e.kind = ANY(%(kinds)s)")
        bind["kinds"] = list(filters.kinds)
    if filters.chamber:
        where.append("e.chamber = %(chamber)s")
        bind["chamber"] = filters.chamber
    if filters.ministry:
        where.append("e.ministry = %(ministry)s")
        bind["ministry"] = filters.ministry
    if filters.faction:
        where.append("e.factions @> ARRAY[%(faction)s]::text[]")
        bind["faction"] = filters.faction
    if filters.dossier:
        where.append(
            "EXISTS (SELECT 1 FROM unnest(e.labels) AS label"
            " WHERE starts_with(label, %(dossier)s))"
        )
        bind["dossier"] = filters.dossier
    if filters.cabinet:
        ctes = "WITH " + _CABINET_PERIOD.lstrip(",\n ")
        where.append(_IN_PERIOD.replace("{date}", "e.date"))
        bind["cabinet"] = filters.cabinet
    words = _words_filter(filters, queries or [], bind)
    if words:
        where.append(words)
    return ctes, where, bind


def periods_query(
    filters: FeedFilters, per: str, queries: list[str | None] | None = None
) -> tuple[str, dict[str, Any]]:
    """SQL and parameters: per period (``per``) and kind the events under *filters*, from
    ``lg_feed_events``. Every kind is counted unless ``kinds`` names some."""
    ctes, where, bind = _matching(filters, queries)
    period = _period(per)
    return (
        f"""{ctes}
        SELECT {period} AS period, e.kind, count(*)::int AS n
        FROM {FEED_EVENTS_TABLE} e
        WHERE {" AND ".join(f"({clause})" for clause in where)}
        GROUP BY 1, 2
        ORDER BY 1 ASC NULLS LAST, 2 ASC NULLS LAST""",
        bind,
    )


# The days back from the day the events were last written that a poll writes again
# (``scripts/poll.sh``: ``feed-events --days 14``): what the table may lack is dated in them.
RECENT_DAYS = 14


def first_day_of_page(
    store: GraphStore, filters: FeedFilters, limit: int, before: str | None
) -> tuple[str, bool] | None:
    """The first day the page of the feed under *filters* (with words, without a first day)
    reaches back to, and whether the table holds a whole page: the day of the
    ``limit + 1``-th newest event that matches them in ``lg_feed_events``, of those before
    the day *before* (a cursor's: its own day is read whole), else of the oldest; no later
    than ``RECENT_DAYS`` before today (what the table may lack yet). None where the table
    cannot tell: never written, or a filter it does not keep. The feed then reads its page
    from that day on, once, instead of window after window."""
    if unsupported(filters):
        return None
    state = "SELECT written_at FROM lg_feed_events_state WHERE id"
    if next(iter(store.query(state)), None) is None:
        return None
    ctes, where, bind = _matching(filters, word_queries(store, filters))
    if before:
        where.append("e.date < %(before)s")
        bind["before"] = before
    bind["n"] = limit
    condition = " AND ".join(f"({clause})" for clause in where)
    row = (
        next(
            iter(
                store.query(
                    f"""{ctes}
                SELECT
                    (SELECT e.date FROM {FEED_EVENTS_TABLE} e WHERE {condition}
                     ORDER BY e.date DESC NULLS LAST LIMIT 1 OFFSET %(n)s) AS nth,
                    (SELECT min(e.date) FROM {FEED_EVENTS_TABLE} e WHERE {condition})
                        AS oldest""",
                    bind,
                )
            ),
            None,
        )
        or {}
    )
    found = row.get("nth") or row.get("oldest")
    recent = (dt.date.today() - dt.timedelta(days=RECENT_DAYS)).isoformat()
    day = min(str(found)[:10], recent) if found else recent
    return day, row.get("nth") is not None


# How long the periods under a filter are kept (seconds). They are kept per writing of the
# events too (``written_at`` is part of the key): a new writing is counted at once.
PERIODS_MAX_AGE = 3600.0


def get_periods(store: GraphStore, filters: FeedFilters, per: str) -> dict[str, Any]:
    """``periods`` (oldest first: ``period``, ``total``, ``counts`` per kind, in the order
    of ``FEED_KINDS``) and ``written_at``, when the events were last written (None: never,
    and so no periods). Kept per filter and writing (``lasting``): the whole feed by month
    counts every row."""
    written = next(
        iter(store.query("SELECT written_at FROM lg_feed_events_state WHERE id")), None
    )
    if written is None:
        return {"periods": [], "written_at": None}
    periods = lasting(
        store,
        ("feed periods", filters, per, written),
        lambda: _count(store, filters, per),
        PERIODS_MAX_AGE,
    )
    return {"periods": periods, "written_at": written}


def _count(store: GraphStore, filters: FeedFilters, per: str) -> list[dict[str, Any]]:
    queries = word_queries(store, filters)
    statement, bind = periods_query(filters, per, queries)
    rows = list(store.query(statement, bind))
    by_period: dict[str, dict[str, int]] = {}
    for row in rows:
        by_period.setdefault(row["period"], {})[row["kind"]] = row["n"]
    chains = (
        _count_chains(store, filters, per, queries)
        if not filters.kinds or AMENDMENT in filters.kinds
        else None
    )
    order = {kind: n for n, kind in enumerate(FEED_KINDS)}
    periods = sorted(set(by_period) | set(chains or {}))
    return [
        {
            "period": period,
            "total": sum(by_period.get(period, {}).values()),
            "counts": dict(
                sorted(
                    by_period.get(period, {}).items(),
                    key=lambda kv: order.get(kv[0], 99),
                )
            ),
            **(
                {"amendment_chains": chains.get(period) or _no_chains()}
                if chains is not None
                else {}
            ),
        }
        for period in periods
    ]


# The kind of event of an amendment (``core.feed``): its chains are counted beside it.
AMENDMENT = "Amendement"
OUTCOMES = ("aangenomen", "verworpen", "other")


def _no_chains() -> dict[str, int]:
    return {"count": 0, **dict.fromkeys(OUTCOMES, 0)}


def _count_chains(
    store: GraphStore, filters: FeedFilters, per: str, queries: list[str | None]
) -> dict[str, dict[str, int]]:
    """Per period the chains of the amendments (``lg_amendment_chains``) of which any paper
    is an event under *filters* (of whatever day), each once, in the period of its first
    paper and by its outcome."""
    ctes, where, bind = _matching(
        replace(filters, kinds=(AMENDMENT,), since=None, until=None), queries
    )
    bind["since"] = filters.since or "0"
    period = _period(per).replace("e.date", "c.first_date")
    days = ["c.first_date >= %(since)s"]
    if filters.until:
        days.append("c.first_date <= %(until)s")
        bind["until"] = filters.until
    condition = " AND ".join(f"({clause})" for clause in where)
    rows = store.query(
        f"""{ctes}
        SELECT {period} AS period, c.outcome, count(DISTINCT c.chain_id)::int AS n
        FROM lg_amendment_chains c
        WHERE c.paper_id IN (SELECT e.id FROM {FEED_EVENTS_TABLE} e WHERE {condition})
          AND {" AND ".join(days)}
        GROUP BY 1, 2""",
        bind,
    )
    found: dict[str, dict[str, int]] = {}
    for row in rows:
        counts = found.setdefault(row["period"], _no_chains())
        counts[row["outcome"]] += row["n"]
        counts["count"] += row["n"]
    return found


def unsupported(filters: FeedFilters) -> list[str]:
    """The filters of the feed that ``lg_feed_events`` does not keep."""
    found = []
    if filters.member:
        found.append("member")
    if filters.tiers:
        found.append("tier")
    return found
