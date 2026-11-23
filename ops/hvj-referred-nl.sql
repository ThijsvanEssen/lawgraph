-- B184a: prejudiciele zaken uit NL op prod (alleen lezen). Voor review door de orchestrator.
-- 1. Wat GET /api/judgments?tier=hvj_eu&referred_by=NL telt (zonder stubs en vervangen publicaties).
SET default_transaction_read_only = on;
SELECT count(*) AS referred_by_nl
FROM judgments j
WHERE j.tier = 'hvj_eu' AND j.stub IS NOT TRUE AND j.same_as IS NULL
  AND EXISTS (SELECT FROM edges e JOIN judgments r ON r.id = e.to_id
              WHERE e.from_id = j.id AND e.relation = 'ANSWERS'
                AND e.to_collection = 'judgments' AND starts_with(r.ecli, 'ECLI:NL:'));
-- 2. Het gat: HvJ-zaken die CELLAR als verwezen uit NL kent (meta.country), met en zonder edge.
--    Leest de props (detoast) van de HvJ-arresten: eenmalig, buiten de piek.
SELECT count(*) AS cellar_nld,
       count(*) FILTER (WHERE EXISTS (SELECT FROM edges e WHERE e.from_id = j.id
                                      AND e.relation = 'ANSWERS')) AS with_edge
FROM judgments j
WHERE j.tier = 'hvj_eu' AND j.stub IS NOT TRUE AND j.props -> 'meta' ->> 'country' = 'NLD';
-- 3. Uitspraken die meer dan één beslissing beantwoorden (de lijst toont de eerste op datum).
SELECT count(*) AS several FROM (
  SELECT e.from_id FROM edges e JOIN judgments j ON j.id = e.from_id
  WHERE e.relation = 'ANSWERS' AND e.to_collection = 'judgments' AND j.tier = 'hvj_eu'
  GROUP BY e.from_id HAVING count(*) > 1) s;
