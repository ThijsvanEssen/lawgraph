"""PostgreSQL schema: a table per collection, the edges, the SQL helpers and the data version.

Every node collection is a table of the same shape: ``id`` (``collection/key``, the key of the
graph), ``key``, ``type``, ``labels`` and ``props``. ``props`` is ``json``, not ``jsonb``: the
API serves props as they are, and ``jsonb`` sorts the keys of an object (probe P1). What the
queries filter, sort or count on is a column of its own (a derived column, which a trigger of
the table fills from ``props``: ``_derive``), with the indexes the ArangoDB schema had on it.

Strings sort and compare as in ArangoDB: the database is created with the ICU root collation
with upper case first (``und-u-kf-upper``, probe P2); ``lg_tokens`` cuts and stems words as
the ``text_nl`` analyzer does (probe P3).

Everything here is idempotent: ``ensure_schema`` runs on every connect.
"""

from __future__ import annotations

import re
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
from lawgraph.core.bwb_xml import KIND_PUBLICATION

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
-- Inside a body every function, table and dictionary of this schema is named with its
-- schema, ``public.``: a restore (pg_restore) runs with an empty search_path, and builds the
-- generated columns, which inline these functions, and fires the data version trigger.
-- (A ``SET search_path`` on the function would keep the planner from inlining it.)

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

-- AQL's truthiness of a json value (``x ? a : b``, ``x || y``, ``FILTER x``): null or a
-- missing value, false, 0 and "" are false; anything else is true, an empty array or
-- object too.
CREATE OR REPLACE FUNCTION lg_truthy(v json) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE json_typeof(v)
        WHEN 'boolean' THEN (v #>> '{}')::boolean
        WHEN 'number' THEN (v #>> '{}')::numeric <> 0
        WHEN 'string' THEN v #>> '{}' <> ''
        WHEN 'array' THEN true
        WHEN 'object' THEN true
        ELSE false
    END
$$;

-- A value without the attributes that are null, at every depth, objects inside arrays too,
-- and without the nulls an array ends in. What AQL compares: an object with an attribute set
-- to null equals one without it, and an array compares position by position with what the
-- shorter one lacks as null (``[1] == [1, null]``); a null between elements stays
-- (``jsonb_strip_nulls`` with ``strip_in_arrays`` would drop those as well).
CREATE OR REPLACE FUNCTION lg_strip_nulls(v jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
    stripped jsonb := CASE jsonb_typeof(v) WHEN 'object' THEN jsonb_strip_nulls(v) ELSE v END;
    name text;
    value jsonb;
    n bigint;
BEGIN
    -- jsonb_strip_nulls strips nested objects, not the objects inside an array: each
    -- array (and an object that may hold one) is stripped in its place
    IF jsonb_typeof(stripped) = 'object' THEN
        FOR name, value IN SELECT e.key, e.value FROM jsonb_each(stripped) AS e LOOP
            IF jsonb_typeof(value) IN ('object', 'array') THEN
                stripped := jsonb_set(stripped, ARRAY[name], public.lg_strip_nulls(value));
            END IF;
        END LOOP;
    ELSIF jsonb_typeof(stripped) = 'array' THEN
        FOR value, n IN SELECT e.value, e.n - 1
                        FROM jsonb_array_elements(stripped) WITH ORDINALITY AS e(value, n) LOOP
            IF jsonb_typeof(value) IN ('object', 'array') THEN
                stripped := jsonb_set(stripped, ARRAY[n::text], public.lg_strip_nulls(value));
            END IF;
        END LOOP;
        WHILE jsonb_typeof(stripped -> -1) = 'null' LOOP
            stripped := stripped - -1;
        END LOOP;
    END IF;
    RETURN stripped;
END
$$;

-- Whether two values are equal as AQL compares them (``==``, ``MATCHES``): an attribute
-- set to null is the same as a missing one. Equal values are not stripped.
CREATE OR REPLACE FUNCTION lg_same(a jsonb, b jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN a IS NOT DISTINCT FROM b THEN true
                ELSE public.lg_strip_nulls(a) IS NOT DISTINCT FROM public.lg_strip_nulls(b) END
$$;

-- The strings of a JSON array, in order (``doc.props.subjects[*]``); NULL for another type.
CREATE OR REPLACE FUNCTION lg_text_array(v json) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN json_typeof(v) = 'array' THEN ARRAY(
        SELECT e #>> '{}' FROM json_array_elements(v) WITH ORDINALITY AS a(e, n)
        WHERE json_typeof(e) = 'string' ORDER BY n
    ) END
$$;

-- The main areas of law of a judgment's subjects (``Bestuursrecht; Belastingrecht`` is in
-- ``Bestuursrecht``): each subject up to its first ';', trimmed, each area once, in order.
CREATE OR REPLACE FUNCTION lg_subject_areas(subjects text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(area ORDER BY first), '{}'::text[]) FROM (
        SELECT btrim(split_part(s, ';', 1)) AS area, min(n) AS first
        FROM unnest(subjects) WITH ORDINALITY AS u(s, n)
        WHERE btrim(split_part(s, ';', 1)) <> ''
        GROUP BY 1
    ) areas
$$;

-- The keys a regulation is filed under by its WTI (`legal_areas`, normalize bwb): the TOOI id
-- and the slug of every main and specific area, so that a filter on a main area also finds
-- the regulations under its specific areas. Lower case, each once.
CREATE OR REPLACE FUNCTION lg_legal_area_keys(props json) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(DISTINCT lower(k)), '{}'::text[])
    FROM json_array_elements(CASE WHEN json_typeof(props -> 'legal_areas') = 'array'
                                  THEN props -> 'legal_areas' END) AS a(area)
    CROSS JOIN LATERAL unnest(ARRAY[
        area ->> 'main_id', area ->> 'main_slug',
        area ->> 'specific_id', area ->> 'specific_slug'
    ]) AS u(k)
    WHERE k IS NOT NULL AND k <> ''
$$;

-- The keys of the government themes of a regulation (`policy_domains`): id and slug.
CREATE OR REPLACE FUNCTION lg_policy_domain_keys(props json) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(DISTINCT lower(k)), '{}'::text[])
    FROM json_array_elements(CASE WHEN json_typeof(props -> 'policy_domains') = 'array'
                                  THEN props -> 'policy_domains' END) AS d(domain)
    CROSS JOIN LATERAL unnest(ARRAY[domain ->> 'id', domain ->> 'slug']) AS u(k)
    WHERE k IS NOT NULL AND k <> ''
$$;

-- A member is seated: one of their faction memberships has no end date.
CREATE OR REPLACE FUNCTION lg_member_seated(props json) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT EXISTS (
        SELECT 1 FROM json_array_elements(
            CASE WHEN json_typeof(props -> 'faction_memberships') = 'array'
                 THEN props -> 'faction_memberships' ELSE '[]'::json END
        ) AS f(period)
        WHERE coalesce(json_typeof(period -> 'to_date'), 'null') = 'null'
    )
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

-- An update of props or meta: *a* with the values of *b*, one level deep, every key in the
-- order of the collation. How the store and the steps that set props in place write (D11): an
-- order that does not depend on what was written first, or on a hash.
CREATE OR REPLACE FUNCTION lg_update(a json, b json) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(json_object_agg(key, value ORDER BY key), '{}'::json)
    FROM (
        SELECT key, CASE WHEN r.value IS NOT NULL THEN r.value ELSE l.value END AS value
        FROM json_each(coalesce(a, '{}')) AS l(key, value)
        FULL JOIN json_each(coalesce(b, '{}')) AS r(key, value) USING (key)
    ) merged
$$;

-- UNSET(a, keys): *a* without *keys*, the others in their order.
CREATE OR REPLACE FUNCTION lg_unset(a json, keys text[]) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(json_object_agg(key, value ORDER BY n), '{}'::json)
    FROM json_each(coalesce(a, '{}')) WITH ORDINALITY AS e(key, value, n)
    WHERE key <> ALL(keys)
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
        array_agg(coalesce((ts_lexize('public.lawgraph_dutch', m[1]))[1], m[1]) ORDER BY o), '{}')
    FROM regexp_matches(
        public.lg_fold(t),
        '([[:alnum:]_]+(?:(?:(?<=[[:alpha:]])[:''’](?=[[:alpha:]])'
        '|(?<=[[:digit:]])[.,](?=[[:digit:]]))[[:alnum:]_]+)*)',
        'g'
    ) WITH ORDINALITY AS r(m, o)
$$;

-- The nodes within w_depth edges of w_focal, breadth first, at most w_cap of them (D9), in
-- one statement: a level is read whole (the neighbours along the edges of the relations
-- and status asked for, in the directions asked for, not seen before) and kept in id order
-- until the cap; a node that is gone is not one; a node outside w_collections (when given)
-- is seen but neither kept nor walked through. Whether a neighbour is there is asked of
-- its own table only (w_tables), w_chunk at a time in id order, so a capped walk does not
-- look up the neighbours it will never keep.
CREATE OR REPLACE FUNCTION lg_walk(
    w_focal text, w_depth int, w_cap int, w_relations text[], w_status text,
    w_outbound boolean, w_inbound boolean, w_collections text[], w_tables text[],
    w_chunk int DEFAULT 500
) RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
DECLARE
    seen text[] := ARRAY[w_focal];
    kept text[] := '{}';
    frontier text[] := ARRAY[w_focal];
    reached text[];
    chunk text[];
    present text[];
    level text[];
    reads text;
    node text;
    start int;
BEGIN
    FOR step IN 1..w_depth LOOP
        reached := ARRAY(
            SELECT f.id FROM (
                SELECT e.to_id AS id FROM public.edges e
                WHERE w_outbound AND e.from_id = ANY(frontier)
                  AND (w_relations IS NULL OR e.relation = ANY(w_relations))
                  AND (w_status IS NULL OR e.status = w_status)
                UNION
                SELECT e.from_id FROM public.edges e
                WHERE w_inbound AND e.to_id = ANY(frontier)
                  AND (w_relations IS NULL OR e.relation = ANY(w_relations))
                  AND (w_status IS NULL OR e.status = w_status)
                EXCEPT
                SELECT unnest(seen)
            ) f
            ORDER BY f.id
        );
        level := '{}';
        start := 1;
        WHILE start <= coalesce(array_length(reached, 1), 0) LOOP
            chunk := reached[start:start + w_chunk - 1];
            start := start + w_chunk;
            SELECT string_agg(
                format('SELECT id FROM public.%I WHERE id = ANY($1)', c), ' UNION ALL '
            ) INTO reads
            FROM (
                SELECT DISTINCT split_part(x, '/', 1) AS c FROM unnest(chunk) x
            ) cs
            WHERE c = ANY(w_tables);
            IF reads IS NULL THEN
                CONTINUE;
            END IF;
            EXECUTE 'SELECT coalesce(array_agg(id ORDER BY id), ''{}'') FROM ('
                || reads || ') t' INTO present USING chunk;
            seen := seen || present;
            FOREACH node IN ARRAY present LOOP
                IF w_collections IS NULL OR split_part(node, '/', 1) = ANY(w_collections) THEN
                    level := level || node;
                    IF coalesce(array_length(kept, 1), 0)
                       + array_length(level, 1) = w_cap THEN
                        RETURN kept || level;
                    END IF;
                END IF;
            END LOOP;
        END LOOP;
        kept := kept || level;
        frontier := level;
        EXIT WHEN coalesce(array_length(frontier, 1), 0) = 0;
    END LOOP;
    RETURN kept;
END
$$;

"""

SEARCH_FUNCTIONS = r"""
-- The strings a field holds: a string, or the strings of an array (``names``, ``aliases``).
CREATE OR REPLACE FUNCTION lg_values(v json) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE json_typeof(v)
        WHEN 'string' THEN ARRAY[v #>> '{}']
        WHEN 'array' THEN public.lg_text_array(v)
        ELSE '{}'::text[]
    END
$$;
CREATE OR REPLACE FUNCTION lg_tokens_all(vs text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(t ORDER BY n, m), '{}')
    FROM unnest(vs) WITH ORDINALITY AS v(value, n),
         unnest(public.lg_tokens(value)) WITH ORDINALITY AS w(t, m)
$$;
CREATE OR REPLACE FUNCTION lg_fold_all(vs text[]) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(public.lg_fold(value) ORDER BY n), '{}')
    FROM unnest(vs) WITH ORDINALITY AS v(value, n)
$$;
-- The folded values in one string, for a substring search (array_to_string is only STABLE:
-- for the text arrays here its answer does not change).
CREATE OR REPLACE FUNCTION lg_join(vs text[]) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT array_to_string(vs, chr(31))
$$;
-- BM25 of one term in one field (``queries/_bm25.py``): *tf* is evaluated once.
CREATE OR REPLACE FUNCTION lg_bm25(tf float8, len float8, weight float8, avglen float8)
RETURNS float8 LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN tf > 0
        THEN weight * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len / avglen)) ELSE 0 END
$$;
-- The 3- to 12-grams of a string of *l* characters.
CREATE OR REPLACE FUNCTION lg_ngrams(l int) RETURNS int
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN l >= 12 THEN 10 * l - 75 WHEN l >= 3 THEN (l - 2) * (l - 1) / 2 ELSE 0 END
$$;
-- The names a member or a faction is searched by, in lower case (``queries/search.py``):
-- its name, its party, and the abbreviation, name and aliases of every faction it was in.
CREATE OR REPLACE FUNCTION lg_member_names(props json) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT lower(concat_ws(' ',
        coalesce(props ->> 'name', ''),
        coalesce(props ->> 'party', ''),
        (SELECT string_agg(concat_ws(' ',
                    coalesce(m ->> 'abbreviation', ''),
                    coalesce(m ->> 'name', ''),
                    public.lg_join(public.lg_text_array(m -> 'aliases'))
                ), ' ' ORDER BY n)
         FROM json_array_elements(
             CASE WHEN json_typeof(props -> 'faction_memberships') = 'array'
                  THEN props -> 'faction_memberships' ELSE '[]'::json END
         ) WITH ORDINALITY AS fm(m, n))
    ))
$$;
CREATE OR REPLACE FUNCTION lg_faction_names(props json) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT lower(concat_ws(' ',
        coalesce(props ->> 'name', ''),
        coalesce(props ->> 'abbreviation', ''),
        public.lg_join(public.lg_text_array(props -> 'aliases'))
    ))
$$;
-- A word as a LIKE pattern that matches it literally.
CREATE OR REPLACE FUNCTION lg_like(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT replace(replace(replace(t, '\', '\\'), '%', '\%'), '_', '\_')
$$;
-- Tokens as a tsvector of one weight, each at its position, for the rank of a hit.
CREATE OR REPLACE FUNCTION lg_tsv(tokens text[], weight "char") RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(
        string_agg(quote_literal(t) || ':' || least(n, 16383) || weight::text, ' ')::tsvector,
        ''::tsvector
    )
    FROM unnest(tokens) WITH ORDINALITY AS w(t, n)
$$;
"""

DICTIONARY = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_dict WHERE dictname = 'lawgraph_dutch') THEN
        CREATE TEXT SEARCH DICTIONARY lawgraph_dutch (TEMPLATE = snowball, Language = dutch);
    END IF;
END $$
"""

# Substring search on the ngram columns (``LIKE '%word%'`` from an index).
TRIGRAMS = "CREATE EXTENSION IF NOT EXISTS pg_trgm"

# ── node tables ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Column:
    """A derived column of a node table: *name*, its SQL type and the props it holds
    (*expression*, over ``props``). The trigger of the table computes it (``_derive``)."""

    name: str
    sql_type: str
    expression: str


def _str(field: str, name: str | None = None) -> Column:
    return Column(name or field, "text", f"lg_str(props -> '{field}')")


def _num(field: str) -> Column:
    return Column(field, "double precision", f"lg_num(props -> '{field}')")


def _bool(field: str) -> Column:
    return Column(field, "boolean", f"lg_bool(props -> '{field}')")


def _json(field: str) -> Column:
    """A prop as stored (its JSON value), for a document whose props are large: reading it
    from ``props`` parses them whole."""
    return Column(f"pj_{field}", "json", f"props -> '{field}'")


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
        _num("position"),
        _bool("stub"),
        _bool("repealed"),
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
        _str("valid_until"),
        # whether there is a valid_until at all, of any type (a version without one is in
        # force still); the props of a version, its text too, need not be read for it
        Column("valid_until_set", "boolean", "props ->> 'valid_until' IS NOT NULL"),
        _num("position"),
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
        # "Datum publicatie": the date the feed shows a judgment on
        _str("published_on"),
        _str("tier"),
        _str("court_kind"),
        _str("court_code"),
        _str("court"),
        # the procedure (psi:procedure) as the source gives it: "Hoger beroep", "Cassatie"
        Column("procedure", "text", "lg_str(props -> 'judgment_metadata' -> 'type')"),
        _bool("stub"),
        _strings("subjects"),
        _num("inbound_citation_count"),
        # what the lists and the citing judgments show of a judgment (its props hold its
        # text and paragraphs)
        *(
            _json(field)
            for field in (
                "ecli",
                "display_name",
                "summary",
                "names",
                "decision_kind",
                "court_code",
                "tier",
                "court_kind",
                "date_eff",
                "source",
                "subjects",
                "inbound_citation_count",
                "outbound_citation_count",
                "series_id",
                "series_size",
            )
        ),
    ),
    COLLECTION_DOCUMENTS: (
        _str("source"),
        _str("kind"),
        _str("date"),
        _str("dossier_number"),
        _strings("dossier_numbers"),
        # what the feed reads of every paper (``queries/feed.py``): its props hold the
        # whole record of the source
        *(_json(field) for field in ("actors", "dossier_numbers", "subject", "title")),
    ),
    COLLECTION_DOSSIERS: (
        _str("number"),
        _str("order", "sort_order"),
        _str("label"),
        _str("opened_on"),
        _str("last_activity"),
        _bool("closed"),
        _str("closed_on"),
        _str("cabinet"),
        _str("ministry"),
        # a government bill: ``kind`` and not ``initiative`` (the counts per cabinet)
        _str("kind"),
        _bool("initiative"),
        # what the dossier lists filter, sort and count on, as stored (any type, as
        # ArangoDB compared it): read without the rest of the props
        *(
            _json(field)
            for field in (
                "outcome",
                "kind",
                "current_phase",
                "ministry",
                "order",
                "opened_on",
                "last_activity",
                "closed_on",
                "title",
                "phases",
                "initiative",
            )
        ),
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
        _bool("active"),
        _str("name"),
        Column("search_names", "text", "lg_member_names(props)"),
        # what the member lists filter and sort on (``queries/committees.py``): the name a
        # member goes by (``name OR known_as OR government_name``), whether they ever held
        # a seat, hold one now, and are in the Eerste Kamer list
        Column(
            "list_name",
            "text",
            "CASE WHEN lg_truthy(props -> 'name') THEN props ->> 'name'"
            " WHEN lg_truthy(props -> 'known_as') THEN props ->> 'known_as'"
            " ELSE props ->> 'government_name' END",
        ),
        Column(
            "in_parliament",
            "boolean",
            "CASE WHEN json_typeof(props -> 'faction_memberships') = 'array'"
            " THEN json_array_length(props -> 'faction_memberships') > 0 ELSE false END",
        ),
        Column("seated", "boolean", "lg_member_seated(props)"),
        _json("faction_memberships"),
        Column(
            "in_ek", "boolean", "coalesce(json_typeof(props -> 'ek'), 'null') <> 'null'"
        ),
    ),
    COLLECTION_FACTIONS: (
        _bool("active"),
        _str("name"),
        _num("seats"),
        Column("search_names", "text", "lg_faction_names(props)"),
    ),
    COLLECTION_ANNEXES: (_str("bwb_id"),),
}

# collection -> indexes: the columns of each and whether it is unique. An array column
# alone (``labels``, ``subjects``) gets a GIN index. A column may carry its order
# (``date_eff DESC NULLS LAST``): an index in the order of a list serves its page without
# sorting the list (read backwards, it serves the opposite order too).
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
        (("procedure",), False),
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
        (("date_eff DESC NULLS LAST", "key DESC"), False),
        (("inbound_citation_count DESC NULLS LAST", "key DESC"), False),
        # the feed: per tier, newest publication first (``db/queries/feed.py``)
        (("tier", "published_on"), False),
    ),
    COLLECTION_DOSSIERS: (
        (("labels",), False),
        (("number",), False),
        (("sort_order",), False),
        (("label",), False),
        (("opened_on",), False),
        (("last_activity",), False),
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


# ── search ───────────────────────────────────────────────────────────────────

# What ArangoSearch indexed, per collection and field, with which analyzers: ``text``
# (text_nl, stemmed words), ``identity`` (the value as is, for a prefix), ``norm``
# (lawgraph_norm, the folded value) and ``ngram`` (lawgraph_ngram_v2, a part of the folded
# value). Each becomes a column the search reads (``queries/search.py``).
SEARCH_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    COLLECTION_ARTICLES: {
        "display_name": ("text", "identity", "ngram"),
        "text": ("text",),
        "article_number": ("text", "identity", "norm"),
        "bwb_id": ("text", "identity", "norm"),
        "heading": ("text", "identity", "norm", "ngram"),
        "breadcrumb.title": ("text",),
    },
    COLLECTION_INSTRUMENTS: {
        "title": ("text", "ngram"),
        "citation_title": ("text", "identity", "ngram"),
        "official_title": ("text", "ngram"),
        "display_name": ("text", "identity", "ngram"),
        "short_title": ("identity", "norm"),
        "aliases": ("text", "identity", "norm"),
        "bwb_id": ("identity", "norm"),
    },
    COLLECTION_JUDGMENTS: {
        "display_name": ("text", "identity", "ngram"),
        "names": ("text", "identity", "norm", "ngram"),
        "summary": ("text",),
        "ecli": ("identity", "norm"),
        "appno": ("identity", "norm"),
    },
    COLLECTION_DOSSIERS: {
        "title": ("text", "ngram"),
        "display_name": ("text", "ngram"),
        "number": ("identity", "norm"),
    },
    COLLECTION_DOCUMENTS: {
        "title": ("text", "ngram"),
        "display_name": ("text", "ngram"),
        "external_id": ("identity", "norm"),
    },
    COLLECTION_COMMITTEES: {
        "name": ("text", "ngram"),
        "abbreviation": ("text", "identity", "norm"),
    },
}

# The weight of a field's words in the rank of a hit (``search_tsv``): the boosts of the
# search, A the highest. A field not named weighs D.
SEARCH_WEIGHTS: dict[str, dict[str, str]] = {
    COLLECTION_ARTICLES: {"heading": "A", "display_name": "B", "breadcrumb.title": "C"},
    COLLECTION_INSTRUMENTS: {"aliases": "A", "citation_title": "B"},
}


def search_column(field: str, analyzer: str) -> str:
    """The column of *field* a search under *analyzer* reads."""
    suffix = {"identity": "v", "text": "t", "norm": "n", "ngram": "g", "prefix": "p"}[
        analyzer
    ]
    return f"s_{field.replace('.', '_')}_{suffix}"


def start_of_value_sql(table: str, field: str, word: str, row: str = "doc") -> str:
    """SQL: a value of *field* (of the row *row*; no row: the table read) starts with the
    word in the SQL *word*, in any case. A field searched for a part of its value as well
    (``ngram``) is folded there, accents and all (``lg_fold``): its start is matched there,
    at the start of the column or after the separator of its values. Another field (an
    abbreviation, an identifier) is matched in any case on its values as they are."""
    on = f"{row}." if row else ""
    if "ngram" in SEARCH_FIELDS[table][field]:
        column = f"{on}{search_column(field, 'ngram')}"
        folded = f"lg_like(lg_fold({word}))"
        return (
            f"({column} LIKE {folded} || '%%'"
            f" OR {column} LIKE '%%' || chr(31) || {folded} || '%%')"
        )
    return (
        f"{on}{search_column(field, 'prefix')}"
        f" ILIKE '%%' || chr(31) || lg_like({word}) || '%%'"
    )


def _values_sql(field: str) -> str:
    if "." in field:
        parent, child = field.split(".", 1)
        return f"coalesce(lg_path_array(props -> '{parent}', '{child}'), '{{}}')"
    return f"lg_values(props -> '{field}')"


def _search_columns(collection: str) -> list[Column]:
    columns: list[Column] = []
    weighted: list[str] = []
    for field, analyzers in SEARCH_FIELDS.get(collection, {}).items():
        values = _values_sql(field)
        expressions = {
            "identity": ("text[]", values),
            "text": ("text[]", f"lg_tokens_all({values})"),
            "norm": ("text[]", f"lg_fold_all({values})"),
            "ngram": ("text", f"lg_join(lg_fold_all({values}))"),
        }
        for analyzer in analyzers:
            sql_type, expression = expressions[analyzer]
            columns.append(Column(search_column(field, analyzer), sql_type, expression))
        if "identity" in analyzers:
            # every value after a separator: a prefix of a value is an indexed part of it
            columns.append(
                Column(
                    search_column(field, "prefix"),
                    "text",
                    f"chr(31) || lg_join({values})",
                )
            )
        if "text" in analyzers:
            weight = SEARCH_WEIGHTS.get(collection, {}).get(field, "D")
            weighted.append(f"lg_tsv(lg_tokens_all({values}), '{weight}')")
    if weighted:
        columns.append(Column("search_tsv", "tsvector", " || ".join(weighted)))
    return columns


# The words a cabinet and a commitment are searched by, lower case, as ``search_names`` of
# members and factions: a trigram index on the expression serves "every word in it". An
# expression, not a column: the tables keep their columns (no rebuild).
SEARCH_WORDS: dict[str, str] = {
    COLLECTION_CABINETS: "lower(coalesce({p}props ->> 'name', ''))",
    COLLECTION_COMMITMENTS: (
        "lower(coalesce({p}props ->> 'text', '') || ' ' || coalesce({p}props ->> 'number', ''))"
    ),
    # a vote: what was voted on and its kind (Motie, Amendement, Wetgeving)
    COLLECTION_DECISIONS: (
        "lower(coalesce({p}props ->> 'subject', '') || ' ' || coalesce({p}props ->> 'kind', ''))"
    ),
}


def search_words(collection: str, alias: str = "") -> str:
    """The expression of ``SEARCH_WORDS`` over the props of the row *alias*."""
    return SEARCH_WORDS[collection].format(p=f"{alias}." if alias else "")


def _search_indexes(collection: str) -> list[str]:
    statements = []
    if collection in SEARCH_WORDS:
        statements.append(
            f"CREATE INDEX IF NOT EXISTS {collection}_search_words ON {collection}"
            f" USING gin (({search_words(collection)}) gin_trgm_ops)"
        )
    if collection in (COLLECTION_MEMBERS, COLLECTION_FACTIONS):
        statements.append(
            f"CREATE INDEX IF NOT EXISTS {collection}_search_names ON {collection}"
            " USING gin (search_names gin_trgm_ops)"
        )
        # the name folded as the search folds (``lg_fold``): ``yesilgoz`` finds Yeşilgöz.
        # An index, not a column: no row is written again (``search_names`` is lower case
        # only, a stored column).
        folded = (
            "lg_fold(name)"
            if collection == COLLECTION_MEMBERS
            else "lg_fold(search_names)"
        )
        statements.append(
            f"CREATE INDEX IF NOT EXISTS {collection}_names_folded ON {collection}"
            f" USING gin (({folded}) gin_trgm_ops)"
        )
    for column in _search_columns(collection):
        name = f"{collection}_{column.name}"
        if column.name.endswith(("_t", "_n")):
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {name} ON {collection} USING gin ({column.name})"
            )
        elif column.name.endswith(("_g", "_p")):
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {name} ON {collection}"
                f" USING gin ({column.name} gin_trgm_ops)"
            )
    return statements


def _array_columns(collection: str) -> set[str]:
    arrays = {c.name for c in COLUMNS.get(collection, ()) if c.sql_type.endswith("[]")}
    return arrays | {"labels"}


def _derived(collection: str) -> list[Column]:
    return [*COLUMNS.get(collection, ()), *_search_columns(collection)]


_PROP = re.compile(r"props -> '(\w+)'")
_FUNCTION_CALL = re.compile(r"(?<![\w.])(lg_\w+)\(")
_WHOLE_PROPS = re.compile(r"(?<![\w.\"])props\b")


def _derive(collection: str) -> list[str]:
    """The trigger that fills the derived columns of *collection* from ``props`` when a row
    is written, its function and the trigger itself.

    Generated columns would each read their prop with ``props -> 'x'``, and on ``json`` that
    parses the whole document: a judgment (its text, some 20 KB) was parsed 48 times a row.
    The trigger parses it once (``json_each``, which keeps every value as written, key order
    of a nested object included) and evaluates the same expressions on those values. Of a
    key that occurs twice the last one counts, as with ``->``. The names are qualified: a
    restore runs without a search path."""
    columns = _derived(collection)
    keys = sorted({k for c in columns for k in _PROP.findall(c.expression)})
    values = ", ".join(
        f"(array_agg(value ORDER BY n) FILTER (WHERE key = '{k}'))"
        f"[count(*) FILTER (WHERE key = '{k}')] AS \"p_{k}\""
        for k in keys
    )

    def over_values(expression: str) -> str:
        expression = _PROP.sub(lambda m: f'v."p_{m.group(1)}"', expression)
        # what reads the props whole (lg_member_names, ->>) reads the row's own
        expression = _WHOLE_PROPS.sub("NEW.props", expression)
        return _FUNCTION_CALL.sub(r"public.\1(", expression)

    targets = ", ".join(f"NEW.{c.name}" for c in columns)
    expressions = ",\n        ".join(over_values(c.expression) for c in columns)
    return [
        f"""CREATE OR REPLACE FUNCTION public.lg_derive_{collection}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    SELECT {expressions}
    INTO {targets}
    FROM (SELECT {values}
          FROM json_each(NEW.props) WITH ORDINALITY AS e(key, value, n)) v;
    RETURN NEW;
END $$""",
        f"CREATE OR REPLACE TRIGGER {collection}_derive"
        f" BEFORE INSERT OR UPDATE OF props ON {collection}"
        f" FOR EACH ROW EXECUTE FUNCTION public.lg_derive_{collection}()",
    ]


def node_table(collection: str) -> list[str]:
    derived = _derived(collection)
    columns = "".join(f",\n    {c.name} {c.sql_type}" for c in derived)
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
        name = f"{collection}_{'_'.join(f.split()[0] for f in fields)}"
        gin = len(fields) == 1 and fields[0] in _array_columns(collection)
        method = " USING gin" if gin else ""
        kind = "UNIQUE INDEX" if unique else "INDEX"
        statements.append(
            f"CREATE {kind} IF NOT EXISTS {name} ON {collection}{method} ({', '.join(fields)})"
        )
    return (
        statements
        + (_derive(collection) if derived else [])
        + list(_LIST_INDEXES.get(collection, ()))
        + _search_indexes(collection)
    )


# The dossier numbers of an instrument (a publication's), as text: the expression of the
# index ``instruments_dossier_numbers``.
INSTRUMENT_DOSSIER_NUMBERS = "public.lg_text_array(props -> 'dossier_numbers')"


def feed_title(alias: str = "") -> str:
    """The title the feed shows of a paper (``queries/feed.py``), its subject or else its
    title, folded as the search folds (``lg_fold``): the expression of the trigram index
    ``documents_feed_title_g``, which serves the words (``q``) of the feed. The index and
    the feed write it alike, or the planner does not take the index."""
    p = f"{alias}." if alias else ""
    return (
        f"public.lg_fold(coalesce((CASE WHEN public.lg_truthy({p}pj_subject)"
        f" THEN {p}pj_subject ELSE {p}pj_title END) #>> '{{}}', ''))"
    )


# The instruments list holds every instrument but the publications: an index per sort of
# it over those alone, so that a page does not pass every publication on the way.
_LISTED = f"kind IS DISTINCT FROM '{KIND_PUBLICATION}'"
_LIST_INDEXES: dict[str, tuple[str, ...]] = {
    COLLECTION_INSTRUMENTS: (
        "CREATE INDEX IF NOT EXISTS instruments_list_title"
        f" ON instruments (citation_title NULLS FIRST, key) WHERE {_LISTED}",
        "CREATE INDEX IF NOT EXISTS instruments_list_article_count"
        f" ON instruments (article_count DESC NULLS LAST, key DESC) WHERE {_LISTED}",
        # /api/instruments by legal area and theme (BE-14): GIN indexes on their keys
        "CREATE INDEX IF NOT EXISTS instruments_legal_areas"
        " ON instruments USING gin (public.lg_legal_area_keys(props))",
        "CREATE INDEX IF NOT EXISTS instruments_policy_domains"
        " ON instruments USING gin (public.lg_policy_domain_keys(props))",
        # the publications of a dossier, for the words (``q``) of the feed in its title
        "CREATE INDEX IF NOT EXISTS instruments_dossier_numbers"
        f" ON instruments USING gin (({INSTRUMENT_DOSSIER_NUMBERS}))",
    ),
    # /api/documents, newest first: a page without a kind or dossier reads only itself.
    COLLECTION_DOCUMENTS: (
        "CREATE INDEX IF NOT EXISTS documents_list_date"
        " ON documents (date DESC NULLS LAST, key)",
        # the words of the feed (``q``) in the title it shows; on a large database built
        # beforehand with CREATE INDEX CONCURRENTLY
        "CREATE INDEX IF NOT EXISTS documents_feed_title_g"
        f" ON documents USING gin (({feed_title()}) gin_trgm_ops)",
    ),
    # /api/judgments by the main area of law (``subject_area``): a GIN index on the areas
    COLLECTION_JUDGMENTS: (
        "CREATE INDEX IF NOT EXISTS judgments_subject_areas"
        " ON judgments USING gin (public.lg_subject_areas(subjects))",
    ),
    # the member lists in name order: those who held a seat, and the Eerste Kamer's
    COLLECTION_MEMBERS: (
        "CREATE INDEX IF NOT EXISTS members_list_name ON members"
        " (list_name NULLS FIRST, key) WHERE in_parliament AND list_name <> ''",
        "CREATE INDEX IF NOT EXISTS members_list_ek ON members"
        " (list_name NULLS FIRST, key) WHERE in_ek",
    ),
}


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
        (lg_text_array(doc -> 'meta' -> 'record_ids')) STORED,
    created_at text GENERATED ALWAYS AS (lg_str(doc -> 'created_at')) STORED
);
CREATE INDEX IF NOT EXISTS edges_from ON edges (from_id, relation, to_collection);
CREATE INDEX IF NOT EXISTS edges_to ON edges (to_id, relation, from_collection);
-- The edges at a node by relation and the other collection, in key order, with both ends
-- without the row: a level of ``paths`` reads a node with 20,000 edges from a few hundred
-- pages of the index, not a page of the table per edge; a page of a node's neighbours stops
-- after its limit in key order instead of reading and sorting the whole bucket. On a large
-- database built beforehand with CREATE INDEX CONCURRENTLY.
CREATE INDEX IF NOT EXISTS edges_to_cover ON edges (to_id, relation, from_collection, key)
    INCLUDE (from_id, to_collection);
CREATE INDEX IF NOT EXISTS edges_from_cover ON edges (from_id, relation, to_collection, key)
    INCLUDE (to_id, from_collection);
CREATE INDEX IF NOT EXISTS edges_relation ON edges (relation);
CREATE INDEX IF NOT EXISTS edges_created_at ON edges (created_at, to_id);
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
CREATE INDEX IF NOT EXISTS raw_sources_source_kind ON raw_sources (source, kind, key);
CREATE INDEX IF NOT EXISTS raw_sources_source_fetched_at ON raw_sources (source, fetched_at)
"""

PIPELINE_STATE = f"""
CREATE TABLE IF NOT EXISTS {COLLECTION_PIPELINE_STATE} (
    key text PRIMARY KEY,
    doc json NOT NULL
)
"""

# The heat of the whole graph (``/api/nodes/heat`` without ids), kept by ``semantic graph-heat``:
# per window of months the nodes with the highest count, and when it was counted. Not a
# table of the graph: writing it raises no data version.
HEAT = """
CREATE TABLE IF NOT EXISTS lg_heat (
    months int NOT NULL,
    id text NOT NULL,
    count int NOT NULL,
    PRIMARY KEY (months, id)
);
CREATE INDEX IF NOT EXISTS lg_heat_highest ON lg_heat (months, count DESC, id);
CREATE TABLE IF NOT EXISTS lg_heat_state (
    one boolean PRIMARY KEY DEFAULT true CHECK (one),
    computed_at text NOT NULL,
    data_version text
)
"""

# What a judgment is as a neighbour, a node of a neighbourhood or of a path (the props the
# explorer reads of it there, in their stored order; its summary as long as a preview needs),
# kept apart from its props, which hold its whole text: a neighbour reads these, not the text.
# Kept by triggers on every write of a judgment; ``semantic graph-light`` fills it once. Not
# a table of the graph: writing it raises no data version.
JUDGMENT_LIGHT_PROPS = (
    "ecli",
    "display_name",
    "names",
    "summary",
    "date",
    "court",
    "court_code",
    "case_number",
    "source",
    "jurisdiction",
    "stub",
    "translation_of",
    "advocate_general",
    "advocate_general_role",
)
# The characters of a summary kept: one more than a neighbour shows, so it knows to cut.
JUDGMENT_LIGHT_SUMMARY = 401


def judgment_light() -> list[str]:
    keys = ", ".join(f"'{key}'" for key in JUDGMENT_LIGHT_PROPS)
    statements = [
        """CREATE TABLE IF NOT EXISTS lg_judgment_light (
    id text PRIMARY KEY,
    props json NOT NULL
)""",
        f"""CREATE OR REPLACE FUNCTION lg_judgment_light_props(p json) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(json_object_agg(
        e.key,
        CASE WHEN e.key = 'summary' AND json_typeof(e.value) = 'string'
             THEN to_json(left(e.value #>> '{{}}', {JUDGMENT_LIGHT_SUMMARY}))
             ELSE e.value END
        ORDER BY e.n), '{{}}'::json)
    FROM json_each(CASE WHEN json_typeof(p) = 'object' THEN p ELSE '{{}}'::json END)
        WITH ORDINALITY AS e(key, value, n)
    WHERE e.key IN ({keys})
$$""",
        """CREATE OR REPLACE FUNCTION lg_keep_judgment_light() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.lg_judgment_light l USING changed c WHERE l.id = c.id;
    ELSE
        INSERT INTO public.lg_judgment_light (id, props)
        SELECT c.id, public.lg_judgment_light_props(c.props) FROM changed c
        ON CONFLICT (id) DO UPDATE SET props = EXCLUDED.props;
    END IF;
    RETURN NULL;
END $$""",
    ]
    for event, transition in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
        statements.append(
            f"CREATE OR REPLACE TRIGGER judgments_light_{event.lower()}"
            f" AFTER {event} ON judgments REFERENCING {transition} TABLE AS changed"
            " FOR EACH STATEMENT EXECUTE FUNCTION lg_keep_judgment_light()"
        )
    return statements


# What ``normalize tk-dossiers`` reads of each paper of a dossier to derive its title, kind
# and phases (``queries/normalize/tk.dossier_signals``), kept apart from its props, which
# hold its whole text: the signals of a dossier read these, not the text of its papers.
# Kept by triggers on every write of a document; ``semantic graph-light`` fills it once. Not
# a table of the graph: writing it raises no data version.
DOCUMENT_LIGHT_PROPS = (
    "kind",
    "date",
    "dossier_title",
    "title",
    "display_name",
    "dossier_numbers",
    "case_kinds",
    "dossier_number",
    "dossier_suffix",
    "sequence",
)


def document_light() -> list[str]:
    keys = ", ".join(f"'{key}'" for key in DOCUMENT_LIGHT_PROPS)
    statements = [
        """CREATE TABLE IF NOT EXISTS lg_document_light (
    id text PRIMARY KEY,
    props json NOT NULL
)""",
        f"""CREATE OR REPLACE FUNCTION lg_document_light_props(p json) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT json_object_agg(e.key, e.value ORDER BY e.n)
    FROM json_each(CASE WHEN json_typeof(p) = 'object' THEN p ELSE '{{}}'::json END)
        WITH ORDINALITY AS e(key, value, n)
    WHERE e.key IN ({keys})
$$""",
        """CREATE OR REPLACE FUNCTION lg_keep_document_light() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.lg_document_light l USING changed c WHERE l.id = c.id;
    ELSE
        INSERT INTO public.lg_document_light (id, props)
        SELECT c.id, coalesce(public.lg_document_light_props(c.props), '{}'::json)
        FROM changed c
        ON CONFLICT (id) DO UPDATE SET props = EXCLUDED.props;
    END IF;
    RETURN NULL;
END $$""",
    ]
    for event, transition in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
        statements.append(
            f"CREATE OR REPLACE TRIGGER documents_light_{event.lower()}"
            f" AFTER {event} ON documents REFERENCING {transition} TABLE AS changed"
            " FOR EACH STATEMENT EXECUTE FUNCTION lg_keep_document_light()"
        )
    return statements


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
        UPDATE public.lg_data_version SET version = version + 1 WHERE collection = TG_TABLE_NAME;
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
    found = [DICTIONARY, FUNCTIONS, SEARCH_FUNCTIONS, DATA_VERSION, TRIGRAMS]
    for collection in NODE_COLLECTIONS:
        found += node_table(collection)
        found += data_version_triggers(collection)
    found += [
        EDGES,
        RAW_SOURCES,
        PIPELINE_STATE,
        HEAT,
        *judgment_light(),
        *document_light(),
        nodes_view(),
    ]
    found += data_version_triggers(COLLECTION_EDGES)
    return found


class SchemaOutdated(RuntimeError):
    """The tables of the database are not those of the schema: it needs building again."""


class CollationMismatch(RuntimeError):
    """The database compares and sorts strings by another collation than ``COLLATION``."""


# ``pg_database.datlocprovider``: the library a database's collation comes from.
_PROVIDERS = {"i": "icu", "c": "libc", "b": "builtin"}


def collation_of(conn: psycopg.Connection) -> str:
    """The collation of the database of *conn*: ``icu und-u-kf-upper``, ``libc en_US.utf8``."""
    row = conn.execute(
        "SELECT datlocprovider, datlocale, datcollate FROM pg_database"
        " WHERE datname = current_database()"
    ).fetchone()
    assert row is not None  # the database of the connection exists
    provider, locale, collate = row
    name = _PROVIDERS.get(str(provider), str(provider))
    return f"{name} {locale if provider in ('i', 'b') else collate}"


def check_collation(conn: psycopg.Connection, allowed: str = "") -> None:
    """Refuse a database that does not sort by ``COLLATION``, unless it is *allowed*.

    A database lawgraph makes has it (``create_database_sql``); one the postgres image
    made at its first start (``POSTGRES_DB``) has the collation of the system. Under that
    one strings compare otherwise: a bound "after every date" falls before the dates, and
    names, titles and keys sort in another order than the API promises."""
    found = collation_of(conn)
    if found == f"icu {COLLATION}":
        return
    if allowed and found == allowed:
        return
    raise CollationMismatch(
        f"the database sorts strings by {found}, not by icu {COLLATION}; queries that "
        "compare or sort strings answer otherwise. Make a database with lawgraph "
        "(create_database_sql) and restore a dump of this one into it (docs/operations.md, "
        f"Database). LAWGRAPH_ALLOW_COLLATION='{found}' lets this one through for that."
    )


_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \(")
_COMMENT = re.compile(r"--[^\n]*")
_NOT_A_COLUMN = ("PRIMARY", "UNIQUE", "CONSTRAINT", "CHECK", "FOREIGN", "EXCLUDE")


def _definitions(text: str, start: int) -> list[str]:
    """The definitions between the parenthesis that opens at *start* in *text* and the one
    that closes it, split on the commas outside parentheses."""
    parts: list[str] = []
    depth, begin = 0, start + 1
    for i in range(start, len(text)):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return [*parts, text[begin:i]]
        elif char == "," and depth == 1:
            parts.append(text[begin:i])
            begin = i + 1
    raise ValueError("a CREATE TABLE without its closing parenthesis")


def _columns(generated: bool) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for statement in statements():
        text = _COMMENT.sub("", statement)
        for match in _TABLE.finditer(text):
            found[match.group(1)] = {
                words[0]
                for part in _definitions(text, match.end() - 1)
                if (words := part.split())
                and words[0].upper() not in _NOT_A_COLUMN
                and (not generated or "GENERATED ALWAYS" in part)
            }
    return found


def expected_columns() -> dict[str, set[str]]:
    """table -> the names of its columns, read from the schema's own CREATE TABLE
    statements."""
    return _columns(generated=False)


def expected_generated() -> dict[str, set[str]]:
    """table -> the names of its generated columns. The derived columns of a node table are
    no generated columns: its trigger fills them (``_derive``)."""
    return _columns(generated=True)


def schema_drift(conn: psycopg.Connection) -> list[str]:
    """What differs between the tables of the database and those of the schema: a column
    the schema has and the table lacks, or the other way round, and a column that is
    generated in one and not in the other. A table that is not there yet differs in
    nothing."""
    expected, generated = expected_columns(), expected_generated()
    actual: dict[str, set[str]] = {}
    actual_generated: dict[str, set[str]] = {}
    for table, column, is_generated in conn.execute(
        "SELECT table_name, column_name, is_generated = 'ALWAYS'"
        " FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        (list(expected),),
    ):
        actual.setdefault(table, set()).add(column)
        if is_generated:
            actual_generated.setdefault(table, set()).add(column)
    differences = []
    for table, columns in sorted(expected.items()):
        present = actual.get(table)
        if present is None:
            continue  # not there yet: it is created as the schema says
        differences += [f"{table}.{c} ontbreekt" for c in sorted(columns - present)]
        differences += [
            f"{table}.{c} staat niet in het schema" for c in sorted(present - columns)
        ]
        was, wanted = actual_generated.get(table, set()), generated.get(table, set())
        differences += [
            f"{table}.{c} is gegenereerd, het schema vult hem met een trigger"
            for c in sorted((was - wanted) & columns)
        ]
        differences += [
            f"{table}.{c} is niet gegenereerd" for c in sorted((wanted - was) & present)
        ]
    return differences


def ensure_schema(conn: psycopg.Connection, *, allowed_collation: str = "") -> None:
    """Create what is missing of the schema in the database of *conn*, in one transaction
    that holds a lock, so two processes that start together do not race.

    A table that exists keeps its columns: ``CREATE TABLE IF NOT EXISTS`` adds none. When
    they are not those of the schema any more (a column added to or dropped from the schema
    since the database was built), this stops with ``SchemaOutdated`` before anything is
    created, instead of letting queries fail later: the database is built again, there is
    no migration (clean slate). A changed expression is not seen: of a generated column, nor
    of a derived column of a node table (its trigger is replaced here, but rows written
    before keep what the old one computed). A database that does not sort by ``COLLATION``
    is refused first (``check_collation``), unless it is *allowed_collation*."""
    with conn.transaction():
        check_collation(conn, allowed_collation)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('lawgraph_schema'))")
        # before anything is created: an index on a column the table lacks would fail first
        differences = schema_drift(conn)
        if differences:
            raise SchemaOutdated(
                "schema verouderd: herbouw nodig (" + "; ".join(differences) + ")"
            )
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
