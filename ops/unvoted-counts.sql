-- Backfill check of the Besluiten without a vote (read-only): withdrawn, postponed, held and lapsed.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
-- the decisions without a vote, per kind (0 before the backfill but for those of bills)
SELECT lg_str(props -> 'decision_kind') AS decision_kind, count(*) AS decisions
FROM decisions
WHERE lg_str(props -> 'decision_kind') IN (
    'Stemmen - ingetrokken', 'Stemmen - uitstellen', 'Stemmen - aangehouden', 'Stemmen - vervallen'
)
GROUP BY 1
ORDER BY 1;
-- the cases that say whether the Kamer is done with them (Zaak.Afgedaan, written by normalize tk)
SELECT count(*) AS cases_with_done FROM cases WHERE json_typeof(props -> 'done') = 'boolean';
