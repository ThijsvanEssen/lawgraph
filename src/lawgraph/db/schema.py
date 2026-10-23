"""PostgreSQL schema: a table per collection, the edges, the SQL helpers and the data version.

Every node collection is a table of the same shape: ``id`` (``collection/key``, the key of the
graph), ``key``, ``type``, ``labels`` and ``props``. ``props`` is ``json``, not ``jsonb``: the
API serves props as they are, and ``jsonb`` sorts the keys of an object. What the queries
filter, sort or count on is a column of its own (a derived column, which a trigger of the
table fills from ``props``: ``_derive``), with an index where a read needs one.

Strings sort and compare by the ICU root collation with upper case first
(``und-u-kf-upper``), with which the database is created; ``lg_tokens`` cuts and stems the
words of the full-text search.

Everything here is idempotent: ``ensure_schema`` runs on every connect.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.types.json import Json

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
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_TRANSPOSED_TO,
    RELATION_VOTED,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.letter_kinds import ARTICLE_100_SUBJECT, GOVERNMENT_LETTER
from lawgraph.core.logging import get_logger
from lawgraph.core.models import COLLECTIONS
from lawgraph.core.votes import DOCUMENT_OUTCOME_PROPS
from lawgraph.core.xml import collapse_ws
from lawgraph.db._rows import NEIGHBOR_SUMMARY_CHARS
from lawgraph.db._sql import sql_text_list

logger = get_logger(__name__)

# The collation of the database: how strings sort and compare (upper case first).
COLLATION = "und-u-kf-upper"

# The node collections: every collection but the raw records, the pipeline state and the
# edges, which have tables of their own.
NODE_COLLECTIONS: tuple[str, ...] = tuple(spec.name for spec in COLLECTIONS)

# ── SQL helpers ──────────────────────────────────────────────────────────────

FUNCTIONS = r"""
-- Inside a body every function, table and dictionary of this schema is named with its
-- schema, ``public.``: a restore (pg_restore) runs with an empty search_path, and builds the
-- generated columns, which inline these functions, and fires the data version trigger.
-- (A ``SET search_path`` on the function would keep the planner from inlining it.)

-- The value of a props field, only when it has the type the column holds: a string, a
-- number or a boolean; anything else is NULL.
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

-- Whether a json value counts as set: null or a missing value, false, 0 and "" do not;
-- anything else does, an empty array or object too.
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
-- and without the nulls an array ends in, for ``lg_same``: an object with an attribute set
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

-- Whether a write would leave a value as it is: an attribute set to null is the same as a
-- missing one. Equal values are not stripped.
CREATE OR REPLACE FUNCTION lg_same(a jsonb, b jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN a IS NOT DISTINCT FROM b THEN true
                ELSE public.lg_strip_nulls(a) IS NOT DISTINCT FROM public.lg_strip_nulls(b) END
$$;

-- The strings of a JSON array, in order (``props.subjects[*]``); NULL for another type.
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

-- A seat (the meta of a MEMBER_OF edge) holds on *today*: it has no last day or one not yet
-- past, and of the Eerste Kamer, the last snapshot still shows it.
CREATE OR REPLACE FUNCTION lg_seated(meta json, today text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT (coalesce(json_typeof(meta -> 'to_date'), 'null') = 'null'
            OR coalesce(public.lg_str(meta -> 'to_date') >= today, false))
       AND coalesce(json_typeof(meta -> 'observed_until'), 'null') = 'null'
$$;

-- The string *field* of every object of a JSON array (``[*].cabinet_key``).
CREATE OR REPLACE FUNCTION lg_path_array(v json, field text) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN json_typeof(v) = 'array' THEN ARRAY(
        SELECT e ->> field FROM json_array_elements(v) WITH ORDINALITY AS a(e, n)
        WHERE json_typeof(e) = 'object' AND json_typeof(e -> field) = 'string' ORDER BY n
    ) END
$$;

-- An update of props or meta: *a* with the values of *b*, one level deep, every key in the
-- order of the collation. How the store and the steps that set props in place write: an
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

-- *a* without *keys*, the others in their order.
CREATE OR REPLACE FUNCTION lg_unset(a json, keys text[]) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(json_object_agg(key, value ORDER BY n), '{}'::json)
    FROM json_each(coalesce(a, '{}')) WITH ORDINALITY AS e(key, value, n)
    WHERE key <> ALL(keys)
$$;

-- The values of the arrays *a* and *b*, every value once, where it first occurs.
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
-- ß, æ and the typographic apostrophe).
CREATE OR REPLACE FUNCTION lg_fold(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT normalize(regexp_replace(normalize(lower(t), NFD), '[̀-ͯ]', '', 'g'), NFC)
$$;

-- The node key ``core.models.make_node_key`` makes of the identifier t: its compatibility
-- form without accents, in lower case, without what is not ASCII (``Straße`` is
-- ``strae``), each run of other than a letter or a digit one '_', none at the ends;
-- ``node`` when nothing is left. Null of null.
CREATE OR REPLACE FUNCTION lg_node_key(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN t IS NOT NULL THEN coalesce(nullif(trim(both '_' from regexp_replace(
        regexp_replace(
            lower(regexp_replace(normalize(t, NFKD), '[̀-ͯ]', '', 'g')),
            '[^\x01-\x7f]', '', 'g'),
        '[^a-z0-9]+', '_', 'g')), ''), 'node') END
$$;

-- The words of a text for the full-text search: the folded text cut into words (letters,
-- digits and '_'; ':' and apostrophes join letters, '.' and ',' join digits), each word
-- stemmed by the Dutch snowball stemmer without stop words. In order, with repeats.
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

-- The nodes within w_depth edges of w_focal, breadth first, at most w_cap of them, in
-- one statement: a level is read whole (the neighbours along the edges of the relations
-- and status asked for, in the directions asked for, not seen before) and the room the cap
-- leaves is shared among its collections: in rounds, each collection with neighbours left
-- takes up to an equal share of the room, in id order, so a collection with fewer than its
-- share is kept whole and what it leaves goes to the others (not every case of a minister
-- before any of his papers, as id order would). A node that is gone is not one; a node
-- outside w_collections (when given) or w_tables is neither kept nor walked through. A node
-- of w_stop (when given) but the focal one is kept but not walked through, but for its
-- seats: an edge out of it whose relation and collection of its other end are one of
-- w_seats ('MEMBER_OF factions'). A law is not walked back to the old articles whose
-- outcome it holds (lg_transposition_outcome).
-- Whether a neighbour is there is asked of its own table only, w_chunk at a time, so a
-- capped walk does not look up the neighbours it will never keep.
CREATE OR REPLACE FUNCTION lg_walk(
    w_focal text, w_depth int, w_cap int, w_relations text[], w_status text,
    w_outbound boolean, w_inbound boolean, w_collections text[], w_tables text[],
    w_stop text[], w_seats text[], w_chunk int DEFAULT 500
) RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
DECLARE
    seen text[] := ARRAY[w_focal];
    kept text[] := '{}';
    frontier text[] := ARRAY[w_focal];
    -- of the frontier: the nodes walked through, and those walked to their seats only
    free text[];
    stopped text[];
    seat_relations text[] := ARRAY(SELECT split_part(s, ' ', 1) FROM unnest(w_seats) s);
    reached text[];
    chunk text[];
    present text[];
    level text[];
    -- per collection of a level: its name, and the run of ``reached`` that is its (ids
    -- begin with their collection, so a collection's neighbours are one run of them)
    b_coll text[];
    b_pos int[];
    b_end int[];
    room int;
    n_open int;
    share int;
    took int;
    n int;
BEGIN
    FOR step IN 1..w_depth LOOP
        IF w_stop IS NULL OR step = 1 THEN
            free := frontier;
            stopped := '{}';
        ELSE
            free := ARRAY(SELECT x FROM unnest(frontier) x
                          WHERE split_part(x, '/', 1) <> ALL(w_stop));
            stopped := ARRAY(SELECT x FROM unnest(frontier) x
                             WHERE split_part(x, '/', 1) = ANY(w_stop));
        END IF;
        reached := ARRAY(
            SELECT f.id FROM (
                SELECT e.to_id AS id FROM public.edges e
                WHERE w_outbound AND e.from_id = ANY(free)
                  AND (w_relations IS NULL OR e.relation = ANY(w_relations))
                  AND (w_status IS NULL OR e.status = w_status)
                UNION
                SELECT e.from_id FROM public.edges e
                WHERE w_inbound AND e.to_id = ANY(free)
                  AND (w_relations IS NULL OR e.relation = ANY(w_relations))
                  AND (w_status IS NULL OR e.status = w_status)
                  AND NOT public.lg_transposition_outcome(e.relation, e.to_id)
                UNION
                SELECT e.to_id FROM public.edges e
                WHERE w_outbound AND e.from_id = ANY(stopped)
                  AND e.relation = ANY(seat_relations)
                  AND e.relation || ' ' || e.to_collection = ANY(w_seats)
                  AND (w_relations IS NULL OR e.relation = ANY(w_relations))
                  AND (w_status IS NULL OR e.status = w_status)
                EXCEPT
                SELECT unnest(seen)
            ) f
            ORDER BY f.id
        );
        level := '{}';
        SELECT coalesce(array_agg(b.c ORDER BY b.c ASC NULLS LAST), '{}'),
               coalesce(array_agg(b.lo ORDER BY b.c ASC NULLS LAST), '{}'),
               coalesce(array_agg(b.hi ORDER BY b.c ASC NULLS LAST), '{}')
        INTO b_coll, b_pos, b_end
        FROM (
            SELECT split_part(r.x, '/', 1) AS c, min(r.i)::int AS lo, max(r.i)::int AS hi
            FROM unnest(reached) WITH ORDINALITY AS r(x, i)
            GROUP BY 1
        ) b
        WHERE b.c = ANY(w_tables) AND (w_collections IS NULL OR b.c = ANY(w_collections));
        LOOP
            room := w_cap - coalesce(array_length(kept, 1), 0)
                - coalesce(array_length(level, 1), 0);
            SELECT count(*) INTO n_open
            FROM generate_subscripts(b_coll, 1) AS g(i) WHERE b_pos[g.i] <= b_end[g.i];
            EXIT WHEN n_open = 0;
            share := ceil(room::numeric / n_open)::int;
            FOR i IN 1..coalesce(array_length(b_coll, 1), 0) LOOP
                CONTINUE WHEN b_pos[i] > b_end[i];
                took := 0;
                WHILE took < share AND b_pos[i] <= b_end[i] LOOP
                    n := least(w_chunk, share - took, b_end[i] - b_pos[i] + 1);
                    chunk := reached[b_pos[i]:b_pos[i] + n - 1];
                    b_pos[i] := b_pos[i] + n;
                    EXECUTE format(
                        'SELECT coalesce(array_agg(id ORDER BY id), ''{}'')'
                        ' FROM public.%I WHERE id = ANY($1)', b_coll[i]
                    ) INTO present USING chunk;
                    seen := seen || present;
                    level := level || present;
                    took := took + coalesce(array_length(present, 1), 0);
                    IF coalesce(array_length(kept, 1), 0)
                       + coalesce(array_length(level, 1), 0) >= w_cap THEN
                        RETURN kept
                            || level[1:w_cap - coalesce(array_length(kept, 1), 0)];
                    END IF;
                END LOOP;
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

# Whether an edge tells what became of an article of an old law that no article of the new
# law takes the place of: TRANSPOSED_TO the new law itself (an instrument, ``meta.outcome``).
# It is read from the old article; the new law neither walks (``lg_walk``) nor counts it as a
# neighbour (db/queries/nodes.py): a recodification leaves some 1,300 of them on its law.
TRANSPOSITION_OUTCOME = f"""
CREATE OR REPLACE FUNCTION lg_transposition_outcome(relation text, to_id text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT relation = '{RELATION_TRANSPOSED_TO}'
       AND split_part(to_id, '/', 1) = '{COLLECTION_INSTRUMENTS}'
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
-- The 3- to 12-grams of a string of *l* characters.
CREATE OR REPLACE FUNCTION lg_ngrams(l int) RETURNS int
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN l >= 12 THEN 10 * l - 75 WHEN l >= 3 THEN (l - 2) * (l - 1) / 2 ELSE 0 END
$$;
-- The names a member or a faction is searched by, in lower case (``queries/search``):
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


# The GIN index of a column: on its values, on its trigrams, or none.
Index = Literal["gin", "trgm"] | None


@dataclass(frozen=True)
class Column:
    """A derived column of a node table: *name*, its SQL type and the props it holds
    (*expression*, over ``props``). The trigger of the table computes it (``_derive``).
    *index*: the GIN index a search reads it by, on its values (``gin``) or on its
    trigrams (``trgm``); none by default."""

    name: str
    sql_type: str
    expression: str
    index: Index = None
    # a column of a table that is older than it: the start adds it (``ADD COLUMN IF NOT
    # EXISTS``, nullable, without rewriting the table)
    added: bool = False


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


# collection -> the props it is filtered, sorted and counted on.
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
        # the Staatsblad publication that enacted a law the BWB does not hold (yet)
        Column("official_id", "text", "lg_str(props -> 'official_id')", added=True),
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
        # what the feed reads of every document (``queries/feed_sql.py``): its props hold the
        # whole record of the source
        *(_json(field) for field in ("actors", "dossier_numbers", "subject", "title")),
    ),
    COLLECTION_DOSSIERS: (
        _str("number"),
        _str("label"),
        _str("opened_on"),
        _str("last_activity"),
        _bool("closed"),
        _str("cabinet"),
        _str("ministry"),
        # a government bill: ``kind`` and not ``initiative`` (the counts per cabinet)
        _str("kind"),
        _bool("initiative"),
        # what the dossier lists filter, sort and count on, as stored (any type): read
        # without the rest of the props
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
        _str("name"),
        Column("search_names", "text", "lg_member_names(props)"),
        # what the member lists filter and sort on (``queries/members.py``): the name a
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


@dataclass(frozen=True)
class IndexStatement:
    """A ``CREATE [UNIQUE] INDEX IF NOT EXISTS <name> ON <table> ...`` of the schema."""

    statement: str

    def _parts(self) -> re.Match[str]:
        found = _INDEX_HEAD.match(collapse_ws(self.statement))
        assert found, self.statement
        return found

    @property
    def concurrently(self) -> str:
        """The statement on one line, as ``CREATE [UNIQUE] INDEX CONCURRENTLY IF NOT
        EXISTS``."""
        unique = "UNIQUE " if self._parts().group("unique") else ""
        head = f"CREATE {unique}INDEX IF NOT EXISTS "
        return f"CREATE {unique}INDEX CONCURRENTLY IF NOT EXISTS " + collapse_ws(
            self.statement
        ).removeprefix(head)

    @property
    def name(self) -> str:
        return self._parts().group("name")

    @property
    def table(self) -> str:
        return self._parts().group("table")

    @property
    def on_expression(self) -> bool:
        """Whether it indexes an expression (which only ``ANALYZE`` gathers statistics of),
        not only columns: a parenthesis inside its list of what it indexes."""
        rest = self._parts().group("rest")
        depth = 0
        for char in rest:
            if char == "(":
                depth += 1
                if depth == 2:
                    return True
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return False
        return False


_INDEX_HEAD = re.compile(
    r"CREATE (?P<unique>UNIQUE )?INDEX IF NOT EXISTS (?P<name>\w+) ON (?P<table>\w+)"
    r"(?: USING \w+)? (?P<rest>\(.*)",
    re.S,
)

# The indexes of a large table that a release adding one builds beforehand, by hand, with
# CREATE INDEX CONCURRENTLY (``lawgraph built-beforehand`` gives the SQL): ``ensure_schema``
# creates what is missing in one transaction that blocks the table, and then finds it.
BUILT_BEFOREHAND: list[IndexStatement] = []


def built_beforehand(statement: str) -> str:
    """*statement*, an index of ``BUILT_BEFOREHAND``."""
    BUILT_BEFOREHAND.append(IndexStatement(statement))
    return statement


def built_beforehand_sql() -> list[str]:
    """The statements, one a line, that build every index of ``BUILT_BEFOREHAND`` before a
    deploy: each ``CREATE INDEX CONCURRENTLY IF NOT EXISTS``, the query that says whether
    each is valid, and the ``ANALYZE`` of each table with an index on an expression."""
    lines = [f"{index.concurrently};" for index in BUILT_BEFOREHAND]
    names = ", ".join(f"'{index.name}'" for index in BUILT_BEFOREHAND)
    lines.append(
        "SELECT indexrelid::regclass, indisvalid FROM pg_index"
        f" WHERE indexrelid::regclass::text IN ({names});"
    )
    tables = dict.fromkeys(i.table for i in BUILT_BEFOREHAND if i.on_expression)
    return lines + [f"ANALYZE {table};" for table in tables]


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
        # the feed: per tier, newest publication first (``db/queries/feed_sql.py``)
        (("tier", "published_on"), False),
    ),
    COLLECTION_DOSSIERS: (
        (("labels",), False),
        (("number",), False),
        (("label",), False),
        (("opened_on",), False),
        (("last_activity",), False),
        (("closed",), False),
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

# What the search reads, per collection and field, in which forms: ``text``
# (text_nl, stemmed words), ``identity`` (the value as is, for a prefix), ``norm``
# (lawgraph_norm, the folded value) and ``ngram`` (lawgraph_ngram_v2, a part of the folded
# value). Each becomes a column the search reads (``queries/search``).
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

# The last letter of the name of the column a search under an analyzer reads.
SEARCH_COLUMN_SUFFIXES = {
    "identity": "v",
    "text": "t",
    "norm": "n",
    "ngram": "g",
    "prefix": "p",
}


def search_column(field: str, analyzer: str) -> str:
    """The column of *field* a search under *analyzer* reads."""
    return f"s_{field.replace('.', '_')}_{SEARCH_COLUMN_SUFFIXES[analyzer]}"


def start_of_value_sql(table: str, field: str, word: str, row: str) -> str:
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


# Per analyzer: the SQL type, the expression over the values of a field and the index of
# its column. ``prefix``: every value after a separator, so a prefix of a value is an
# indexed part of it.
_ANALYZED: dict[str, Callable[[str], tuple[str, str, Index]]] = {
    "identity": lambda values: ("text[]", values, None),
    "text": lambda values: ("text[]", f"lg_tokens_all({values})", "gin"),
    "norm": lambda values: ("text[]", f"lg_fold_all({values})", "gin"),
    "ngram": lambda values: ("text", f"lg_join(lg_fold_all({values}))", "trgm"),
    "prefix": lambda values: ("text", f"chr(31) || lg_join({values})", "trgm"),
}


def _search_columns(collection: str) -> list[Column]:
    columns: list[Column] = []
    for field, analyzers in SEARCH_FIELDS.get(collection, {}).items():
        values = _values_sql(field)
        # an identity is matched whole on its own column, a prefix of it on ``prefix``
        columns.extend(
            Column(search_column(field, analyzer), *_ANALYZED[analyzer](values))
            for analyzer in analyzers
        )
        if "identity" in analyzers:
            columns.append(
                Column(search_column(field, "prefix"), *_ANALYZED["prefix"](values))
            )
    return columns


# The props a cabinet, a commitment and a vote are searched by, every word of them, lower
# case, as ``search_names`` of members and factions: a trigram index on their expression
# (``search_words``) serves "every word in it". An expression, not a column: the tables keep
# their columns (no rebuild).
SEARCH_WORDS: dict[str, tuple[str, ...]] = {
    COLLECTION_CABINETS: ("name",),
    COLLECTION_COMMITMENTS: ("text", "number"),
    # a vote: what was voted on and its kind (Motie, Amendement, Wetgeving)
    COLLECTION_DECISIONS: ("subject", "kind"),
}


def search_words(collection: str, alias: str = "") -> str:
    """The expression of ``SEARCH_WORDS`` over the props of the row *alias*."""
    p = f"{alias}." if alias else ""
    words = " || ' ' || ".join(
        f"coalesce({p}props ->> '{field}', '')" for field in SEARCH_WORDS[collection]
    )
    return f"lower({words})"


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
        if column.index is None:
            continue
        operators = " gin_trgm_ops" if column.index == "trgm" else ""
        statements.append(
            f"CREATE INDEX IF NOT EXISTS {collection}_{column.name} ON {collection}"
            f" USING gin ({column.name}{operators})"
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


# ``pipeline_state``: per table the digest of its derivation (``derive_digest``) that its
# rows were derived by, under ``derive <table>``.
DERIVE_STATE = "derive "

_DEFINED = re.compile(r"CREATE OR REPLACE FUNCTION (?:public\.)?(lg_\w+)\(")
_CALLED = re.compile(r"\b(lg_\w+)\(")


def derived_collections() -> list[str]:
    """The node tables with derived columns, and so a trigger that derives them."""
    return [c for c in NODE_COLLECTIONS if _derived(c)]


def _function_definitions() -> dict[str, str]:
    """name -> the definition of every ``lg_`` function of the schema, without comments."""
    found: dict[str, str] = {}
    for statement in statements():
        text = _COMMENT.sub("", statement)
        starts = list(_DEFINED.finditer(text))
        for n, start in enumerate(starts):
            end = starts[n + 1].start() if n + 1 < len(starts) else len(text)
            found[start.group(1)] = text[start.start() : end].strip()
    return found


def derive_digest(collection: str) -> str:
    """The digest of how *collection* derives its columns: its trigger function and the
    definition of every ``lg_`` function it calls, through those they call. A release that
    changes one of them changes the digest; rows written before keep what the old one
    derived, until ``semantic graph-derive`` writes them again."""
    definitions = _function_definitions()
    function = _derive(collection)[0]
    called: list[str] = []
    todo = _CALLED.findall(function)
    while todo:
        name = todo.pop(0)
        if name in called or name not in definitions:
            continue
        called.append(name)
        todo += _CALLED.findall(definitions[name])
    digest = hashlib.sha256(function.encode())
    for name in sorted(called):
        digest.update(definitions[name].encode())
    return digest.hexdigest()[:16]


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
        *(
            f"ALTER TABLE {collection} ADD COLUMN IF NOT EXISTS {c.name} {c.sql_type}"
            for c in derived
            if c.added
        ),
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


def instrument_date_in_force(alias: str = "") -> str:
    """The day an instrument (of the row *alias*) came into force, as text: the expression
    of the index ``instruments_date_in_force``."""
    p = f"{alias}." if alias else ""
    return f"public.lg_str({p}props -> 'date_in_force')"


def instrument_dossier_numbers(alias: str = "") -> str:
    """The dossier numbers of an instrument (a publication's; of the row *alias*), as text:
    the expression of the index ``instruments_dossier_numbers``."""
    p = f"{alias}." if alias else ""
    return f"public.lg_text_array({p}props -> 'dossier_numbers')"


def feed_title(alias: str = "") -> str:
    """The title the feed shows of a document (``queries/feed_sql.py``), its subject or else its
    title, folded as the search folds (``lg_fold``): the expression of the trigram index
    ``documents_feed_title_g``, which serves the words (``q``) of the feed. The index and
    the feed write it alike, or the planner does not take the index."""
    p = f"{alias}." if alias else ""
    return (
        f"public.lg_fold(coalesce((CASE WHEN public.lg_truthy({p}pj_subject)"
        f" THEN {p}pj_subject ELSE {p}pj_title END) #>> '{{}}', ''))"
    )


def article_100_letter(alias: str = "") -> str:
    """Whether a document (of the row *alias*) is an artikel 100-brief: the rule of
    ``core/letter_kinds.letter_kind`` on its ``kind`` and ``pj_subject``, the predicate of
    the partial index ``documents_article_100``. The index and the list write it alike, or
    the planner does not take the index."""
    p = f"{alias}." if alias else ""
    return (
        f"{p}kind = '{GOVERNMENT_LETTER}'"
        f" AND public.lg_str({p}pj_subject) ~* '{ARTICLE_100_SUBJECT}'"
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
        # the instruments of the list (no publications: a few thousand) by the day they
        # came into force (``from``/``to``)
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS instruments_date_in_force"
            f" ON instruments (({instrument_date_in_force()})) WHERE {_LISTED}"
        ),
        # and by the day they were published (``published_from``/``published_to``):
        # ``(kind, date_published)`` holds every publication too
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS instruments_list_date_published"
            f" ON instruments (date_published) WHERE {_LISTED}"
        ),
        # the publications of a dossier, for the words (``q``) of the feed in its title
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS instruments_dossier_numbers"
            f" ON instruments USING gin (({instrument_dossier_numbers()}))"
        ),
        # the regulations a publication enacted (``props.enacted_publication``): the laws a
        # publication of the feed establishes (``queries/feed_relations``)
        "CREATE INDEX IF NOT EXISTS instruments_enacted_publication"
        f" ON instruments ((public.lg_str(props -> 'enacted_publication'))) WHERE {_LISTED}",
    ),
    # an article of a law of the Staatsblad by its number (``official_id`` as ``bwb_id``):
    # every row but those of these laws has none
    COLLECTION_ARTICLES: (
        built_beforehand(
            "CREATE UNIQUE INDEX IF NOT EXISTS articles_official_id_article_number"
            " ON articles (official_id, article_number)"
        ),
    ),
    # /api/documents, newest first: a page without a kind or dossier reads only itself.
    COLLECTION_DOCUMENTS: (
        "CREATE INDEX IF NOT EXISTS documents_list_date"
        " ON documents (date DESC NULLS LAST, key)",
        # the words of the feed (``q``) in the title it shows
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS documents_feed_title_g"
            f" ON documents USING gin (({feed_title()}) gin_trgm_ops)"
        ),
        # the artikel 100-brieven (``letter_kind=article_100``): a few hundred letters,
        # newest first
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS documents_article_100"
            f" ON documents (date DESC NULLS LAST, key) WHERE {article_100_letter()}"
        ),
    ),
    # /api/decisions, newest first: a page reads as far as it goes in the order of the list,
    # not every decision under the filters sorted (1.6 s a first page on the full graph)
    COLLECTION_DECISIONS: (
        "CREATE INDEX IF NOT EXISTS decisions_list_date"
        " ON decisions (date DESC NULLS LAST, key)",
        # the votes on a motion of censure or of no confidence (``motion_kind``): a few
        # hundred of them
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS decisions_motion_kind"
            " ON decisions (public.lg_str(props -> 'motion_kind'))"
            " WHERE public.lg_str(props -> 'motion_kind') IS NOT NULL"
        ),
    ),
    # /api/judgments by the main area of law (``subject_area``): a GIN index on the areas
    COLLECTION_JUDGMENTS: (
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS judgments_subject_areas"
            " ON judgments USING gin (public.lg_subject_areas(subjects))"
        ),
    ),
    # the member lists in name order: those who held a seat, and the Eerste Kamer's; a
    # member by their slug (``/leden/rob-jetten``)
    COLLECTION_MEMBERS: (
        "CREATE INDEX IF NOT EXISTS members_list_name ON members"
        " (list_name NULLS FIRST, key) WHERE in_parliament AND list_name <> ''",
        "CREATE INDEX IF NOT EXISTS members_list_ek ON members"
        " (list_name NULLS FIRST, key) WHERE in_ek",
        "CREATE INDEX IF NOT EXISTS members_slug"
        " ON members (public.lg_str(props -> 'slug'))",
    ),
    # a zaak by its number (``/zaken/2025Z15468``)
    COLLECTION_CASES: (
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS cases_number"
            " ON cases (public.lg_str(props -> 'number'))"
        ),
    ),
    # an activity by its number (``/activiteiten/2026A01323``)
    COLLECTION_ACTIVITIES: (
        built_beforehand(
            "CREATE INDEX IF NOT EXISTS activities_number"
            " ON activities (public.lg_str(props -> 'number'))"
        ),
    ),
    # a committee by its slug or its key (``/commissies/szw``)
    COLLECTION_COMMITTEES: (
        "CREATE INDEX IF NOT EXISTS committees_slug"
        " ON committees (public.lg_str(props -> 'slug'))",
        "CREATE INDEX IF NOT EXISTS committees_lower_key ON committees (lower(key))",
    ),
}


# ── edges, raw records, pipeline state ───────────────────────────────────────

_EDGES_TO_COVER = built_beforehand(
    "CREATE INDEX IF NOT EXISTS edges_to_cover ON edges (to_id, relation, from_collection, key)"
    "\n    INCLUDE (from_id, to_collection)"
)
_EDGES_FROM_COVER = built_beforehand(
    "CREATE INDEX IF NOT EXISTS edges_from_cover ON edges (from_id, relation, to_collection, key)"
    "\n    INCLUDE (to_id, from_collection)"
)

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
-- The edges at a node by relation and the other collection, in key order, with both ends
-- without the row: a level of ``paths`` reads a node with 20,000 edges from a few hundred
-- pages of the index, not a page of the table per edge; a page of a node's neighbours stops
-- after its limit in key order instead of reading and sorting the whole bucket. The only
-- indexes by end: one on the ends alone, smaller, was taken for a bucket the planner
-- thought held one edge, and read the table for every edge of a hub. On a large database
-- built beforehand with CREATE INDEX CONCURRENTLY.
{_EDGES_TO_COVER};
{_EDGES_FROM_COVER};
CREATE INDEX IF NOT EXISTS edges_relation ON edges (relation);
CREATE INDEX IF NOT EXISTS edges_created_at ON edges (created_at, to_id);
CREATE INDEX IF NOT EXISTS edges_status_relation ON edges (status, relation);
CREATE INDEX IF NOT EXISTS edges_record_ids ON edges USING gin (record_ids);
CREATE INDEX IF NOT EXISTS edges_semantic_type ON edges (semantic_type)
    WHERE semantic_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS edges_from_semantic_type ON edges (from_id, semantic_type)
    WHERE semantic_type IS NOT NULL
"""

RAW_SOURCES = f"""
CREATE TABLE IF NOT EXISTS {COLLECTION_RAW_SOURCES} (
    key text PRIMARY KEY,
    -- the record as ``raw_source_doc`` makes it, without ``key``
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

# ── side tables ──────────────────────────────────────────────────────────────

_ALL_EVENTS = ("INSERT", "UPDATE", "DELETE")


def _after_each_statement(
    table: str, name: str, function: str, events: tuple[str, ...] = _ALL_EVENTS
) -> list[str]:
    """The triggers ``{table}_{name}_{event}`` that run *function* after each statement
    of *events* on *table*, with the rows it wrote (or deleted) as ``changed``."""
    return [
        f"CREATE OR REPLACE TRIGGER {table}_{name}_{event.lower()}"
        f" AFTER {event} ON {table}"
        f" REFERENCING {'OLD' if event == 'DELETE' else 'NEW'} TABLE AS changed"
        f" FOR EACH STATEMENT EXECUTE FUNCTION {function}()"
        for event in events
    ]


def case_date_sql(case: str) -> str:
    """SQL: the date of the row *case* of ``cases``: the day it started (``Zaak.GestartOp``,
    ``started_on`` of its props; the table has no column of it)."""
    return f"public.lg_str({case}.props -> 'started_on')"


def _follow_dates(
    side: str, alias: str, id_column: str, name: str, tables: dict[str, str]
) -> list[str]:
    """The functions and triggers that give the rows of the side table *side* (as
    *alias*) whose *id_column* names a row written to one of *tables* the date of that row
    again (*tables*: per table the SQL of the date of its row ``c``): a row written after
    the one that refers to it, or its date changed. Named ``lg_keep_{name}_{table}_date``
    and ``{table}_{name}_date_{event}``."""
    statements = []
    for table, date in tables.items():
        function = f"lg_keep_{name}_{table}_date"
        statements.append(
            f"""CREATE OR REPLACE FUNCTION {function}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE public.{side} {alias} SET date = {date}
    FROM changed c
    WHERE {alias}.{id_column} = c.id AND {alias}.date IS DISTINCT FROM {date};
    RETURN NULL;
END $$"""
        )
        statements += _after_each_statement(
            table, f"{name}_date", function, ("INSERT", "UPDATE")
        )
    return statements


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
    "stub",
    "translation_of",
    "advocate_general",
    "advocate_general_role",
    # how it ended and what a conclusion proposes (``core/judgment_outcome.py``), what the
    # ECHR found per article (``core/echr_findings.py``): what a row of it shows
    "outcome",
    "outcome_text",
    "conclusion_outcome",
    "conclusion_outcome_text",
    "echr_findings",
)
# The characters of a summary kept: one more than a neighbour shows, so it knows to cut.
JUDGMENT_LIGHT_SUMMARY = NEIGHBOR_SUMMARY_CHARS + 1


def judgment_light() -> list[str]:
    keys = sql_text_list(JUDGMENT_LIGHT_PROPS)
    return [
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
        *_after_each_statement("judgments", "light", "lg_keep_judgment_light"),
    ]


# The persons a judgment names, which the search finds it by (``queries/search``): each party
# whose name is not anonymised ("[appellant]") and each who acts for a party
# (``core.judgment_counsel``), with the party's alias or name. ``words`` is the name folded
# (``lg_fold``) with every run of other characters a space, between spaces: " mr drs r van
# gelder ", so a word of a name is found whole or by its start. Kept by a trigger on every
# write of a judgment's props; ``semantic graph-light`` fills it for the judgments written
# before. Not a table of the graph: writing it raises no data version.
def judgment_persons() -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS lg_judgment_persons (
    id text NOT NULL,
    n integer NOT NULL,
    name text NOT NULL,
    role text,
    party text,
    date_eff text,
    words text NOT NULL,
    PRIMARY KEY (id, n)
)""",
        "CREATE INDEX IF NOT EXISTS lg_judgment_persons_words ON lg_judgment_persons"
        " USING gin (words gin_trgm_ops)",
        r"""CREATE OR REPLACE FUNCTION lg_person_words(name text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT ' ' || btrim(regexp_replace(public.lg_fold(name), '[^[:alnum:]]+', ' ', 'g'))
        || ' '
$$""",
        r"""CREATE OR REPLACE FUNCTION lg_judgment_person_rows(p json)
RETURNS TABLE (n integer, name text, role text, party text)
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    WITH parties AS (
        SELECT x.party, x.i
        FROM json_array_elements(
            CASE WHEN json_typeof(p -> 'parties') = 'array' THEN p -> 'parties'
                 ELSE '[]'::json END
        ) WITH ORDINALITY AS x(party, i)
        WHERE json_typeof(x.party) = 'object'
    ), persons AS (
        SELECT (i * 1000)::int AS n, party ->> 'name' AS name, party ->> 'role' AS role,
               NULL::text AS party
        FROM parties
        UNION ALL
        SELECT (i * 1000 + j)::int, r ->> 'name', r ->> 'role',
               coalesce(party ->> 'alias', party ->> 'name')
        FROM parties, json_array_elements(
            CASE WHEN json_typeof(party -> 'representatives') = 'array'
                 THEN party -> 'representatives' ELSE '[]'::json END
        ) WITH ORDINALITY AS y(r, j)
        WHERE json_typeof(r) = 'object'
    )
    SELECT n, name, role, party FROM persons
    WHERE coalesce(btrim(name), '') <> '' AND name !~ '^\s*\['
$$""",
        """CREATE OR REPLACE FUNCTION lg_keep_judgment_persons() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        DELETE FROM public.lg_judgment_persons WHERE id = OLD.id;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    INSERT INTO public.lg_judgment_persons (id, n, name, role, party, date_eff, words)
    SELECT NEW.id, f.n, f.name, f.role, f.party, NEW.date_eff,
           public.lg_person_words(f.name)
    FROM public.lg_judgment_person_rows(NEW.props) f
    ON CONFLICT (id, n) DO NOTHING;
    RETURN NEW;
END $$""",
        # a row trigger: a statement trigger with transition tables cannot be limited to
        # a write of the props, and every other column of a judgment is written in bulk
        "CREATE OR REPLACE TRIGGER judgments_persons"
        " AFTER INSERT OR DELETE OR UPDATE OF props ON judgments"
        " FOR EACH ROW EXECUTE FUNCTION lg_keep_judgment_persons()",
    ]


# What ``normalize tk-dossiers`` reads of each document of a dossier to derive its title, kind
# and phases (``queries/normalize/tk.dossier_signals``), kept apart from its props, which
# hold its whole text: the signals of a dossier read these, not the text of its documents.
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
    # the day of an advice of the Raad van State as its paper opens, which the phase of a
    # bill dates by (``core/advice_dates.py``)
    "advice_date",
    # what a motion asks or says, which a list of votes shows (``core/motion_dictum.py``)
    "dictum",
    # what an amendment is for, as its Toelichting opens (``core/amendment_explanation.py``)
    "explanation",
    # how a motion or an amendment ended (``core/votes.py``), which a row of it
    # shows and ``semantic tk-paper-outcomes`` compares with
    *DOCUMENT_OUTCOME_PROPS,
    # of a motion of censure or of no confidence its kind (``core/motion_kinds.py``), which
    # the list of papers filters on and ``semantic tk-motion-kinds`` compares with
    "motion_kind",
)
# ... and, after them, ``has_text``: whether the document's text is in the data (a string, not
# empty), which a row of the feed opens on; read from the same pass over the props.


# a document by its dossier and number (``queries/lookup.find_document``): one index probe,
# where the props of every document of a budget dossier were read for it
_DOCUMENT_LIGHT_BY_NUMBER = built_beforehand(
    "CREATE INDEX IF NOT EXISTS lg_document_light_paper ON lg_document_light"
    " (lg_str(props -> 'dossier_number'),"
    " upper(coalesce(lg_str(props -> 'dossier_suffix'), '')),"
    " lg_num(props -> 'sequence'))"
)


# the motions of censure and of no confidence (``GET /api/documents?motion_kind=``): a few
# hundred rows of the light row of every paper
_DOCUMENT_LIGHT_BY_MOTION_KIND = built_beforehand(
    "CREATE INDEX IF NOT EXISTS lg_document_light_motion_kind ON lg_document_light"
    " (lg_str(props -> 'motion_kind'))"
    " WHERE lg_str(props -> 'motion_kind') IS NOT NULL"
)


def document_light() -> list[str]:
    keys = sql_text_list(DOCUMENT_LIGHT_PROPS)
    statements = [
        """CREATE TABLE IF NOT EXISTS lg_document_light (
    id text PRIMARY KEY,
    props json NOT NULL
)""",
        f"""CREATE OR REPLACE FUNCTION lg_document_light_props(p json) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    WITH e AS (
        SELECT key, value, n
        FROM json_each(CASE WHEN json_typeof(p) = 'object' THEN p ELSE '{{}}'::json END)
            WITH ORDINALITY AS e(key, value, n)
    )
    SELECT json_object_agg(x.key, x.value ORDER BY x.n)
    FROM (
        SELECT key, value, n FROM e WHERE key IN ({keys})
        UNION ALL
        SELECT 'has_text', to_json(coalesce(bool_or(
            key = 'text' AND json_typeof(value) = 'string' AND value::text <> '""'
        ), false)), 9223372036854775807
        FROM e
    ) x
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
        *_after_each_statement("documents", "light", "lg_keep_document_light"),
    ]
    statements += [_DOCUMENT_LIGHT_BY_NUMBER, _DOCUMENT_LIGHT_BY_MOTION_KIND]
    return statements


# The names of an instrument a dossier title may give it besides its citation title (a
# column of ``instruments``), without its props, which a read of one prop would parse whole:
# what ``queries/law_names.load_law_names`` reads of every instrument. Kept by triggers on
# every write of an instrument; ``semantic graph-light`` fills it once. Not a table of the
# graph: writing it raises no data version.
def instrument_name_columns(row: str) -> str:
    """SQL: ``title, short_title`` of the ``instruments`` row *row*, as ``lg_instrument_names``
    keeps them; its trigger and ``queries/instrument_names.fill_instrument_names`` read them
    from here."""
    return (
        f"coalesce({row}.props -> 'title' #>> '{{}}', ''),"
        f" coalesce({row}.props -> 'short_title' #>> '{{}}', '')"
    )


def instrument_names() -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS lg_instrument_names (
    id text PRIMARY KEY,
    title text NOT NULL,
    short_title text NOT NULL
)""",
        f"""CREATE OR REPLACE FUNCTION lg_keep_instrument_names() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.lg_instrument_names n USING changed c WHERE n.id = c.id;
    ELSE
        INSERT INTO public.lg_instrument_names (id, title, short_title)
        SELECT c.id, {instrument_name_columns("c")}
        FROM changed c
        ON CONFLICT (id) DO UPDATE
            SET title = EXCLUDED.title, short_title = EXCLUDED.short_title;
    END IF;
    RETURN NULL;
END $$""",
        *_after_each_statement("instruments", "names", "lg_keep_instrument_names"),
    ]


# Every vote of a faction (a ``VOTED`` edge from ``factions``) with the date, key and kind of
# vote of its decision: what the page of a member's votes reads of the faction's periods, a
# range of an index per period instead of a walk over the decisions with a probe of the edges
# per decision (``queries/member_votes.get_member_votes``). Kept by triggers on every write of
# ``edges`` and ``decisions``; ``semantic graph-light`` fills it once. Not a table of the
# graph: writing it raises no data version.
def faction_vote_columns(edge: str, decision: str) -> str:
    """SQL: ``edge_key, faction_id, decision_id, date, decision_key, vote_kind`` of the
    ``VOTED`` edge *edge* of a faction and its decision *decision*, as ``lg_faction_votes``
    keeps them; its triggers and ``queries/faction_votes.fill_faction_votes`` read them from
    here."""
    return (
        f"{edge}.key, {edge}.from_id, {edge}.to_id, {decision}.date, {decision}.key,"
        f" public.lg_str({decision}.props -> 'vote_kind')"
    )


def faction_votes() -> list[str]:
    return [
        """CREATE TABLE IF NOT EXISTS lg_faction_votes (
    edge_key text PRIMARY KEY,
    faction_id text NOT NULL,
    decision_id text NOT NULL,
    date text,
    decision_key text NOT NULL,
    vote_kind text
)""",
        "CREATE INDEX IF NOT EXISTS lg_faction_votes_period ON lg_faction_votes"
        " (faction_id, date DESC, decision_key ASC)",
        "CREATE INDEX IF NOT EXISTS lg_faction_votes_decision ON lg_faction_votes"
        " (decision_id)",
        f"""CREATE OR REPLACE FUNCTION lg_keep_faction_votes_of_edges() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        DELETE FROM public.lg_faction_votes v USING changed c
        WHERE v.edge_key = c.key
          AND c.relation = '{RELATION_VOTED}' AND c.from_collection = '{COLLECTION_FACTIONS}';
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO public.lg_faction_votes
            (edge_key, faction_id, decision_id, date, decision_key, vote_kind)
        SELECT {faction_vote_columns("c", "d")}
        FROM changed c JOIN public.decisions d ON d.id = c.to_id
        WHERE c.relation = '{RELATION_VOTED}' AND c.from_collection = '{COLLECTION_FACTIONS}'
        ON CONFLICT (edge_key) DO UPDATE SET
            faction_id = EXCLUDED.faction_id, decision_id = EXCLUDED.decision_id,
            date = EXCLUDED.date, decision_key = EXCLUDED.decision_key,
            vote_kind = EXCLUDED.vote_kind;
    END IF;
    RETURN NULL;
END $$""",
        f"""CREATE OR REPLACE FUNCTION lg_keep_faction_votes_of_decisions() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.lg_faction_votes v USING changed c WHERE v.decision_id = c.id;
    ELSE
        -- a vote written before its decision, and a decision whose date or kind changed
        INSERT INTO public.lg_faction_votes
            (edge_key, faction_id, decision_id, date, decision_key, vote_kind)
        SELECT {faction_vote_columns("e", "c")}
        FROM changed c
        JOIN public.edges e
          ON e.to_id = c.id AND e.relation = '{RELATION_VOTED}'
         AND e.from_collection = '{COLLECTION_FACTIONS}'
        ON CONFLICT (edge_key) DO UPDATE SET
            date = EXCLUDED.date, decision_key = EXCLUDED.decision_key,
            vote_kind = EXCLUDED.vote_kind;
    END IF;
    RETURN NULL;
END $$""",
        *_after_each_statement(
            "edges", "faction_votes", "lg_keep_faction_votes_of_edges"
        ),
        *_after_each_statement(
            "decisions", "faction_votes", "lg_keep_faction_votes_of_decisions"
        ),
    ]


def signed_date_sql(document: str) -> str:
    """SQL: the date of the document, case or other node *document* (an SQL text value) signed.
    ``lg_signed_date`` is made of it; a query that reads it for many rows writes it in
    itself, which is many times faster than the call of the function per row."""
    return f"""CASE
        WHEN starts_with({document}, '{COLLECTION_DOCUMENTS}/') THEN
            (SELECT d.date FROM public.{COLLECTION_DOCUMENTS} d WHERE d.id = {document})
        WHEN starts_with({document}, '{COLLECTION_CASES}/') THEN
            (SELECT {case_date_sql("k")} FROM public.{COLLECTION_CASES} k
             WHERE k.id = {document})
        ELSE (SELECT public.lg_str(n.props -> 'date') FROM public.nodes n
              WHERE n.id = {document})
    END"""


def dossiers_of_sql(document: str) -> str:
    """SQL: the ids of the dossiers of the document (or the case) *document* (an SQL text value),
    directly and through the cases it is part of, each once. ``lg_dossiers_of`` is made of
    it; a query that reads it for many rows writes it in itself, as a subquery."""
    part_of = RELATION_PART_OF
    return f"""
        SELECT p.to_id FROM public.edges p
        WHERE p.from_id = {document} AND p.relation = '{part_of}'
          AND p.to_collection = '{COLLECTION_DOSSIERS}'
        UNION
        SELECT p2.to_id FROM public.edges p1
        JOIN public.edges p2 ON p2.from_id = p1.to_id AND p2.relation = '{part_of}'
         AND p2.to_collection = '{COLLECTION_DOSSIERS}'
        WHERE p1.from_id = {document} AND p1.relation = '{part_of}'
          AND p1.to_collection = '{COLLECTION_CASES}'
    """


# Every document a member signed (an ``AUTHORED`` edge from ``members``) with what the edge says
# of the signature and the dossiers of the document, directly or through its case: what the
# page of a member's dossiers reads, a range of an index instead of the edges of every document
# they signed and a probe of its dossiers each (``queries/actors.get_actor_dossiers``).
# With the date of the document or case and the capacity of the signature, so that what a
# member signed within a cabinet is a range of an index, not a probe of every document they
# ever signed for its date (``queries/cabinets``). Kept by triggers on every write of
# ``edges`` (the signatures, and the documents placed in a dossier or a case, and the cases in
# a dossier), and of ``documents`` and ``cases`` (their dates); ``semantic graph-light``
# fills it once. Not a table of the graph: writing it raises no data version.
# what a member signed in a capacity within a period, from the index alone
_AUTHORED_MEMBER_DATE = built_beforehand(
    "CREATE INDEX IF NOT EXISTS lg_authored_member_date"
    " ON lg_authored (member_id, capacity, date) INCLUDE (dossiers)"
)


def member_authored() -> list[str]:
    part_of, authored = RELATION_PART_OF, RELATION_AUTHORED
    return [
        """CREATE TABLE IF NOT EXISTS lg_authored (
    edge_key text PRIMARY KEY,
    member_id text NOT NULL,
    document_id text NOT NULL,
    meta json NOT NULL,
    dossiers text[] NOT NULL,
    date text,
    capacity text
)""",
        "CREATE INDEX IF NOT EXISTS lg_authored_member ON lg_authored (member_id)",
        "CREATE INDEX IF NOT EXISTS lg_authored_document ON lg_authored (document_id)",
        _AUTHORED_MEMBER_DATE,
        # the date of a document, a case or another node signed (plpgsql: the view of every
        # node it reads for another node is made after this)
        f"""CREATE OR REPLACE FUNCTION lg_signed_date(paper text) RETURNS text
LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
BEGIN
    RETURN {signed_date_sql("paper")};
END $$""",
        # the dossiers of a document (or a case): directly, and through the cases it is part of
        f"""CREATE OR REPLACE FUNCTION lg_dossiers_of(paper text) RETURNS text[]
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(DISTINCT d ORDER BY d ASC NULLS LAST), '{{}}')
    FROM ({dossiers_of_sql("paper")}) found(d)
$$""",
        f"""CREATE OR REPLACE FUNCTION lg_keep_authored() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        DELETE FROM public.lg_authored a USING changed c
        WHERE a.edge_key = c.key
          AND c.relation = '{authored}' AND c.from_collection = '{COLLECTION_MEMBERS}';
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO public.lg_authored
            (edge_key, member_id, document_id, meta, dossiers, date, capacity)
        SELECT c.key, c.from_id, c.to_id,
               json_build_object('role', c.doc -> 'meta' -> 'role',
                                 'function', c.doc -> 'meta' -> 'function',
                                 'capacity', c.doc -> 'meta' -> 'capacity'),
               public.lg_dossiers_of(c.to_id), public.lg_signed_date(c.to_id),
               public.lg_str(c.doc -> 'meta' -> 'capacity')
        FROM changed c
        WHERE c.relation = '{authored}' AND c.from_collection = '{COLLECTION_MEMBERS}'
        ON CONFLICT (edge_key) DO NOTHING;
    END IF;
    -- a paper placed in a dossier or a case, or a case in a dossier (or taken out): the
    -- dossiers of the papers signed that it reaches again
    WITH placed AS MATERIALIZED (
        SELECT c.from_id, c.from_collection, c.to_collection FROM changed c
        WHERE c.relation = '{part_of}'
          AND c.to_collection IN ('{COLLECTION_DOSSIERS}', '{COLLECTION_CASES}')
    )
    UPDATE public.lg_authored a SET dossiers = public.lg_dossiers_of(a.document_id)
    WHERE a.document_id IN (
        SELECT p.from_id FROM placed p
        UNION
        SELECT e.from_id FROM placed p
        JOIN public.edges e ON e.to_id = p.from_id AND e.relation = '{part_of}'
        WHERE p.from_collection = '{COLLECTION_CASES}'
          AND p.to_collection = '{COLLECTION_DOSSIERS}'
    );
    RETURN NULL;
END $$""",
        *_after_each_statement("edges", "authored", "lg_keep_authored"),
        # a document or a case written after its signature, or its date changed
        *_follow_dates(
            "lg_authored",
            "a",
            "document_id",
            "authored",
            {COLLECTION_DOCUMENTS: "c.date", COLLECTION_CASES: case_date_sql("c")},
        ),
    ]


# What each committee leads: every ``LED_BY`` edge into a committee (from an activity or a
# case) with the date of that item and its dossiers (an activity is ``ABOUT`` them, a case
# ``PART_OF`` them). What the pages of a committee read (``queries/committees``): its
# activities a range of an index in the order of their dates, its dossiers those kept with its
# items, instead of a probe of the edges or the row of every item it leads (8.9 s for the
# dossiers of Financiën on prod, 17,920 items). Kept by triggers on ``edges`` (an item led, a
# dossier it is about or part of) and on ``activities``
# and ``cases`` (their dates); ``semantic graph-light`` fills it once. Not a table of the
# graph: writing it raises no data version.
def committee_led() -> list[str]:
    led_by, about, part_of = RELATION_LED_BY, RELATION_ABOUT, RELATION_PART_OF
    return [
        """CREATE TABLE IF NOT EXISTS lg_led (
    edge_key text PRIMARY KEY,
    committee_id text NOT NULL,
    item_id text NOT NULL,
    item_collection text NOT NULL,
    date text,
    dossiers text[] NOT NULL
)""",
        "CREATE INDEX IF NOT EXISTS lg_led_committee ON lg_led"
        " (committee_id, item_collection, date DESC NULLS LAST, item_id) INCLUDE (dossiers)",
        "CREATE INDEX IF NOT EXISTS lg_led_item ON lg_led (item_id)",
        # the dossiers an activity is about or a case is part of
        f"""CREATE OR REPLACE FUNCTION lg_led_dossiers(item text) RETURNS text[]
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT coalesce(array_agg(DISTINCT e.to_id ORDER BY e.to_id ASC NULLS LAST), '{{}}')
    FROM public.edges e
    WHERE e.from_id = item AND e.relation IN ('{about}', '{part_of}')
      AND e.to_collection = '{COLLECTION_DOSSIERS}'
$$""",
        # the date of an activity or a case
        f"""CREATE OR REPLACE FUNCTION lg_led_date(item text) RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN starts_with(item, '{COLLECTION_ACTIVITIES}/') THEN
            (SELECT a.date FROM public.{COLLECTION_ACTIVITIES} a WHERE a.id = item)
        WHEN starts_with(item, '{COLLECTION_CASES}/') THEN
            (SELECT {case_date_sql("k")} FROM public.{COLLECTION_CASES} k
             WHERE k.id = item)
    END
$$""",
        f"""CREATE OR REPLACE FUNCTION lg_keep_led() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        DELETE FROM public.lg_led l USING changed c
        WHERE l.edge_key = c.key AND c.relation = '{led_by}';
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO public.lg_led
            (edge_key, committee_id, item_id, item_collection, date, dossiers)
        SELECT c.key, c.to_id, c.from_id, c.from_collection,
               public.lg_led_date(c.from_id), public.lg_led_dossiers(c.from_id)
        FROM changed c
        WHERE c.relation = '{led_by}' AND c.to_collection = '{COLLECTION_COMMITTEES}'
        ON CONFLICT (edge_key) DO NOTHING;
    END IF;
    -- an item led placed in a dossier or taken out: its dossiers again
    UPDATE public.lg_led l SET dossiers = public.lg_led_dossiers(l.item_id)
    WHERE l.item_id IN (
        SELECT c.from_id FROM changed c
        WHERE c.relation IN ('{about}', '{part_of}')
          AND c.to_collection = '{COLLECTION_DOSSIERS}'
    );
    RETURN NULL;
END $$""",
        *_after_each_statement("edges", "led", "lg_keep_led"),
        # an activity or a case written after the edge that leads it, or its date changed
        *_follow_dates(
            "lg_led",
            "l",
            "item_id",
            "led",
            {COLLECTION_ACTIVITIES: "c.date", COLLECTION_CASES: case_date_sql("c")},
        ),
    ]


# The judgments that cite an article: every ``REFERS_TO`` edge from a judgment into an article,
# with how many passages of the judgment cite it (``mentions``, the length of the edge's
# ``meta.mentions``), the leden each passage names, in their order (``leden``), and what
# the citing judgments are filtered, sorted and counted on (its date, ECLI, court, tier and
# ``inbound_citation_count`` as ``cited``). What ``/cited-by`` of an article and
# ``/judgments`` of a law read: a range of the index of the article, instead of the edge of
# every citing judgment and its mentions (6:162 BW: 10,500 edges, 25 s cold on prod).
# Kept by triggers on ``edges`` and ``judgments``, a row for each edge of a judgment that
# is there; ``semantic graph-light`` fills it once. Not a table of the graph: writing it
# raises no data version.
CITED_BY_TABLE = "lg_cited_by"
CITED_BY_COLUMNS = (
    "edge_key, article_id, judgment_id, mentions, leden,"
    " date_eff, ecli, court_code, tier, cited"
)


def cited_by_values(edge: str, judgment: str) -> str:
    """SQL: the ``CITED_BY_COLUMNS`` of the row of the edge *edge* from the judgment
    *judgment* (rows of ``edges`` and ``judgments``)."""
    leden = f"public.lg_cited_by_leden({edge}.doc)"
    return (
        f"{edge}.key, {edge}.to_id, {edge}.from_id, json_array_length({leden}), {leden},"
        f" {judgment}.date_eff, {judgment}.ecli, {judgment}.court_code, {judgment}.tier,"
        f" {judgment}.inbound_citation_count"
    )


def cited_by_judgment(edge: str) -> str:
    """SQL: the judgment ``j`` the edge *edge* comes from, read by its key alone (a
    ``LATERAL`` with a limit is not made a join: of a transition table of thousands of
    edges the planner would read the whole table of the judgments)."""
    return (
        f"CROSS JOIN LATERAL (SELECT x.date_eff, x.ecli, x.court_code, x.tier,"
        f" x.inbound_citation_count FROM public.{COLLECTION_JUDGMENTS} x"
        f" WHERE x.id = {edge}.from_id LIMIT 1) j"
    )


def cited_by_edges(edge: str) -> str:
    """SQL: the edge *edge* is one ``CITED_BY_TABLE`` keeps: ``REFERS_TO`` from a judgment
    into an article."""
    return (
        f"{edge}.relation = '{RELATION_REFERS_TO}'"
        f" AND {edge}.from_collection = '{COLLECTION_JUDGMENTS}'"
        f" AND {edge}.to_collection = '{COLLECTION_ARTICLES}'"
    )


def article_cited_by() -> list[str]:
    return [
        f"""CREATE TABLE IF NOT EXISTS {CITED_BY_TABLE} (
    edge_key text PRIMARY KEY,
    article_id text NOT NULL,
    judgment_id text NOT NULL,
    mentions integer NOT NULL,
    leden json NOT NULL,
    date_eff text,
    ecli text,
    court_code text,
    tier text,
    cited double precision
)""",
        f"CREATE INDEX IF NOT EXISTS lg_cited_by_article ON {CITED_BY_TABLE} (article_id)"
        " INCLUDE (judgment_id, edge_key, mentions, date_eff, ecli, court_code, tier, cited)",
        f"CREATE INDEX IF NOT EXISTS lg_cited_by_judgment ON {CITED_BY_TABLE} (judgment_id)",
        # per mention of the edge *doc*, in its order, the leden it names (``meta.mentions``)
        """CREATE OR REPLACE FUNCTION lg_cited_by_leden(doc json) RETURNS json
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(json_agg(m.mention -> 'leden' ORDER BY m.n), '[]'::json)
    FROM json_array_elements(
        CASE WHEN json_typeof(doc -> 'meta' -> 'mentions') = 'array'
             THEN doc -> 'meta' -> 'mentions' ELSE '[]'::json END
    ) WITH ORDINALITY AS m(mention, n)
$$""",
        f"""CREATE OR REPLACE FUNCTION lg_keep_cited_by() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.{CITED_BY_TABLE} l USING changed c WHERE l.edge_key = c.key;
    ELSE
        INSERT INTO public.{CITED_BY_TABLE} ({CITED_BY_COLUMNS})
        SELECT {cited_by_values("c", "j")}
        FROM changed c {cited_by_judgment("c")}
        WHERE {cited_by_edges("c")}
        ON CONFLICT (edge_key) DO NOTHING;
    END IF;
    RETURN NULL;
END $$""",
        *_after_each_statement(
            "edges", "cited_by", "lg_keep_cited_by", ("INSERT", "DELETE")
        ),
        # an edge written again: only one whose ends, relation or mentions changed is kept
        # again (a run of the linker writes hundreds of thousands of them unchanged, and the
        # leden of each would be read and compared)
        f"""CREATE OR REPLACE FUNCTION lg_keep_cited_by_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.{CITED_BY_TABLE} l USING changed c, previous o
    WHERE o.key = c.key AND l.edge_key = c.key
      AND {cited_by_edges("o")} AND NOT ({cited_by_edges("c")});
    INSERT INTO public.{CITED_BY_TABLE} AS l ({CITED_BY_COLUMNS})
    SELECT {cited_by_values("c", "j")}
    FROM changed c
    JOIN previous o ON o.key = c.key
    {cited_by_judgment("c")}
    WHERE {cited_by_edges("c")}
      AND (c.from_id, c.to_id, c.relation, (c.doc -> 'meta' -> 'mentions')::text)
          IS DISTINCT FROM
          (o.from_id, o.to_id, o.relation, (o.doc -> 'meta' -> 'mentions')::text)
    ON CONFLICT (edge_key) DO UPDATE SET
        article_id = EXCLUDED.article_id, judgment_id = EXCLUDED.judgment_id,
        mentions = EXCLUDED.mentions, leden = EXCLUDED.leden;
    RETURN NULL;
END $$""",
        "CREATE OR REPLACE TRIGGER edges_cited_by_update AFTER UPDATE ON edges"
        " REFERENCING OLD TABLE AS previous NEW TABLE AS changed"
        " FOR EACH STATEMENT EXECUTE FUNCTION lg_keep_cited_by_update()",
        # a judgment written after the edges from it, its date, court or citations changed,
        # or gone
        f"""CREATE OR REPLACE FUNCTION lg_keep_cited_by_judgment() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM public.{CITED_BY_TABLE} l USING changed c WHERE l.judgment_id = c.id;
    ELSIF TG_OP = 'INSERT' THEN
        INSERT INTO public.{CITED_BY_TABLE} ({CITED_BY_COLUMNS})
        SELECT {cited_by_values("e", "j")}
        FROM changed j
        JOIN public.edges e ON e.from_id = j.id AND {cited_by_edges("e")}
        ON CONFLICT (edge_key) DO NOTHING;
    ELSE
        UPDATE public.{CITED_BY_TABLE} l
        SET date_eff = c.date_eff, ecli = c.ecli, court_code = c.court_code,
            tier = c.tier, cited = c.inbound_citation_count
        FROM changed c
        WHERE l.judgment_id = c.id
          AND (l.date_eff, l.ecli, l.court_code, l.tier, l.cited) IS DISTINCT FROM
              (c.date_eff, c.ecli, c.court_code, c.tier, c.inbound_citation_count);
    END IF;
    RETURN NULL;
END $$""",
        *_after_each_statement(
            COLLECTION_JUDGMENTS, "cited_by", "lg_keep_cited_by_judgment"
        ),
    ]


# What the coalition did on each vote (``core.coalition.vote_pattern``), kept by ``semantic
# tk-coalition-votes``: its seats for and against, the opposition's, the pattern (``together``,
# ``split``, ``wissel``), whether it carried or decided the vote, and each coalition
# faction's choice (``factions``); a row per decision with a cabinet and a coalition vote. Not
# a table of the graph: writing it raises no data version.
DECISION_COALITION = """
CREATE TABLE IF NOT EXISTS lg_decision_coalition (
    id text PRIMARY KEY,
    cabinet text NOT NULL,
    coalition_for int NOT NULL,
    coalition_against int NOT NULL,
    opposition_for int NOT NULL,
    opposition_against int NOT NULL,
    pattern text NOT NULL,
    carried boolean NOT NULL,
    decisive boolean NOT NULL,
    factions json NOT NULL DEFAULT '[]'
)
"""

# The definitions each regulation gives itself (``core.bwb_definitions``), kept by ``semantic
# bwb-definitions``: a row per regulation that has any. Apart from the instrument's props, so
# its lists and their warm-up do not carry them (the Wft has hundreds). Not a table of the
# graph, but the article routes serve what it holds: writing it raises the data version.
DEFINITIONS_TABLE = "lg_instrument_definitions"
INSTRUMENT_DEFINITIONS = f"""
CREATE TABLE IF NOT EXISTS {DEFINITIONS_TABLE} (
    instrument_id text PRIMARY KEY,
    bwb_id text NOT NULL,
    definitions json NOT NULL
)
"""

# Per node a step read the references of: how many its text makes that the step recognized and
# could not link (a law or an article not in the graph), 0 when it linked every one; no row
# when the step has not read it (``core.completeness.references_part``). Kept by ``semantic
# bwb`` (an article of the BWB), ``semantic eurlex`` (an EU article), ``semantic rechtspraak``
# (a judgment) and ``semantic tk`` (a paper of the Tweede Kamer), each under its own
# ``step``. Of a judgment also ``ljns``: how many LJNs its text cites that no one judgment in
# the graph has, kept by ``semantic rechtspraak-citations`` on the row ``semantic rechtspraak``
# wrote; null when it cites none such. Apart from the props, so a run that counts every
# judgment rewrites no texts. Not a table of the graph, but the detail routes serve it:
# writing it raises the data version. ``ljns`` is added to a table built before it (nullable:
# a version without it starts on it).
UNLINKED_TABLE = "lg_unlinked_references"
UNLINKED_REFERENCES = f"""
CREATE TABLE IF NOT EXISTS {UNLINKED_TABLE} (
    id text PRIMARY KEY,
    step text NOT NULL,
    count integer NOT NULL,
    ljns integer
);
ALTER TABLE {UNLINKED_TABLE} ADD COLUMN IF NOT EXISTS ljns integer;
CREATE INDEX IF NOT EXISTS lg_unlinked_references_step ON {UNLINKED_TABLE} (step)
"""

# The terms of an article: the stems that recur in the summaries of the judgments that cite
# it more than in all summaries ("noodweer" of art. 41 Sr, whose words do not hold it), with
# the strength of each (how far it names the article, ``article_terms.strength``), and the
# number of light summaries each stem is in, which the terms are weighed against.
# ``semantic graph-article-terms`` keeps both; the search finds an article by its terms as by
# its words, and names it by its strong terms. Not tables of the graph: the step raises the
# data version of ``articles`` itself. The strengths are added to a table built before them
# (nullable: a version without them starts on it, and keeps its terms without one).
ARTICLE_TERMS = """
CREATE TABLE IF NOT EXISTS lg_article_terms (
    article_id text PRIMARY KEY,
    terms text[] NOT NULL,
    strengths real[]
);
ALTER TABLE lg_article_terms ADD COLUMN IF NOT EXISTS strengths real[];
CREATE INDEX IF NOT EXISTS lg_article_terms_terms ON lg_article_terms USING gin (terms);
CREATE TABLE IF NOT EXISTS lg_summary_stems (
    stem text PRIMARY KEY,
    judgments integer NOT NULL
)
"""

# The hits of a word searched often, ready to rank (``queries/search/candidates.py``): per
# type and word the hits the search ranks (``RANK_CANDIDATES``), in the order it takes them,
# with what their rank reads of each (the frequency of every term, the length of every
# field, the citations), so that a search of the word reads neither the hits it leaves nor
# the large columns of those it ranks. ``lg_search_candidates_state`` holds the version of
# the type's table they were read at (``lg_data_version``) and the shape of the search they
# were read for: a search takes them only while both are those of now. Not tables of the
# graph: writing them raises no data version.
SEARCH_CANDIDATES = """
CREATE TABLE IF NOT EXISTS lg_search_candidates (
    collection text NOT NULL,
    word text NOT NULL,
    pos integer NOT NULL,
    id text NOT NULL,
    key text NOT NULL,
    citations double precision,
    tf bigint[] NOT NULL,
    len bigint[] NOT NULL,
    PRIMARY KEY (collection, word, pos)
);
CREATE TABLE IF NOT EXISTS lg_search_candidates_state (
    collection text NOT NULL,
    word text NOT NULL,
    version bigint NOT NULL,
    signature text NOT NULL,
    hits integer NOT NULL,
    PRIMARY KEY (collection, word)
)
"""


# One light row per event of the feed (``queries/feed_events.py``), written by ``lawgraph
# feed-events`` from the same reading of the events as the feed: what ``GET
# /api/feed/periods`` counts per month or day, with an index on its words instead of a
# reading of every event per request. ``title`` and ``dossier_title`` are the texts the
# feed matches ``q`` against (its title and that of its first dossier), in lower case;
# ``words`` their tokens of letters and digits (``lg_alnum_tokens``), a superset of what
# matches, which the feed's own pattern then checks. Not a table of the graph: writing it
# raises no data version; ``lg_feed_events_state`` says when it was written.
FEED_EVENTS_TABLE = "lg_feed_events"
FEED_EVENTS_COLUMNS = """
    kind text NOT NULL,
    id text NOT NULL,
    date text NOT NULL,
    chamber text,
    ministry text,
    factions text[] NOT NULL,
    labels text[] NOT NULL,
    title text,
    dossier_title text,
    words tsvector NOT NULL,
    PRIMARY KEY (kind, id)
"""
# The indexes of the table, per name a definition on ``{table}`` (the table itself, or the
# one a full rewrite builds before it takes its place).
FEED_EVENTS_INDEXES = {
    "lg_feed_events_date": "CREATE INDEX IF NOT EXISTS {name} ON {table} (date, kind)",
    "lg_feed_events_words": "CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (words)",
    "lg_feed_events_factions": (
        "CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (factions)"
    ),
}


# The seats of the Eerste Kamer per term and per stretch (``normalize eerstekamer-mutations``):
# each term from the Kiesraad's result of its election through the changes the Kamer's pages
# tell (``core.ek_seat_walk``), and whether it added up (``checked``). Not tables of the graph.
EK_SEATS = """
CREATE TABLE IF NOT EXISTS lg_ek_terms (
    start text PRIMARY KEY,
    election text NOT NULL,
    source json NOT NULL,
    checked boolean NOT NULL,
    mismatches json NOT NULL
);
CREATE TABLE IF NOT EXISTS lg_ek_seats (
    from_date text PRIMARY KEY,
    to_date text,
    term text NOT NULL,
    seats json NOT NULL,
    events json NOT NULL
)
"""


def feed_events() -> list[str]:
    statements = [
        f"CREATE TABLE IF NOT EXISTS {FEED_EVENTS_TABLE} ({FEED_EVENTS_COLUMNS})",
        """CREATE TABLE IF NOT EXISTS lg_feed_events_state (
    id boolean PRIMARY KEY DEFAULT true CHECK (id),
    written_at timestamptz NOT NULL,
    since text
)""",
        # the amendments as the Kamer handles them (``queries/feed_events.CHAINS``): a row
        # per chain of documents that replace each other (REVISES; the chain is named by its
        # last document) and document of it, with the day of its first document and its outcome
        """CREATE TABLE IF NOT EXISTS lg_amendment_chains (
    chain_id text NOT NULL,
    paper_id text NOT NULL,
    first_date text,
    outcome text NOT NULL,
    PRIMARY KEY (chain_id, paper_id)
)""",
        "CREATE INDEX IF NOT EXISTS lg_amendment_chains_paper"
        " ON lg_amendment_chains (paper_id)",
        # the tokens of letters and digits of a text, as the feed's pattern (``\m``, ``\M``)
        # tells a word: by the character classes of the database
        """CREATE OR REPLACE FUNCTION lg_alnum_tokens(t text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT array_to_tsvector(coalesce(array_remove(
        regexp_split_to_array(lower(coalesce(t, '')), '[^[:alnum:]]+'), ''), '{}'))
$$""",
        # the events whose ``words`` may hold the words *q* (``queries/_words``): every
        # token of them but the last as a whole, the last from its start (whole as well
        # when *whole*, a short word); NULL when *q* has no letter or digit
        """CREATE OR REPLACE FUNCTION lg_word_query(q text, whole boolean) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN cardinality(tokens) = 0 THEN NULL ELSE (
        SELECT string_agg(
            quote_literal(token)
            || CASE WHEN n = cardinality(tokens) AND NOT whole THEN ':*' ELSE '' END,
            ' & ' ORDER BY n)
        FROM unnest(tokens) WITH ORDINALITY AS u(token, n)
    )::tsquery END
    FROM (SELECT coalesce(array_remove(
        regexp_split_to_array(lower(q), '[^[:alnum:]]+'), ''), '{}') AS tokens) t
$$""",
    ]
    statements += [
        definition.format(name=name, table=FEED_EVENTS_TABLE)
        for name, definition in FEED_EVENTS_INDEXES.items()
    ]
    return statements


# ── data version ─────────────────────────────────────────────────────────────

# A number per table that a statement which changed rows raises: ``data_version`` hashes
# them. A statement that changed nothing (an upsert of what was stored) leaves it.
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
    return [
        f"INSERT INTO lg_data_version (collection) VALUES ('{table}') ON CONFLICT DO NOTHING",
        *_after_each_statement(table, "version", "lg_bump_data_version"),
    ]


# ── nodes view ───────────────────────────────────────────────────────────────


def nodes_view() -> str:
    """Every node of every collection, for a lookup by id (``DOCUMENT(id)``)."""
    parts = "\nUNION ALL\n".join(
        f"SELECT id, key, '{c}' AS collection, type, labels, props FROM {c}"
        for c in NODE_COLLECTIONS
    )
    return f"CREATE OR REPLACE VIEW nodes AS\n{parts}"


def node_of(id_sql: str, collection_sql: str) -> str:
    """SQL: ``LATERAL (...)``, the node *id_sql* names (the columns of the view ``nodes``)
    from its own table, *collection_sql* (``e.from_collection``, or ``split_part(id, '/',
    1)``). A join of the view on its id alone looked in every table of it, an index probe
    each per row (``tests/test_nodes_view_joins.py`` keeps that from coming back): here
    each table's part is gated on its name, so only the node's own table is read."""
    parts = "\n        UNION ALL\n        ".join(
        f"SELECT x.id, x.key, '{c}'::text AS collection, x.type, x.labels, x.props"
        f" FROM {c} x WHERE {collection_sql} = '{c}' AND x.id = {id_sql}"
        for c in NODE_COLLECTIONS
    )
    return f"LATERAL (\n        {parts}\n    )"


def node_exists(id_sql: str, collection_sql: str) -> str:
    """SQL: whether the node *id_sql* is in its own table, *collection_sql*, gated on the
    table's name as in ``node_of``: one index probe, and false for a collection that is no
    table of the graph."""
    parts = "\n        UNION ALL\n        ".join(
        f"SELECT 1 FROM {c} x WHERE {collection_sql} = '{c}' AND x.id = {id_sql}"
        for c in NODE_COLLECTIONS
    )
    return f"EXISTS (\n        {parts}\n    )"


def statements() -> list[str]:
    """The whole schema, in the order it is created."""
    found = [
        DICTIONARY,
        FUNCTIONS,
        TRANSPOSITION_OUTCOME,
        SEARCH_FUNCTIONS,
        DATA_VERSION,
        TRIGRAMS,
    ]
    for collection in NODE_COLLECTIONS:
        found += node_table(collection)
        found += data_version_triggers(collection)
    found += [
        EDGES,
        RAW_SOURCES,
        PIPELINE_STATE,
        HEAT,
        *judgment_light(),
        *judgment_persons(),
        *document_light(),
        *instrument_names(),
        *faction_votes(),
        *member_authored(),
        *committee_led(),
        *article_cited_by(),
        ARTICLE_TERMS,
        SEARCH_CANDIDATES,
        DECISION_COALITION,
        INSTRUMENT_DEFINITIONS,
        UNLINKED_REFERENCES,
        *feed_events(),
        EK_SEATS,
        nodes_view(),
    ]
    found += data_version_triggers(COLLECTION_EDGES)
    found += data_version_triggers(DEFINITIONS_TABLE)
    found += data_version_triggers(UNLINKED_TABLE)
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


# A column the schema adds to a table that may be older than it (a step 0 of a deploy).
_ADDED = re.compile(
    r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)([^;]*)", re.IGNORECASE
)


def added_columns() -> dict[str, set[str]]:
    """table -> the columns the schema adds itself (``ALTER TABLE … ADD COLUMN IF NOT
    EXISTS``) to a table built before them, but a generated one: PostgreSQL adds a column
    without a default, or with a constant one, without rewriting the table, so a start adds
    it at once; a stored generated column would rewrite a large table at the start."""
    found: dict[str, set[str]] = {}
    for statement in statements():
        for table, column, rest in _ADDED.findall(_COMMENT.sub("", statement)):
            if "GENERATED" not in rest.upper():
                found.setdefault(table, set()).add(column)
    return found


def expected_generated() -> dict[str, set[str]]:
    """table -> the names of its generated columns. The derived columns of a node table are
    no generated columns: its trigger fills them (``_derive``)."""
    return _columns(generated=True)


def schema_drift(conn: psycopg.Connection) -> list[str]:
    """What differs between the tables of the database and those of the schema, so far that
    this version cannot run on it: a column the schema has and the table lacks, but one the
    schema adds itself (``added_columns``); a column the table has and the schema does not,
    but one that is nullable or has a default (a later version's, added before its deploy:
    this version writes its rows without it, and starts after that version's step 0 or on a
    rollback); and a column that is generated in one and not in the other. A table that is
    not there yet differs in nothing. A column of the table the schema does not know is
    logged."""
    expected, generated, added = (
        expected_columns(),
        expected_generated(),
        added_columns(),
    )
    actual: dict[str, set[str]] = {}
    actual_generated: dict[str, set[str]] = {}
    required: dict[str, set[str]] = {}  # NOT NULL without a default
    for table, column, is_generated, is_required in conn.execute(
        "SELECT table_name, column_name, is_generated = 'ALWAYS',"
        " is_nullable = 'NO' AND column_default IS NULL AND is_generated <> 'ALWAYS'"
        " FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        (list(expected),),
    ):
        actual.setdefault(table, set()).add(column)
        if is_generated:
            actual_generated.setdefault(table, set()).add(column)
        if is_required:
            required.setdefault(table, set()).add(column)
    differences = []
    for table, columns in sorted(expected.items()):
        present = actual.get(table)
        if present is None:
            continue  # not there yet: it is created as the schema says
        missing = columns - present - added.get(table, set())
        differences += [f"{table}.{c} is missing" for c in sorted(missing)]
        extra = present - columns
        differences += [
            f"{table}.{c} is not in the schema and is required (NOT NULL without a default)"
            for c in sorted(extra & required.get(table, set()))
        ]
        for column in sorted(extra - required.get(table, set())):
            logger.warning(
                "%s.%s is not in the schema of this version (one of a later version?): "
                "left alone, written as null.",
                table,
                column,
            )
        was, wanted = actual_generated.get(table, set()), generated.get(table, set())
        differences += [
            f"{table}.{c} is generated, the schema fills it with a trigger"
            for c in sorted((was - wanted) & columns)
        ]
        differences += [
            f"{table}.{c} is not generated" for c in sorted((wanted - was) & present)
        ]
    return differences


def ensure_schema(conn: psycopg.Connection, *, allowed_collation: str = "") -> None:
    """Create what is missing of the schema in the database of *conn*, in one transaction
    that holds a lock, so two processes that start together do not race.

    A table that exists keeps its columns: ``CREATE TABLE IF NOT EXISTS`` adds none. When
    this version cannot run on them (a column of its schema the table lacks and the schema
    does not add itself, a required column it does not know: ``schema_drift``), this stops
    with ``SchemaOutdated`` before anything is created, instead of letting queries fail
    later: the database is built again, there is no migration (clean slate). A column the
    schema adds with ``ADD COLUMN IF NOT EXISTS`` is added here; a nullable column of a
    later version is left alone, so an older version starts on a database a step 0 of the
    next one prepared, and on a rollback. A changed expression of a generated column is not seen.
    The trigger of a node table's derived columns is replaced here, but rows written before
    keep what the old one derived: the digest of the derivation their rows were derived by
    is kept per table (``derive_digest``, under ``DERIVE_STATE``), set here for a new table,
    and ``semantic graph-derive`` derives them again. A database that does not sort by ``COLLATION``
    is refused first (``check_collation``), unless it is *allowed_collation*."""
    with conn.transaction():
        check_collation(conn, allowed_collation)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('lawgraph_schema'))")
        # before anything is created: an index on a column the table lacks would fail first
        differences = schema_drift(conn)
        if differences:
            raise SchemaOutdated(
                "schema outdated, build the database again ("
                + "; ".join(differences)
                + ")"
            )
        for statement in statements():
            conn.execute(statement.encode())
        # a table created now is derived by this version; one there already keeps the
        # digest its rows were derived by
        for collection in derived_collections():
            conn.execute(
                f"INSERT INTO {COLLECTION_PIPELINE_STATE} (key, doc) VALUES (%s, %s)"
                " ON CONFLICT (key) DO NOTHING",
                (
                    DERIVE_STATE + collection,
                    Json({"digest": derive_digest(collection)}),
                ),
            )


def create_database_sql(name: str) -> str:
    """The database, with the collation that sorts its strings (``COLLATION``)."""
    return (
        f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING UTF8 LOCALE_PROVIDER icu'
        f" ICU_LOCALE '{COLLATION}' LOCALE 'C.UTF-8'"
    )
