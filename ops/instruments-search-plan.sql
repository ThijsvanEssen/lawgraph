-- Where /api/instruments?q=water&article_count_min=1&sort=title&limit=100&facets=false spends its 1.4 s cold
-- (backlog item 6). Read only: the statement the route runs, as it runs it, under EXPLAIN (ANALYZE, BUFFERS), twice:
-- the first is as cold as the database is, the second warm. Its parts: the count and the page each search the
-- 14 title, name and id columns (a BitmapOr), and of every match test the kind, article_count and that no
-- Verdragenbank treaty SAME_AS points into it (an index probe of edges per match); the page reads the props of 100.
-- Section 0 counts the matches, to weigh the per-match work.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== 0. the instruments the search matches, and those the filters keep'
SELECT count(*) AS matched,
       count(*) FILTER (WHERE kind IS DISTINCT FROM 'publicatie' AND article_count >= 1) AS kept_by_columns
FROM instruments
WHERE instruments.s_title_t && lg_tokens('water')
   OR instruments.s_citation_title_g LIKE '%' || lg_like(lg_fold('water')) || '%'
   OR instruments.s_title_g LIKE '%' || lg_like(lg_fold('water')) || '%';

\echo '== 1. the statement of the route, as cold as it is'
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

\echo '== 2. the same, warm'
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
