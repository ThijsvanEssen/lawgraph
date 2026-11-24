-- B217: where /api/nodes/instruments/<bwb>/neighborhood?depth=3&cap=200&props=canvas spends its 4.5-12 s cold,
-- read only. The walk (lg_neighborhood) per depth for the Grondwet, then the whole statement of the route for
-- the BW as the API runs it (cold, then warm), and what the props of the nodes it keeps weigh.
-- The Buffers line of each top node holds the reads of the statements inside the walk too.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== 0. the neighbours of the Grondwet and the BW per direction, relation and collection'
SELECT 'out' AS dir, from_id AS node, relation, to_collection AS other, count(*) FROM edges
WHERE from_id IN ('instruments/bwbr0001840', 'instruments/bwbr0005289') GROUP BY 1, 2, 3, 4
UNION ALL
SELECT 'in', to_id, relation, from_collection, count(*) FROM edges
WHERE to_id IN ('instruments/bwbr0001840', 'instruments/bwbr0005289') GROUP BY 1, 2, 3, 4
ORDER BY 2, 1, 3, 4;

\echo '== 1. the walk of the Grondwet, depth 1'
EXPLAIN (ANALYZE, BUFFERS)
SELECT cardinality(lg_neighborhood('instruments/bwbr0001840', 1, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}'));

\echo '== 2. the walk of the Grondwet, depth 2'
EXPLAIN (ANALYZE, BUFFERS)
SELECT cardinality(lg_neighborhood('instruments/bwbr0001840', 2, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}'));

\echo '== 3. the walk of the Grondwet, depth 3'
EXPLAIN (ANALYZE, BUFFERS)
SELECT cardinality(lg_neighborhood('instruments/bwbr0001840', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}'));

\echo '== 4. the whole statement of the route for the BW, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)

                WITH walked AS (
                    SELECT lg_neighborhood(
                        'instruments/bwbr0005289', 3, 200, NULL, NULL,
                        true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}',
                        NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}') AS ids
                )
                SELECT
                    (SELECT coalesce(json_agg(json_build_array(
                         n.id, n.key, n.type, n.labels, (SELECT coalesce(json_object_agg(p.key,
            CASE WHEN p.key = 'actors' AND json_typeof(p.value) = 'array' THEN (SELECT coalesce(json_agg(json_build_object('role', a.actor -> 'role', 'name', a.actor -> 'name', 'faction', a.actor -> 'faction') ORDER BY a.n), '[]')
        FROM json_array_elements(p.value) WITH ORDINALITY AS a(actor, n))
                 ELSE p.value END
            ORDER BY p.n), '{}'::json)
        FROM (SELECT (CASE WHEN n.collection = 'judgments' THEN (SELECT l.props FROM lg_judgment_light l WHERE l.id = n.id) WHEN n.collection = ANY(ARRAY['instruments', 'instrument_versions', 'article_versions']::text[]) THEN lg_update(lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']), json_strip_nulls(json_build_object('date', coalesce(lg_str(n.props -> 'date'), CASE WHEN n.collection = 'instruments' THEN CASE WHEN lg_str(n.props -> 'kind') = 'publicatie' THEN lg_str(n.props -> 'date_published') ELSE coalesce(lg_str(n.props -> 'version_date_in_force'), lg_str(n.props -> 'date_in_force')) END ELSE lg_str(n.props -> 'valid_from') END)))) WHEN n.collection = 'activities' THEN lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb', 'case_ids', 'case_kinds_by_dossier']) WHEN n.collection = 'commitments' THEN lg_unset(n.props, ARRAY['paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']) ELSE lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']) END) AS v) AS light
        CROSS JOIN LATERAL (
            SELECT * FROM json_each(
                CASE WHEN json_typeof(light.v) = 'object' THEN light.v END
            ) WITH ORDINALITY
            UNION ALL
            SELECT 'instrument_citation_title', to_json(coalesce(
                   nullif(i.citation_title, ''), nullif(t.title, ''))), 1000000::bigint
        FROM instruments i
        LEFT JOIN lg_instrument_names t ON t.id = i.id
        WHERE n.collection = 'instrument_versions'
          AND i.bwb_id = lg_str(n.props -> 'bwb_id')
          AND coalesce(nullif(i.citation_title, ''), nullif(t.title, '')) IS NOT NULL
        ) AS p(key, value, n)
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END)))) ORDER BY n.id), '[]')
                     FROM walked w, nodes n
                     WHERE n.id = ANY(w.ids) AND n.collection = ANY(ARRAY(SELECT DISTINCT split_part(x, '/', 1) FROM unnest(w.ids) x))
                    ) AS nodes,
                    (SELECT coalesce(json_agg(json_build_array(
                         e.key, e.from_id, e.to_id, e.doc) ORDER BY e.key), '[]')
                     FROM walked w, edges e
                     WHERE e.from_id = ANY(w.ids || 'instruments/bwbr0005289'::text)
                       AND e.to_id = ANY(w.ids || 'instruments/bwbr0005289'::text) )
                        AS edges,
                    (SELECT coalesce(lg_str(n.props -> 'date'), CASE WHEN n.collection = 'instruments' THEN CASE WHEN lg_str(n.props -> 'kind') = 'publicatie' THEN lg_str(n.props -> 'date_published') ELSE coalesce(lg_str(n.props -> 'version_date_in_force'), lg_str(n.props -> 'date_in_force')) END ELSE lg_str(n.props -> 'valid_from') END) FROM nodes n
                     WHERE n.id = 'instruments/bwbr0005289'
                       AND n.collection = ANY(ARRAY['instruments', 'instrument_versions', 'article_versions']::text[])) AS day
                FROM walked
                ;

\echo '== 5. the same, warm'
EXPLAIN (ANALYZE, BUFFERS)

                WITH walked AS (
                    SELECT lg_neighborhood(
                        'instruments/bwbr0005289', 3, 200, NULL, NULL,
                        true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}',
                        NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}') AS ids
                )
                SELECT
                    (SELECT coalesce(json_agg(json_build_array(
                         n.id, n.key, n.type, n.labels, (SELECT coalesce(json_object_agg(p.key,
            CASE WHEN p.key = 'actors' AND json_typeof(p.value) = 'array' THEN (SELECT coalesce(json_agg(json_build_object('role', a.actor -> 'role', 'name', a.actor -> 'name', 'faction', a.actor -> 'faction') ORDER BY a.n), '[]')
        FROM json_array_elements(p.value) WITH ORDINALITY AS a(actor, n))
                 ELSE p.value END
            ORDER BY p.n), '{}'::json)
        FROM (SELECT (CASE WHEN n.collection = 'judgments' THEN (SELECT l.props FROM lg_judgment_light l WHERE l.id = n.id) WHEN n.collection = ANY(ARRAY['instruments', 'instrument_versions', 'article_versions']::text[]) THEN lg_update(lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']), json_strip_nulls(json_build_object('date', coalesce(lg_str(n.props -> 'date'), CASE WHEN n.collection = 'instruments' THEN CASE WHEN lg_str(n.props -> 'kind') = 'publicatie' THEN lg_str(n.props -> 'date_published') ELSE coalesce(lg_str(n.props -> 'version_date_in_force'), lg_str(n.props -> 'date_in_force')) END ELSE lg_str(n.props -> 'valid_from') END)))) WHEN n.collection = 'activities' THEN lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb', 'case_ids', 'case_kinds_by_dossier']) WHEN n.collection = 'commitments' THEN lg_unset(n.props, ARRAY['paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']) ELSE lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']) END) AS v) AS light
        CROSS JOIN LATERAL (
            SELECT * FROM json_each(
                CASE WHEN json_typeof(light.v) = 'object' THEN light.v END
            ) WITH ORDINALITY
            UNION ALL
            SELECT 'instrument_citation_title', to_json(coalesce(
                   nullif(i.citation_title, ''), nullif(t.title, ''))), 1000000::bigint
        FROM instruments i
        LEFT JOIN lg_instrument_names t ON t.id = i.id
        WHERE n.collection = 'instrument_versions'
          AND i.bwb_id = lg_str(n.props -> 'bwb_id')
          AND coalesce(nullif(i.citation_title, ''), nullif(t.title, '')) IS NOT NULL
        ) AS p(key, value, n)
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END)))) ORDER BY n.id), '[]')
                     FROM walked w, nodes n
                     WHERE n.id = ANY(w.ids) AND n.collection = ANY(ARRAY(SELECT DISTINCT split_part(x, '/', 1) FROM unnest(w.ids) x))
                    ) AS nodes,
                    (SELECT coalesce(json_agg(json_build_array(
                         e.key, e.from_id, e.to_id, e.doc) ORDER BY e.key), '[]')
                     FROM walked w, edges e
                     WHERE e.from_id = ANY(w.ids || 'instruments/bwbr0005289'::text)
                       AND e.to_id = ANY(w.ids || 'instruments/bwbr0005289'::text) )
                        AS edges,
                    (SELECT coalesce(lg_str(n.props -> 'date'), CASE WHEN n.collection = 'instruments' THEN CASE WHEN lg_str(n.props -> 'kind') = 'publicatie' THEN lg_str(n.props -> 'date_published') ELSE coalesce(lg_str(n.props -> 'version_date_in_force'), lg_str(n.props -> 'date_in_force')) END ELSE lg_str(n.props -> 'valid_from') END) FROM nodes n
                     WHERE n.id = 'instruments/bwbr0005289'
                       AND n.collection = ANY(ARRAY['instruments', 'instrument_versions', 'article_versions']::text[])) AS day
                FROM walked
                ;

\echo '== 6. the nodes the walk of the BW keeps, per collection, and the size of their props'
SELECT split_part(x, '/', 1) AS collection, count(*), avg(pg_column_size(n.props))::int AS avg_bytes,
       sum(pg_column_size(n.props)) AS bytes
FROM unnest(lg_neighborhood('instruments/bwbr0005289', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL,
     '{"MEMBER_OF factions","SERVED_IN cabinets"}')) x
JOIN nodes n ON n.id = x
GROUP BY 1 ORDER BY 4 DESC;
