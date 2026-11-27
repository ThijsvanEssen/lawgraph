-- B222: where the network of a law (GET /api/nodes/instruments/{key}?limit=200&props=canvas) spends its
-- time on prod, read only: EXPLAIN (ANALYZE, BUFFERS) of its three heavy statements, each twice in a row,
-- for three laws. Shared read against hit says whether the time is disk or computing.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off
SET track_io_timing = on;
\echo '== bwbr0001840 statement 1 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT e.relation, 'outbound' AS direction, e.to_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.from_id = 'instruments/bwbr0001840'
            GROUP BY e.relation, e.to_collection
             UNION ALL
            SELECT e.relation, 'inbound' AS direction, e.from_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.to_id = 'instruments/bwbr0001840'   AND NOT lg_transposition_outcome(e.relation, e.to_id)
            GROUP BY e.relation, e.from_collection
             ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST;
\echo '== bwbr0001840 statement 1 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT e.relation, 'outbound' AS direction, e.to_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.from_id = 'instruments/bwbr0001840'
            GROUP BY e.relation, e.to_collection
             UNION ALL
            SELECT e.relation, 'inbound' AS direction, e.from_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.to_id = 'instruments/bwbr0001840'   AND NOT lg_transposition_outcome(e.relation, e.to_id)
            GROUP BY e.relation, e.from_collection
             ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST;
\echo '== bwbr0001840 statement 2 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT b.relation, 'outbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{IMPLEMENTS,REFERS_TO}'::text[],
                            '{instruments,instruments}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.from_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.to_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.to_id AND n.collection = 'instruments'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{PART_OF}'::text[],
                            '{articles}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'articles'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{REFERS_TO}'::text[],
                            '{documents}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'documents'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{VERSION_OF}'::text[],
                            '{instrument_versions}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'instrument_versions'
                 ORDER BY direction, ord, pos ASC NULLS LAST, edge_key;
\echo '== bwbr0001840 statement 2 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT b.relation, 'outbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{IMPLEMENTS,REFERS_TO}'::text[],
                            '{instruments,instruments}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.from_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.to_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.to_id AND n.collection = 'instruments'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{PART_OF}'::text[],
                            '{articles}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'articles'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{REFERS_TO}'::text[],
                            '{documents}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'documents'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{VERSION_OF}'::text[],
                            '{instrument_versions}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0001840'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'instrument_versions'
                 ORDER BY direction, ord, pos ASC NULLS LAST, edge_key;
\echo '== bwbr0001840 statement 4 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT DISTINCT ON (label) label, lg_str(pj_title) AS title
    FROM dossiers
    WHERE label IS NOT NULL
    ORDER BY label ASC NULLS LAST, key ASC NULLS LAST;
\echo '== bwbr0001840 statement 4 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT DISTINCT ON (label) label, lg_str(pj_title) AS title
    FROM dossiers
    WHERE label IS NOT NULL
    ORDER BY label ASC NULLS LAST, key ASC NULLS LAST;
\echo '== bwbr0011353 statement 1 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT e.relation, 'outbound' AS direction, e.to_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.from_id = 'instruments/bwbr0011353'
            GROUP BY e.relation, e.to_collection
             UNION ALL
            SELECT e.relation, 'inbound' AS direction, e.from_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.to_id = 'instruments/bwbr0011353'   AND NOT lg_transposition_outcome(e.relation, e.to_id)
            GROUP BY e.relation, e.from_collection
             ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST;
\echo '== bwbr0011353 statement 1 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT e.relation, 'outbound' AS direction, e.to_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.from_id = 'instruments/bwbr0011353'
            GROUP BY e.relation, e.to_collection
             UNION ALL
            SELECT e.relation, 'inbound' AS direction, e.from_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.to_id = 'instruments/bwbr0011353'   AND NOT lg_transposition_outcome(e.relation, e.to_id)
            GROUP BY e.relation, e.from_collection
             ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST;
\echo '== bwbr0011353 statement 2 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT b.relation, 'outbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{IMPLEMENTS,REFERS_TO}'::text[],
                            '{instruments,instruments}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.from_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.to_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.to_id AND n.collection = 'instruments'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{PART_OF}'::text[],
                            '{articles}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'articles'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{REFERS_TO}'::text[],
                            '{documents}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'documents'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{VERSION_OF}'::text[],
                            '{instrument_versions}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'instrument_versions'
                 ORDER BY direction, ord, pos ASC NULLS LAST, edge_key;
\echo '== bwbr0011353 statement 2 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT b.relation, 'outbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{IMPLEMENTS,REFERS_TO}'::text[],
                            '{instruments,instruments}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.from_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.to_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.to_id AND n.collection = 'instruments'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{PART_OF}'::text[],
                            '{articles}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'articles'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{REFERS_TO}'::text[],
                            '{documents}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'documents'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{VERSION_OF}'::text[],
                            '{instrument_versions}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0011353'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'instrument_versions'
                 ORDER BY direction, ord, pos ASC NULLS LAST, edge_key;
\echo '== bwbr0011353 statement 4 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT DISTINCT ON (label) label, lg_str(pj_title) AS title
    FROM dossiers
    WHERE label IS NOT NULL
    ORDER BY label ASC NULLS LAST, key ASC NULLS LAST;
\echo '== bwbr0011353 statement 4 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT DISTINCT ON (label) label, lg_str(pj_title) AS title
    FROM dossiers
    WHERE label IS NOT NULL
    ORDER BY label ASC NULLS LAST, key ASC NULLS LAST;
\echo '== bwbr0002221 statement 1 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT e.relation, 'outbound' AS direction, e.to_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.from_id = 'instruments/bwbr0002221'
            GROUP BY e.relation, e.to_collection
             UNION ALL
            SELECT e.relation, 'inbound' AS direction, e.from_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.to_id = 'instruments/bwbr0002221'   AND NOT lg_transposition_outcome(e.relation, e.to_id)
            GROUP BY e.relation, e.from_collection
             ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST;
\echo '== bwbr0002221 statement 1 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT e.relation, 'outbound' AS direction, e.to_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.from_id = 'instruments/bwbr0002221'
            GROUP BY e.relation, e.to_collection
             UNION ALL
            SELECT e.relation, 'inbound' AS direction, e.from_collection AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.to_id = 'instruments/bwbr0002221'   AND NOT lg_transposition_outcome(e.relation, e.to_id)
            GROUP BY e.relation, e.from_collection
             ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST;
\echo '== bwbr0002221 statement 2 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT b.relation, 'outbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{IMPLEMENTS,REFERS_TO}'::text[],
                            '{instruments,instruments}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.from_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.to_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.to_id AND n.collection = 'instruments'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{PART_OF}'::text[],
                            '{articles}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'articles'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{REFERS_TO}'::text[],
                            '{documents}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'documents'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{VERSION_OF}'::text[],
                            '{instrument_versions}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'instrument_versions'
                 ORDER BY direction, ord, pos ASC NULLS LAST, edge_key;
\echo '== bwbr0002221 statement 2 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT b.relation, 'outbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{IMPLEMENTS,REFERS_TO}'::text[],
                            '{instruments,instruments}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.from_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.to_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.to_id AND n.collection = 'instruments'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{PART_OF}'::text[],
                            '{articles}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'articles'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{REFERS_TO}'::text[],
                            '{documents}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'documents'
                 UNION ALL
                SELECT b.relation, 'inbound' AS direction, b.collection, b.ord,
                       e.key AS edge_key, e.from_id, e.to_id, e.doc,
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
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END))) AS props, e.pos
                FROM unnest('{VERSION_OF}'::text[],
                            '{instrument_versions}'::text[])
                    WITH ORDINALITY AS b(relation, collection, ord)
                CROSS JOIN LATERAL (
                    SELECT e.*, page.pos FROM (
                        SELECT k.key, 0 AS pos FROM edges k
                        WHERE k.to_id = 'instruments/bwbr0002221'
                          AND k.relation = b.relation
                          AND k.from_collection = b.collection
                        ORDER BY k.key
                        LIMIT 200 OFFSET 0
                    ) page
                    JOIN edges e ON e.key = page.key
                ) e
                JOIN nodes n ON n.id = e.from_id AND n.collection = 'instrument_versions'
                 ORDER BY direction, ord, pos ASC NULLS LAST, edge_key;
\echo '== bwbr0002221 statement 4 cold'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT DISTINCT ON (label) label, lg_str(pj_title) AS title
    FROM dossiers
    WHERE label IS NOT NULL
    ORDER BY label ASC NULLS LAST, key ASC NULLS LAST;
\echo '== bwbr0002221 statement 4 warm'
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON) SELECT DISTINCT ON (label) label, lg_str(pj_title) AS title
    FROM dossiers
    WHERE label IS NOT NULL
    ORDER BY label ASC NULLS LAST, key ASC NULLS LAST;
