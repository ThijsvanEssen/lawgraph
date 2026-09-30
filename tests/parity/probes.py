"""Probes P1–P5: where ArangoDB and PostgreSQL differ in what a query returns.

Each probe asks both servers the same question on the same literal data and prints both
answers and whether they agree, so the translation rules of the port (json key order,
collation, analyzers, grouping and order without SORT) rest on what the servers do, not on
what their manuals say. Writes only to scratch databases of its own on the test servers
(Arango 8530, PostgreSQL 5433) and drops them afterwards:

    python -m tests.parity.probes
"""

from __future__ import annotations

import json
import os
import random
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from arango.client import ArangoClient
from arango.database import StandardDatabase

from lawgraph.config import settings
from lawgraph.db.schema import ensure_schema

ARANGO_URL = os.environ.get("LAWGRAPH_TEST_ARANGO_URL", "http://localhost:8530")
PG_URL = os.environ.get(
    "LAWGRAPH_TEST_DB_URL",
    "postgresql://lawgraph:lawgraph-test@localhost:5433/lawgraph",
)

# ICU root with upper case first: how ArangoDB sorts and compares strings (probe P2).
COLLATION = "und-u-kf-upper"

Probe = Callable[[StandardDatabase, psycopg.Connection], list[tuple[str, Any, Any]]]


@contextmanager
def scratch_arango() -> Iterator[StandardDatabase]:
    client = ArangoClient(hosts=ARANGO_URL)
    auth = {"username": settings.ARANGO_USER, "password": settings.ARANGO_PASSWORD}
    system = client.db("_system", **auth)
    name = f"lawgraph_probe_{uuid.uuid4().hex[:8]}"
    system.create_database(name)
    try:
        db = client.db(name, **auth)
        ensure_schema(db)
        yield db
    finally:
        system.delete_database(name)


@contextmanager
def scratch_pg() -> Iterator[psycopg.Connection]:
    name = f"lawgraph_probe_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(PG_URL, autocommit=True) as admin:
        admin.execute(
            f"CREATE DATABASE {name} TEMPLATE template0 LOCALE_PROVIDER icu"
            f" ICU_LOCALE '{COLLATION}' LOCALE 'C.UTF-8'"
        )
        try:
            base = PG_URL.rsplit("/", 1)[0]
            with psycopg.connect(f"{base}/{name}", autocommit=True) as conn:
                yield conn
        finally:
            admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


def aql(db: StandardDatabase, query: str, **bind: Any) -> list[Any]:
    return list(db.aql.execute(query, bind_vars=bind))  # type: ignore[union-attr]


def sql(conn: psycopg.Connection, query: str, *params: Any) -> list[Any]:
    rows = conn.execute(query, params or None).fetchall()  # type: ignore[arg-type]
    return [row[0] if len(row) == 1 else list(row) for row in rows]


# ── P1: key order of objects ─────────────────────────────────────────────────

# MERGE as ArangoDB does it: the keys of the left object in byte order, then the keys only
# the right one has, in its order. ArangoDB takes the latter from a hash map, so with two or
# more new keys its order is the hash order; those rows are expected to differ.
LG_MERGE = """
CREATE FUNCTION lg_merge(a json, b json) RETURNS json LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(json_object_agg(key, value ORDER BY grp, sort_key COLLATE "C", ord),
                    '{}'::json)
    FROM (
        SELECT l.key, coalesce(r.value, l.value) AS value, 0 AS grp, l.key AS sort_key,
               0::bigint AS ord
        FROM json_each(a) AS l(key, value)
        LEFT JOIN json_each(b) AS r(key, value) USING (key)
        UNION ALL
        SELECT r.key, r.value, 1, '', r.ord
        FROM json_each(b) WITH ORDINALITY AS r(key, value, ord)
        WHERE r.key NOT IN (SELECT key FROM json_each(a))
    ) merged
$$
"""

MERGES = [
    ("{zeta: 1, b: 2}", "{alpha: 3}"),
    ("{b: 1, a: 2, c: 3}", "{a: 20, d: 4}"),
    ("{b: 1, B: 2, aa: 3, a: 4, _z: 5, '10': 6, '9': 7, 'é': 8}", "{}"),
    ("{zeta: {y: 1, x: 2}, b: 1}", "{c: 1}"),
    ("{}", "{zeta: 1, b: 2}"),
    ("{zeta: 1, b: 2}", "{c: 2, y: 1}"),
    ("{zeta: 1, b: 2}", "{y: 1, c: 2, a: 3}"),
]


def _json_text(aql_object: str) -> str:
    quoted = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', aql_object)
    return quoted.replace("'", '"')


def p1_key_order(
    db: StandardDatabase, pg: psycopg.Connection
) -> list[tuple[str, Any, Any]]:
    tally = {"voor": 76, "tegen": 74, "niet_deelgenomen": 0}
    decisions = db.collection("decisions")
    decisions.insert({"_key": "d1", "props": {"z": 1, "tally": tally, "a": 2}})
    pg.execute("CREATE TABLE decisions (id text PRIMARY KEY, props json, propsb jsonb)")
    doc = json.dumps({"z": 1, "tally": tally, "a": 2})
    pg.execute("INSERT INTO decisions VALUES ('d1', %s, %s)", (doc, doc))
    pg.execute(LG_MERGE)
    stored = aql(db, "RETURN DOCUMENT('decisions/d1').props")[0]
    literal = aql(db, "RETURN {zeta: 1, alpha: 2, mid: {b: 1, a: 2}}")[0]
    rows = [
        ("stored props / json", stored, sql(pg, "SELECT props FROM decisions")[0]),
        ("stored props / jsonb", stored, sql(pg, "SELECT propsb FROM decisions")[0]),
        (
            "object literal / json_build_object",
            literal,
            sql(
                pg,
                "SELECT json_build_object('zeta', 1, 'alpha', 2, 'mid',"
                " json_build_object('b', 1, 'a', 2))",
            )[0],
        ),
        (
            "object literal / jsonb_build_object",
            literal,
            sql(
                pg,
                "SELECT jsonb_build_object('zeta', 1, 'alpha', 2, 'mid',"
                " jsonb_build_object('b', 1, 'a', 2))",
            )[0],
        ),
        (
            "KEEP / json_build_object with the keys in byte order",
            aql(db, "RETURN KEEP({zeta: 1, b: 2, alpha: 3}, 'zeta', 'alpha')")[0],
            sql(pg, "SELECT json_build_object('alpha', 3, 'zeta', 1)")[0],
        ),
    ]
    for left, right in MERGES:
        rows.append(
            (
                f"MERGE({left}, {right}) / lg_merge",
                aql(db, f"RETURN MERGE({left}, {right})")[0],
                sql(pg, "SELECT lg_merge(%s, %s)", _json_text(left), _json_text(right))[
                    0
                ],
            )
        )
    # The node writer updates with MERGE(OLD.props, @props) and mergeObjects: false.
    decisions.insert({"_key": "d2", "props": {"zeta": {"y": 1, "x": 2}, "b": 2}})
    aql(
        db,
        "UPDATE 'd2' WITH {props: MERGE(DOCUMENT('decisions/d2').props, {alpha: 3})}"
        " IN decisions OPTIONS {mergeObjects: false}",
    )
    rows.append(
        (
            "stored props after an upsert update / lg_merge",
            aql(db, "RETURN DOCUMENT('decisions/d2').props")[0],
            sql(
                pg,
                """SELECT lg_merge('{"zeta": {"y": 1, "x": 2}, "b": 2}', '{"alpha": 3}')""",
            )[0],
        )
    )
    return rows


# ── P2: collation ────────────────────────────────────────────────────────────

STRINGS = [
    "Wet",
    "wet",
    "WET",
    "Wét",
    "wet ",
    "wet-",
    "Wetboek",
    "wetboek van Strafrecht",
    "Wet op de ...",
    "Wet  dubbel",
    "Wet_x",
    "Wet.x",
    "Wet'x",
    "Ärztekammer",
    "Aa",
    "aa",
    "ab",
    "Ab",
    "a",
    "b",
    "B",
    "",
    " ",
    "1",
    "10",
    "2",
    "9a",
    "1:2",
    "1a",
    "1 a",
    "art. 1",
    "art. 10",
    "art. 2",
    "IJssel",
    "Ijssel",
    "ijs",
    "Ĳssel",
    "Zwolle",
    "zz",
    "é",
    "e",
    "f",
    "Œuvre",
    "Øresund",
    "ß",
    "ss",
    "(haakje",
    "[blok",
    "#hash",
    "~tilde",
    "€ euro",
    "ω",
    "Ω",
    "BWBR0001840",
    "BWBR0001854",
    "bwbr0001840",
    "ECLI:NL:HR:2020:1",
    "ECLI:NL:HR:2020:10",
    "ECLI:NL:HR:2020:2",
    "CDA",
    "CU",
    "ChristenUnie",
    "D66",
    "GL-PvdA",
    "GroenLinks-PvdA",
    "PVV",
    "PvdD",
    "VVD",
    "50PLUS",
    "JA21",
    "van Dijk",
    "Van Dijk",
    "Dijk",
    "de Jong",
    "Jong",
    "’s-Gravenhage",
    "'s-Gravenhage",
    "s-Gravenhage",
]
COLLATIONS = [
    "default",
    "und-x-icu",
    "nl-NL-x-icu",
    "C",
    "und-u-kf-upper",
    "nl-u-kf-upper",
]
PAIRS = [
    ("a", "B"),
    ("Wet", "wet"),
    ("1", "10"),
    ("", " "),
    ("IJssel", "Ijssel"),
    ("e", "é"),
]


def p2_collation(
    db: StandardDatabase, pg: psycopg.Connection
) -> list[tuple[str, Any, Any]]:
    for name in ("und-u-kf-upper", "nl-u-kf-upper"):
        pg.execute(f"CREATE COLLATION \"{name}\" (provider = icu, locale = '{name}')")
    arango = aql(db, "FOR s IN @l SORT s RETURN s", l=STRINGS)
    rows = []
    for name in COLLATIONS:
        collate = f' COLLATE "{name}"' if name != "default" else ""
        query = f"SELECT s FROM unnest(%s::text[]) AS s ORDER BY s{collate}"
        rows.append(
            (
                f"SORT / ORDER BY{collate or ' (database default)'}",
                arango,
                sql(pg, query, STRINGS),
            )
        )
    rows.append(
        (
            'SORT DESC / ORDER BY DESC COLLATE "und-u-kf-upper"',
            aql(db, "FOR s IN @l SORT s DESC RETURN s", l=STRINGS),
            sql(
                pg,
                'SELECT s FROM unnest(%s::text[]) AS s ORDER BY s COLLATE "und-u-kf-upper"'
                " DESC",
                STRINGS,
            ),
        )
    )
    compare = 'SELECT %s::text < %s::text COLLATE "und-u-kf-upper", %s::text = %s::text'
    rows.append(
        (
            'a < b, a == b / COLLATE "und-u-kf-upper"',
            aql(db, "FOR p IN @p RETURN [p[0] < p[1], p[0] == p[1]]", p=PAIRS),
            [sql(pg, compare, a, b, a, b)[0] for a, b in PAIRS],
        )
    )
    values = [None, "b", "A", None, "a"]
    rows += [
        (
            "SORT with null / NULLS FIRST",
            aql(db, "FOR v IN @v SORT v RETURN v", v=values),
            sql(
                pg,
                'SELECT v FROM unnest(%s::text[]) AS v ORDER BY v COLLATE "und-u-kf-upper"'
                " NULLS FIRST",
                values,
            ),
        ),
        (
            "SORT DESC with null / DESC NULLS LAST",
            aql(db, "FOR v IN @v SORT v DESC RETURN v", v=values),
            sql(
                pg,
                'SELECT v FROM unnest(%s::text[]) AS v ORDER BY v COLLATE "und-u-kf-upper"'
                " DESC NULLS LAST",
                values,
            ),
        ),
        (
            "SORT with null / ORDER BY (PostgreSQL default)",
            aql(db, "FOR v IN @v SORT v RETURN v", v=values),
            sql(
                pg,
                'SELECT v FROM unnest(%s::text[]) AS v ORDER BY v COLLATE "und-u-kf-upper"',
                values,
            ),
        ),
        (
            "LOWER / lower()",
            aql(db, "RETURN [LOWER('ÄÉ IJ Ĳ ẞ Ω'), UPPER('ß é')]")[0],
            sql(pg, "SELECT ARRAY[lower('ÄÉ IJ Ĳ ẞ Ω'), upper('ß é')]")[0],
        ),
    ]
    return rows


# ── P3: analyzers ────────────────────────────────────────────────────────────

# text_nl as SQL: fold (lower case, combining marks off, as the norm analyzers do), cut into
# words as ArangoDB does (letters and digits; ':' and apostrophes join letters, '.' and ','
# join digits), then the Dutch snowball stemmer without stop words.
LAWGRAPH_NL = r"""
CREATE TEXT SEARCH DICTIONARY lawgraph_dutch (TEMPLATE = snowball, Language = dutch);
CREATE FUNCTION lg_fold(t text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT normalize(regexp_replace(normalize(lower(t), NFD), '[̀-ͯ]', '', 'g'), NFC)
$$;
CREATE FUNCTION lg_tokens(t text) RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(
        array_agg(coalesce((ts_lexize('lawgraph_dutch', m[1]))[1], m[1]) ORDER BY o), '{}')
    FROM regexp_matches(
        lg_fold(t),
        '([[:alnum:]_]+(?:(?:(?<=[[:alpha:]])[:''’](?=[[:alpha:]])'
        '|(?<=[[:digit:]])[.,](?=[[:digit:]]))[[:alnum:]_]+)*)',
        'g'
    ) WITH ORDINALITY AS r(m, o)
$$;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE TEXT SEARCH CONFIGURATION lawgraph_parser (COPY = simple);
ALTER TEXT SEARCH CONFIGURATION lawgraph_parser
    ALTER MAPPING FOR asciiword, word, hword, hword_part, asciihword, hword_asciipart
    WITH unaccent, lawgraph_dutch;
"""

TEXTS = [
    "De Wet op de rechterlijke organisatie en de Algemene wet bestuursrecht",
    "Het Wetboek van Strafvordering is gewijzigd; de wijzigingen treden in werking.",
    "Artikel 3:4 Awb, art. 6:162 BW en artikel 1a lid 2 onder b",
    "ECLI:NL:HR:2020:1234 en BWBR0001840",
    "Zo'n café, één reünie, ´s-Gravenhage en coördinatie van naïeve ideeën",
    "Aanbestedingswet 2012 (Aw 2012), e.v. en t/m 1-1-2020",
    "gemeenten gemeente gemeentelijke kinderen kinderopvang",
    "niet nietig vernietigd vernietiging",
    "€ 1.000,50 en 3.4, a.b.c, x-y, art.1, A.B. Jansen, zo’n, d66, 50PLUS, foo_bar, C-123/45",
    "HR:2020, www.rechtspraak.nl, info@x.nl, 1e, 2°",
    "Kamerstukken II 2019/20, 35 300 VI, nr. 12; Stb. 2021, 234 (Ω, ß, æ, Œ, Ĳ, ﬁ, café's)",
    "HR 13-03-2020, NJ 2020/123 m.nt. A.C. van Schaik §3.2 1°. 'quoted' \"dq\" x—y x–y",
]


def p3_analyzers(
    db: StandardDatabase, pg: psycopg.Connection
) -> list[tuple[str, Any, Any]]:
    pg.execute(LAWGRAPH_NL)
    rows = []
    for text in TEXTS:
        arango = aql(db, "RETURN TOKENS(@t, 'text_nl')", t=text)[0]
        rows.append(
            (
                f"text_nl / lg_tokens: {text[:40]}",
                arango,
                sql(pg, "SELECT lg_tokens(%s)", text)[0],
            )
        )
    for text in TEXTS[3:5]:
        parser = sql(
            pg,
            "SELECT array(SELECT unnest(tsvector_to_array("
            "to_tsvector('lawgraph_parser', %s))))",
            text,
        )[0]
        rows.append(
            (
                f"text_nl / the PostgreSQL parser (sets): {text[:40]}",
                sorted(set(aql(db, "RETURN TOKENS(@t, 'text_nl')", t=text)[0])),
                sorted(parser),
            )
        )
    for text in [
        "BWBR0001840",
        "Wét op de Ärzte",
        "ECLI:NL:HR:2020:1",
        "Straße Æ ’s-Gravenhage ﬁ",
    ]:
        rows.append(
            (
                f"lawgraph_norm / lg_fold: {text}",
                aql(db, "RETURN TOKENS(@t, 'lawgraph_norm')", t=text)[0],
                [sql(pg, "SELECT lg_fold(%s)", text)[0]],
            )
        )
    haystack = "Wetboek van Strafvordering"
    for needle in [
        "Vordering",
        "strafv",
        "boek van",
        "vorderingen",
        "wét",
        "Wetboek van Straf",
    ]:
        arango = aql(
            db,
            "LET h = TOKENS(@h, 'lawgraph_ngram_v2') LET n = TOKENS(@n, 'lawgraph_ngram_v2')"
            " RETURN LENGTH(n) > 0 AND LENGTH(MINUS(n, h)) == 0",
            h=haystack,
            n=needle,
        )[0]
        postgres = sql(
            pg, "SELECT strpos(lg_fold(%s), lg_fold(%s)) > 0", haystack, needle
        )[0]
        rows.append(
            (f"ngram / substring: {needle!r} in {haystack!r}", arango, postgres)
        )
    return rows


# ── P4: COLLECT without SORT ─────────────────────────────────────────────────

GROUP_VALUES = ["b", None, "A", "a", "", "B", "a", None, "10", "9", "Ä", "b"]


def p4_collect(
    db: StandardDatabase, pg: psycopg.Connection
) -> list[tuple[str, Any, Any]]:
    arango = aql(
        db, "FOR v IN @v COLLECT k = v WITH COUNT INTO n RETURN [k, n]", v=GROUP_VALUES
    )
    unordered = sql(
        pg,
        "SELECT k, count(*)::int FROM unnest(%s::text[]) AS k GROUP BY k",
        GROUP_VALUES,
    )
    ordered = sql(
        pg,
        "SELECT k, count(*)::int FROM unnest(%s::text[]) AS k GROUP BY k"
        " ORDER BY k NULLS FIRST",
        GROUP_VALUES,
    )
    random.seed(4)
    items = [{"g": random.choice("xyz"), "v": i} for i in range(30)]
    random.shuffle(items)
    arango_into = aql(
        db, "FOR i IN @items COLLECT g = i.g INTO vs = i.v RETURN [g, vs]", items=items
    )
    pg_agg = sql(
        pg,
        "SELECT g, array_agg(v ORDER BY ord) FROM ROWS FROM"
        " (json_to_recordset(%s::json) AS (g text, v int)) WITH ORDINALITY AS t(g, v, ord)"
        " GROUP BY g ORDER BY g",
        json.dumps(items),
    )
    return [
        ("COLLECT / GROUP BY (no ORDER BY)", arango, unordered),
        ("COLLECT / GROUP BY … ORDER BY k NULLS FIRST", arango, ordered),
        (
            "COLLECT INTO keeps input order / array_agg(… ORDER BY ord)",
            arango_into,
            pg_agg,
        ),
    ]


# ── P5: LIMIT without SORT ───────────────────────────────────────────────────


def p5_limit(
    db: StandardDatabase, pg: psycopg.Connection
) -> list[tuple[str, Any, Any]]:
    random.seed(5)
    keys = [f"k{n:04d}" for n in range(2000)]
    random.shuffle(keys)
    docs = [
        {"_key": k, "props": {"kind": "a" if n % 3 else "b", "n": n}}
        for n, k in enumerate(keys)
    ]
    db.collection("documents").import_bulk(docs)
    pg.execute("CREATE TABLE documents (id text PRIMARY KEY, kind text, n int)")
    with pg.cursor().copy("COPY documents (id, kind, n) FROM STDIN") as copy:
        for d in docs:
            copy.write_row((d["_key"], d["props"]["kind"], d["props"]["n"]))
    pg.execute("CREATE INDEX ON documents (kind)")
    pg.execute("ANALYZE documents")
    first = [
        (
            "LIMIT 5 on a collection scan",
            aql(db, "FOR d IN documents LIMIT 5 RETURN d._key"),
            sql(pg, "SELECT id FROM documents LIMIT 5"),
        ),
        (
            "FILTER kind LIMIT 5",
            aql(
                db,
                "FOR d IN documents FILTER d.props.kind == 'b' LIMIT 5 RETURN d._key",
            ),
            sql(pg, "SELECT id FROM documents WHERE kind = 'b' LIMIT 5"),
        ),
    ]
    # Update the first rows: Arango keeps its order, a PostgreSQL heap moves them.
    aql(
        db,
        "FOR d IN documents LIMIT 100 UPDATE d WITH {props: {touched: true}} IN documents",
    )
    pg.execute(
        "UPDATE documents SET n = n + 0 WHERE id IN "
        "(SELECT id FROM documents LIMIT 100)"
    )
    return first + [
        (
            "LIMIT 5 after updating the first 100",
            aql(db, "FOR d IN documents LIMIT 5 RETURN d._key"),
            sql(pg, "SELECT id FROM documents LIMIT 5"),
        ),
        (
            "SORT _key LIMIT 5 / ORDER BY id LIMIT 5",
            aql(db, "FOR d IN documents SORT d._key LIMIT 5 RETURN d._key"),
            sql(pg, "SELECT id FROM documents ORDER BY id LIMIT 5"),
        ),
    ]


PROBES: list[tuple[str, Probe]] = [
    ("P1 key order", p1_key_order),
    ("P2 collation", p2_collation),
    ("P3 analyzers", p3_analyzers),
    ("P4 COLLECT without SORT", p4_collect),
    ("P5 LIMIT without SORT", p5_limit),
]


def main() -> None:
    for title, probe in PROBES:
        print(f"\n## {title}\n")
        with scratch_arango() as db, scratch_pg() as pg:
            for label, arango, postgres in probe(db, pg):
                same = json.dumps(arango) == json.dumps(postgres)
                print(f"- [{'same' if same else 'DIFFERS'}] {label}")
                if not same:
                    print(f"    arango:   {json.dumps(arango, ensure_ascii=False)}")
                    print(f"    postgres: {json.dumps(postgres, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
