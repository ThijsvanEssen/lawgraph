-- #378 backfill check (read-only): the amendments a gewijzigd amendement replaces.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
-- REVISES between the amendments of 36496 and 36602 (0 before the backfill)
SELECT f.dossier_number, count(*) AS revises
FROM edges e
JOIN documents f ON f.id = e.from_id
JOIN documents t ON t.id = e.to_id
WHERE e.relation = 'REVISES' AND e.from_collection = 'documents' AND e.to_collection = 'documents'
  AND f.dossier_number IN ('36496', '36602')
  AND starts_with(f.kind, 'Amendement') AND starts_with(t.kind, 'Amendement')
GROUP BY f.dossier_number
ORDER BY f.dossier_number;
-- REVISES of the rule vervanging in all (an amended amendment or motion)
SELECT count(*) AS revises_vervanging
FROM edges
WHERE relation = 'REVISES' AND lg_str(doc -> 'meta' -> 'rule') = 'vervanging';
-- cases that name the cases they replace (Zaak.VervangenVanuit, about 11,600 after)
SELECT count(*) AS cases_with_replaces
FROM cases
WHERE json_typeof(props -> 'replaces_cases') = 'array';
