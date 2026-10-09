-- Read only: the abbreviations two or more laws claim (short title or source abbreviation, any case), which
-- the linker gives to none of them, and the ones the code beside its version keeps (the title of the others
-- is its title with "(…)" after it: Rv); then the names a title without its year adds ("Vreemdelingenwet").
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== 1. Abbreviations claimed by two or more laws: in all, and of those kept by the code beside its versions'
WITH claims AS (
    SELECT upper(a) AS abbreviation, i.key, lg_str(i.props -> 'citation_title') AS title
    FROM instruments i
    CROSS JOIN LATERAL json_array_elements_text(
        CASE WHEN json_typeof(i.props -> 'aliases') = 'array' THEN i.props -> 'aliases' ELSE '[]' END
    ) AS a
    WHERE i.bwb_id IS NOT NULL OR i.celex IS NOT NULL
    UNION
    SELECT upper(lg_str(i.props -> 'short_title')), i.key, lg_str(i.props -> 'citation_title')
    FROM instruments i
    WHERE (i.bwb_id IS NOT NULL OR i.celex IS NOT NULL) AND lg_str(i.props -> 'short_title') IS NOT NULL
),
shared AS (
    SELECT abbreviation, count(DISTINCT key) AS laws FROM claims GROUP BY 1 HAVING count(DISTINCT key) > 1
),
based AS (
    SELECT s.abbreviation FROM shared s
    WHERE EXISTS (
        SELECT 1 FROM claims b
        WHERE b.abbreviation = s.abbreviation AND b.title IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM claims o
              WHERE o.abbreviation = s.abbreviation AND o.key <> b.key
                AND (o.title IS NULL OR o.title NOT LIKE b.title || ' (%')
          )
    )
)
SELECT (SELECT count(*) FROM shared) AS shared, (SELECT count(*) FROM based) AS kept_by_the_code;

\echo '== 2. The 40 abbreviations most laws claim, and RV, PW, WWB, VW, WVW whatever their count'
WITH claims AS (
    SELECT upper(a) AS abbreviation, i.key, lg_str(i.props -> 'citation_title') AS title
    FROM instruments i
    CROSS JOIN LATERAL json_array_elements_text(
        CASE WHEN json_typeof(i.props -> 'aliases') = 'array' THEN i.props -> 'aliases' ELSE '[]' END
    ) AS a
    WHERE i.bwb_id IS NOT NULL OR i.celex IS NOT NULL
    UNION
    SELECT upper(lg_str(i.props -> 'short_title')), i.key, lg_str(i.props -> 'citation_title')
    FROM instruments i
    WHERE (i.bwb_id IS NOT NULL OR i.celex IS NOT NULL) AND lg_str(i.props -> 'short_title') IS NOT NULL
)
SELECT abbreviation, count(DISTINCT key) AS laws, string_agg(DISTINCT key || ' ' || left(coalesce(title, ''), 60), ' | ') AS which
FROM claims
GROUP BY abbreviation
HAVING count(DISTINCT key) > 1 OR abbreviation IN ('RV', 'PW', 'WWB', 'VW', 'WVW')
ORDER BY abbreviation IN ('RV', 'PW', 'WWB', 'VW', 'WVW') DESC, count(DISTINCT key) DESC, abbreviation
LIMIT 45;

\echo '== 3. Names a title without its year adds: one law has the name with a year, none is called so'
WITH titled AS (
    SELECT DISTINCT i.key, t AS title
    FROM instruments i
    CROSS JOIN LATERAL (VALUES (lg_str(i.props -> 'title')), (lg_str(i.props -> 'citation_title'))) AS v(t)
    WHERE (i.bwb_id IS NOT NULL OR i.celex IS NOT NULL) AND t IS NOT NULL
),
yearless AS (
    SELECT substring(title FROM '^(.*\S)\s+(?:1[89]|20)\d\d$') AS name, key FROM titled
)
SELECT count(*) AS names_added
FROM (
    SELECT name FROM yearless WHERE name IS NOT NULL GROUP BY name HAVING count(DISTINCT key) = 1
) y
WHERE NOT EXISTS (SELECT 1 FROM titled t WHERE t.title = y.name);
