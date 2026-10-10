-- Where a search for a common word spends its time: "belasting" took 8.75 s on prod during the 0.79.42 warm-up,
-- partial on articles, documents and judgments (~/Development/search-timing-0.79.42-warmup.txt). The statements are
-- those /api/search?q=belasting sends per type (captured from the code of develop, parameters filled in): the articles
-- by their case-law terms, the frequency of the word per field (a request counts it unless the word is among the most
-- common elements the planner keeps of the field, then it takes their frequency) and the ranking. Each with EXPLAIN
-- (ANALYZE, BUFFERS) and its time. Not here: the table statistics BM25 weighs by, a sample of 2% kept six hours and
-- never waited for in a request. Read only; each statement runs once.
SET default_transaction_read_only = on;
SET statement_timeout = '60s';
\pset pager off
\timing on

\echo '== articles: articles by their case-law terms (lg_article_terms)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT w.n::int AS n,
       coalesce(array_agg(t.article_id ORDER BY t.article_id)
                FILTER (WHERE t.article_id IS NOT NULL), '{}') AS ids
FROM unnest('{belasting}'::text[]) WITH ORDINALITY AS w(forms, n)
LEFT JOIN LATERAL (
    -- found through the index of the terms first (OFFSET 0), not by walking the keys in
    -- order until the cap
    SELECT a.article_id FROM (
        SELECT a.article_id FROM lg_article_terms a
        WHERE a.terms && lg_tokens(w.forms)
        OFFSET 0
    ) a
    ORDER BY a.article_id NULLS LAST
    LIMIT 1000
) t ON true
GROUP BY w.n
ORDER BY w.n;

\echo '== articles: frequency of the word per field'
EXPLAIN (ANALYZE, BUFFERS)
SELECT 1 AS one, (SELECT count(*) FROM articles WHERE s_display_name_t && ARRAY['belast']::text[]) AS d0, (SELECT count(*) FROM articles WHERE char_length('belasting') >= 3 AND (s_display_name_g LIKE lg_like(lg_fold('belasting')) || '%' OR s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) AS d1, (SELECT count(*) FROM articles WHERE char_length('belasting') BETWEEN 3 AND 12 AND s_display_name_g LIKE '%' || replace(replace(replace(lg_fold('belasting'), '\', '\\'), '%', '\%'), '_', '\_') || '%') AS d2, (SELECT count(*) FROM articles WHERE s_heading_t && ARRAY['belast']::text[]) AS d3, (SELECT count(*) FROM articles WHERE char_length('belasting') >= 3 AND (s_heading_g LIKE lg_like(lg_fold('belasting')) || '%' OR s_heading_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) AS d4, (SELECT count(*) FROM articles WHERE s_heading_n && ARRAY[lg_fold('belasting')]) AS d5, (SELECT count(*) FROM articles WHERE char_length('belasting') BETWEEN 3 AND 12 AND s_heading_g LIKE '%' || replace(replace(replace(lg_fold('belasting'), '\', '\\'), '%', '\%'), '_', '\_') || '%') AS d6, (SELECT count(*) FROM articles WHERE s_breadcrumb_title_t && ARRAY['belast']::text[]) AS d7, (SELECT count(*) FROM articles WHERE s_text_t && ARRAY['belast']::text[]) AS d8, (SELECT count(*) FROM articles WHERE s_article_number_t && ARRAY['belast']::text[]) AS d9, (SELECT count(*) FROM articles WHERE char_length('belasting') >= 3 AND s_article_number_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') AS d10, (SELECT count(*) FROM articles WHERE s_article_number_n && ARRAY[lg_fold('belasting')]) AS d11, (SELECT count(*) FROM articles WHERE s_bwb_id_t && ARRAY['belast']::text[]) AS d12, (SELECT count(*) FROM articles WHERE char_length('belasting') >= 3 AND s_bwb_id_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') AS d13, (SELECT count(*) FROM articles WHERE s_bwb_id_n && ARRAY[lg_fold('belasting')]) AS d14;

\echo '== articles: the ranking'
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'articles', 'type', doc.type,
        'display_name', doc.props -> 'display_name',
        'snippet', left(coalesce(doc.props ->> 'text', ''), 200),
        'extra', json_build_object(
            'bwb_id', doc.props -> 'bwb_id',
            'celex', doc.props -> 'celex',
            'article_number', doc.props -> 'article_number',
            'heading', doc.props -> 'heading',
            'division_titles', (
                SELECT coalesce(json_agg(b -> 'title' ORDER BY n), '[]'::json)
                FROM json_array_elements(
                    CASE WHEN json_typeof(doc.props -> 'breadcrumb') = 'array'
                         THEN doc.props -> 'breadcrumb' ELSE '[]'::json END
                ) WITH ORDINALITY AS c(b, n)
                WHERE coalesce(json_typeof(b -> 'title'), 'null') <> 'null'
            ),
            'instrument_title', (CASE WHEN coalesce(json_typeof(coalesce(by_bwb.props, by_celex.props) -> 'citation_title'), 'null') <> 'null' THEN coalesce(by_bwb.props, by_celex.props) -> 'citation_title' WHEN coalesce(json_typeof(coalesce(by_bwb.props, by_celex.props) -> 'title'), 'null') <> 'null' THEN coalesce(by_bwb.props, by_celex.props) -> 'title' END),
            'citation_title', coalesce(by_bwb.props, by_celex.props) -> 'citation_title',
            'short_title', coalesce(by_bwb.props, by_celex.props) -> 'short_title'
        )
    )

        FROM (
            SELECT doc.id, 0 AS rank
            FROM (SELECT * FROM articles doc WHERE ((cardinality(lg_tokens('belasting')) > 0 AND doc.s_display_name_t @> lg_tokens('belasting')) OR (char_length('belasting') >= 3 AND (doc.s_display_name_g LIKE lg_like(lg_fold('belasting')) || '%' OR doc.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) OR (char_length('belasting') BETWEEN 3 AND 12 AND doc.s_display_name_g LIKE '%' || lg_like(lg_fold('belasting')) || '%') OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_heading_t @> lg_tokens('belasting')) OR (char_length('belasting') >= 3 AND (doc.s_heading_g LIKE lg_like(lg_fold('belasting')) || '%' OR doc.s_heading_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) OR doc.s_heading_n @> ARRAY[lg_fold('belasting')] OR (char_length('belasting') BETWEEN 3 AND 12 AND doc.s_heading_g LIKE '%' || lg_like(lg_fold('belasting')) || '%') OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_breadcrumb_title_t @> lg_tokens('belasting')) OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_text_t @> lg_tokens('belasting')) OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_article_number_t @> lg_tokens('belasting')) OR (char_length('belasting') >= 3 AND doc.s_article_number_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') OR doc.s_article_number_n @> ARRAY[lg_fold('belasting')] OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_bwb_id_t @> lg_tokens('belasting')) OR (char_length('belasting') >= 3 AND doc.s_bwb_id_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') OR doc.s_bwb_id_n @> ARRAY[lg_fold('belasting')])  OFFSET 0) doc
            ORDER BY rank DESC, doc.key
            LIMIT 20
        ) top
        JOIN articles doc ON doc.id = top.id
    LEFT JOIN LATERAL (
        SELECT i.props FROM instruments i
        WHERE doc.bwb_id IS NOT NULL AND i.bwb_id = doc.bwb_id
        ORDER BY i.key LIMIT 1
    ) by_bwb ON true
    LEFT JOIN LATERAL (
        SELECT i.props FROM instruments i
        WHERE doc.celex IS NOT NULL AND i.celex = doc.celex
        ORDER BY i.key LIMIT 1
    ) by_celex ON true

        ORDER BY top.rank DESC, doc.key;

\echo '== documents: frequency of the word per field'
EXPLAIN (ANALYZE, BUFFERS)
SELECT 1 AS one, (SELECT count(*) FROM documents WHERE s_display_name_t && ARRAY['belast']::text[]) AS d0, (SELECT count(*) FROM documents WHERE char_length('belasting') BETWEEN 3 AND 12 AND s_display_name_g LIKE '%' || replace(replace(replace(lg_fold('belasting'), '\', '\\'), '%', '\%'), '_', '\_') || '%') AS d1, (SELECT count(*) FROM documents WHERE s_title_t && ARRAY['belast']::text[]) AS d2, (SELECT count(*) FROM documents WHERE char_length('belasting') BETWEEN 3 AND 12 AND s_title_g LIKE '%' || replace(replace(replace(lg_fold('belasting'), '\', '\\'), '%', '\%'), '_', '\_') || '%') AS d3, (SELECT count(*) FROM documents WHERE char_length('belasting') >= 3 AND s_external_id_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') AS d4, (SELECT count(*) FROM documents WHERE s_external_id_n && ARRAY[lg_fold('belasting')]) AS d5;

\echo '== documents: the ranking'
EXPLAIN (ANALYZE, BUFFERS)
SELECT
        json_build_object(
            'id', doc.id, 'key', doc.key,
            'collection', 'documents', 'type', doc.type,
            'display_name', (CASE WHEN coalesce(json_typeof(doc.props -> 'title'), 'null') <> 'null' THEN doc.props -> 'title' WHEN coalesce(json_typeof(doc.props -> 'display_name'), 'null') <> 'null' THEN doc.props -> 'display_name' END),
            'snippet', doc.props -> 'kind',
            'extra', json_build_object(
                'kind', doc.props -> 'kind',
                'external_id', doc.props -> 'external_id',
                'dossier_number', CASE WHEN json_typeof(doc.props -> 'dossier_numbers') = 'array'
                                       THEN doc.props -> 'dossier_numbers' -> 0 END,
                'sequence', doc.props -> 'sequence',
                'number', CASE CASE WHEN 'EK' = ANY(doc.labels) THEN 'EK' WHEN 'TK' = ANY(doc.labels) THEN 'TK' END
                              WHEN 'EK' THEN doc.props ->> 'number'
                              WHEN 'TK' THEN doc.props ->> 'sequence'
                          END,
                'date', doc.props -> 'date',
                'chamber', CASE WHEN 'EK' = ANY(doc.labels) THEN 'EK' WHEN 'TK' = ANY(doc.labels) THEN 'TK' END
            ),
            -- what its readable address is built from: its own dossier, not a label
            'path_props', json_build_object(
                'dossier_number', doc.dossier_number,
                'dossier_suffix', doc.props -> 'dossier_suffix',
                'sequence', doc.props -> 'sequence',
                'number', doc.props -> 'number'
            )
        )

        FROM (
            SELECT doc.id, 0 AS rank
            FROM (SELECT * FROM documents doc WHERE ((cardinality(lg_tokens('belasting')) > 0 AND doc.s_display_name_t @> lg_tokens('belasting')) OR (char_length('belasting') BETWEEN 3 AND 12 AND doc.s_display_name_g LIKE '%' || lg_like(lg_fold('belasting')) || '%') OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_title_t @> lg_tokens('belasting')) OR (char_length('belasting') BETWEEN 3 AND 12 AND doc.s_title_g LIKE '%' || lg_like(lg_fold('belasting')) || '%') OR (char_length('belasting') >= 3 AND doc.s_external_id_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') OR doc.s_external_id_n @> ARRAY[lg_fold('belasting')])  OFFSET 0) doc
            ORDER BY rank DESC, doc.key
            LIMIT 20
        ) top
        JOIN documents doc ON doc.id = top.id
        ORDER BY top.rank DESC, doc.key;

\echo '== judgments: frequency of the word per field'
EXPLAIN (ANALYZE, BUFFERS)
SELECT 1 AS one, (SELECT count(*) FROM judgments WHERE s_display_name_t && ARRAY['belast']::text[]) AS d0, (SELECT count(*) FROM judgments WHERE char_length('belasting') >= 3 AND (s_display_name_g LIKE lg_like(lg_fold('belasting')) || '%' OR s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) AS d1, (SELECT count(*) FROM judgments WHERE char_length('belasting') BETWEEN 3 AND 12 AND s_display_name_g LIKE '%' || replace(replace(replace(lg_fold('belasting'), '\', '\\'), '%', '\%'), '_', '\_') || '%') AS d2, (SELECT count(*) FROM judgments WHERE s_names_t && ARRAY['belast']::text[]) AS d3, (SELECT count(*) FROM judgments WHERE char_length('belasting') >= 3 AND (s_names_g LIKE lg_like(lg_fold('belasting')) || '%' OR s_names_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) AS d4, (SELECT count(*) FROM judgments WHERE s_names_n && ARRAY[lg_fold('belasting')]) AS d5, (SELECT count(*) FROM judgments WHERE char_length('belasting') BETWEEN 3 AND 12 AND s_names_g LIKE '%' || replace(replace(replace(lg_fold('belasting'), '\', '\\'), '%', '\%'), '_', '\_') || '%') AS d6, (SELECT count(*) FROM judgments WHERE s_summary_t && ARRAY['belast']::text[]) AS d7, (SELECT count(*) FROM judgments WHERE char_length('belasting') >= 3 AND s_ecli_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') AS d8, (SELECT count(*) FROM judgments WHERE s_ecli_n && ARRAY[lg_fold('belasting')]) AS d9, (SELECT count(*) FROM judgments WHERE char_length('belasting') >= 3 AND s_appno_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') AS d10, (SELECT count(*) FROM judgments WHERE s_appno_n && ARRAY[lg_fold('belasting')]) AS d11;

\echo '== judgments: the ranking'
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    json_build_object(
        'id', doc.id, 'key', doc.key,
        'collection', 'judgments', 'type', doc.type,
        'display_name', doc.props -> 'display_name',
        'snippet', left(coalesce(doc.props ->> 'summary', ''), 200),
        'extra', json_build_object(
            'ecli', doc.props -> 'ecli',
            'appno', doc.props -> 'appno',
            'names', doc.props -> 'names'
        )
    )

        FROM (
            SELECT doc.id, (CASE WHEN f.t7 > 0 THEN 0.6329005593939179 * f.t7 / (f.t7 + 0.3 + 0.8999999999999999 * f.l0) ELSE 0 END) AS rank
            FROM (SELECT * FROM judgments doc WHERE ((cardinality(lg_tokens('belasting')) > 0 AND doc.s_display_name_t @> lg_tokens('belasting')) OR (char_length('belasting') >= 3 AND (doc.s_display_name_g LIKE lg_like(lg_fold('belasting')) || '%' OR doc.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) OR (char_length('belasting') BETWEEN 3 AND 12 AND doc.s_display_name_g LIKE '%' || lg_like(lg_fold('belasting')) || '%') OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_names_t @> lg_tokens('belasting')) OR (char_length('belasting') >= 3 AND (doc.s_names_g LIKE lg_like(lg_fold('belasting')) || '%' OR doc.s_names_g LIKE '%' || chr(31) || lg_like(lg_fold('belasting')) || '%')) OR doc.s_names_n @> ARRAY[lg_fold('belasting')] OR (char_length('belasting') BETWEEN 3 AND 12 AND doc.s_names_g LIKE '%' || lg_like(lg_fold('belasting')) || '%') OR (cardinality(lg_tokens('belasting')) > 0 AND doc.s_summary_t @> lg_tokens('belasting')) OR (char_length('belasting') >= 3 AND doc.s_ecli_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') OR doc.s_ecli_n @> ARRAY[lg_fold('belasting')] OR (char_length('belasting') >= 3 AND doc.s_appno_p ILIKE '%' || chr(31) || lg_like('belasting') || '%') OR doc.s_appno_n @> ARRAY[lg_fold('belasting')])  OFFSET 0) doc CROSS JOIN LATERAL (SELECT coalesce(cardinality(doc.s_summary_t), 0) AS l0, cardinality(array_positions(doc.s_summary_t, 'belast'::text)) AS t7 OFFSET 0) f
            ORDER BY rank DESC, doc.key
            LIMIT 20
        ) top
        JOIN judgments doc ON doc.id = top.id
        ORDER BY top.rank DESC, doc.key;
