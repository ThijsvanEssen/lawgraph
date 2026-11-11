-- The conclusions of the Parket bij de Hoge Raad (ECLI:NL:PHR) since 2026-08-01: stored or not, per week of their
-- decision date. Read only. Until the index read every document (no `type=Uitspraak`), a conclusion came only as a
-- cited one (`retrieve rechtspraak --mode gaps`), weeks or months after it was published.
--
-- 1. per week of the decision date: the raw records (rs-content, rs-content-missing), the judgments, the stubs
--    among them and the median days between decision and fetch.
-- 2. the seven conclusions the site answered 404 for on 11 Nov and three it showed: raw record, node, stub.
-- 3. per year of the decision date, all history: the PHR judgments and stubs stored (the index lists 34,221
--    conclusions of the Parket on 11 Nov 2026; 1,341 of 2025).
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. PHR per week of the decision date (since 2026-08-01)'
WITH j AS (
    SELECT j.ecli, j.date_eff, coalesce(j.stub, false) AS stub
    FROM judgments j
    WHERE j.source = 'rechtspraak' AND j.ecli LIKE 'ECLI:NL:PHR:2026:%' AND j.date_eff >= '2026-08-01'),
r AS (
    SELECT external_id AS ecli, kind, fetched_at
    FROM raw_sources
    WHERE source = 'rechtspraak' AND kind IN ('rs-content', 'rs-content-missing')
      AND external_id LIKE 'ECLI:NL:PHR:2026:%')
SELECT date_trunc('week', j.date_eff::date)::date AS week,
       count(*) AS judgments,
       count(*) FILTER (WHERE j.stub) AS stubs,
       count(r.ecli) FILTER (WHERE r.kind = 'rs-content') AS raw,
       count(r.ecli) FILTER (WHERE r.kind = 'rs-content-missing') AS missing,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.fetched_at::date - j.date_eff::date)
           FILTER (WHERE r.kind = 'rs-content') AS median_days_to_fetch
FROM j
LEFT JOIN r ON r.ecli = j.ecli
GROUP BY 1
ORDER BY 1;

\echo '== 2. the conclusions checked on concordans.nl on 11 Nov'
WITH want(ecli, site) AS (VALUES
    ('ECLI:NL:PHR:2026:1019', '404'), ('ECLI:NL:PHR:2026:1033', '404'), ('ECLI:NL:PHR:2026:1036', '404'),
    ('ECLI:NL:PHR:2026:1057', '404'), ('ECLI:NL:PHR:2026:956', '404'), ('ECLI:NL:PHR:2026:878', '404'),
    ('ECLI:NL:PHR:2026:858', '404'), ('ECLI:NL:PHR:2026:889', 'shown'), ('ECLI:NL:PHR:2026:751', 'shown'),
    ('ECLI:NL:PHR:2026:591', 'shown'))
SELECT w.ecli, w.site,
       (SELECT string_agg(r.kind || ' ' || r.fetched_at::date, ', ')
        FROM raw_sources r
        WHERE r.source = 'rechtspraak' AND r.external_id = w.ecli) AS raw,
       j.date_eff, j.stub
FROM want w
LEFT JOIN judgments j ON j.source = 'rechtspraak' AND j.ecli = w.ecli
ORDER BY w.site, w.ecli;

\echo '== 3. PHR per year of the decision date'
SELECT left(j.date_eff, 4) AS y, count(*) AS judgments, count(*) FILTER (WHERE j.stub) AS stubs
FROM judgments j
WHERE j.source = 'rechtspraak' AND j.ecli LIKE 'ECLI:NL:PHR:%'
GROUP BY 1
ORDER BY 1;
