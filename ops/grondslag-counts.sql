-- Read-only counts for the BASED_ON changes of `semantic bwb-grondslagen` (ranges, text,
-- basis_kind) and the regulations `/delegated` shows one level down (`sub_delegated`).
-- Run before and after the first run of the step on the new release:
--   psql "$LAWGRAPH_DB" -f ops/grondslag-counts.sql
-- Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

-- 1. The preamble references that name a range of articles ("artikelen 26 tot en met 30"),
--    and the regulations that have one.
SELECT count(*) AS range_refs, count(DISTINCT i.key) AS regulations_with_a_range
FROM instruments i
CROSS JOIN LATERAL json_array_elements(
    CASE WHEN json_typeof(i.props -> 'basis') = 'array' THEN i.props -> 'basis' END
) r
WHERE r ->> 'article' IS NOT NULL
  AND r ->> 'text' ~* '^\s*(artikel(en)?\s+)?[^\s,]+\s*,?\s+tot\s+en\s+met\s+(artikel\s+)?[0-9]';

-- 2. BASED_ON edges and regulations; after the run: per basis_kind, and the texts that
--    still open with a list word (0 after the run).
SELECT count(*) AS based_on_edges, count(DISTINCT from_id) AS regulations,
       count(*) FILTER (WHERE doc -> 'meta' ->> 'basis_kind' = 'delegates') AS delegates,
       count(*) FILTER (WHERE doc -> 'meta' ->> 'basis_kind' = 'mentioned') AS mentioned,
       count(*) FILTER (WHERE doc -> 'meta' ->> 'basis_kind' IS NULL) AS kind_unknown,
       count(*) FILTER (WHERE doc -> 'meta' ->> 'text' ~* '^\s*artikel') AS text_list_word
FROM edges
WHERE relation = 'BASED_ON';

-- 3. Regulations issued under a regulation that is issued under a law, and not under that
--    law itself: what `/delegated` of the law newly lists under `sub_delegated`.
WITH based AS (
    SELECT e.from_id AS reg, a.bwb_id AS law
    FROM edges e JOIN articles a ON a.id = e.to_id
    WHERE e.relation = 'BASED_ON' AND e.to_collection = 'articles'
),
regs AS (
    SELECT id, bwb_id FROM instruments
    WHERE id IN (SELECT reg FROM based)
)
SELECT count(DISTINCT s.reg) AS sub_delegated_regulations,
       count(DISTINCT top.law) AS laws_that_gain_them
FROM based s
JOIN regs mid ON mid.bwb_id = s.law
JOIN based top ON top.reg = mid.id
WHERE top.law <> s.law
  AND NOT EXISTS (SELECT 1 FROM based d WHERE d.reg = s.reg AND d.law = top.law);
