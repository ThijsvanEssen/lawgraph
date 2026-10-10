-- Read only: what the members' counts of /api/cabinets/{key} cost, for rutte_iv (2.0 s cold)
-- and balkenende_ii (503 after 30 s; old cabinets' members signed many cases): the walk over
-- every paper each member signed and its cases as the API does it now (before, a case's date
-- through the view of every node), the same walk reading a case's date from cases by key, and
-- the read of lg_authored, a range of its index per member (once it is filled). EXPLAIN ANALYZE
-- runs the SELECTs; nothing is written. A plan past 120 s ends with a timeout and the next runs.
-- Run cold if it can be, e.g. right after a restart; the Buffers lines (shared read) say what
-- came from disk.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== whether lg_authored is filled (the API reads it once it is)'
SELECT EXISTS (SELECT 1 FROM lg_authored_state WHERE id) AS lg_authored_filled;

\echo '== rutte_iv: before: the walk, case dates through nodes'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT m.key, signed.dossiers, signed.bills
FROM (
    SELECT c.*, lg_str(c.props -> 'from_date') AS period_start,
           CASE WHEN lg_truthy(c.props -> 'to_date') THEN lg_str(c.props -> 'to_date')
                ELSE to_char(current_date, 'YYYY-MM-DD') END AS period_end
    FROM cabinets c WHERE c.key = 'rutte_iv' OFFSET 0
) c
JOIN edges e ON e.to_id = c.id AND e.relation = 'SERVED_IN'
JOIN members m ON m.id = e.from_id
CROSS JOIN LATERAL (
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = 'Wetgeving')
       )::int AS bills
FROM (
    SELECT DISTINCT CASE WHEN p.to_collection = 'cases'
                         THEN q.to_id ELSE p.to_id END AS target
    FROM (
        -- each date read once: OFFSET 0 keeps the subquery from being inlined into every
        -- comparison of the date below, where it would be read again per comparison
        SELECT a.to_id,
               CASE WHEN a.to_collection = 'documents' THEN doc.date
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n WHERE n.id = a.to_id)
               END AS date
        FROM edges a
        LEFT JOIN documents doc
            ON a.to_collection = 'documents' AND doc.id = a.to_id
        WHERE a.from_id = m.id AND a.relation = 'AUTHORED'
          AND lg_str(a.doc -> 'meta' -> 'capacity') = 'bewindspersoon'
        OFFSET 0
    ) a
    JOIN edges p ON p.from_id = a.to_id AND p.relation = 'PART_OF'
    LEFT JOIN edges q ON p.to_collection = 'cases' AND q.from_id = p.to_id
        AND q.relation = 'PART_OF' AND q.to_collection = 'dossiers'
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.target
WHERE starts_with(signed.target, 'dossiers/')
) signed
ORDER BY e.key;

\echo '== rutte_iv: the walk, case dates from cases'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT m.key, signed.dossiers, signed.bills
FROM (
    SELECT c.*, lg_str(c.props -> 'from_date') AS period_start,
           CASE WHEN lg_truthy(c.props -> 'to_date') THEN lg_str(c.props -> 'to_date')
                ELSE to_char(current_date, 'YYYY-MM-DD') END AS period_end
    FROM cabinets c WHERE c.key = 'rutte_iv' OFFSET 0
) c
JOIN edges e ON e.to_id = c.id AND e.relation = 'SERVED_IN'
JOIN members m ON m.id = e.from_id
CROSS JOIN LATERAL (
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = 'Wetgeving')
       )::int AS bills
FROM (
    SELECT DISTINCT CASE WHEN p.to_collection = 'cases'
                         THEN q.to_id ELSE p.to_id END AS target
    FROM (
        -- each date read once: OFFSET 0 keeps the subquery from being inlined into every
        -- comparison of the date below, where it would be read again per comparison; a
        -- case's from its own table by key, not through the view of every node
        SELECT a.to_id,
               CASE WHEN a.to_collection = 'documents' THEN doc.date
                    WHEN a.to_collection = 'cases' THEN (
                        SELECT lg_str(k.props -> 'date') FROM cases k
                        WHERE k.id = a.to_id)
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n WHERE n.id = a.to_id)
               END AS date
        FROM edges a
        LEFT JOIN documents doc
            ON a.to_collection = 'documents' AND doc.id = a.to_id
        WHERE a.from_id = m.id AND a.relation = 'AUTHORED'
          AND lg_str(a.doc -> 'meta' -> 'capacity') = 'bewindspersoon'
        OFFSET 0
    ) a
    JOIN edges p ON p.from_id = a.to_id AND p.relation = 'PART_OF'
    LEFT JOIN edges q ON p.to_collection = 'cases' AND q.from_id = p.to_id
        AND q.relation = 'PART_OF' AND q.to_collection = 'dossiers'
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.target
WHERE starts_with(signed.target, 'dossiers/')
) signed
ORDER BY e.key;

\echo '== rutte_iv: after: lg_authored'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT m.key, signed.dossiers, signed.bills
FROM (
    SELECT c.*, lg_str(c.props -> 'from_date') AS period_start,
           CASE WHEN lg_truthy(c.props -> 'to_date') THEN lg_str(c.props -> 'to_date')
                ELSE to_char(current_date, 'YYYY-MM-DD') END AS period_end
    FROM cabinets c WHERE c.key = 'rutte_iv' OFFSET 0
) c
JOIN edges e ON e.to_id = c.id AND e.relation = 'SERVED_IN'
JOIN members m ON m.id = e.from_id
CROSS JOIN LATERAL (
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = 'Wetgeving'))::int AS bills
FROM (
    SELECT DISTINCT x.dossier_id
    FROM (
        SELECT a.dossiers,
               CASE WHEN starts_with(a.document_id, 'documents/') THEN doc.date
                    WHEN starts_with(a.document_id, 'cases/') THEN (
                        SELECT lg_str(k.props -> 'date') FROM cases k
                        WHERE k.id = a.document_id)
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n
                          WHERE n.id = a.document_id)
               END AS date
        FROM lg_authored a
        LEFT JOIN documents doc ON doc.id = a.document_id
        WHERE a.member_id = m.id
          AND lg_str(a.meta -> 'capacity') = 'bewindspersoon'
        OFFSET 0
    ) a
    CROSS JOIN LATERAL unnest(a.dossiers) AS x(dossier_id)
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.dossier_id
) signed
ORDER BY e.key;

\echo '== balkenende_ii: before: the walk, case dates through nodes'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT m.key, signed.dossiers, signed.bills
FROM (
    SELECT c.*, lg_str(c.props -> 'from_date') AS period_start,
           CASE WHEN lg_truthy(c.props -> 'to_date') THEN lg_str(c.props -> 'to_date')
                ELSE to_char(current_date, 'YYYY-MM-DD') END AS period_end
    FROM cabinets c WHERE c.key = 'balkenende_ii' OFFSET 0
) c
JOIN edges e ON e.to_id = c.id AND e.relation = 'SERVED_IN'
JOIN members m ON m.id = e.from_id
CROSS JOIN LATERAL (
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = 'Wetgeving')
       )::int AS bills
FROM (
    SELECT DISTINCT CASE WHEN p.to_collection = 'cases'
                         THEN q.to_id ELSE p.to_id END AS target
    FROM (
        -- each date read once: OFFSET 0 keeps the subquery from being inlined into every
        -- comparison of the date below, where it would be read again per comparison
        SELECT a.to_id,
               CASE WHEN a.to_collection = 'documents' THEN doc.date
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n WHERE n.id = a.to_id)
               END AS date
        FROM edges a
        LEFT JOIN documents doc
            ON a.to_collection = 'documents' AND doc.id = a.to_id
        WHERE a.from_id = m.id AND a.relation = 'AUTHORED'
          AND lg_str(a.doc -> 'meta' -> 'capacity') = 'bewindspersoon'
        OFFSET 0
    ) a
    JOIN edges p ON p.from_id = a.to_id AND p.relation = 'PART_OF'
    LEFT JOIN edges q ON p.to_collection = 'cases' AND q.from_id = p.to_id
        AND q.relation = 'PART_OF' AND q.to_collection = 'dossiers'
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.target
WHERE starts_with(signed.target, 'dossiers/')
) signed
ORDER BY e.key;

\echo '== balkenende_ii: the walk, case dates from cases'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT m.key, signed.dossiers, signed.bills
FROM (
    SELECT c.*, lg_str(c.props -> 'from_date') AS period_start,
           CASE WHEN lg_truthy(c.props -> 'to_date') THEN lg_str(c.props -> 'to_date')
                ELSE to_char(current_date, 'YYYY-MM-DD') END AS period_end
    FROM cabinets c WHERE c.key = 'balkenende_ii' OFFSET 0
) c
JOIN edges e ON e.to_id = c.id AND e.relation = 'SERVED_IN'
JOIN members m ON m.id = e.from_id
CROSS JOIN LATERAL (
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = 'Wetgeving')
       )::int AS bills
FROM (
    SELECT DISTINCT CASE WHEN p.to_collection = 'cases'
                         THEN q.to_id ELSE p.to_id END AS target
    FROM (
        -- each date read once: OFFSET 0 keeps the subquery from being inlined into every
        -- comparison of the date below, where it would be read again per comparison; a
        -- case's from its own table by key, not through the view of every node
        SELECT a.to_id,
               CASE WHEN a.to_collection = 'documents' THEN doc.date
                    WHEN a.to_collection = 'cases' THEN (
                        SELECT lg_str(k.props -> 'date') FROM cases k
                        WHERE k.id = a.to_id)
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n WHERE n.id = a.to_id)
               END AS date
        FROM edges a
        LEFT JOIN documents doc
            ON a.to_collection = 'documents' AND doc.id = a.to_id
        WHERE a.from_id = m.id AND a.relation = 'AUTHORED'
          AND lg_str(a.doc -> 'meta' -> 'capacity') = 'bewindspersoon'
        OFFSET 0
    ) a
    JOIN edges p ON p.from_id = a.to_id AND p.relation = 'PART_OF'
    LEFT JOIN edges q ON p.to_collection = 'cases' AND q.from_id = p.to_id
        AND q.relation = 'PART_OF' AND q.to_collection = 'dossiers'
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.target
WHERE starts_with(signed.target, 'dossiers/')
) signed
ORDER BY e.key;

\echo '== balkenende_ii: after: lg_authored'
EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON)
SELECT m.key, signed.dossiers, signed.bills
FROM (
    SELECT c.*, lg_str(c.props -> 'from_date') AS period_start,
           CASE WHEN lg_truthy(c.props -> 'to_date') THEN lg_str(c.props -> 'to_date')
                ELSE to_char(current_date, 'YYYY-MM-DD') END AS period_end
    FROM cabinets c WHERE c.key = 'balkenende_ii' OFFSET 0
) c
JOIN edges e ON e.to_id = c.id AND e.relation = 'SERVED_IN'
JOIN members m ON m.id = e.from_id
CROSS JOIN LATERAL (
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = 'Wetgeving'))::int AS bills
FROM (
    SELECT DISTINCT x.dossier_id
    FROM (
        SELECT a.dossiers,
               CASE WHEN starts_with(a.document_id, 'documents/') THEN doc.date
                    WHEN starts_with(a.document_id, 'cases/') THEN (
                        SELECT lg_str(k.props -> 'date') FROM cases k
                        WHERE k.id = a.document_id)
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n
                          WHERE n.id = a.document_id)
               END AS date
        FROM lg_authored a
        LEFT JOIN documents doc ON doc.id = a.document_id
        WHERE a.member_id = m.id
          AND lg_str(a.meta -> 'capacity') = 'bewindspersoon'
        OFFSET 0
    ) a
    CROSS JOIN LATERAL unnest(a.dossiers) AS x(dossier_id)
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.dossier_id
) signed
ORDER BY e.key;
