-- Where the search while typing spends its time (B32), read only: the live searches of /api/search under
-- EXPLAIN (ANALYZE, BUFFERS), as the API plans them (store.query(indexes_only=True): no sequential scan).
-- 1-2: the articles as release 0.80.21 searches them (a walk over articles_pkey with a filter, expected) and
-- as this release does (each set of candidates found on its own: bitmap scans of the word indexes);
-- 3-4: documents and laws; 5: the words whose hits are kept that still hold; 6: whether the search indexes
-- are read from disk; 7: the ministries in the graph.
SET default_transaction_read_only = on;
SET statement_timeout = '30s';
SET enable_seqscan = off;
\pset pager off

-- 1a. Live articles 'burgerlijk wetboek', release 0.80.21
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id
        FROM (
            SELECT r.id, row_number() OVER (ORDER BY (r.s_display_name_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_heading_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_heading_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%') DESC, ((cardinality(lg_tokens('burgerlijk')) > 0 AND (r.s_heading_t @> lg_tokens('burgerlijk') OR r.s_breadcrumb_title_t @> lg_tokens('burgerlijk'))) AND (cardinality(lg_tokens('wetboek')) > 0 AND (r.s_heading_t @> lg_tokens('wetboek') OR r.s_breadcrumb_title_t @> lg_tokens('wetboek')))) DESC, r.inbound_citation_count DESC NULLS LAST, r.key) AS n
            FROM (SELECT r.* FROM ((SELECT r.id FROM articles r WHERE (((cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_display_name_t @> lg_tokens('burgerlijk')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_heading_t @> lg_tokens('burgerlijk')) OR r.s_heading_n @> ARRAY[lg_fold('burgerlijk')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_text_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_article_number_t @> lg_tokens('burgerlijk')) OR r.s_article_number_n @> ARRAY[lg_fold('burgerlijk')] OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_bwb_id_t @> lg_tokens('burgerlijk')) OR r.s_bwb_id_n @> ARRAY[lg_fold('burgerlijk')]) AND ((cardinality(lg_tokens('wetboek')) > 0 AND r.s_display_name_t @> lg_tokens('wetboek')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_heading_t @> lg_tokens('wetboek')) OR r.s_heading_n @> ARRAY[lg_fold('wetboek')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_text_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_article_number_t @> lg_tokens('wetboek')) OR r.s_article_number_n @> ARRAY[lg_fold('wetboek')] OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_bwb_id_t @> lg_tokens('wetboek')) OR r.s_bwb_id_n @> ARRAY[lg_fold('wetboek')])) AND r.stub IS NOT TRUE  LIMIT 2000) UNION (SELECT r.id FROM articles r WHERE (cardinality(lg_tokens('burgerlijk')) > 0 AND (r.s_heading_t @> lg_tokens('burgerlijk') OR r.s_breadcrumb_title_t @> lg_tokens('burgerlijk'))) AND (cardinality(lg_tokens('wetboek')) > 0 AND (r.s_heading_t @> lg_tokens('wetboek') OR r.s_breadcrumb_title_t @> lg_tokens('wetboek'))) AND (((cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_display_name_t @> lg_tokens('burgerlijk')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_heading_t @> lg_tokens('burgerlijk')) OR r.s_heading_n @> ARRAY[lg_fold('burgerlijk')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_text_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_article_number_t @> lg_tokens('burgerlijk')) OR r.s_article_number_n @> ARRAY[lg_fold('burgerlijk')] OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_bwb_id_t @> lg_tokens('burgerlijk')) OR r.s_bwb_id_n @> ARRAY[lg_fold('burgerlijk')]) AND ((cardinality(lg_tokens('wetboek')) > 0 AND r.s_display_name_t @> lg_tokens('wetboek')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_heading_t @> lg_tokens('wetboek')) OR r.s_heading_n @> ARRAY[lg_fold('wetboek')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_text_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_article_number_t @> lg_tokens('wetboek')) OR r.s_article_number_n @> ARRAY[lg_fold('wetboek')] OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_bwb_id_t @> lg_tokens('wetboek')) OR r.s_bwb_id_n @> ARRAY[lg_fold('wetboek')])) AND r.stub IS NOT TRUE  LIMIT 2000)) found JOIN articles r ON r.id = found.id) r
            ORDER BY n
            LIMIT 6
        ) top
        JOIN articles r ON r.id = top.id
        ORDER BY top.n;

-- 1b. Live articles 'burgerlijk wetboek', this release
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id
        FROM (
            SELECT r.id, row_number() OVER (ORDER BY (r.s_display_name_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_heading_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_heading_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%') DESC, ((cardinality(lg_tokens('burgerlijk')) > 0 AND (r.s_heading_t @> lg_tokens('burgerlijk') OR r.s_breadcrumb_title_t @> lg_tokens('burgerlijk'))) AND (cardinality(lg_tokens('wetboek')) > 0 AND (r.s_heading_t @> lg_tokens('wetboek') OR r.s_breadcrumb_title_t @> lg_tokens('wetboek')))) DESC, r.inbound_citation_count DESC NULLS LAST, r.key) AS n
            FROM (SELECT r.* FROM ((SELECT f.id FROM (SELECT r.id FROM articles r WHERE (((cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_display_name_t @> lg_tokens('burgerlijk')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_heading_t @> lg_tokens('burgerlijk')) OR r.s_heading_n @> ARRAY[lg_fold('burgerlijk')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_text_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_article_number_t @> lg_tokens('burgerlijk')) OR r.s_article_number_n @> ARRAY[lg_fold('burgerlijk')] OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_bwb_id_t @> lg_tokens('burgerlijk')) OR r.s_bwb_id_n @> ARRAY[lg_fold('burgerlijk')]) AND ((cardinality(lg_tokens('wetboek')) > 0 AND r.s_display_name_t @> lg_tokens('wetboek')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_heading_t @> lg_tokens('wetboek')) OR r.s_heading_n @> ARRAY[lg_fold('wetboek')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_text_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_article_number_t @> lg_tokens('wetboek')) OR r.s_article_number_n @> ARRAY[lg_fold('wetboek')] OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_bwb_id_t @> lg_tokens('wetboek')) OR r.s_bwb_id_n @> ARRAY[lg_fold('wetboek')])) AND r.stub IS NOT TRUE OFFSET 0) f LIMIT 2000) UNION (SELECT f.id FROM (SELECT r.id FROM articles r WHERE (cardinality(lg_tokens('burgerlijk')) > 0 AND (r.s_heading_t @> lg_tokens('burgerlijk') OR r.s_breadcrumb_title_t @> lg_tokens('burgerlijk'))) AND (cardinality(lg_tokens('wetboek')) > 0 AND (r.s_heading_t @> lg_tokens('wetboek') OR r.s_breadcrumb_title_t @> lg_tokens('wetboek'))) AND (((cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_display_name_t @> lg_tokens('burgerlijk')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_heading_t @> lg_tokens('burgerlijk')) OR r.s_heading_n @> ARRAY[lg_fold('burgerlijk')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_text_t @> lg_tokens('burgerlijk')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_article_number_t @> lg_tokens('burgerlijk')) OR r.s_article_number_n @> ARRAY[lg_fold('burgerlijk')] OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_bwb_id_t @> lg_tokens('burgerlijk')) OR r.s_bwb_id_n @> ARRAY[lg_fold('burgerlijk')]) AND ((cardinality(lg_tokens('wetboek')) > 0 AND r.s_display_name_t @> lg_tokens('wetboek')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_heading_t @> lg_tokens('wetboek')) OR r.s_heading_n @> ARRAY[lg_fold('wetboek')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_text_t @> lg_tokens('wetboek')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_article_number_t @> lg_tokens('wetboek')) OR r.s_article_number_n @> ARRAY[lg_fold('wetboek')] OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_bwb_id_t @> lg_tokens('wetboek')) OR r.s_bwb_id_n @> ARRAY[lg_fold('wetboek')])) AND r.stub IS NOT TRUE OFFSET 0) f LIMIT 2000)) found JOIN articles r ON r.id = found.id) r
            ORDER BY n
            LIMIT 6
        ) top
        JOIN articles r ON r.id = top.id
        ORDER BY top.n;

-- 2a. Live articles 'huurrecht', release 0.80.21
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id
        FROM (
            SELECT r.id, row_number() OVER (ORDER BY (r.s_display_name_g LIKE lg_like(lg_fold('huurrecht')) || '%' OR r.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('huurrecht')) || '%' OR r.s_heading_g LIKE lg_like(lg_fold('huurrecht')) || '%' OR r.s_heading_g LIKE '%' || chr(31) || lg_like(lg_fold('huurrecht')) || '%') DESC, ((cardinality(lg_tokens('huurrecht')) > 0 AND (r.s_heading_t @> lg_tokens('huurrecht') OR r.s_breadcrumb_title_t @> lg_tokens('huurrecht')))) DESC, r.inbound_citation_count DESC NULLS LAST, r.key) AS n
            FROM (SELECT r.* FROM ((SELECT r.id FROM articles r WHERE (((cardinality(lg_tokens('huurrecht')) > 0 AND r.s_display_name_t @> lg_tokens('huurrecht')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_heading_t @> lg_tokens('huurrecht')) OR r.s_heading_n @> ARRAY[lg_fold('huurrecht')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_text_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_article_number_t @> lg_tokens('huurrecht')) OR r.s_article_number_n @> ARRAY[lg_fold('huurrecht')] OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_bwb_id_t @> lg_tokens('huurrecht')) OR r.s_bwb_id_n @> ARRAY[lg_fold('huurrecht')])) AND r.stub IS NOT TRUE  LIMIT 2000) UNION (SELECT r.id FROM articles r WHERE (cardinality(lg_tokens('huurrecht')) > 0 AND (r.s_heading_t @> lg_tokens('huurrecht') OR r.s_breadcrumb_title_t @> lg_tokens('huurrecht'))) AND (((cardinality(lg_tokens('huurrecht')) > 0 AND r.s_display_name_t @> lg_tokens('huurrecht')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_heading_t @> lg_tokens('huurrecht')) OR r.s_heading_n @> ARRAY[lg_fold('huurrecht')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_text_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_article_number_t @> lg_tokens('huurrecht')) OR r.s_article_number_n @> ARRAY[lg_fold('huurrecht')] OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_bwb_id_t @> lg_tokens('huurrecht')) OR r.s_bwb_id_n @> ARRAY[lg_fold('huurrecht')])) AND r.stub IS NOT TRUE  LIMIT 2000)) found JOIN articles r ON r.id = found.id) r
            ORDER BY n
            LIMIT 6
        ) top
        JOIN articles r ON r.id = top.id
        ORDER BY top.n;

-- 2b. Live articles 'huurrecht', this release
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id
        FROM (
            SELECT r.id, row_number() OVER (ORDER BY (r.s_display_name_g LIKE lg_like(lg_fold('huurrecht')) || '%' OR r.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('huurrecht')) || '%' OR r.s_heading_g LIKE lg_like(lg_fold('huurrecht')) || '%' OR r.s_heading_g LIKE '%' || chr(31) || lg_like(lg_fold('huurrecht')) || '%') DESC, ((cardinality(lg_tokens('huurrecht')) > 0 AND (r.s_heading_t @> lg_tokens('huurrecht') OR r.s_breadcrumb_title_t @> lg_tokens('huurrecht')))) DESC, r.inbound_citation_count DESC NULLS LAST, r.key) AS n
            FROM (SELECT r.* FROM ((SELECT f.id FROM (SELECT r.id FROM articles r WHERE (((cardinality(lg_tokens('huurrecht')) > 0 AND r.s_display_name_t @> lg_tokens('huurrecht')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_heading_t @> lg_tokens('huurrecht')) OR r.s_heading_n @> ARRAY[lg_fold('huurrecht')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_text_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_article_number_t @> lg_tokens('huurrecht')) OR r.s_article_number_n @> ARRAY[lg_fold('huurrecht')] OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_bwb_id_t @> lg_tokens('huurrecht')) OR r.s_bwb_id_n @> ARRAY[lg_fold('huurrecht')])) AND r.stub IS NOT TRUE OFFSET 0) f LIMIT 2000) UNION (SELECT f.id FROM (SELECT r.id FROM articles r WHERE (cardinality(lg_tokens('huurrecht')) > 0 AND (r.s_heading_t @> lg_tokens('huurrecht') OR r.s_breadcrumb_title_t @> lg_tokens('huurrecht'))) AND (((cardinality(lg_tokens('huurrecht')) > 0 AND r.s_display_name_t @> lg_tokens('huurrecht')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_heading_t @> lg_tokens('huurrecht')) OR r.s_heading_n @> ARRAY[lg_fold('huurrecht')] OR r.s_heading_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('huurrecht'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_breadcrumb_title_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_text_t @> lg_tokens('huurrecht')) OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_article_number_t @> lg_tokens('huurrecht')) OR r.s_article_number_n @> ARRAY[lg_fold('huurrecht')] OR (cardinality(lg_tokens('huurrecht')) > 0 AND r.s_bwb_id_t @> lg_tokens('huurrecht')) OR r.s_bwb_id_n @> ARRAY[lg_fold('huurrecht')])) AND r.stub IS NOT TRUE OFFSET 0) f LIMIT 2000)) found JOIN articles r ON r.id = found.id) r
            ORDER BY n
            LIMIT 6
        ) top
        JOIN articles r ON r.id = top.id
        ORDER BY top.n;

-- 3. Live documents 'stikstof'
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id
        FROM (
            SELECT r.id, row_number() OVER (ORDER BY (r.s_display_name_g LIKE lg_like(lg_fold('stikstof')) || '%' OR r.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('stikstof')) || '%' OR r.s_title_g LIKE lg_like(lg_fold('stikstof')) || '%' OR r.s_title_g LIKE '%' || chr(31) || lg_like(lg_fold('stikstof')) || '%') DESC, r.date DESC NULLS LAST, r.key DESC) AS n
            FROM (SELECT * FROM documents r WHERE ((cardinality(lg_tokens('stikstof')) > 0 AND r.s_display_name_t @> lg_tokens('stikstof')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('stikstof'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('stikstof')) > 0 AND r.s_title_t @> lg_tokens('stikstof')) OR r.s_title_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('stikstof'), '([^[:alnum:]])', '\\\1', 'g')) OR r.s_external_id_n @> ARRAY[lg_fold('stikstof')])  LIMIT 2000) r
            ORDER BY n
            LIMIT 6
        ) top
        JOIN documents r ON r.id = top.id
        ORDER BY top.n;

-- 4. Live laws 'burgerlijk wetboek'
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    json_build_object(
        'id', r.id, 'key', r.key,
        'collection', 'instruments', 'type', r.type,
        'display_name', (CASE WHEN coalesce(json_typeof(r.props -> 'citation_title'), 'null') <> 'null' THEN r.props -> 'citation_title' WHEN coalesce(json_typeof(r.props -> 'display_name'), 'null') <> 'null' THEN r.props -> 'display_name' WHEN coalesce(json_typeof(r.props -> 'title'), 'null') <> 'null' THEN r.props -> 'title' END),
        'snippet', left(coalesce(r.props ->> 'title', ''), 200),
        'extra', json_build_object(
            'bwb_id', r.props -> 'bwb_id',
            'citation_title', r.props -> 'citation_title',
            'short_title', r.props -> 'short_title',
            'aliases', r.props -> 'aliases',
            'kind', r.props -> 'kind',
            'date_published', r.props -> 'date_published',
            'date_in_force', r.props -> 'date_in_force',
            'version_date_in_force', r.props -> 'version_date_in_force',
            'expired_on', lg_str(r.props -> 'date_expired')
        )
    )

        FROM (
            SELECT r.id, row_number() OVER (ORDER BY (r.s_title_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_title_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_citation_title_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_citation_title_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_official_title_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_official_title_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_display_name_g LIKE lg_like(lg_fold('burgerlijk wetboek')) || '%' OR r.s_display_name_g LIKE '%' || chr(31) || lg_like(lg_fold('burgerlijk wetboek')) || '%') DESC, r.article_count DESC NULLS LAST, r.key) AS n
            FROM (SELECT * FROM instruments r WHERE ((cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_title_t @> lg_tokens('burgerlijk')) OR r.s_title_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_citation_title_t @> lg_tokens('burgerlijk')) OR r.s_citation_title_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_official_title_t @> lg_tokens('burgerlijk')) OR r.s_official_title_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_display_name_t @> lg_tokens('burgerlijk')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('burgerlijk'), '([^[:alnum:]])', '\\\1', 'g')) OR r.s_short_title_n @> ARRAY[lg_fold('burgerlijk')] OR (cardinality(lg_tokens('burgerlijk')) > 0 AND r.s_aliases_t @> lg_tokens('burgerlijk')) OR r.s_aliases_n @> ARRAY[lg_fold('burgerlijk')] OR r.s_bwb_id_n @> ARRAY[lg_fold('burgerlijk')]) AND ((cardinality(lg_tokens('wetboek')) > 0 AND r.s_title_t @> lg_tokens('wetboek')) OR r.s_title_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_citation_title_t @> lg_tokens('wetboek')) OR r.s_citation_title_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_official_title_t @> lg_tokens('wetboek')) OR r.s_official_title_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_display_name_t @> lg_tokens('wetboek')) OR r.s_display_name_g ~ ('(^|[ ' || chr(31) || '])' || regexp_replace(lg_fold('wetboek'), '([^[:alnum:]])', '\\\1', 'g')) OR r.s_short_title_n @> ARRAY[lg_fold('wetboek')] OR (cardinality(lg_tokens('wetboek')) > 0 AND r.s_aliases_t @> lg_tokens('wetboek')) OR r.s_aliases_n @> ARRAY[lg_fold('wetboek')] OR r.s_bwb_id_n @> ARRAY[lg_fold('wetboek')])  LIMIT 2000) r
            ORDER BY n
            LIMIT 6
        ) top
        JOIN instruments r ON r.id = top.id
        ORDER BY top.n;

RESET enable_seqscan;

-- 5. The words whose hits are kept, per collection: how many are of the current data version
SELECT s.collection, count(*) AS words,
       count(*) FILTER (WHERE v.version = s.version) AS current
FROM lg_search_candidates_state s
LEFT JOIN lg_data_version v ON v.collection = s.collection
GROUP BY 1 ORDER BY 1;

-- 6. The cache of the search indexes: blocks read from disk against those found in memory
SELECT relname, indexrelname, idx_blks_read, idx_blks_hit,
       round(100.0 * idx_blks_hit / nullif(idx_blks_hit + idx_blks_read, 0), 1) AS hit_pct
FROM pg_statio_user_indexes
WHERE indexrelname ~ '^(articles|documents|judgments|instruments)_s_'
ORDER BY idx_blks_read DESC LIMIT 20;

-- 7. The ministries in the graph
SELECT key, props ->> 'name' AS name, props ->> 'abbreviation' AS abbr FROM ministries ORDER BY key;
