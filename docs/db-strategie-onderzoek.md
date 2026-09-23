# Databasestrategie bij groei naar 200 GB+

Onderzoek naar hoe LawGraph met zijn database omgaat nu de dataset naar verwachting boven de
grens van de ArangoDB Community-licentie groeit. Datum: 22 september 2026. Er is geen code,
schema of data gewijzigd; de lokale database is alleen gelezen.

Markering in dit document:

- **[code]**: een feit uit de code of documentatie van deze repository.
- **[gemeten]**: gemeten op de lokale database, alleen lezend (`statistics()`, `count()`,
  `GET /_admin/license` en AQL-queries die alleen lezen).
- **[bron]**: gecontroleerd bij de leverancier (link bij het feit).
- **[aanname]**: een schatting of aanname van dit onderzoek.
- **[te verifiëren]**: niet bij de bron te bevestigen.

## 1. Samenvatting

- De omvang hangt af van **wat er geladen wordt** (bronnen, hoe ver terug, ruwe bestanden), niet van gebruikers.
- `raw_sources` (verbatim bron-XML/JSON) is 87 % van de opslag. De API leest die collectie nooit.
- De graph is een **onderdeel, geen kern**: er is één traversal; de rest zijn edge-joins, lookups, filters en ArangoSearch.
- Standaardbouw: ongeveer 14 GiB op schijf, over 3 jaar ongeveer 24 GiB. Met de volledige historie: 66 tot 108 GiB **[aanname]**.
- **Advies: D1.** Zet `raw_sources` in object storage (1 tot 2 weken). De graph-kern blijft dan in elk scenario onder 40 GiB.
- Bouw daarnaast een scheidingslaag, monitoring (alert bij 70 GiB) en geteste backups.
- **Grootste risico is niet de grootte**: de Community-licentie staat alleen "internal business purposes" toe en kan worden ingetrokken.
- Wordt LawGraph een publieke of commerciële dienst, kies dan C (PostgreSQL, 6 tot 10 weken) boven A (Enterprise, prijs onbekend).

## 2. Inventaris

Alle collecties staan in `config/constants.py` en worden aangemaakt door `db/schema.py`
**[code]**. Er zijn geen named graphs, SmartGraphs, Foxx-services of transacties: de graph
bestaat uit 15 node-collecties plus één edge-collectie `edges`, die met een `relation`-veld
18 relatietypen draagt **[code]**. Migraties bestaan niet: `ArangoStore()` maakt bij de start
aan wat ontbreekt **[code]**.

Groottes: **gemeten** op de lokale database van 22-09-2026, een kleine proefbouw (1,2 GB
volume, 3.259 uitspraken, 85.383 edges). "Gecomprimeerd" is `documents_size` uit
`statistics()`, dus de RocksDB-opslag met LZ4. "Ongecomprimeerd" is `LENGTH(TO_STRING(doc))`.
De verhouding tussen die twee is 2,9 tot 3,5 **[gemeten]**.

| Collectie | Type | Rol | Grote velden | Relaties (via `edges`) | Gemeten: aantal / gem. ongecompr. | Klasse (§4) |
|---|---|---|---|---|---|---|
| `raw_sources` | document | verbatim payload per bronrecord; invoer van normalize en semantic | `payload_text` (XML/HTML, gem. 3,2 MB per BWB-toestand, 644 KB per EU-akte, 238 KB per Kamerstuk, 24 KB per uitspraak), `payload_json` | geen | 125.852 / 19 KB; **87 % van de opslag** | **blob** |
| `judgments` | node | uitspraken (Rechtspraak, EHRM) | `text` (gem. 7,8 KB) en `paragraphs` (8,2 KB, dezelfde tekst in alinea's) | `REFERS_TO`, `APPEAL_OF` | 3.259 / 16,8 KB (max 585 KB) | kern + **bulk** (tekst) |
| `documents` | node | Kamerstukken, Staatsblad, Staatscourant, EK | `text` (tot 2 miljoen tekens), `sections`, `footnotes`, `actors` | `PART_OF`, `AUTHORED`, `EXPLAINS`, `AMENDS`/`INTRODUCES`/`REPEALS` (voorgesteld), `REFERS_TO` | 386 / 12,2 KB (max 550 KB) | kern + **bulk** (tekst) |
| `articles` | node | artikel (huidige tekst, historische identiteiten) | `text`, `parts`, `references` | `PART_OF`, `VERSION_OF`, `REFERS_TO`, `BASED_ON`, `SCOPED_BY`, `EXPLAINS` | 4.662 / 1,6 KB | graph-kern |
| `article_versions` | node | gedateerde artikelversies | `text`, `parts` | `VERSION_OF`, `EXPLAINS` | 9.884 / 2,7 KB | graph-kern |
| `instruments` | node | wet, AMvB, regeling, verdrag, EU-akte, publicatie | `basis`, `celex_refs` (klein) | alle wetgevingsrelaties | 1.240 / 0,4 KB | graph-kern |
| `instrument_versions` | node | toestand per datum | geen | `VERSION_OF` | 538 / 0,4 KB | graph-kern |
| `annexes` | node | bijlagen van regelingen | tekst (tot 28 KB) | `PART_OF`, `SCOPED_BY` | 12 / 3,3 KB | graph-kern |
| `dossiers` | node | Kamerdossier | geen | `PART_OF`, `LEGISLATED_IN`, `ABOUT` | 922 / 1,0 KB | graph-kern |
| `cases` | node | TK-Zaak | geen | `PART_OF`, `ABOUT`, `AUTHORED` | 0 | graph-kern |
| `activities` | node | debat, overleg | geen | `ABOUT`, `LED_BY`, `MADE_IN` | 15.082 / 0,9 KB | graph-kern |
| `decisions` | node | TK-Besluit met stemuitslag | `tally`, `voters` | `ABOUT`, `VOTED` | 5 / 1,6 KB | graph-kern |
| `commitments` | node | toezegging | geen | `ABOUT`, `MADE_IN` | 1.228 / 0,7 KB | graph-kern |
| `members`, `factions`, `committees` | node | personen, fracties, commissies | `faction_memberships` | `MEMBER_OF`, `VOTED`, `AUTHORED`, `LED_BY` | 4.476 / 57 / 234, < 0,4 KB | graph-kern |
| `edges` | edge | alle relaties; `meta` met bewijs (snippets, tot 100 vermeldingen) | `meta.mentions`, `meta.sections` | n.v.t. | 85.383 / 0,41 KB (max 19 KB); indexen 2,6× de data | graph-kern |
| `watches` | document | opgeslagen watches (enige gebruikersdata) | geen | verwijst naar node-id | 0 | kern (klein) |
| `pipeline_state` | document | "last complete run" per fase | geen | geen | 2 | kern (klein) |
| `edge_status_log` | document | auditlog; niets schrijft er nu in | geen | verwijst naar edge-key | 0 | bulk (klein) |
| `topics` | document | alleen schema; niets schrijft er in | geen | geen | 0 | vervalt |

**Indexen** **[code]**: ruim 50 persistent indexes, onder meer array-indexen op `labels[*]`
en `props.dossier_numbers[*]`, unieke sparse indexen op `bwb_id`, `celex` en `ecli`, en op
`edges` de combinaties `(_from, relation)`, `(_to, relation)` en `(_from, semantic_type)`.

**ArangoSearch** **[code]**: zes views (`search_articles`, `search_instruments`,
`search_judgments`, `search_dossiers`, `search_documents` en `search_committees`) met de
analyzers `text_en`, `identity`, `lawgraph_norm` (identifier in kleine letters) en
`lawgraph_ngram_v2` (n-grammen van 3 tot 12 tekens, voor deelwoorden: "vordering" vindt
"Strafvordering"). De views indexeren titels, identifiers, de artikeltekst en de samenvatting van
een uitspraak, **niet** de volledige tekst van uitspraken en Kamerstukken.

**Referentiepunt voor de volledige bouw** **[code]** (commit d0823e0, `docs/operations.md`):
de volledige database van 21-09-2026 had 165.000 uitspraken, 2,8 miljoen edges en 937.000
documenten in de zoekviews, met 3,0 GB ArangoSearch-index op schijf. De totale schijfomvang is
toen niet vastgelegd; die database bestaat niet meer.

## 3. Querygebruik

Alle AQL-strings in `src/lawgraph` **[code]**, ingedeeld per categorie. Categorie 3 is gesplitst
in **3a**, een echte traversal (`FOR v, e, p IN 1..n`), en **3b**, een join van één stap over de
edge-collectie (`FOR e IN edges FILTER e._from == x AND e.relation == ...`), eventueel een paar
keer genest. 3b\* is een scan of aggregatie over heel `edges`.

| | 1. CRUD / key | 2. filter / aggregatie | 3a. traversal | 3b. edge-join (waarvan 3b\*) | 4. ArangoSearch | totaal |
|---|---|---|---|---|---|---|
| API (`api/queries/`) | 8 | 28 | **1** | 53 (8) | 7 | 97 |
| Pipelines | 8 | 55 | 0 | 10 | 0 | 73 |
| Commands (`check`, `gaps`, `expand-graph`) | 0 | 7 | 0 | 1 (1) | 1 | 9 |
| `db/` (upserts, `existing_keys`) | 3 | 0 | 0 | 0 | 0 | 3 |

**Kritiek voor de applicatie** (interactief):

- **Zoeken**: `/api/search` en `/api/resolve`. Vijf BM25-queries op de views, n-grammen voor
  deelwoorden. **Categorie 4: kritiek.** Hier zit de meeste ArangoDB-specifieke logica.
- **Artikelpagina, uitspraak, dossier-hub, instrument-tabs, node-detail**: `/api/articles/...`,
  `/api/judgments/{ecli}`, `/api/dossiers/{n}` en `/api/nodes/{c}/{k}`. **Categorie 3b:
  kritiek**, dit is het hart van de API. De diepste query is 4 stappen:
  dossier ← zaak ← document → artikel → instrument (`api/queries/dossiers.py`, `get_dossier_hub`),
  en factie ← lid → document → zaak → dossier (`api/queries/committees.py`, `get_actor_dossiers`).
  Het zijn vaste paden met bekende relaties per stap: joins, geen zoektocht door de graph.
- **Buurtweergave**: `/api/nodes/{c}/{k}/neighborhood`, de enige traversal (diepte 1 tot 4,
  cap 1.000, `PRUNE`, `uniqueVertices: 'global'`, `bfs: true`; `api/queries/nodes.py`).
  **Categorie 3a: belangrijk voor de front-end, maar één query.**
- **Zwaar maar gecachet**: `/api/graph/*`, `/api/nodes/heat` en `/api/nodes/in-flux` (3b\*,
  scans over alle edges met een TTL-cache), en `/api/stats`.
- **Batch**: alle pipelines. Vooral categorie 2 (raw records per `(source, kind)` en
  `fetched_at`, props-joins) en bulk-upserts.

**ArangoDB-specifieke features** die een migratie lastiger maken **[code]**:

| Feature | Waar | Vervanging buiten ArangoDB |
|---|---|---|
| ArangoSearch-views en de analyzers `lawgraph_ngram_v2`, `lawgraph_norm`, `text_en` en `identity`; `SEARCH`, `ANALYZER()`, `TOKENS()`, `BM25` | `db/schema.py`, `api/queries/search.py`, `resolve.py`, `instruments.py`, `judgments.py` | PostgreSQL `pg_trgm` (GIN) en `tsvector`; andere ranking |
| Traversal met `PRUNE`, `OPTIONS` en `p.edges[*] ALL IN` | `api/queries/nodes.py` | `WITH RECURSIVE` met een cycluscheck en `LIMIT` |
| `UPSERT` met `mergeObjects`, `UPDATE ... OPTIONS {keepNull:false}` | `db/store.py`, `relationships.py`, `graph_list_stats.py`, `bwb_relation_types.py`, `normalize/bwb.py` | `INSERT ... ON CONFLICT DO UPDATE`, `jsonb ||` |
| `DOCUMENT()` op ids met de collectienaam erin (ongeveer 90×), `PARSE_IDENTIFIER`, `MERGE` als hashmap, `COLLECTION_COUNT` | overal in `api/queries/` | joins op `(type, key)`; ids splitsen in collectie en key |
| Streaming cursors (`stream=True`) | `db/store.py` | server-side cursors (`psycopg` named cursors) |
| Array-indexen `labels[*]`, `props.dossier_numbers[*]` | `db/schema.py` | GIN op `text[]` of `jsonb` |

**Niet gebruikt** **[code]**: Foxx, transacties, named graphs (`GRAPH`), SmartGraphs,
SatelliteGraphs en `import_bulk`.

**Aandachtspunten voor elke migratie** **[code]**:

- AQL staat niet alleen in `db/`. `api/queries/` (96 aanroepen), `pipelines/` (70) en
  `commands/` (9) bouwen hun eigen f-strings. `api/` gebruikt het driverobject ook direct: de
  watches, `has_collection`, `collection().get` en `.count()`. Dat moet eerst achter een laag (§6).
- Op vier plaatsen heeft een `LET`-variabele dezelfde naam als de collectie waarover de query
  daarna itereert (`dossiers.py`, `instruments.py`, `tk_mvt.py`). Wat AQL dan leest, is niet
  nagegaan **[te verifiëren]**. Een vertaling naar SQL moet hier kiezen wat bedoeld is.
- De artikelpagina haalt de bron van elk citaat los op, met twee round-trips per edge
  (`get_article_citations`). Bij een database op afstand (optie B) wordt dat merkbaar.

**Is de graph de kern?** Nee: **de graph is een onderdeel van het datamodel, niet de kern
van het querygebruik.** Het model is wel een graph (typed nodes, één edge-collectie met 18
relaties, en bewijs in `edges.meta`). Maar op één na alle queries lezen het als een relationeel
model: lookups, filters, en joins over edges met een bekend pad van hooguit 4 stappen. Er is
één traversal van variabele diepte en geen shortest-path of k-paths. De ArangoDB-specifieke
waarde zit meer in **ArangoSearch** (deelwoorden en BM25) dan in de graph-engine.

## 4. Groeiprojectie

### Waardoor groeit de data

| Groeibron | Soort groei | Grootte per eenheid (ongecompr.) |
|---|---|---|
| Keuze van de bouw: `--window` (standaard 730 dagen of `all`), rechtbanken (`--court`, standaard `hr`, `rvs`, `hoven`), `bwb-history`, `tk-content --kind` | **eenmalige sprong**, verreweg de grootste factor | zie hieronder |
| Nieuwe uitspraken | continu: 71.300 gepubliceerd in 2025, alle gerechten ([jaarverslag Rechtspraak 2025](https://www.rechtspraak.nl/organisatie-en-contact/organisatie/raad-voor-de-rechtspraak/nieuws/2026/04/jaarverslag-rechtspraak-15-miljoen-beslissingen-in-2025)) **[bron]** | 24 KB ruw + ongeveer 38 KB node **[gemeten]** + edges |
| Nieuwe Kamerstukken met tekst | continu | 238 KB ruw + ongeveer 180 KB node **[gemeten]** |
| Nieuwe BWB-toestanden | continu; een nieuwe toestand van een grote wet kost MB's | gem. 80 KB (44.000 huidige toestanden = 3,5 GB **[code]**); grote wetten 3,2 MB **[gemeten]** |
| EU-akten via `expand-graph` | groeit met de verwijzingen | 644 KB HTML per akte **[gemeten]** |
| Edges | groeit met uitspraken en documenten | 0,4 tot 0,7 KB, plus ongeveer 2,5× aan indexen **[gemeten]** |
| Gebruikers | te verwaarlozen: alleen `watches` en stemmen | < 1 KB |

Er zijn geen uploads, geen events en geen gebruikershistorie **[code]**. Het aantal gebruikers
heeft dus geen invloed op de omvang.

### Projectie

Twee scenario's, allebei **[aanname]**, opgebouwd uit de gemeten grootte per record maal de
aantallen per bron (in september 2026 bij de bronnen geteld: 148.287 BWB-toestanden,
712.000 TK-documenten, 341.000 zaken en 100.000 activiteiten). "Op schijf" = ongecomprimeerd / 3
(gemeten verhouding), plus indexen.

- **S1, standaardbouw**: `bootstrap` met de standaardinstellingen, zoals de database van
  21-09-2026 (165.000 uitspraken, 2,8 miljoen edges).
- **S2, volledige historie**: `--window all`, alle gerechten, `retrieve bwb-history` en de
  tekst van alle Kamerstukken.

| Deel | S1 nu | S1 +1 jr | S1 +3 jr | S2 nu | S2 +1 jr | S2 +3 jr |
|---|---|---|---|---|---|---|
| `raw_sources`, ongecompr. | 15 GB | 19 GB | 27 GB | 100–130 GB | 105–135 GB | 115–150 GB |
| nodes (vooral tekst), ongecompr. | 10 GB | 13 GB | 19 GB | 50–70 GB | 55–75 GB | 60–85 GB |
| edges, ongecompr. | 1,3 GB | 1,8 GB | 2,8 GB | 6–8 GB | 7–9 GB | 8–11 GB |
| **totaal ongecompr.** | **≈ 26 GB** | **≈ 34 GB** | **≈ 49 GB** | **≈ 155–210 GB** | **≈ 165–220 GB** | **≈ 185–245 GB** |
| op schijf: data (÷ 3) | 9 GiB | 11 GiB | 16 GiB | 52–70 GiB | 55–73 GiB | 62–82 GiB |
| op schijf: persistent indexes | 2 GiB | 2,5 GiB | 3,5 GiB | 8–12 GiB | 9–13 GiB | 10–15 GiB |
| op schijf: ArangoSearch | 3 GiB | 3,5 GiB | 4,5 GiB | 6–9 GiB | 7–10 GiB | 8–11 GiB |
| **totaal op schijf** | **≈ 14 GiB** | **≈ 17 GiB** | **≈ 24 GiB** | **≈ 66–91 GiB** | **≈ 71–96 GiB** | **≈ 80–108 GiB** |
| waarvan `raw_sources` | ≈ 5 GiB | ≈ 6 GiB | ≈ 9 GiB | ≈ 33–43 GiB | ≈ 35–45 GiB | ≈ 38–50 GiB |

Aannames bij de tabel:

- Groei per jaar, S1: ongeveer 30.000 uitspraken van de standaardgerechten, 5.000 Kamerstukken
  met tekst, 8.000 BWB-toestanden, 1,5 miljoen edges en de Staatscourant. Samen ongeveer
  8 GB ongecomprimeerd per jaar **[aanname]**.
- S2: 800.000 tot 1 miljoen uitspraken in het archief van Rechtspraak **[te verifiëren]**,
  100.000 tot 150.000 Kamerstukken met XML **[te verifiëren]**, en de BWB-historie op
  10 tot 40 GB, omdat grote wetten veel en grote toestanden hebben **[aanname]**.
- De compressieverhouding van 3 is gemeten op een steekproef met veel XML. Bij meer
  platte tekst kan die lager uitvallen **[aanname]**.

Twee conclusies zijn robuust, ook als de getallen een factor 1,5 afwijken:

1. **De "200 GB" komt alleen in beeld bij S2, en dan als ongecomprimeerde omvang.** Op schijf,
   dus in de maat die de licentie waarschijnlijk telt (zie hieronder), ligt ook S2 rond de
   70 tot 110 GiB.
2. **Zonder `raw_sources` en zonder de volledige teksten blijft de graph-kern in elk scenario
   ruim onder 70 GiB** (§4).

### Wat de licentie meet

`GET /_admin/license` gaf lokaal `bytesUsed` = 789.789.772 (0,74 GiB) bij een Docker-volume van
1,2 GB en een som van `documents_size` van 0,85 GiB **[gemeten]**. `bytesUsed` volgt dus
ongeveer de gecomprimeerde documentopslag, niet de ongecomprimeerde JSON en niet het hele
volume. Hoe de meting precies werkt, staat niet in de documentatie **[te verifiëren]**.

### Wat ontbreekt

- De schijfomvang van de volledige bouw van 21-09-2026 is niet vastgelegd. Na de eerste bouw op
  de server: `bytesUsed` en `statistics()` per collectie noteren. Daarmee wordt de tabel
  hierboven van schatting tot meting.
- Welke bouw (S1, S2 of iets ertussen) de product-owner wil (§8).
- Het werkelijke aantal uitspraken en Kamerstukken per jaar dat de gekozen filters opleveren.

### Classificatie voor optie D

| Klasse | Collecties en velden | Waarom |
|---|---|---|
| **graph-kern** | alle nodes zonder hun grote tekstvelden, `edges`, `watches`, `pipeline_state` | nodig voor traversals, edge-joins en ArangoSearch; hoort bij de edges |
| **bulk** | `judgments.props.text` en `.paragraphs`, `documents.props.text`, `.sections` en `.footnotes`, `edge_status_log` | groot, en de API leest ze alleen per node op key (`GET /api/judgments/{key}`, `GET /api/documents/{key}`); niet in de zoekviews |
| **blob** | `raw_sources` (alle payloads) | verbatim bronbestanden; alleen pipelines lezen ze, sequentieel per `(source, kind)` en `fetched_at` |

Artikelteksten (`articles.props.text`, `article_versions.props.text`) blijven in de kern: ze zijn
klein (gemiddeld 0,6 tot 1,5 KB), de zoekview `search_articles` indexeert ze, en de semantic
pipelines scannen ze.

Omvang van de graph-kern op schijf **[aanname]**, zelfde rekenwijze als §4:

| | S1 +3 jr | S2 nu | S2 +3 jr |
|---|---|---|---|
| kern-data | 4 GiB | 8–11 GiB | 10–14 GiB |
| persistent indexes | 3,5 GiB | 8–12 GiB | 10–15 GiB |
| ArangoSearch | 4,5 GiB | 6–9 GiB | 8–11 GiB |
| **graph-kern totaal** | **≈ 12 GiB** | **≈ 22–32 GiB** | **≈ 28–40 GiB** |

**De graph-kern blijft in elk scenario onder het doel van 70 GiB**, met een marge van minstens
30 GiB. Alleen `raw_sources` verplaatsen is al genoeg voor S1 en haalt S2 onder de ongeveer
40 tot 60 GiB. Daarbij blijven de teksten in ArangoDB: de kleinste ingreep.

## 5. Evaluatie opties A–D (en E)

Scores van 1 (slecht) tot 5 (goed), bij de huidige omvang en een groei naar S2.

| Criterium | A. Enterprise | B. Managed Arango | C. PostgreSQL | D. Hybride (raw naar object storage) | E. Zelf bouwen uit BUSL-broncode |
|---|---|---|---|---|---|
| Licentie | 5 | 5 | 5 | 2–4 ¹ | 2 ² |
| Migratie-inspanning | 5 (geen) | 3 | 1 | 4 | 3 |
| Performance van kritieke queries | 5 | 3 (netwerk) | 4 | 5 | 5 |
| Operationeel beheer | 4 | 5 | 4 | 3 | 2 |
| Kosten | 1–2 ³ | 2 ³ | 5 | 5 | 4 |
| Lock-in en risico | 2 | 1 | 5 | 2 | 2 |
| Complexiteit | 5 | 4 | 4 | 3 | 3 |

¹ D lost het grootteprobleem op, niet de beperking tot "internal business purposes" (§1, punt 5).
Dat is 4 als intern gebruik de bedoeling is, 2 als het een publieke dienst wordt.
² Juridisch onzeker, zie E.
³ Prijs niet gepubliceerd, alleen op aanvraag **[bron]**.

### A. ArangoDB Enterprise

- **Licentie** **[bron]**: Enterprise heft de 100 GiB-grens en het verbod op commercieel gebruik
  op. Sinds 3.12.5 heeft Community dezelfde code en functies als Enterprise
  ([features](https://docs.arango.ai/arangodb/stable/features/)); het verschil is alleen nog
  de licentie. De lokale server meldt `license: enterprise` in `version(details=True)` bij status
  `good` **[gemeten]**.
- **Migratie**: geen. Er verandert alleen een licentiesleutel.
- **Performance en beheer**: gelijk aan nu. Enterprise voegt hot backup toe
  (`arangobackup`, restore in minuten); welke licentievorm dat ontsluit, is **[te verifiëren]**.
- **Kosten**: prijs op aanvraag ([pricing](https://arango.ai/pricing/)) **[bron]**. De hoogte is
  **[te verifiëren]** en een open vraag voor het budget.
- **Lock-in**: groot. De leverancier bepaalt prijs en voorwaarden jaarlijks en heeft de licentie
  in 2024 al eenzijdig gewijzigd.
- **Geraakt in de code**: niets.

### B. Managed ArangoDB (Arango Managed Platform)

- **Licentie**: in de dienst inbegrepen.
- **Regio's**: AWS en GCP **[bron]**; of er een EU-regio (Frankfurt of Amsterdam) is, en tegen
  welke prijs, is **[te verifiëren]**. Vanaf LeafCloud (Amsterdam) komt er bij elke query een
  round-trip bij van naar schatting 5 tot 15 ms **[aanname]**. De API doet per request 1 tot
  ongeveer 10 queries (de dossier-hub het meest), de pipelines duizenden bulkschrijfacties per
  run. Beide worden trager, en er komt egress bij.
- **Kosten**: "vanaf $0,20 per uur" per node **[bron]**. Voor 100 GiB of meer met genoeg
  geheugen voor ArangoSearch is dat eerder honderden dollars per maand **[aanname]**.
- **Voordeel**: backups, upgrades en monitoring vallen onder de leverancier.
- **Risico**: de meeste lock-in van alle opties, persoonsgegevens (Kamerleden, zaakpartijen in
  uitspraken) buiten de eigen VPS, en een verwerkersovereenkomst nodig (AVG).
- **Geraakt in de code**: `config/settings.py` (URL en TLS), `docker-compose.yml`, de
  retry-logica in `db/store.py` (meer netwerkfouten).

### C. Migratie naar PostgreSQL

- **Licentie**: PostgreSQL License (vrij, geen grens). Apache AGE ondersteunt PostgreSQL tot en
  met 18 ([AGE](https://github.com/apache/age), [PG17/18-discussie](https://github.com/apache/age/discussions/2305))
  **[bron]**, maar is niet nodig: zie hieronder.
- **Past het model?** Ja, goed. Elke node-collectie heeft één type en een strikt Pydantic-schema
  (`core/props.py`) **[code]**. Dat wordt één tabel per type met vaste kolommen voor wat er
  gefilterd en gesorteerd wordt, plus `props jsonb`. `edges` wordt één tabel met
  `(from_id, relation, to_id)` als unieke sleutel en B-tree-indexen op `(from_id, relation)` en
  `(to_id, relation)`. De één-staps-edge-joins worden gewone SQL-joins. De enige traversal
  (buurt tot diepte 4 met cap en `PRUNE`) wordt een `WITH RECURSIVE`-query met `LIMIT`.
  Apache AGE voegt dan alleen een tweede querytaal toe.
- **Zoeken**: `lawgraph_ngram_v2` (deelwoorden) wordt `pg_trgm` met een GIN-index,
  `text_en` wordt `tsvector` met een Nederlandse of Engelse configuratie, en de identifiers
  worden `lower()`-indexen. De rangschikking verschilt en de zoektests moeten opnieuw worden
  afgesteld.
- **Upserts**: `UPSERT ... props merge` wordt `INSERT ... ON CONFLICT DO UPDATE SET props =
  t.props || EXCLUDED.props`. De shallow merge is gelijk; `labels` (union) wordt een array met
  een expliciete union.
- **Inspanning** **[aanname]**: ongeveer 170 AQL-querystrings (§3) herschrijven, de schemalaag,
  `db/store.py`, `db/nodes.py`, `db/edges.py` en `db/raw.py`, de fake store en de
  integratietests (die een echte ArangoDB verwachten). Bij één ontwikkelaar die de code kent:
  **6 tot 10 weken**, plus een volledige herbouw van de data vanuit de bronnen. Datamigratie is
  niet nodig: alles wordt opnieuw opgehaald.
- **Performance**: vergelijkbaar of beter voor filteren, aggregeren en joins; de lijstendpoints
  zijn nu al op indexen gebouwd. Traversals tot diepte 4 met cap 1.000 zijn met een recursieve
  CTE prima te doen. Full-text met trigrammen over 1 miljoen documenten gaat goed met GIN.
  **[aanname]**, na te meten met de bestaande integratietests.
- **Beheer**: het beste van alle opties. `pg_dump` en `pgBackRest` of WAL-archivering naar
  object storage (point-in-time restore), breed bekende monitoring, en upgrades via
  `pg_upgrade`.
- **Geraakt in de code**: `db/*` (volledig), `api/queries/*` (volledig), alle pipelines met
  een eigen AQL-string (§3), `commands/check.py`, `commands/gaps.py`,
  `pipelines/retrieve/_gaps.py`, `tests/integration/*`, `tests/test_aql_validity.py`,
  `docker-compose*.yml` en `docs/data-model.md`, `docs/architecture.md` en
  `docs/operations.md`.

### D. Hybride: graph-kern in ArangoDB, bulk en blob erbuiten

Twee stappen, elk los bruikbaar:

1. **D1, alleen `raw_sources` naar object storage** (LeafCloud S3-compatible, €0,024 per GB per
   maand, [pricing](https://www.leaf.cloud/pricing) **[bron]**). Eén object per record,
   gecomprimeerd (gzip of zstd), met als sleutel `<source>/<kind>/<raw_key>`. Een kleine
   index-collectie of -tabel (`raw_index`: key, source, kind, external_id, fetched_at, meta,
   object-sleutel) blijft in ArangoDB, zodat `--since`, de gap-queries en `lawgraph check` blijven
   werken. Van S2 +3 jaar (80 tot 108 GiB) gaat dan 38 tot 50 GiB af.
2. **D2, ook de lange teksten erbuiten** (`judgments.text`/`paragraphs`, `documents.text`/`sections`),
   in object storage of PostgreSQL, en per node op key te halen. Alleen nodig bij S2 en als D1
   niet genoeg blijkt; kost een extra fetch per detailpagina.

- **Licentie**: lost de grootte op, niet de vraag van "internal business purposes".
- **Inspanning** **[aanname]**: D1 1 tot 2 weken. `RawSourceWriter` (`db/raw.py`),
  `_iter_raw_sources` (`pipelines/normalize/base.py`), `RawRecords` (`core/raw_records.py`),
  het lezen van ruwe XML in `pipelines/semantic/base.py`, `bwb.py`, `eurlex.py` en `tk.py`, de
  raw-queries in `pipelines/retrieve/base.py`, `bwb.py`, `staatsblad.py` en `_gaps.py`,
  `pipelines/normalize/tk_dossiers.py`, `commands/check.py`, `commands/expand_graph.py`,
  een fake object store voor de unit tests, en MinIO in `docker-compose.test.yml` voor de
  integratietests. D2 nog eens 1 tot 2 weken.
- **Performance**: API ongewijzigd bij D1 (de API leest `raw_sources` nooit **[code]**).
  Pipelines lezen dan over HTTP uit object storage. Streamen in batches van 20 blijft mogelijk,
  maar vraagt parallel ophalen om niet trager te worden.
- **Complexiteit**: twee opslagplekken zonder gezamenlijke transactie. Dat is hier
  onproblematisch: een ruw record is onveranderlijk, wordt eerst als object geschreven en daarna
  in de index gezet, en een wees-object is onschadelijk.
- **Geraakt in de code**: zie inspanning. `api/` alleen bij D2 (`routes/judgments.py`,
  `routes/documents.py`).

### E. Zelf bouwen uit de broncode (BUSL-1.1)

Deze optie stond niet in de opdracht, maar hoort erbij. De broncode valt onder BUSL-1.1 met
een Additional Use Grant: intern productiegebruik mag, zolang het geen commercieel aanbod is
waarmee derden databases met hun eigen data benaderen of beheren
([LICENSE](https://github.com/arangodb/arangodb/blob/devel/LICENSE)) **[bron]**. De grens van
100 GiB staat in de Community-licentie van de voorgebouwde binaries, niet in de BUSL **[bron]**.
Na vier jaar gaat de code over naar Apache 2.0; de 3.12-reeks heeft als releasedatum maart 2024
**[bron]**.

- Onzeker: of de grensbewaking ook in een eigen build zit en of een eigen build die mag
  omzeilen **[te verifiëren]**, en of een publieke dienst onder "internally in production" valt
  (juridisch advies nodig).
- Zelf C++ bouwen, patchen en upgraden van een database is voor een eenmansproject een zware
  beheerlast.
- Daarom **niet aanbevolen** als hoofdroute. Wel een terugvaloptie als D1 en C allebei niet
  uitkomen.

## 6. Aanbeveling

**Nu: D1 (`raw_sources` naar object storage) plus de maatregelen hieronder, op ArangoDB
Community, mits het antwoord op de licentievraag in §8 dat toelaat.**

Waarom:

- Het haalt het grootste en snelst groeiende deel (ongeveer de helft, bij S2 38 tot 50 GiB) uit
  de database. Daarmee blijft de graph-kern ook bij een volledige bouw en drie jaar groei onder
  70 GiB (§4).
- Het is de kleinste ingreep (1 tot 2 weken). De API verandert niet, want die leest geen ruwe
  data.
- Object storage is voor verbatim bronbestanden ook inhoudelijk de juiste plek: onveranderlijk,
  goedkoop (€0,024 per GB per maand tegen €0,096 voor blockstorage **[bron]**) en los te back-uppen.
- Het houdt alle opties open. D1 is ook nuttig als later C of A wordt gekozen.

**Zodra LawGraph publiek of commercieel wordt aangeboden, of de licentievraag "nee" oplevert:
C (PostgreSQL).** Dat gaat voor A omdat:

- de graph hier een onderdeel is en geen kern: één traversal, en verder joins die SQL even goed
  doet (§3);
- er geen datamigratie nodig is, want alles wordt opnieuw uit de bronnen opgebouwd;
- het de licentie- en leveranciersrisico's voorgoed wegneemt, tegen een eenmalige inspanning
  van 6 tot 10 weken in plaats van een jaarlijkse licentie van onbekende hoogte;
- de scheidingslaag (hieronder) dat werk vooraf kleiner maakt.

A is te verkiezen boven C als de licentieprijs laag uitvalt en er geen tijd is voor een migratie.

Afgevallen:

- **B (Managed)**: de meeste lock-in, extra netwerklatentie voor de API en de bulk-pipelines,
  persoonsgegevens buiten de eigen omgeving, en prijs op aanvraag. De beheerwinst weegt daar
  bij deze omvang (één server, tientallen GiB) niet tegen op.
- **D2 nu**: niet nodig bij S1, en bij S2 waarschijnlijk ook niet na D1. Kost een extra fetch
  per detailpagina. Pas doen als de meting na de serverbouw erom vraagt.
- **E**: juridisch en operationeel te onzeker (§5).

### Architectuuradvies, ongeacht de keuze

#### Scheidingslaag voor data-access

Nu is `python-arango` al afgeschermd: alleen `db/store.py`, `db/schema.py` en
`api/queries/watches.py` importeren de driver **[code]**. De **querytaal** is dat niet: ongeveer
96 AQL-aanroepen staan in `api/queries/` en ongeveer 80 in `pipelines/` en `commands/`, als
f-strings die aan `store.query(...)` worden meegegeven **[code]**. Daarnaast geeft
`ArangoStore.collection(name)` het ruwe driverobject vrij.

Voorstel:

1. Een `Protocol` per domein in `db/` (bijvoorbeeld `ArticleRepository`, `EdgeRepository`,
   `SearchRepository`, `RawStore`) met methoden in domeintermen:
   `neighbours(node_id, depth, filters, cap)`, `citing_judgments(article_id, page)`,
   `search(tokens, kinds, limit)`. De huidige functies in `api/queries/` zijn al bijna zulke
   methoden en kunnen per module verhuizen.
2. De AQL komt in `db/arango/` en een eventuele PostgreSQL-implementatie later in `db/postgres/`.
   De routes en pipelines krijgen een repository via `Depends` of de constructor, in plaats van
   `ArangoStore`.
3. Een conventietest zoals die al bestaan (`tests/test_conventions.py`): geen AQL-sleutelwoorden
   (`FOR ... IN`, `FILTER`, `RETURN`) in strings buiten `db/`, en geen `store.collection(` buiten
   `db/`.
4. `RawStore` los van de graph-store: dat is ook de naad voor D1.

Dit is fase 4 van de roadmap en past bij de bestaande regel dat `api/` en `pipelines/` elkaar
niet importeren.

#### Monitoring van de datagrootte

Zolang ArangoDB Community draait:

- Een dagelijkse controle, als stap in `scripts/daily.sh` of als `lawgraph check`-onderdeel dat
  alleen leest, van `GET /_admin/license` → `diskUsage.bytesUsed`, `status` en
  `secondsUntilReadOnly`. Ook `statistics()` per collectie, geschreven naar het runs-log.
- Alert (mail, of een exit-code die de scheduler meldt) bij **70 GiB**, en direct bij `status`
  ≠ `good`. Tussen de eerste waarschuwing en het stoppen van de server zitten maar vier dagen
  **[bron]**, en een load kan in één nacht tientallen GiB toevoegen.
- Ook de vrije schijfruimte van het volume bewaken. RocksDB-compactie vraagt tijdelijk extra
  ruimte, reken op 1,5 tot 2 keer de data **[aanname]**.
- Het API-endpoint `GET /api/stats` kan `bytesUsed` meegeven, zodat het in de front-end
  zichtbaar is.

#### Backupstrategie

De data is grotendeels opnieuw op te bouwen uit publieke bronnen **[code]**. Wat niet
opnieuw op te bouwen is: `watches`, curatie en stemmen op edges (`semantic_source` `expert` en
`community`, `explanation`, `community_upvotes`/`downvotes`), en `pipeline_state`. De RPO geldt
dus vooral voor die kleine set. Een herbouw duurt uren tot dagen, zodat een backup vooral de
RTO bewaakt.

| Wat | Hoe | Frequentie | Verwachte restore **[aanname]** |
|---|---|---|---|
| Curatie en gebruikersdata | `arangoexport` van `watches` plus de edges met `semantic_source IN ["expert", "community"]`, naar object storage | elk uur of dagelijks, afhankelijk van de RPO | minuten |
| Hele database (S1, ≈ 15–25 GiB) | `arangodump --compress-output` naar object storage | dagelijks | `arangorestore` van ongeveer 20 GiB met het herbouwen van indexen en views: 1 tot 3 uur |
| Hele database (S2, ≈ 70–110 GiB, of na D1 30–60 GiB) | `arangodump` wekelijks plus dagelijkse volumesnapshot van LeafCloud (€0,096 per GB per maand **[bron]**), met ArangoDB even gestopt of met `arangobackup` als de licentie dat toelaat **[te verifiëren]** | snapshot dagelijks, dump wekelijks | snapshot: minuten tot een uur; dump: 4 tot 10 uur (ArangoSearch-views bouwen opnieuw op) |
| `raw_sources` na D1 | versioning of replicatie van de bucket; objecten zijn onveranderlijk | continu | n.v.t. (lezen blijft werken) |
| Na een C-migratie | `pgBackRest` met WAL-archivering naar object storage | continu (point-in-time) | vergelijkbaar met de dump, met PITR tot op de seconde |

Elke backupvorm krijgt een **periodieke restore-test** op een tweede, kleine server (vergelijk
`docker-compose.test.yml`), met de gemeten duur in het log. Pas dan is de RTO een meting in
plaats van een aanname.

## 7. Migratie-roadmap

| Fase | Wat | Inspanning **[aanname]** | Risico |
|---|---|---|---|
| 0 | Open vragen van §8 beantwoorden: licentie (intern of publiek), bouwkeuze S1/S2, RPO/RTO, budget | – | een verkeerde aanname over "internal business purposes" maakt alle volgende fasen tot een tussenstap |
| 1 | Monitoring van `bytesUsed` met alert op 70 GiB; backupscript met restore-test (§6) | 1–2 dagen | geen |
| 2 | Eerste bouw op de server; `bytesUsed` en `statistics()` per collectie vastleggen en de projectie van §4 bijstellen | de bouw zelf (uren tot dagen) | S2 raakt zonder D1 de 70 GiB-grens mogelijk al bij de bouw: dan eerst fase 3 |
| 3 | D1: `raw_sources` naar object storage, met index-collectie; integratietest met MinIO | 1–2 weken | pipelines trager als het lezen niet parallel gebeurt; afvangen met de bestaande integratietests op schaal |
| 4 | Scheidingslaag: queries achter functies per domein in `db/`, geen AQL buiten `db/` (§6) | 2–3 weken, kan geleidelijk | geen functionele wijziging; de bestaande tests dekken het af |
| 5 (als nodig) | C: PostgreSQL-implementatie van dezelfde laag, schema per type, `pg_trgm` en `tsvector`, integratietests tegen PostgreSQL, volledige herbouw, de API parallel draaien en vergelijken, overschakelen | 6–10 weken (minder na fase 4) | andere volgorde van zoekresultaten; upsert- en merge-semantiek precies nabouwen (tests bestaan) |
| 5-alt | A: Enterprise-licentie afsluiten | dagen (inkoop) | jaarlijkse prijs- en voorwaardenwijziging |

## 8. Open vragen voor de product-owner

1. **Gebruik**: wordt LawGraph een dienst die derden (publiek, klanten, andere organisaties)
   gebruiken, en is er een verdienmodel? De Community-licentie staat alleen "internal business
   purposes" toe en is door Arango op elk moment op te zeggen **[bron]**. Dit bepaalt of A of C
   nodig is, los van de grootte. Laat het bij twijfel juridisch toetsen.
2. **Bouwkeuze**: welke omvang is het doel: S1 (twee jaar, drie rechterlijke niveaus, alleen
   memories van toelichting) of S2 (volledige historie, alle gerechten, alle Kamerstuk-teksten),
   of iets ertussen? Bij S1 is het grootteprobleem de komende jaren afwezig.
3. **Waar komt "200 GB+" vandaan?** Is dat ongecomprimeerd, op schijf, of inclusief backups en
   ruwe bestanden? Op schijf is ongeveer een derde van ongecomprimeerd **[gemeten]**.
4. **RPO**: hoeveel curatie- en gebruikersdata (watches, stemmen, expertlabels) mag verloren
   gaan: een uur, een dag?
5. **RTO**: hoe lang mag de API onbereikbaar zijn na een verloren server: uren (restore) of
   dagen (herbouw uit de bronnen)?
6. **Budget**: wat mag de database per maand of per jaar kosten? Is er ruimte voor een
   Enterprise-offerte, of juist voor 6 tot 10 weken migratiewerk?
7. **Persoonsgegevens**: mogen gegevens van Kamerleden en uit uitspraken bij een Amerikaanse
   cloudprovider staan (optie B)?
8. **Tijdlijn**: wanneer is de eerste bouw op de server gepland? Monitoring en backups (fase 1)
   moeten daarvoor klaar zijn.

## Bronnen

- [ArangoDB 3.12, incompatible changes (licentie)](https://docs.arango.ai/arangodb/stable/release-notes/version-3.12/incompatible-changes-in-3-12/)
- [ArangoDB Community License Agreement (PDF)](https://arango.ai/wp-content/uploads/2025/11/ADB-Community-License_31OCT2023.pdf)
- [ArangoDB features (3.12.5: Community gelijk aan Enterprise; grensbewaking)](https://docs.arango.ai/arangodb/stable/features/)
- [ArangoDB BUSL-1.1 LICENSE](https://github.com/arangodb/arangodb/blob/devel/LICENSE)
- [Arango: licentiemodel (blog)](https://arango.ai/blog/evolving-arangodbs-licensing-model-for-a-sustainable-future/)
- [Arango pricing](https://arango.ai/pricing/)
- [LeafCloud pricing](https://www.leaf.cloud/pricing)
- [Apache AGE](https://github.com/apache/age), [PG17/PG18-ondersteuning](https://github.com/apache/age/discussions/2305)
- [Jaarverslag Rechtspraak 2025](https://www.rechtspraak.nl/organisatie-en-contact/organisatie/raad-voor-de-rechtspraak/nieuws/2026/04/jaarverslag-rechtspraak-15-miljoen-beslissingen-in-2025)
