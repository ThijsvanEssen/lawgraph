-- The members without a role (core/member_role.py: no faction_memberships, government_functions or
-- ek_faction_memberships, no ek) by when they were born and by what the Tweede Kamer's record of the person
-- (raw tk-persoon, Functie) calls them; how many share a birth date and surname with a member who has a role (one
-- person under two records); and those born since 1940 with what the record says. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\set no_role 'WITH no_role AS (SELECT m.key, m.props ->> ''name'' AS name, m.props ->> ''family_name'' AS family_name, m.props ->> ''birth_date'' AS birth_date, m.props ->> ''external_id'' AS external_id FROM members m WHERE NOT ( CASE json_typeof(m.props -> ''faction_memberships'') WHEN ''array'' THEN json_array_length(m.props -> ''faction_memberships'') ELSE 0 END > 0 OR CASE json_typeof(m.props -> ''government_functions'') WHEN ''array'' THEN json_array_length(m.props -> ''government_functions'') ELSE 0 END > 0 OR CASE json_typeof(m.props -> ''ek_faction_memberships'') WHEN ''array'' THEN json_array_length(m.props -> ''ek_faction_memberships'') ELSE 0 END > 0 OR coalesce(json_typeof(m.props -> ''ek''), ''null'') = ''object''))'

\echo '== without a role, by birth'
:no_role
SELECT count(*) AS members,
       count(*) FILTER (WHERE birth_date < '1900') AS before_1900,
       count(*) FILTER (WHERE birth_date >= '1900' AND birth_date < '1940') AS from_1900,
       count(*) FILTER (WHERE birth_date >= '1940') AS from_1940,
       count(*) FILTER (WHERE birth_date IS NULL) AS unknown
FROM no_role;

\echo '== without a role, by the Functie of their record, born since 1940 or not'
:no_role
SELECT r.doc -> 'payload_json' ->> 'Functie' AS functie, count(*) AS members,
       count(*) FILTER (WHERE n.birth_date >= '1940') AS from_1940
FROM no_role n
LEFT JOIN raw_sources r ON r.source = 'tk' AND r.kind = 'tk-persoon' AND r.external_id = n.external_id
GROUP BY 1 ORDER BY 2 DESC;

\echo '== without a role, sharing birth date and surname with a member who has one'
:no_role
SELECT count(DISTINCT n.key) AS members
FROM no_role n
JOIN members o ON o.props ->> 'birth_date' = n.birth_date AND o.props ->> 'family_name' = n.family_name
     AND o.key <> n.key AND o.key NOT IN (SELECT key FROM no_role);

\echo '== born since 1940, newest first (30)'
:no_role
SELECT n.name, n.birth_date, r.doc -> 'payload_json' ->> 'Functie' AS functie,
       EXISTS (SELECT 1 FROM members o WHERE o.props ->> 'birth_date' = n.birth_date
               AND o.props ->> 'family_name' = n.family_name AND o.key <> n.key) AS namesake_born_same_day
FROM no_role n
LEFT JOIN raw_sources r ON r.source = 'tk' AND r.kind = 'tk-persoon' AND r.external_id = n.external_id
WHERE n.birth_date >= '1940'
ORDER BY n.birth_date DESC LIMIT 30;
