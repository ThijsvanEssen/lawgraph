"""PostgreSQL schema: a table per collection, the edges, the SQL helpers and the data version.

Every node collection is a table of the same shape: ``id`` (``collection/key``, the key of the
graph), ``key``, ``type``, ``labels`` and ``props``. ``props`` is ``json``, not ``jsonb``: the
API serves props as they are, and ``jsonb`` sorts the keys of an object (probe P1). What the
queries filter, sort or count on is a STORED generated column of its own, with the indexes
the ArangoDB schema had on it.

Strings sort and compare as in ArangoDB: the database is created with the ICU root collation
with upper case first (``und-u-kf-upper``, probe P2); ``lg_tokens`` cuts and stems words as
the ``text_nl`` analyzer does (probe P3).

Everything here is idempotent: ``ensure_schema`` runs on every connect.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    COLLECTION_PIPELINE_STATE,
    COLLECTION_RAW_SOURCES,
)

# The collation of the database: how ArangoDB sorts and compares strings (probe P2).
COLLATION = "und-u-kf-upper"

# The node collections: every collection but the raw records, the pipeline state and the
# edges, which have tables of their own.
NODE_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_INSTRUMENTS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_ACTIVITIES,
    COLLECTION_DECISIONS,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_MEMBERS,
    COLLECTION_FACTIONS,
    COLLECTION_CABINETS,
    COLLECTION_ANNEXES,
)

# ── SQL helpers ──────────────────────────────────────────────────────────────

FUNCTIONS = r"""
-- The value of a props field, only when it has the type the column holds: a string, a
-- number or a boolean; anything else is NULL, as ArangoDB compares values of another type
-- unequal.
CREATE OR REPLACE FUNCTION lg_str(v json) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN json_typeof(v) = 'string' THEN v #>> '{}' END
$$;
CREATE OR REPLACE FUNCTION lg_num(v json) RETURNS double precision
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN json_typeof(v) = 'number' THEN (v #>> '{}')::double precision END
$$;
CREATE OR REPLACE FUNCTION lg_bool(v json) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN json_typeof(v) = 'boolean' THEN (v #>> '{}')::boolean END
$$;

-- The strings of a JSON array, in order (``doc.props.subjects[*]``); NULL for another type.
CREATE OR REPLACE FUNCTION lg_text_array(v json) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN json_typeof(v) = 'array' THEN ARRAY(
        SELECT e #>> '{}' FROM json_array_elements(v) WITH ORDINALITY AS a(e, n)
        WHERE json_typeof(e) = 'string' ORDER BY n
    ) END
$$;

-- The string *field* of every object of a JSON array (``[*].cabinet_key``).
CREATE OR REPLACE FUNCTION lg_path_array(v json, field text) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN json_typeof(v) = 'array' THEN ARRAY(
        SELECT e ->> field FROM json_array_elements(v) WITH ORDINALITY AS a(e, n)
        WHERE json_typeof(e) = 'object' AND json_typeof(e -> field) = 'string' ORDER BY n
    ) END
$$;

-- MERGE(a, b) as ArangoDB does it (probe P1): the keys of *a* in byte order with the values
-- of *b* where it has them, then the keys only *b* has, in its order. (ArangoDB takes those
-- from a hash map, so with two or more new keys its order is arbitrary.)
CREATE OR REPLACE FUNCTION lg_merge(a json, b json) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(json_object_agg(key, value ORDER BY grp, sort_key COLLATE "C", ord),
                    '{}'::json)
    FROM (
        SELECT l.key, coalesce(r.value, l.value) AS value, 0 AS grp, l.key AS sort_key,
               0::bigint AS ord
        FROM json_each(coalesce(a, '{}')) AS l(key, value)
        LEFT JOIN json_each(coalesce(b, '{}')) AS r(key, value) USING (key)
        UNION ALL
        SELECT r.key, r.value, 1, '', r.ord
        FROM json_each(coalesce(b, '{}')) WITH ORDINALITY AS r(key, value, ord)
        WHERE r.key NOT IN (SELECT key FROM json_each(coalesce(a, '{}')))
    ) merged
$$;

-- UNIQUE(APPEND(a, b)) and UNION_DISTINCT: every value once, where it first occurs.
CREATE OR REPLACE FUNCTION lg_array_union(a text[], b text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(v ORDER BY first), '{}')
    FROM (
        SELECT v, min(n) AS first
        FROM unnest(coalesce(a, '{}') || coalesce(b, '{}')) WITH ORDINALITY AS u(v, n)
        GROUP BY v
    ) once
$$;

-- The norm analyzers: lower case, combining marks off (not unaccent, which also rewrites
-- ß, æ and the typographic apostrophe; probe P3).
CREATE OR REPLACE FUNCTION lg_fold(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT normalize(regexp_replace(normalize(lower(t), NFD), '[̀-ͯ]', '', 'g'), NFC)
$$;

-- text_nl: the folded text cut into words as ArangoDB does (letters, digits and '_'; ':'
-- and apostrophes join letters, '.' and ',' join digits), each word stemmed by the Dutch
-- snowball stemmer without stop words. In order, with repeats (probe P3).
CREATE OR REPLACE FUNCTION lg_tokens(t text) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(
        array_agg(coalesce((ts_lexize('lawgraph_dutch', m[1]))[1], m[1]) ORDER BY o), '{}')
    FROM regexp_matches(
        lg_fold(t),
        '([[:alnum:]_]+(?:(?:(?<=[[:alpha:]])[:''’](?=[[:alpha:]])'
        '|(?<=[[:digit:]])[.,](?=[[:digit:]]))[[:alnum:]_]+)*)',
        'g'
    ) WITH ORDINALITY AS r(m, o)
$$;
"""

DICTIONARY = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_dict WHERE dictname = 'lawgraph_dutch') THEN
        CREATE TEXT SEARCH DICTIONARY lawgraph_dutch (TEMPLATE = snowball, Language = dutch);
    END IF;
END $$
"""

# ── node tables ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Column:
    """A generated column of a node table: *name*, its SQL type and the props it holds."""

    name: str
    sql_type: str
    expression: str


def _str(field: str, name: str | None = None) -> Column:
    return Column(name or field, "text", f"lg_str(props -> '{field}')")


def _num(field: str) -> Column:
    return Column(field, "double precision", f"lg_num(props -> '{field}')")


def _bool(field: str) -> Column:
    return Column(field, "boolean", f"lg_bool(props -> '{field}')")


def _strings(field: str) -> Column:
    return Column(field, "text[]", f"lg_text_array(props -> '{field}')")


# collection -> the props it is filtered, sorted and counted on (the persistent indexes of
# the ArangoDB schema).
COLUMNS: dict[str, tuple[Column, ...]] = {
    COLLECTION_INSTRUMENTS: (
        _str("bwb_id"),
        _str("celex"),
        _str("jurisdiction"),
        _str("kind"),
        _num("article_count"),
        _bool("stub"),
        _str("citation_title"),
        _str("treaty_number"),
        _str("date_published"),
    ),
    COLLECTION_ARTICLES: (
        _str("bwb_id"),
        _str("celex"),
        _str("article_number"),
        _str("stam_id"),
        _num("inbound_citation_count"),
        _bool("stub"),
    ),
    COLLECTION_INSTRUMENT_VERSIONS: (
        _str("bwb_id"),
        _str("valid_from"),
        _bool("current"),
    ),
    COLLECTION_ARTICLE_VERSIONS: (
        _str("bwb_id"),
        _str("stam_id"),
        _str("article_number"),
        _str("valid_from"),
        _bool("current"),
    ),
    COLLECTION_JUDGMENTS: (
        _str("ecli"),
        _str("appno"),
        _strings("case_number_keys"),
        _str("series_id"),
        _str("replaced_by"),
        _str("same_as"),
        _str("source"),
        _str("date_eff"),
        _str("tier"),
        _str("court_kind"),
        _str("court_code"),
        _str("court"),
        _bool("stub"),
        _strings("subjects"),
        _num("inbound_citation_count"),
    ),
    COLLECTION_DOCUMENTS: (
        _str("source"),
        _str("kind"),
        _str("date"),
        _str("dossier_number"),
        _strings("dossier_numbers"),
    ),
    COLLECTION_DOSSIERS: (
        _str("number"),
        _str("order", "sort_order"),
        _str("label"),
        _str("opened_on"),
        _bool("closed"),
        _str("closed_on"),
        _str("cabinet"),
        _str("ministry"),
    ),
    COLLECTION_ACTIVITIES: (_str("date"),),
    COLLECTION_DECISIONS: (
        _bool("passed"),
        _str("date"),
        _strings("dossier_numbers"),
    ),
    COLLECTION_COMMITMENTS: (
        _str("dossier_id"),
        _str("status"),
        _str("number"),
        _str("member_key"),
        _str("cabinet"),
        _str("ministry"),
        _str("made_on"),
    ),
    COLLECTION_MEMBERS: (
        Column(
            "cabinet_keys",
            "text[]",
            "lg_path_array(props -> 'government_functions', 'cabinet_key')",
        ),
    ),
    COLLECTION_ANNEXES: (_str("bwb_id"),),
}

# collection -> indexes: the columns of each and whether it is unique. An array column
# alone (``labels``, ``subjects``) gets a GIN index.
INDEXES: dict[str, tuple[tuple[tuple[str, ...], bool], ...]] = {
    COLLECTION_INSTRUMENTS: (
        (("bwb_id",), True),
        (("celex",), True),
        (("jurisdiction",), False),
        (("kind",), False),
        (("article_count",), False),
        (("stub",), False),
        (("citation_title",), False),
        (("treaty_number",), False),
        (("kind", "date_published"), False),
    ),
    COLLECTION_ARTICLES: (
        (("labels",), False),
        (("bwb_id", "article_number"), True),
        (("celex", "article_number"), True),
        (("bwb_id", "stam_id"), False),
        (("celex",), False),
        (("inbound_citation_count",), False),
        (("stub",), False),
    ),
    COLLECTION_INSTRUMENT_VERSIONS: (
        (("bwb_id", "valid_from"), False),
        (("bwb_id", "current"), False),
        (("valid_from",), False),
    ),
    COLLECTION_ARTICLE_VERSIONS: (
        (("bwb_id", "stam_id"), False),
        (("bwb_id", "article_number", "valid_from"), False),
        (("bwb_id", "valid_from"), False),
        (("bwb_id", "article_number", "current"), False),
    ),
    COLLECTION_CASES: ((("labels",), False),),
    COLLECTION_DOCUMENTS: (
        (("labels",), False),
        (("source",), False),
        (("kind", "date"), False),
        (("date",), False),
        (("dossier_number",), False),
        (("dossier_numbers",), False),
    ),
    COLLECTION_JUDGMENTS: (
        (("labels",), False),
        (("ecli",), True),
        (("appno",), False),
        (("case_number_keys",), False),
        (("series_id",), False),
        (("replaced_by",), False),
        (("same_as",), False),
        (("source", "date_eff", "tier", "court_kind", "stub", "same_as"), False),
        (("stub", "source", "tier", "court_code", "court", "date_eff"), False),
        (("tier", "court_kind", "date_eff", "stub", "source", "same_as"), False),
        (
            (
                "court_code",
                "date_eff",
                "tier",
                "court_kind",
                "stub",
                "source",
                "same_as",
            ),
            False,
        ),
        (("date_eff", "tier", "court_kind", "stub", "source", "same_as"), False),
        (("court_kind", "date_eff", "stub", "source", "same_as"), False),
        (("subjects",), False),
        (("inbound_citation_count",), False),
    ),
    COLLECTION_DOSSIERS: (
        (("labels",), False),
        (("number",), False),
        (("sort_order",), False),
        (("label",), False),
        (("opened_on",), False),
        (("closed",), False),
        (("closed_on",), False),
        (("cabinet",), False),
        (("ministry",), False),
    ),
    COLLECTION_ACTIVITIES: ((("date",), False),),
    COLLECTION_DECISIONS: (
        (("passed",), False),
        (("date",), False),
        (("dossier_numbers",), False),
    ),
    COLLECTION_COMMITMENTS: (
        (("dossier_id",), False),
        (("status",), False),
        (("number",), False),
        (("member_key",), False),
        (("cabinet",), False),
        (("ministry",), False),
        (("made_on",), False),
    ),
    COLLECTION_MEMBERS: ((("cabinet_keys",), False),),
    COLLECTION_ANNEXES: ((("bwb_id",), False),),
}


def _array_columns(collection: str) -> set[str]:
    arrays = {c.name for c in COLUMNS.get(collection, ()) if c.sql_type.endswith("[]")}
    return arrays | {"labels"}


def node_table(collection: str) -> list[str]:
    columns = "".join(
        f",\n    {c.name} {c.sql_type} GENERATED ALWAYS AS ({c.expression}) STORED"
        for c in COLUMNS.get(collection, ())
    )
    prefix = len(collection) + 2
    statements = [
        f"""CREATE TABLE IF NOT EXISTS {collection} (
    id text PRIMARY KEY CHECK (id LIKE '{collection}/%'),
    key text GENERATED ALWAYS AS (substr(id, {prefix})) STORED NOT NULL,
    type text NOT NULL,
    labels text[] NOT NULL DEFAULT '{{}}',
    props json NOT NULL DEFAULT '{{}}'{columns}
)""",
        f"CREATE UNIQUE INDEX IF NOT EXISTS {collection}_key ON {collection} (key)",
    ]
    for fields, unique in INDEXES.get(collection, ()):
        name = f"{collection}_{'_'.join(fields)}"
        gin = len(fields) == 1 and fields[0] in _array_columns(collection)
        method = " USING gin" if gin else ""
        kind = "UNIQUE INDEX" if unique else "INDEX"
        statements.append(
            f"CREATE {kind} IF NOT EXISTS {name} ON {collection}{method} ({', '.join(fields)})"
        )
    return statements


# ── edges, raw records, pipeline state ───────────────────────────────────────

EDGES = f"""
CREATE TABLE IF NOT EXISTS {COLLECTION_EDGES} (
    key text PRIMARY KEY,
    from_id text NOT NULL,
    to_id text NOT NULL,
    from_collection text GENERATED ALWAYS AS (split_part(from_id, '/', 1)) STORED,
    to_collection text GENERATED ALWAYS AS (split_part(to_id, '/', 1)) STORED,
    -- every other attribute of the edge document, in its order
    doc json NOT NULL DEFAULT '{{}}',
    relation text GENERATED ALWAYS AS (lg_str(doc -> 'relation')) STORED,
    source text GENERATED ALWAYS AS (lg_str(doc -> 'source')) STORED,
    status text GENERATED ALWAYS AS (lg_str(doc -> 'status')) STORED,
    confidence double precision GENERATED ALWAYS AS (lg_num(doc -> 'confidence')) STORED,
    semantic_type text GENERATED ALWAYS AS (lg_str(doc -> 'semantic_type')) STORED,
    record_ids text[] GENERATED ALWAYS AS
        (lg_text_array(doc -> 'meta' -> 'record_ids')) STORED
);
CREATE INDEX IF NOT EXISTS edges_from ON edges (from_id, relation, to_collection);
CREATE INDEX IF NOT EXISTS edges_to ON edges (to_id, relation, from_collection);
CREATE INDEX IF NOT EXISTS edges_relation ON edges (relation);
CREATE INDEX IF NOT EXISTS edges_status_relation ON edges (status, relation);
CREATE INDEX IF NOT EXISTS edges_confidence ON edges (confidence);
CREATE INDEX IF NOT EXISTS edges_record_ids ON edges USING gin (record_ids);
CREATE INDEX IF NOT EXISTS edges_semantic_type ON edges (semantic_type)
    WHERE semantic_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS edges_from_semantic_type ON edges (from_id, semantic_type)
    WHERE semantic_type IS NOT NULL
"""

RAW_SOURCES = f"""
CREATE TABLE IF NOT EXISTS {COLLECTION_RAW_SOURCES} (
    key text PRIMARY KEY,
    -- the record as ``raw_source_doc`` makes it, without ``_key``
    doc json NOT NULL,
    source text GENERATED ALWAYS AS (lg_str(doc -> 'source')) STORED,
    kind text GENERATED ALWAYS AS (lg_str(doc -> 'kind')) STORED,
    external_id text GENERATED ALWAYS AS (lg_str(doc -> 'external_id')) STORED,
    fetched_at text GENERATED ALWAYS AS (lg_str(doc -> 'fetched_at')) STORED
);
CREATE INDEX IF NOT EXISTS raw_sources_source_kind ON raw_sources (source, kind)
"""

PIPELINE_STATE = f"""
CREATE TABLE IF NOT EXISTS {COLLECTION_PIPELINE_STATE} (
    key text PRIMARY KEY,
    doc json NOT NULL
)
"""

# ── data version ─────────────────────────────────────────────────────────────

# A number per table that a statement which changed rows raises: ``data_version`` hashes
# them as it hashed the revisions of the collections. A statement that changed nothing (an
# upsert of what was stored) leaves it, as ArangoDB left its revision.
DATA_VERSION = """
CREATE TABLE IF NOT EXISTS lg_data_version (
    collection text PRIMARY KEY,
    version bigint NOT NULL DEFAULT 0
);
CREATE OR REPLACE FUNCTION lg_bump_data_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM changed) THEN
        UPDATE lg_data_version SET version = version + 1 WHERE collection = TG_TABLE_NAME;
    END IF;
    RETURN NULL;
END $$
"""


def data_version_triggers(table: str) -> list[str]:
    statements = [
        f"INSERT INTO lg_data_version (collection) VALUES ('{table}') ON CONFLICT DO NOTHING"
    ]
    for event, transition in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
        statements.append(
            f"CREATE OR REPLACE TRIGGER {table}_version_{event.lower()}"
            f" AFTER {event} ON {table} REFERENCING {transition} TABLE AS changed"
            " FOR EACH STATEMENT EXECUTE FUNCTION lg_bump_data_version()"
        )
    return statements


# ── nodes view ───────────────────────────────────────────────────────────────


def nodes_view() -> str:
    """Every node of every collection, for a lookup by id (``DOCUMENT(id)``)."""
    parts = "\nUNION ALL\n".join(
        f"SELECT id, key, '{c}' AS collection, type, labels, props FROM {c}"
        for c in NODE_COLLECTIONS
    )
    return f"CREATE OR REPLACE VIEW nodes AS\n{parts}"


def statements() -> list[str]:
    """The whole schema, in the order it is created."""
    found = [DICTIONARY, FUNCTIONS, DATA_VERSION]
    for collection in NODE_COLLECTIONS:
        found += node_table(collection)
        found += data_version_triggers(collection)
    found += [EDGES, RAW_SOURCES, PIPELINE_STATE, nodes_view()]
    found += data_version_triggers(COLLECTION_EDGES)
    return found


def ensure_schema(conn: psycopg.Connection) -> None:
    """Create what is missing of the schema in the database of *conn*, in one transaction
    that holds a lock, so two processes that start together do not race."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('lawgraph_schema'))")
        for statement in statements():
            conn.execute(statement.encode())


def create_database_sql(name: str) -> str:
    """The database, with the collation that sorts strings as ArangoDB did."""
    return (
        f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER icu'
        f" ICU_LOCALE '{COLLATION}' LOCALE 'C.UTF-8'"
    )


# view -> the table it indexed (``lawgraph check`` names the views as before, D7).
SEARCH_VIEWS: dict[str, str] = {
    "search_articles": COLLECTION_ARTICLES,
    "search_instruments": COLLECTION_INSTRUMENTS,
    "search_judgments": COLLECTION_JUDGMENTS,
    "search_dossiers": COLLECTION_DOSSIERS,
    "search_documents": COLLECTION_DOCUMENTS,
    "search_committees": COLLECTION_COMMITTEES,
}
