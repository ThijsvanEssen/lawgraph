# Data Pipelines

## 1. Pipeline architecture

Every source follows the same three-phase pattern: **Retrieve → Normalize → Semantic**.

### Phase 1: Retrieve

- External sources are fetched via HTTP clients in `src/lawgraph/clients/`
- Raw records stored idempotently in `raw_sources`, keyed by `SHA-1(source:kind:external_id)`
- Each source has a retrieve pipeline in `pipelines/retrieve/`

### Phase 2: Normalize

- Raw records queried from `raw_sources`, filtered by `source + kind + (fetched_at >= since)`
- Transformed into typed `Node` objects with deterministic keys
- Upserted into target collections via `store.insert_or_update()`
- Edges built with deterministic SHA-1 keys (idempotent)

### Phase 3: Semantic

- Citation and relation detection on normalized text fields
- Produces edges with confidence scores
- See `design-semantic-pipelines.md` for full detail

### Base classes

**`RetrievePipelineBase`** (`pipelines/retrieve/base.py`): `run() -> PipelineResult`. Subclasses implement `fetch() -> Sequence[RetrieveRecord]`.

**Normalize pipelines** (`pipelines/normalize/`): three steps — `fetch_raw()` → `normalize_nodes()` → `build_edges()`. The `_query_raw_sources(source, kinds, since)` helper filters `raw_sources` by source, kind, and optional `fetched_at >= since`. The `(source, kind)` compound index makes this fast even on large datasets.

### Pipeline factory

`pipelines/factory.py` provides `make_pipeline_cli(pipeline_cls, ...)` which generates a `main(argv)` function for any pipeline class. It handles argument parsing (`--since`, `--since-days`), `ArangoStore` construction, `run()` invocation, error logging, and `sys.exit(1)` on failures.

### Source registry

`sources/registry.py` contains `SourceDescriptor` entries for all sources. Each descriptor declares retrieve, normalize, and semantic entry points. The orchestrators in `pipelines/orchestration.py` iterate this registry to build their step lists automatically.

---

## 2. Retrieve pipelines

### TK Parliamentary Dossiers — `TkDossiersRetrievePipeline`

**File:** `pipelines/retrieve/tk_dossiers.py`

| Entity | Kind | Incremental |
|--------|------|-------------|
| Kamerstukdossier | `tk-dossier` | yes |
| Activiteit | `tk-activiteit` | yes |
| Stemming | `tk-stemming` | yes |
| Toezegging | `tk-toezegging` | yes |
| Commissie | `tk-commissie` | no — always full-refresh |
| Persoon | `tk-persoon` | no — always full-refresh |
| Document (Kamerstuk) | `tk-document` | yes; defaults to `--documents-since` when provided |

CLI flags: `--since DATE`, `--skip-personen`, `--skip-stemmingen`, `--stemmingen-since DATE`, `--skip-documents`, `--documents-since DATE`.

Pagination: skip-based (`$skip=0, 250, 500...`). End-of-page detected when `len(page) < page_size`.

### TK Procedures and Publications — `TKRetrievePipeline`

**File:** `pipelines/retrieve/tk.py`

Fetches Zaak (`tk-zaak`) and DocumentVersie (`tk-documentversie`) via nextLink-based pagination. Accepts `--mode full|incremental` and `--since-days N`.

### TK Text Hydration — `TKTextHydratePipeline`

**File:** `pipelines/retrieve/tk_content.py`

Reads the `publications` collection, fetches PDF binary from TK API for publications where `props.text` is null, extracts plain text via pdfminer, and stores the result back via AQL MERGE. Rate-limited at 0.5 s between calls.

### BWB — `BWBRetrievePipeline`

**File:** `pipelines/retrieve/bwb.py`

Fetches the current `Toestand` XML for BWB IDs from the SRU service. No incremental support — re-provide the full ID list each run.

### Rechtspraak — `RechtspraakRetrievePipeline`

**File:** `pipelines/retrieve/rechtspraak.py`

Fetches the ECLI index feed (`rs-index`) and individual ECLI XML documents (`rs-content`). Supports `--mode incremental` via `modifiedsince` parameter.

### EUR-Lex — `EurlexRetrievePipeline`

**File:** `pipelines/retrieve/eurlex.py`

Fetches HTML for CELEX IDs via the CELLAR server. No incremental support.

---

## 3. Normalize pipelines

All normalize pipelines share the same contract: `fetch_raw()` → `normalize_nodes()` → `build_edges()`.

### TK Parliamentary Dossiers — `TkDossiersNormalizePipeline`

**File:** `pipelines/normalize/tk_dossiers.py`

Processing order:

```
1. Commissies      — no deps
2. Personen        — no deps
3. Fracties        — no deps
4. Kamerstukdossiers — no deps
5. Activiteiten    — depend on Commissie nodes
6. Stemmingen      — grouped by Besluit_Id; depend on Dossier nodes
7. Toezeggingen    — depend on Activiteit nodes
8. TK Documents    — produce publication nodes; link to Dossiers
```

Fase enrichment runs after all nodes are created, traversing Activiteit → Zaak chains to classify dossiers as `wetsvoorstel` / `overig` / `afgehandeld`.

**Stemmingen grouping:** The TK API returns one raw row per fractie per Besluit. The pipeline groups by `Besluit_Id`. Records without a `Besluit_Id` are skipped. The `aangenomen` outcome is derived from `BesluitSoort` text or a majority vote calculation.

**Dossier key collision:** Dossiers with the same `nummer` but different `toevoeging` (e.g. `36554` and `36554-I`) use `make_node_key(nummer, toevoeging)` to avoid overwriting each other.

**Edges written:**

| Relation | From | To |
|----------|------|----|
| `DEEL_VAN_DOSSIER` | TK Document | Kamerstukdossier |
| `DEEL_VAN_DOSSIER` | Activiteit | Kamerstukdossier |
| `DEEL_VAN_DOSSIER` | Stemming | Kamerstukdossier |
| `DEEL_VAN_DOSSIER` | Toezegging | Kamerstukdossier |
| `DEEL_VAN_DOSSIER` | Procedure (Zaak) | Kamerstukdossier |
| `BEHANDELD_DOOR` | Activiteit | Commissie |
| `GEDAAN_IN` | Toezegging | Activiteit |
| `LID_VAN` | Lid | Commissie |
| `LID_VAN_FRACTIE` | Lid | Fractie |
| `STEMT` | Fractie | Stemming |

### TK Procedures and Publications — `TkNormalizePipeline`

**File:** `pipelines/normalize/tk.py`

Processes `tk-zaak` and `tk-documentversie` kinds. Writes procedure nodes to `procedures` and publication nodes to `publications`. Creates `PART_OF_PROCEDURE` edges. Stores `kamerstuknummer` on procedure nodes so `TkDossiersNormalizePipeline` can link them to dossiers.

Accepts a `domain_profile` parameter (default: `"strafrecht"`) that controls classification labels.

### BWB — `BWBNormalizePipeline`

**File:** `pipelines/normalize/bwb.py`

Parses BWB XML (`payload_text`) with `xml.etree.ElementTree`. All XML namespace prefixes are stripped before tag comparison.

**Instrument title extraction:** `_extract_instrument_title()` parses `citeertitel` / `officiele-titel` / `intitule` from toestand XML. Falls back to `"BWB-regeling {bwb_id}"` only if no title element is found.

**Article extraction strategy:**
1. Find elements with tag `"artikel"` or `label` attribute starting with `"artikel"`
2. Extract article number from `<kop><nr>` descendant, falling back to `label` attribute
3. Extract article text from `<lid>` / `<al>` descendants

Articles without a number or empty text are skipped.

**Key scheme:** `make_node_key(bwb_id, article_number)`

**Edges:** `PART_OF_INSTRUMENT` from instrument → article.

### BWB History — `BWBHistoryNormalizePipeline`

**File:** `pipelines/normalize/bwb_history.py`

Processes historical BWB toestanden to produce `instrument_versions` and `instrument_article_versions` nodes, and `VERSION_OF` / `PART_OF_VERSION` edges.

### Rechtspraak — `RechtspraakNormalizePipeline`

**File:** `pipelines/normalize/rechtspraak.py`

Processes `rs-content` XML records. Parses summary (`<inhoudsindicatie>`), full text (`<uitspraak>`), and RDF metadata tags. Creates stub judgment nodes from `rs-index` records (labels: `["Rechtspraak", "Stub"]`).

**Strafrecht classification:** checks ECLI prefix list, full-text keywords, and `rechtsgebied` metadata.

### EUR-Lex — `EUNormalizePipeline`

**File:** `pipelines/normalize/eurlex.py`

Converts HTML to plaintext via a custom `HTMLParser`. Extracts article headers with regex `(?:Artikel|Article)\s+(\d+[a-z]*)`. Article body runs from the end of one header to the start of the next.

Filter: article number > 200 skipped (configurable via `EURLEX_MAX_ARTICLE_NUMBER`). Bodies shorter than 10 chars or starting with `","` skipped.

**Key scheme:** `make_node_key(celex, article_number)`

**Edges:** `PART_OF_INSTRUMENT` from article → instrument.

### Staatsblad — `StaatsbladNormalizePipeline`

**File:** `pipelines/normalize/staatsblad.py`

Normalizes Staatsblad AMvB XML records into publication nodes.

### Staatscourant — `StaatscourantNormalizePipeline`

**File:** `pipelines/normalize/staatscourant.py`

Normalizes Staatscourant ministeriele regeling records.

### Eerste Kamer — `EerstekamerNormalizePipeline`

**File:** `pipelines/normalize/eerstekamer.py`

Normalizes Eerste Kamer Kamerstukken.

### ECHR — `EchrNormalizePipeline`

**File:** `pipelines/normalize/echr.py`

Normalizes ECHR HUDOC judgment JSON into judgment nodes.

### Verdragenbank — `VerdragenbankNormalizePipeline`

**File:** `pipelines/normalize/verdragenbank.py`

Normalizes Dutch treaty records from the Verdragenbank SPARQL endpoint.

---

## 4. Data flow

```
External APIs
       |
       | Retrieve pipelines
       v
raw_sources
  source, kind, external_id, fetched_at, payload_json, payload_text, meta
       |
       | Normalize pipelines (query by source+kind+fetched_at>=since)
       v
Document collections              edges collection
─────────────────                 ──────────────────
instruments                       PART_OF_INSTRUMENT
instrument_articles               DEEL_VAN_DOSSIER
instrument_versions               BEHANDELD_DOOR
instrument_article_versions       PART_OF_PROCEDURE
procedures                        GEDAAN_IN
publications                      LID_VAN / LID_VAN_FRACTIE
judgments                         STEMT
kamerstukdossiers                 VERSION_OF / PART_OF_VERSION
activiteiten
stemmingen
toezeggingen
commissies
leden
fracties
       |
       | Semantic pipelines
       v
Additional edges:
  REFERS_TO_ARTICLE / CITES_ARTICLE / MENTIONS_ARTICLE / EXPLAINS_ARTICLE
  AMENDS_INSTRUMENT / IMPLEMENTS_DIRECTIVE / DISCUSSES / LICHT_TOE
  WIJZIGT / INTRODUCEERT / TREKT_IN / DELEGATED_BY
  CITES_JUDGMENT / APPEAL_OF
  RESULTED_IN / CAUSED_VERSION
```

---

## 5. Incremental update strategy

| Source | Incremental support | Mechanism |
|--------|--------------------|-----------|
| TK Zaak / DocumentVersie | yes | OData `ApiGewijzigdOp ge <datetime>` |
| TK Dossier / Activiteit / Stemming / Toezegging / Document | yes | Same |
| TK Commissie | no | Always full-refresh |
| TK Persoon | no | Always full-refresh |
| Rechtspraak index | yes | `modifiedsince` query param |
| Rechtspraak content | no | Explicit ECLI list required |
| BWB | no | Explicit BWB ID list required |
| EUR-Lex | no | Explicit CELEX list required |

**Normalize incremental:** `_query_raw_sources()` filters by `fetched_at >= since`. The `(source, kind)` compound index on `raw_sources` makes this efficient on 200K+ records.

**Delete tracking:** removed external records persist as stale nodes — there is no delete cascade.
