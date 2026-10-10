-- Why an abbreviation the judgments cite resolves to no law (WWB, WW, TW, Wmo, Zvw, PW, ...): which instruments claim
-- it, and how. Read only. The WTI of BWBR0015703 lists Pw and Wwb, that of BWBR0004045 WW; the article linker takes an
-- abbreviation as a law's only when one law claims it (core/aliases.code_aliases: by short title first, then by the
-- WTI aliases, then the curated ones), so a second claimant leaves it to none.
--
-- 1. per abbreviation: every instrument whose short title or WTI aliases hold it (any case), with its title, kind,
--    date of entry into force and whether it is a stub. (How often the judgments cite each: section 5 of
--    loose-judgments-counts.sql.)
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\set wanted '''{WWB,WW,TW,WMO,ZVW,PW,WAO,WIA,ZW,AOW,ANW,WAJONG,IOAW,IOAZ,BBZ,WSW}'''

\echo '== 1. the instruments that claim each abbreviation'
SELECT upper(a.name) AS abbreviation, a.how, i.bwb_id, i.props ->> 'kind' AS kind,
       left(coalesce(i.props ->> 'citation_title', i.props ->> 'title'), 70) AS title,
       i.props ->> 'date_in_force' AS in_force, coalesce((i.props ->> 'stub')::boolean, false) AS stub
FROM instruments i
CROSS JOIN LATERAL (
    SELECT i.props ->> 'short_title' AS name, 'short title' AS how
    UNION ALL
    SELECT value, 'WTI alias' FROM json_array_elements_text(
        CASE WHEN json_typeof(i.props -> 'aliases') = 'array' THEN i.props -> 'aliases' ELSE '[]'::json END)
) a
WHERE i.bwb_id IS NOT NULL AND upper(a.name) = ANY(:wanted::text[])
ORDER BY 1, 3;
