-- B193: waarom een HvJ-zaak uit NL (NLD in meta.country) geen ANSWERS-edge heeft (alleen lezen).
-- Leest de props van de HvJ-arresten (ongeveer 1.200) en per verwijsdatum de NL-uitspraken van die dag.
SET default_transaction_read_only = on;
-- 1. Per oorzaak, met het aantal van voor 2000 (oorzaak per zaak: de eerste *A9*-regel van meta.national).
WITH hvj AS (
  SELECT j.id, substr(j.ecli, 1, 40) AS ecli,
         (regexp_match(j.props -> 'meta' ->> 'national', '\*A9\*([^<]*)'))[1] AS a9
  FROM judgments j
  WHERE j.tier = 'hvj_eu' AND j.stub IS NOT TRUE AND 'NLD' = ANY(string_to_array(j.props -> 'meta' ->> 'country', ' '))
    AND NOT EXISTS (SELECT FROM edges e WHERE e.from_id = j.id AND e.relation = 'ANSWERS')
), parsed AS (
  SELECT h.*, regexp_match(a9, '(\d{2})/(\d{2})/(\d{4})') AS d,
         substring(a9 FROM '\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*$') AS nums
  FROM hvj h
), keyed AS (
  SELECT p.*, d[3] || '-' || d[2] || '-' || d[1] AS day,
         (SELECT m[1] FROM regexp_matches(coalesce(nums, ''), '\d+', 'g') m
          ORDER BY length(m[1]) DESC LIMIT 1) AS digits
  FROM parsed p
), classed AS (
  SELECT k.*,
    CASE
      WHEN a9 IS NULL THEN '1 geen *A9* (rechtstreeks beroep, of CELLAR noemt de verwijzer niet)'
      WHEN a9 ~* 'ECLI' THEN '2 *A9* met ECLI, toch geen edge'
      WHEN d IS NULL OR nums IS NULL THEN '3 *A9* zonder datum of zaaknummer'
      WHEN NOT EXISTS (SELECT FROM judgments n WHERE n.date_eff = k.day AND starts_with(n.ecli, 'ECLI:NL:'))
        THEN '4 geen NL-uitspraak van die dag in de graaf'
      WHEN EXISTS (SELECT FROM judgments n WHERE n.date_eff = k.day AND starts_with(n.ecli, 'ECLI:NL:')
                   AND length(k.digits) >= 3
                   AND regexp_replace(array_to_string(n.case_number_keys, ' '), '\D', '', 'g')
                       LIKE '%' || k.digits || '%')
        THEN '5 uitspraak van die dag met hetzelfde nummer (matchen faalt?)'
      ELSE '6 die dag wel uitspraken, geen met dat nummer (niet gepubliceerd of anders genummerd)'
    END AS cause
  FROM keyed k
)
SELECT cause, count(*) AS n, count(*) FILTER (WHERE day < '2000') AS before_2000
FROM classed GROUP BY cause ORDER BY cause;
-- 2. Voorbeelden van oorzaak 2 en 5 (te herstellen?) met de kandidaat van die dag.
WITH hvj AS (
  SELECT j.ecli, (regexp_match(j.props -> 'meta' ->> 'national', '\*A9\*([^<]*)'))[1] AS a9
  FROM judgments j
  WHERE j.tier = 'hvj_eu' AND j.stub IS NOT TRUE AND 'NLD' = ANY(string_to_array(j.props -> 'meta' ->> 'country', ' '))
    AND NOT EXISTS (SELECT FROM edges e WHERE e.from_id = j.id AND e.relation = 'ANSWERS')
), keyed AS (
  SELECT h.*, (SELECT d[3] || '-' || d[2] || '-' || d[1]
               FROM regexp_match(a9, '(\d{2})/(\d{2})/(\d{4})') d) AS day,
         (SELECT m[1] FROM regexp_matches(coalesce(substring(a9 FROM '\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*$'), ''), '\d+', 'g') m
          ORDER BY length(m[1]) DESC LIMIT 1) AS digits
  FROM hvj h
)
SELECT k.ecli, left(k.a9, 160) AS a9, n.ecli AS candidate, n.case_number_keys
FROM keyed k
LEFT JOIN LATERAL (
  SELECT n.ecli, n.case_number_keys FROM judgments n
  WHERE n.date_eff = k.day AND starts_with(n.ecli, 'ECLI:NL:') AND length(k.digits) >= 3
    AND regexp_replace(array_to_string(n.case_number_keys, ' '), '\D', '', 'g') LIKE '%' || k.digits || '%'
  LIMIT 1) n ON true
WHERE k.a9 ~* 'ECLI' OR n.ecli IS NOT NULL
ORDER BY k.ecli
LIMIT 40;
-- 3. Dekking: NL-uitspraken in de graaf per decennium (de verwijzers van voor 2000 ontbreken op rechtspraak.nl grotendeels).
SELECT left(date_eff, 3) || '0' AS decade, count(*) AS nl_judgments
FROM judgments
WHERE starts_with(ecli, 'ECLI:NL:') AND stub IS NOT TRUE AND date_eff < '2000'
GROUP BY 1 ORDER BY 1;
