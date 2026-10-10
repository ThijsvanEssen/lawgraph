-- The members of a Persoon record, those with a date of birth and a date of death, before and after, beside the stored
-- records that give a date of death. Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== members, with a date of birth, with a date of death; records with a date of death'
SELECT count(*) AS members,
       count(*) FILTER (WHERE m.props ->> 'birth_date' IS NOT NULL) AS with_birth,
       count(*) FILTER (WHERE m.props ->> 'death_date' IS NOT NULL) AS with_death,
       (SELECT count(*) FROM raw_sources r WHERE r.source = 'tk' AND r.kind = 'tk-persoon'
          AND r.doc -> 'payload_json' ->> 'Overlijdensdatum' IS NOT NULL) AS records_with_death
FROM members m
WHERE m.props ->> 'external_id' IS NOT NULL AND 'TK' = ANY(m.labels);
