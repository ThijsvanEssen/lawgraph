-- Where two cold reads spend their time, read only: the statements the API runs, as it runs them, under
-- EXPLAIN (ANALYZE, BUFFERS), each twice (as cold as the database is, then warm).
--
-- A. /api/instruments?q=water&article_count_min=1&sort=title&limit=100&facets=false (1.4 s cold, backlog item 6, parked):
--    the count and the page each search the 14 title, name and id columns (a BitmapOr), and of every match test the
--    kind, article_count and that no Verdragenbank treaty SAME_AS points into it; the page reads the props of 100.
-- B. the lid counts of art. 6:162 BW (the light node of /api/nodes/articles/bwbr0005289_162, 7.0 s cold): the meta
--    of every edge citing the article, its lids counted per bucket.
-- C. /api/articles/BWBR0005289/162/cited-by?limit=200&sort=date_desc (Verbonden's judgments, ~10 s cold): every
--    citation of the article with its judgment, sorted, then the mentions of the page.
-- Section 0 counts the matches of A and the edges citing 6:162 BW, to weigh the per-row work.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== A0. the instruments the search matches, and those the filters keep'
SELECT count(*) AS matched,
       count(*) FILTER (WHERE kind IS DISTINCT FROM 'publicatie' AND article_count >= 1) AS kept_by_columns
FROM instruments
WHERE instruments.s_title_t && lg_tokens('water')
   OR instruments.s_citation_title_g LIKE '%' || lg_like(lg_fold('water')) || '%'
   OR instruments.s_title_g LIKE '%' || lg_like(lg_fold('water')) || '%';

\echo '== A1. the instruments search, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)

        SELECT t.total, p.*
        FROM (SELECT count(*)::int AS total FROM instruments WHERE kind IS DISTINCT FROM 'publicatie' AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = instruments.id AND e.relation = 'SAME_AS' AND e.from_collection = 'instruments') AND article_count >= 1 AND ((instruments.s_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_citation_title_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_citation_title_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_citation_title_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_citation_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_official_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_official_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_display_name_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_display_name_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_display_name_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR (char_length('water') >= 3 AND instruments.s_short_title_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_short_title_n @> ARRAY[lg_fold('water')] OR (char_length('water') >= 3 AND instruments.s_bwb_id_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_bwb_id_n @> ARRAY[lg_fold('water')]))) t
        LEFT JOIN (
        SELECT key, props, row_number() OVER (ORDER BY citation_title NULLS FIRST, key) AS n
        FROM instruments WHERE kind IS DISTINCT FROM 'publicatie' AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = instruments.id AND e.relation = 'SAME_AS' AND e.from_collection = 'instruments') AND article_count >= 1 AND ((instruments.s_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_citation_title_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_citation_title_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_citation_title_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_citation_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_official_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_official_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_display_name_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_display_name_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_display_name_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR (char_length('water') >= 3 AND instruments.s_short_title_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_short_title_n @> ARRAY[lg_fold('water')] OR (char_length('water') >= 3 AND instruments.s_bwb_id_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_bwb_id_n @> ARRAY[lg_fold('water')]))
        ORDER BY citation_title NULLS FIRST, key
        LIMIT 100 OFFSET 0
    ) p ON true
        ORDER BY p.n
    ;

\echo '== A2. the same, warm'
EXPLAIN (ANALYZE, BUFFERS)

        SELECT t.total, p.*
        FROM (SELECT count(*)::int AS total FROM instruments WHERE kind IS DISTINCT FROM 'publicatie' AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = instruments.id AND e.relation = 'SAME_AS' AND e.from_collection = 'instruments') AND article_count >= 1 AND ((instruments.s_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_citation_title_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_citation_title_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_citation_title_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_citation_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_official_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_official_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_display_name_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_display_name_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_display_name_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR (char_length('water') >= 3 AND instruments.s_short_title_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_short_title_n @> ARRAY[lg_fold('water')] OR (char_length('water') >= 3 AND instruments.s_bwb_id_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_bwb_id_n @> ARRAY[lg_fold('water')]))) t
        LEFT JOIN (
        SELECT key, props, row_number() OVER (ORDER BY citation_title NULLS FIRST, key) AS n
        FROM instruments WHERE kind IS DISTINCT FROM 'publicatie' AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = instruments.id AND e.relation = 'SAME_AS' AND e.from_collection = 'instruments') AND article_count >= 1 AND ((instruments.s_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_citation_title_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_citation_title_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_citation_title_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_citation_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_official_title_t && lg_tokens('water') OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_official_title_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR instruments.s_display_name_t && lg_tokens('water') OR (char_length('water') >= 3 AND (instruments.s_display_name_g LIKE lg_like(lg_fold('water')) || '%' OR instruments.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('water')) || '%')) OR (char_length('water') BETWEEN 3 AND 12 AND instruments.s_display_name_g LIKE '%' || lg_like(lg_fold('water')) || '%') OR (char_length('water') >= 3 AND instruments.s_short_title_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_short_title_n @> ARRAY[lg_fold('water')] OR (char_length('water') >= 3 AND instruments.s_bwb_id_p ILIKE '%' || chr(31) || lg_like('water') || '%') OR instruments.s_bwb_id_n @> ARRAY[lg_fold('water')]))
        ORDER BY citation_title NULLS FIRST, key
        LIMIT 100 OFFSET 0
    ) p ON true
        ORDER BY p.n
    ;


\echo '== B0. the edges citing art. 6:162 BW, per relation and collection'
SELECT relation, from_collection, count(*) FROM edges WHERE to_id = 'articles/bwbr0005289_162' GROUP BY 1, 2 ORDER BY 3 DESC;

\echo '== B1. the lid counts of art. 6:162 BW, as cold as they are'
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.relation, c.direction, c.collection, lid, count(*)::int AS count
        FROM (
            SELECT c.relation, c.direction, c.collection, ARRAY(
                SELECT l FROM unnest(c.lids) AS l
                WHERE '{1,2,3}'::text[] IS NULL OR lower(l) = ANY('{1,2,3}'::text[])
            ) AS lids
            FROM (
            SELECT e.relation, 'outbound' AS direction,
                   e.to_collection AS collection, ARRAY(
    SELECT DISTINCT lid FROM (
        SELECT e.doc -> 'meta' ->> 'lid'
        UNION ALL
        SELECT unnest(lg_text_array(e.doc -> 'meta' -> 'leden'))
        UNION ALL
        SELECT unnest(lg_text_array(m.mention -> 'leden'))
        FROM json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                 THEN e.doc -> 'meta' -> 'mentions' END
        ) AS m(mention)
    ) AS l(lid)
    WHERE lid IS NOT NULL AND lid <> ''
) AS lids
            FROM edges e
            WHERE e.from_id = 'articles/bwbr0005289_162'
             UNION ALL
            SELECT e.relation, 'inbound' AS direction,
                   e.from_collection AS collection, ARRAY(
    SELECT DISTINCT lid FROM (
        SELECT e.doc -> 'meta' ->> 'lid'
        UNION ALL
        SELECT unnest(lg_text_array(e.doc -> 'meta' -> 'leden'))
        UNION ALL
        SELECT unnest(lg_text_array(m.mention -> 'leden'))
        FROM json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                 THEN e.doc -> 'meta' -> 'mentions' END
        ) AS m(mention)
    ) AS l(lid)
    WHERE lid IS NOT NULL AND lid <> ''
) AS lids
            FROM edges e
            WHERE e.to_id = 'articles/bwbr0005289_162'
            ) c
        ) c
        CROSS JOIN LATERAL unnest(
            CASE WHEN cardinality(c.lids) > 0 THEN c.lids ELSE ARRAY[''] END
        ) AS lid
        GROUP BY c.relation, c.direction, c.collection, lid
        ORDER BY c.relation NULLS FIRST, c.direction NULLS FIRST,
                 c.collection NULLS FIRST, lid NULLS FIRST;

\echo '== B2. the same, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.relation, c.direction, c.collection, lid, count(*)::int AS count
        FROM (
            SELECT c.relation, c.direction, c.collection, ARRAY(
                SELECT l FROM unnest(c.lids) AS l
                WHERE '{1,2,3}'::text[] IS NULL OR lower(l) = ANY('{1,2,3}'::text[])
            ) AS lids
            FROM (
            SELECT e.relation, 'outbound' AS direction,
                   e.to_collection AS collection, ARRAY(
    SELECT DISTINCT lid FROM (
        SELECT e.doc -> 'meta' ->> 'lid'
        UNION ALL
        SELECT unnest(lg_text_array(e.doc -> 'meta' -> 'leden'))
        UNION ALL
        SELECT unnest(lg_text_array(m.mention -> 'leden'))
        FROM json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                 THEN e.doc -> 'meta' -> 'mentions' END
        ) AS m(mention)
    ) AS l(lid)
    WHERE lid IS NOT NULL AND lid <> ''
) AS lids
            FROM edges e
            WHERE e.from_id = 'articles/bwbr0005289_162'
             UNION ALL
            SELECT e.relation, 'inbound' AS direction,
                   e.from_collection AS collection, ARRAY(
    SELECT DISTINCT lid FROM (
        SELECT e.doc -> 'meta' ->> 'lid'
        UNION ALL
        SELECT unnest(lg_text_array(e.doc -> 'meta' -> 'leden'))
        UNION ALL
        SELECT unnest(lg_text_array(m.mention -> 'leden'))
        FROM json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                 THEN e.doc -> 'meta' -> 'mentions' END
        ) AS m(mention)
    ) AS l(lid)
    WHERE lid IS NOT NULL AND lid <> ''
) AS lids
            FROM edges e
            WHERE e.to_id = 'articles/bwbr0005289_162'
            ) c
        ) c
        CROSS JOIN LATERAL unnest(
            CASE WHEN cardinality(c.lids) > 0 THEN c.lids ELSE ARRAY[''] END
        ) AS lid
        GROUP BY c.relation, c.direction, c.collection, lid
        ORDER BY c.relation NULLS FIRST, c.direction NULLS FIRST,
                 c.collection NULLS FIRST, lid NULLS FIRST;

\echo '== C1. cited-by of art. 6:162 BW, a page of 200 newest first, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH hits AS (
        SELECT e.key AS edge, m.position - 1 AS position, j.date_eff AS date, j.ecli,
               j.inbound_citation_count AS cited
        FROM edges e
        JOIN judgments j ON j.id = e.from_id
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                THEN e.doc -> 'meta' -> 'mentions' END
        ) WITH ORDINALITY AS m(mention, position)
        WHERE e.to_id = 'articles/bwbr0005289_162' AND e.relation = 'REFERS_TO'
          AND e.from_collection = 'judgments'
          AND (NULL::text IS NULL OR j.court_code = NULL::text)
          AND (NULL::text IS NULL OR j.tier = NULL::text)
          AND (
              NULL::text IS NULL
              OR NULL::text = ANY(lg_text_array(m.mention -> 'leden'))
          )
    ),
    ranked AS (
        SELECT h.*, row_number() OVER (ORDER BY h.date DESC NULLS LAST, h.ecli NULLS FIRST, h.edge, h.position) AS n
        FROM hits h
    )
    SELECT
        (SELECT count(*)::int FROM hits) AS total,
        -- one edge per judgment and article
        (SELECT count(DISTINCT edge)::int FROM hits) AS judgment_total,
        -- the ECHR judgments that cite it: HUDOC names the article (and its leden), no passage
        (
            SELECT count(DISTINCT e.from_id)::int
            FROM edges e
            JOIN judgments j ON j.id = e.from_id
            WHERE e.to_id = 'articles/bwbr0005289_162' AND e.relation = 'REFERS_TO'
              AND e.from_collection = 'judgments' AND j.court_code = 'ECHR'
        ) AS echr_judgment_total,
        (
            SELECT coalesce(json_agg(json_build_object(
                'judgment', json_build_object(
                    '_id', j.id,
                    '_key', j.key,
                    'props', json_build_object(
                        'ecli', j.pj_ecli,
                        'display_name', j.pj_display_name,
                        'court_code', j.pj_court_code,
                        'tier', j.pj_tier,
                        'court_kind', j.pj_court_kind,
                        'date_eff', j.pj_date_eff,
                        'inbound_citation_count', j.pj_inbound_citation_count
                    )
                ),
                'mention', (e.doc -> 'meta' -> 'mentions') -> r.position::int
            ) ORDER BY r.n), '[]'::json)
            FROM ranked r
            JOIN edges e ON e.key = r.edge
            JOIN judgments j ON j.id = e.from_id
            WHERE r.n > 0 AND r.n <= 0 + 200
        ) AS items;

\echo '== C2. the same, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH hits AS (
        SELECT e.key AS edge, m.position - 1 AS position, j.date_eff AS date, j.ecli,
               j.inbound_citation_count AS cited
        FROM edges e
        JOIN judgments j ON j.id = e.from_id
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                THEN e.doc -> 'meta' -> 'mentions' END
        ) WITH ORDINALITY AS m(mention, position)
        WHERE e.to_id = 'articles/bwbr0005289_162' AND e.relation = 'REFERS_TO'
          AND e.from_collection = 'judgments'
          AND (NULL::text IS NULL OR j.court_code = NULL::text)
          AND (NULL::text IS NULL OR j.tier = NULL::text)
          AND (
              NULL::text IS NULL
              OR NULL::text = ANY(lg_text_array(m.mention -> 'leden'))
          )
    ),
    ranked AS (
        SELECT h.*, row_number() OVER (ORDER BY h.date DESC NULLS LAST, h.ecli NULLS FIRST, h.edge, h.position) AS n
        FROM hits h
    )
    SELECT
        (SELECT count(*)::int FROM hits) AS total,
        -- one edge per judgment and article
        (SELECT count(DISTINCT edge)::int FROM hits) AS judgment_total,
        -- the ECHR judgments that cite it: HUDOC names the article (and its leden), no passage
        (
            SELECT count(DISTINCT e.from_id)::int
            FROM edges e
            JOIN judgments j ON j.id = e.from_id
            WHERE e.to_id = 'articles/bwbr0005289_162' AND e.relation = 'REFERS_TO'
              AND e.from_collection = 'judgments' AND j.court_code = 'ECHR'
        ) AS echr_judgment_total,
        (
            SELECT coalesce(json_agg(json_build_object(
                'judgment', json_build_object(
                    '_id', j.id,
                    '_key', j.key,
                    'props', json_build_object(
                        'ecli', j.pj_ecli,
                        'display_name', j.pj_display_name,
                        'court_code', j.pj_court_code,
                        'tier', j.pj_tier,
                        'court_kind', j.pj_court_kind,
                        'date_eff', j.pj_date_eff,
                        'inbound_citation_count', j.pj_inbound_citation_count
                    )
                ),
                'mention', (e.doc -> 'meta' -> 'mentions') -> r.position::int
            ) ORDER BY r.n), '[]'::json)
            FROM ranked r
            JOIN edges e ON e.key = r.edge
            JOIN judgments j ON j.id = e.from_id
            WHERE r.n > 0 AND r.n <= 0 + 200
        ) AS items;
