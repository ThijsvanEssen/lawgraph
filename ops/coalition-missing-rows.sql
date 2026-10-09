-- Read-only: the TK decisions with votes but no row in lg_decision_coalition (8 on 9 Oct), to see why:
-- no cabinet on their date, or no seat of the coalition among the votes.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
SELECT d.key, d.date, lg_str(d.props -> 'decision_kind') AS kind,
       left(lg_str(d.props -> 'subject'), 80) AS subject,
       (SELECT count(*) FROM edges e WHERE e.to_id = d.id AND e.relation = 'VOTED') AS votes,
       (SELECT string_agg(DISTINCT split_part(e.from_id, '/', 1), ',')
          FROM edges e WHERE e.to_id = d.id AND e.relation = 'VOTED') AS voters
FROM decisions d
WHERE 'TK' = ANY(d.labels)
  AND EXISTS (SELECT 1 FROM edges e WHERE e.to_id = d.id AND e.relation = 'VOTED')
  AND NOT EXISTS (SELECT 1 FROM lg_decision_coalition c WHERE c.id = d.id)
ORDER BY d.date
LIMIT 20;
