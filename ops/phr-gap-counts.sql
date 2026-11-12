-- The conclusions of the Parket bij de Hoge Raad (court_code PHR): stored or not. Read only. Until the index read every
-- document (no `type=Uitspraak`, #1162), a conclusion came only as a cited one (`retrieve rechtspraak --mode gaps`).
-- Cheap: judgments by court_code (index court_code, date_eff, ...) and by ecli (unique index); of raw_sources only the
-- small range kind rs-content-missing (index source, kind, key). A judgment exists when its rs-content record does.
--
-- 1. per week of the decision date since 2026-08-01: the judgments and the stubs among them.
-- 2. the seven conclusions the site answered 404 for on 11 Nov and three it showed: judgment, stub, 404 record.
-- 3. per year of the decision date, all history: the judgments and stubs (the index lists 34,221 conclusions of the
--    Parket on 11 Nov 2026; 1,341 of 2025), and the PHR 404 records.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. PHR per week of the decision date (since 2026-08-01)'
SELECT date_trunc('week', j.date_eff::date)::date AS week, count(*) AS judgments,
       count(*) FILTER (WHERE j.stub) AS stubs
FROM judgments j
WHERE j.court_code = 'PHR' AND j.date_eff >= '2026-08-01'
GROUP BY 1
ORDER BY 1;

\echo '== 2. the conclusions checked on concordans.nl on 11 Nov'
WITH want(ecli, site) AS (VALUES
    ('ECLI:NL:PHR:2026:1019', '404'), ('ECLI:NL:PHR:2026:1033', '404'), ('ECLI:NL:PHR:2026:1036', '404'),
    ('ECLI:NL:PHR:2026:1057', '404'), ('ECLI:NL:PHR:2026:956', '404'), ('ECLI:NL:PHR:2026:878', '404'),
    ('ECLI:NL:PHR:2026:858', '404'), ('ECLI:NL:PHR:2026:889', 'shown'), ('ECLI:NL:PHR:2026:751', 'shown'),
    ('ECLI:NL:PHR:2026:591', 'shown')),
missing AS (
    SELECT external_id AS ecli, fetched_at
    FROM raw_sources
    WHERE source = 'rechtspraak' AND kind = 'rs-content-missing')
SELECT w.ecli, w.site, j.date_eff, j.stub, m.fetched_at::date AS answered_404
FROM want w
LEFT JOIN judgments j ON j.ecli = w.ecli
LEFT JOIN missing m ON m.ecli = w.ecli
ORDER BY w.site, w.ecli;

\echo '== 3. PHR per year of the decision date'
SELECT left(j.date_eff, 4) AS y, count(*) AS judgments, count(*) FILTER (WHERE j.stub) AS stubs
FROM judgments j
WHERE j.court_code = 'PHR'
GROUP BY 1
ORDER BY 1;

SELECT count(*) AS phr_404_records
FROM raw_sources
WHERE source = 'rechtspraak' AND kind = 'rs-content-missing' AND external_id LIKE 'ECLI:NL:PHR:%';
