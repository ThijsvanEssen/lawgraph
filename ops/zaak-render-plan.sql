-- Why /render/zaken/2025Z15468 gives the shell alone on prod (no-store, title "Concordans", no main): the render
-- budget (1 s) runs out on the reads of the page of the zaak. Read only: the statements /render runs for it, as it
-- runs them, under EXPLAIN (ANALYZE, BUFFERS), each twice (as cold as it is, then warm). The lookup of the zaak by
-- its number first (the index cases_number), which also gives its id to the others.
SET default_transaction_read_only = on;
SET statement_timeout = '60s';
\pset pager off

\echo '== 0. the zaak, by its number'
SELECT id AS case_id FROM cases WHERE lg_str(props -> 'number') = '2025Z15468' ORDER BY key LIMIT 1 \gset
\echo :case_id

\echo '== 1. the lookup by number'
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id FROM cases c WHERE lg_str(c.props -> 'number') = '2025Z15468' ORDER BY c.key LIMIT 1;

\echo '== 2a. read 2, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.key, json_build_object(
                   'number', lg_str(c.props -> 'number'),
                   'title', lg_str(c.props -> 'title'),
                   'citation_title', lg_str(c.props -> 'citation_title'),
                   'kind', lg_str(c.props -> 'kind'),
                   'started_on', lg_str(c.props -> 'started_on'),
                   'done', c.props -> 'done',
                   'dossier_numbers', c.props -> 'dossier_numbers') AS props
        FROM cases c
        WHERE c.id = :'case_id';

\echo '== 2b. the same, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.key, json_build_object(
                   'number', lg_str(c.props -> 'number'),
                   'title', lg_str(c.props -> 'title'),
                   'citation_title', lg_str(c.props -> 'citation_title'),
                   'kind', lg_str(c.props -> 'kind'),
                   'started_on', lg_str(c.props -> 'started_on'),
                   'done', c.props -> 'done',
                   'dossier_numbers', c.props -> 'dossier_numbers') AS props
        FROM cases c
        WHERE c.id = :'case_id';

\echo '== 3a. read 3, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id, d.kind, d.date, l.props AS light, d.pj_subject AS subject
            FROM edges e
            JOIN documents d ON d.id = e.from_id
            LEFT JOIN lg_document_light l ON l.id = d.id
            WHERE e.to_id = :'case_id' AND e.relation = 'PART_OF'
              AND e.from_collection = 'documents'
            ORDER BY d.date ASC NULLS LAST, d.key ASC
            LIMIT 20;

\echo '== 3b. the same, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id, d.kind, d.date, l.props AS light, d.pj_subject AS subject
            FROM edges e
            JOIN documents d ON d.id = e.from_id
            LEFT JOIN lg_document_light l ON l.id = d.id
            WHERE e.to_id = :'case_id' AND e.relation = 'PART_OF'
              AND e.from_collection = 'documents'
            ORDER BY d.date ASC NULLS LAST, d.key ASC
            LIMIT 20;

\echo '== 4a. read 4, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT dec.id, json_build_object(
                       'subject', lg_str(dec.props -> 'subject'),
                       'date', dec.date, 'passed', dec.passed,
                       'result', lg_str(dec.props -> 'result'),
                       'decision_kind', lg_str(dec.props -> 'decision_kind')) AS props
            FROM edges e
            JOIN decisions dec ON dec.id = e.from_id
            WHERE e.to_id = :'case_id' AND e.relation = 'ABOUT'
              AND e.from_collection = 'decisions'
            ORDER BY dec.date ASC NULLS LAST, dec.key ASC
            LIMIT 20;

\echo '== 4b. the same, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT dec.id, json_build_object(
                       'subject', lg_str(dec.props -> 'subject'),
                       'date', dec.date, 'passed', dec.passed,
                       'result', lg_str(dec.props -> 'result'),
                       'decision_kind', lg_str(dec.props -> 'decision_kind')) AS props
            FROM edges e
            JOIN decisions dec ON dec.id = e.from_id
            WHERE e.to_id = :'case_id' AND e.relation = 'ABOUT'
              AND e.from_collection = 'decisions'
            ORDER BY dec.date ASC NULLS LAST, dec.key ASC
            LIMIT 20;
