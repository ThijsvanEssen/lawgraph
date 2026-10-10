-- Read only: what the page of a committee costs (/api/committees/fin 6.0 s, /activities 2.6 s cold in Back-end #1's
-- route sweep of 10 Oct): the dossiers its activities and cases are about (every LED_BY edge into it and every ABOUT
-- edge of each, then a count and a sort for one page), and its activities (every one read and sorted for one page).
-- EXPLAIN ANALYZE runs the SELECTs; nothing is written. Run cold if it can be; the Buffers lines say what came from disk.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== the dossiers of fin, a page of 100'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
WITH matching AS (
            SELECT d.id, d.key, d.type, d.labels, d.props, d.opened_on
            FROM dossiers d
            WHERE d.id IN (
                SELECT subject.to_id
                FROM edges led
                JOIN edges subject ON subject.from_id = led.from_id
                WHERE led.to_id = (SELECT id FROM committees WHERE key = 'fin' OR lg_str(props -> 'slug') = 'fin' ORDER BY key LIMIT 1) AND led.relation = 'LED_BY'
                  AND subject.relation = 'ABOUT'
                  AND subject.to_collection = 'dossiers'
            )
        )

    SELECT counted.total, page.*
    FROM (SELECT count(*)::int AS total FROM matching) counted
    LEFT JOIN LATERAL (
        SELECT * FROM matching ORDER BY opened_on DESC NULLS LAST, key ASC
        LIMIT 100 OFFSET 0
    ) page ON true
    ORDER BY page.opened_on DESC NULLS LAST, page.key ASC;

\echo '== the activities of fin, a page of 100'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
WITH led AS (
            SELECT a.id, a.key, a.date
            FROM edges e
            JOIN activities a ON a.id = e.from_id
            WHERE e.to_id = (SELECT id FROM committees WHERE key = 'fin' OR lg_str(props -> 'slug') = 'fin' ORDER BY key LIMIT 1) AND e.relation = 'LED_BY'
              AND e.from_collection = 'activities'
        ),
        listed AS (
    SELECT counted.total, page.*
    FROM (SELECT count(*)::int AS total FROM led) counted
    LEFT JOIN LATERAL (
        SELECT * FROM led ORDER BY date DESC NULLS LAST, key ASC
        LIMIT 100 OFFSET 0
    ) page ON true
    ORDER BY page.date DESC NULLS LAST, page.key ASC
    )
        SELECT listed.total, a.id, json_build_object(
            'id', a.id,
            'key', a.key,
            'date', a.props -> 'date',
            'kind', a.props -> 'kind',
            'agenda_title', a.props -> 'agenda_title',
            'status', a.props -> 'status',
            'dossier_numbers', CASE WHEN lg_truthy(a.props -> 'dossier_numbers') THEN a.props -> 'dossier_numbers' ELSE '[]'::json END
        ) AS item
        FROM listed
        LEFT JOIN activities a ON a.id = listed.id
        ORDER BY listed.date DESC NULLS LAST, listed.key ASC;
