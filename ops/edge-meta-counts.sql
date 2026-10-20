-- The keys of edges.doc -> 'meta' on prod, per relation, source, key and JSON type, to hold against the
-- models of meta in core/relations.py (RelationSpec.meta; the edge-meta table of docs/data-model.md). Read
-- only: gh workflow run ops -f action=sql -f name=edge-meta-counts. The output is tab-separated per
-- statement; the samples read 1% of the pages (multiply by ~100). A statement that times out stops the run.
SET default_transaction_read_only = on;
SET statement_timeout = '5min';
\pset format unaligned
\pset fieldsep '\t'

-- 0. Size: the estimate of edges, and the share the samples below read.
SELECT reltuples::bigint AS edges_estimate,
       pg_size_pretty(pg_total_relation_size('edges')) AS size
FROM pg_class WHERE relname = 'edges';

-- 1. Every relation and source, with how many edges carry a meta object at all
--    (1% of the pages; multiply by ~100).
SELECT relation, source, count(*) AS sampled,
       count(*) FILTER (WHERE json_typeof(doc -> 'meta') = 'object'
                          AND doc ->> 'meta' <> '{}') AS with_meta
FROM edges TABLESAMPLE SYSTEM (1) REPEATABLE (48)
GROUP BY 1, 2 ORDER BY 1, 2;

-- 2. Key x JSON type per relation and source (1% of the pages; multiply by ~100).
SELECT relation, source, k AS key, json_typeof(doc -> 'meta' -> k) AS type, count(*) AS sampled
FROM edges TABLESAMPLE SYSTEM (1) REPEATABLE (48),
     json_object_keys(CASE WHEN json_typeof(doc -> 'meta') = 'object'
                           THEN doc -> 'meta' ELSE '{}'::json END) AS k
GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

-- 3. The same, in full, for the relations that are small enough to read whole (the
--    sample can miss a source of a few hundred edges). By the index on relation.
SELECT relation, source, k AS key, json_typeof(doc -> 'meta' -> k) AS type, count(*) AS edges
FROM edges,
     json_object_keys(CASE WHEN json_typeof(doc -> 'meta') = 'object'
                           THEN doc -> 'meta' ELSE '{}'::json END) AS k
WHERE relation = ANY (ARRAY[
    'ESTABLISHES', 'TRANSPOSED_TO', 'BASED_ON', 'IMPLEMENTS', 'LEGISLATED_IN',
    'PUBLISHED_IN', 'APPEAL_OF', 'CONTINUES', 'REFERRED_BY', 'ADVISES_ON', 'ANSWERS',
    'SAME_AS', 'SCOPED_BY', 'LED_BY', 'MADE_IN', 'SERVED_IN', 'RELATED_TO', 'REVISES',
    'ACCOMPANIES', 'SECOND_READING_OF', 'MEMBER_OF'])
GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

-- 4. Keys inside the arrays of objects (mentions, sections, periods, posts, measures,
--    parts, pairs): relation, array key, inner key, type (1% of the pages).
SELECT relation, k AS key, ik AS inner_key, json_typeof(el -> ik) AS type, count(*) AS sampled
FROM edges TABLESAMPLE SYSTEM (1) REPEATABLE (48),
     json_object_keys(CASE WHEN json_typeof(doc -> 'meta') = 'object'
                           THEN doc -> 'meta' ELSE '{}'::json END) AS k,
     json_array_elements(CASE WHEN json_typeof(doc -> 'meta' -> k) = 'array'
                              THEN doc -> 'meta' -> k ELSE '[]'::json END) AS el,
     json_object_keys(CASE WHEN json_typeof(el) = 'object' THEN el ELSE '{}'::json END) AS ik
GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;

-- 5. The values of the keys that hold a word of a closed list (basis, reason, rule,
--    match_type, ...), per relation (1% of the pages; the 15 most frequent per key).
SELECT relation, key, value, sampled FROM (
    SELECT relation, k AS key, doc -> 'meta' ->> k AS value, count(*) AS sampled,
           row_number() OVER (PARTITION BY relation, k ORDER BY count(*) DESC) AS n
    FROM edges TABLESAMPLE SYSTEM (1) REPEATABLE (48),
         unnest(ARRAY['basis', 'reason', 'rule', 'match_type', 'effect', 'choice',
                      'capacity', 'role', 'scope_type', 'reference_kind', 'procedure_type',
                      'basis_kind', 'nota', 'chamber', 'semantic_pattern']) AS k
    WHERE json_typeof(doc -> 'meta' -> k) = 'string'
    GROUP BY 1, 2, 3
) v WHERE n <= 15 ORDER BY 1, 2, 4 DESC;

-- 6. Keys some reader looks for that no writer of develop writes at the top of meta
--    (`lid`, `edge_id`, `paragraph_id`, `paragraph_number`), and keys of earlier writers.
--    REFERS_TO in full by the index on relation; may take minutes, may time out alone.
SELECT relation, source, k AS key, count(*) AS edges
FROM edges, json_object_keys(CASE WHEN json_typeof(doc -> 'meta') = 'object'
                                  THEN doc -> 'meta' ELSE '{}'::json END) AS k
WHERE relation = 'REFERS_TO'
  AND k IN ('lid', 'edge_id', 'paragraph_id', 'paragraph_number', 'passages')
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

-- 7. The spellings of MEMBER_OF meta.role, per source and end (in full: MEMBER_OF is a
--    few tens of thousands of edges).
SELECT source, to_collection, doc -> 'meta' ->> 'role' AS role, count(*) AS edges
FROM edges WHERE relation = 'MEMBER_OF'
GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC;

-- 8. Top-level attributes of the edge document besides the known ones (relation, source,
--    status, confidence, created_at, meta, semantic_type, explanation, updated_at).
SELECT k AS attribute, count(*) AS sampled
FROM edges TABLESAMPLE SYSTEM (1) REPEATABLE (48), json_object_keys(doc) AS k
GROUP BY 1 ORDER BY 1;
