# LawGraph CLI & Cross-cutting Design Document

## 1. CLI Command Catalogue

All commands registered in `pyproject.toml` under `[project.scripts]`.

### Retrieve commands

| Command | Module | Description | Key flags |
|---------|--------|-------------|-----------|
| `lawgraph-retrieve-tk` | `cli/retrieve_tk.py` | Fetch TK Zaak + DocumentVersie (legacy) | `--profile`, `--since-days N` (default 1), `--limit N` (dev cap, default 0) |
| `lawgraph-retrieve-tk-dossiers` | `cli/retrieve_tk_dossiers.py` | Fetch all parliamentary dossier entities | `--since DATE`, `--skip-personen`, `--skip-stemmingen`, `--stemmingen-since DATE`, `--skip-documents`, `--documents-since DATE` |
| `lawgraph-retrieve-rechtspraak` | `cli/retrieve_rechtspraak.py` | Fetch judgments from index + explicit ECLIs | `--profile`, `--since-days N`, `--ecli ECLI` (repeatable) |
| `lawgraph-retrieve-bwb` | `cli/retrieve_bwb.py` | Fetch BWB law XML | `--profile`, `--bwb-id BWBID` (repeatable) |
| `lawgraph-retrieve-eurlex` | `cli/retrieve_eurlex.py` | Fetch EUR-Lex HTML | `--profile`, `--celex CELEX` (repeatable), `--lang` |
| `lawgraph-retrieve-all` | `cli/retrieve_all.py` | Orchestrate all retrieve commands | `--profile`, `--since-days N` |
| `lawgraph-retrieve-tk-content` | `cli/retrieve_tk_content.py` | Hydrate TK document PDFs to text | `--soort TEXT`, `--dry-run` |

### Normalize commands

| Command | Module | Description | Key flags |
|---------|--------|-------------|-----------|
| `lawgraph-normalize-tk` | `cli/normalize_tk.py` | Normalize TK Zaak + DocumentVersie | `--since DATE`, `--profile` |
| `lawgraph-normalize-tk-dossiers` | `cli/normalize_tk_dossiers.py` | Normalize all parliamentary entities | `--since DATE` |
| `lawgraph-normalize-rechtspraak` | `cli/normalize_rechtspraak.py` | Normalize judgments | `--since DATE`, `--profile` |
| `lawgraph-normalize-bwb` | `cli/normalize_bwb.py` | Normalize BWB instruments + articles | `--since DATE` |
| `lawgraph-normalize-eurlex` | `cli/normalize_eurlex.py` | Normalize EU instruments + articles | `--since DATE` |
| `lawgraph-normalize-all` | `cli/normalize_all.py` | Orchestrate all normalize commands | `--profile` |

### Semantic commands

| Command | Module | Description |
|---------|--------|-------------|
| `lawgraph-semantic-bwb-articles` | `cli/semantic_bwb_articles.py` | Detect article cross-references in BWB law text |
| `lawgraph-semantic-rechtspraak-articles` | `cli/semantic_rechtspraak_articles.py` | Detect article citations in judgments |
| `lawgraph-semantic-tk-articles` | `cli/semantic_tk_articles.py` | Detect article references in TK publications |
| `lawgraph-semantic-eu-articles` | `cli/semantic_eu_articles.py` | Detect article references in EU law text |
| `lawgraph-semantic-instrument-relations` | `cli/semantic_instrument_relations.py` | Detect AMENDS/IMPLEMENTS/DISCUSSES relations |
| `lawgraph-semantic-judgment-citations` | `cli/semantic_judgment_citations.py` | Detect ECLI citations in judgments |

All semantic commands are registered in `pyproject.toml`. `lawgraph-semantic-all` orchestrates all six detectors.

### Utility commands

| Command | Module | Description |
|---------|--------|-------------|
| `lawgraph-strafrecht-seed` | `cli/strafrecht_seed.py` | Seed strafrecht domain nodes + edges |
| `lawgraph-api` | `api/app.py` | (Not a CLI — registered as entry point but starts via uvicorn) |

---

## 2. Operational Runbook

### Full initial load (all sources)

```bash
# 1. Retrieve all TK parliamentary entities
#    Documents are large (~116K in 730d window) — always use --documents-since
lawgraph-retrieve-tk-dossiers --documents-since 730d

# 2. Retrieve legacy TK Zaak/DocumentVersie (strafrecht domain)
#    No --since flag — uses --since-days (int); 365 days lookback
lawgraph-retrieve-tk --profile strafrecht --since-days 365

# 3. Retrieve BWB law text (explicit BWB IDs, flag is repeatable)
lawgraph-retrieve-bwb --bwb-id BWBR0001854 --bwb-id BWBR0001903 --bwb-id BWBR0001940

# 4. Retrieve judgments (index snapshot via --since-days, then explicit ECLIs)
lawgraph-retrieve-rechtspraak --profile strafrecht --since-days 365
lawgraph-retrieve-rechtspraak --ecli ECLI:NL:HR:2023:123 --ecli ECLI:NL:HR:2022:456

# 5. Retrieve EU law (explicit CELEX IDs, flag is repeatable)
lawgraph-retrieve-eurlex --celex 31997F0266 --celex 32019L1158

# 6. Normalize all (TK dossiers first — largest)
lawgraph-normalize-tk-dossiers
lawgraph-normalize-tk
lawgraph-normalize-bwb
lawgraph-normalize-rechtspraak
lawgraph-normalize-eurlex

# 7. Seed domain topics
lawgraph-strafrecht-seed

# 8. Run semantic detection (citation graph)
lawgraph-semantic-all
# or individually:
# lawgraph-semantic-bwb-articles
# lawgraph-semantic-rechtspraak-articles
# lawgraph-semantic-tk-articles
# lawgraph-semantic-eu-articles
# lawgraph-semantic-instrument-relations
# lawgraph-semantic-judgment-citations

# 9. (Optional) Hydrate TK document PDF text
lawgraph-retrieve-tk-content --soort toelichting
```

### Incremental update (daily/weekly)

```bash
# Retrieve recent changes (past 7 days)
lawgraph-retrieve-tk-dossiers --since 7d --skip-personen --stemmingen-since 7d --documents-since 7d
lawgraph-retrieve-tk --profile strafrecht --since-days 7
lawgraph-retrieve-rechtspraak --profile strafrecht --since-days 7

# Normalize (only processes records fetched in this window)
lawgraph-normalize-tk-dossiers --since 7d
lawgraph-normalize-tk --since 7d

# Re-run semantic detection on recently changed nodes
lawgraph-semantic-rechtspraak-articles --since-days 7
lawgraph-semantic-tk-articles --since-days 7
lawgraph-semantic-eu-articles --since-days 7
lawgraph-semantic-bwb-articles --since-days 7
```

### Slow operations to schedule carefully

| Command | Typical duration | Notes |
|---------|-----------------|-------|
| `retrieve-tk-dossiers` (full) | ~15 min | Activiteiten: 97K records; Documents: 116K records |
| `normalize-tk-dossiers` | ~30 min | Normalizes 116K documents + builds 350K+ edges |
| `retrieve-tk-content` | Hours | Rate-limited at 0.5s/request; ~400K publications total |
| `semantic-bwb-articles` | 5–10 min | Scans all instrument_articles |

---

## 3. pyproject.toml — Status

### Stale entry points — ✅ Fixed

The three stale entry points (`lawgraph-parliament`, `lawgraph-case-law`, `lawgraph-eu-law`) that referenced non-existent modules have been removed.

### Missing entry points — ✅ Fixed

All seven previously unregistered CLI modules are now registered:

| Command | Module |
|---------|--------|
| `lawgraph-semantic-all` | `cli/semantic_all.py` |
| `lawgraph-semantic-judgment-citations` | `cli/semantic_judgment_citations.py` |
| `lawgraph-semantic-instrument-relations` | `cli/semantic_instrument_relations.py` |
| `lawgraph-retrieve-tk-content` | `cli/retrieve_tk_content.py` |
| `lawgraph-fill-gaps` | `cli/fill_gaps.py` |
| `lawgraph-backfill-edge-status` | `cli/backfill_edge_status.py` |
| `lawgraph-migrate-dedup-instruments` | `cli/migrate_dedup_instruments.py` |

Run `pip install -e .` after pulling to make new entry points discoverable.

### Orchestration gaps — ✅ Fixed

`lawgraph-retrieve-all` and `lawgraph-normalize-all` now include TK dossier pipelines. Both can be disabled per-run via environment variables (`LAWGRAPH_RETRIEVE_SKIP_TK_DOSSIERS=1`, `LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS=1`).

---

## 4. Cross-cutting Bugs

| # | Severity | Span | Status | Description |
|---|----------|------|--------|-------------|
| 1 | **CRITICAL** | API | 🔴 Open | **Zero authentication** — all 12 API endpoint groups are fully public with no API key, OAuth, or RBAC |
| 2 | **HIGH** | API | ✅ Fixed | **CORS hardcoded** — moved to `LAWGRAPH_ALLOWED_ORIGINS` env var |
| 3 | HIGH | CLI | ✅ Fixed | **No exit codes on error** — all retrieve, normalize, and semantic CLIs now call `sys.exit(1)` on pipeline errors; CI/CD can detect failures |
| 4 | HIGH | CLI/pyproject | ✅ Fixed | **3 stale entry points** removed |
| 5 | HIGH | CLI/pyproject | ✅ Fixed | **7 missing entry points** registered |
| 6 | MEDIUM | Pipelines | ✅ Fixed | **`retrieve-all` / `normalize-all`** now include TK dossier pipelines |
| 7 | MEDIUM | Data | ✅ Fixed | **TK dossiers not linked to procedures** — `kamerstuknummer` prop now written to procedure nodes by `TkNormalizePipeline`; `_link_zaken_to_dossiers` in `TkDossiersNormalizePipeline` uses it to build `DEEL_VAN_DOSSIER` edges |
| 8 | MEDIUM | API | ✅ Fixed | **`RELATION_LID_VAN` hardcoded string** — now defined as constant in `settings.py` |
| 9 | MEDIUM | CLI | ✅ Fixed | **Inconsistent `main()` signatures** — all CLIs now accept `argv: list[str] \| None = None` and pass it to `parser.parse_args()` |
| 10 | LOW | CLI | ✅ Fixed | **Mixed Dutch/English log messages** — all Dutch log strings in `normalize/bwb.py` translated to English |
| 11 | LOW | CLI | ✅ Fixed | **`normalize_tk_dossiers.py` uses `print()`** — replaced with `logger.info()` |

---

## 5. Missing Tests

### Current test coverage

```
tests/
  test_clients.py                    — Basic client unit tests (partial)
  test_bwb_detect.py                 — BWB citation detection regex tests
  tests/api/test_parliamentary_api.py — ✅ Added: dossiers, commissies, stemmingen routes (6 tests)
  tests/api/test_judgments_api.py    — Judgment detail endpoint
  tests/api/test_nodes_api.py        — Node graph explorer endpoint
```

### Remaining gaps (no coverage)

| Area | Priority |
|------|----------|
| CLI argument parsing for all commands | P1 |
| `TkDossiersNormalizePipeline` normalization logic | P1 |
| `TkDossiersRetrievePipeline` (fetch + store) | P1 |
| `_skip_paged_get()` pagination logic | P1 |
| OData expand syntax validation | P2 |
| Semantic TK / EU / Rechtspraak detectors | P2 |
| `ArangoStore.insert_or_update()` props merge behavior | P2 |
| End-to-end: retrieve → normalize → semantic → API | P2 |
| Dossier phase enrichment (`_enrich_dossier_fasen`) | P2 |
| Stemmingen aggregation (grouping by Besluit_Id) | P2 |

---

## 6. Observability & Operations

### Current state

- **Logging**: Python `logging` module via `get_logger(__name__)` (`logging.py`). Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. JSON format available via `LAWGRAPH_LOG_FORMAT=json`.
- **Error surfacing**: `PipelineResult.errors` accumulates error messages; printed by CLI after pipeline run
- **Health check**: `GET /api/health` checks ArangoDB connectivity and returns `{status, database}`; `GET /` returns `{name, version}`
- **Request logging**: HTTP middleware logs method, path, status code, and latency (ms) for every request
- **Metrics**: None — no cache hit rates or pipeline throughput tracking

### Gaps

| Gap | Status | Impact |
|-----|--------|--------|
| ~~No request logging middleware on API~~ | ✅ Fixed | — |
| No correlation IDs across retrieve→normalize→semantic chain | 🔴 Open | Can't trace a record's journey through the pipeline |
| ~~No structured log format (JSON)~~ | ✅ Fixed — `LAWGRAPH_LOG_FORMAT=json` | — |
| ~~No `/api/health` endpoint~~ | ✅ Fixed | — |
| No pipeline progress reporting | 🔴 Open | Long-running jobs (30 min normalize) have no progress indicator |
| ~~Some modules use `print()` instead of logger~~ | ✅ Fixed | — |

---

## 7. Security & Configuration

### Authentication

**There is no authentication on the API.** All read endpoints and the watches write endpoint are publicly accessible. Recommended additions:

1. API key middleware (simple, fast to implement)
2. OAuth2/JWT for user-specific features (watches)
3. Role-based access (read-only vs. admin)

### Missing env var validation — ✅ Fixed

Startup lifespan handler now warns on missing `ARANGO_URL`, `ARANGO_PASSWORD`, and `LAWGRAPH_ALLOWED_ORIGINS`. Errors surface at startup rather than at first database call.

### CORS — ✅ Fixed

Previously hardcoded to localhost only. Now configurable via the `LAWGRAPH_ALLOWED_ORIGINS` env var (comma-separated):

```python
origins = os.getenv("LAWGRAPH_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
```

### Input validation — ✅ Fixed

FastAPI `Path(pattern=...)` constraints added to all relevant route parameters:

| Parameter | Route | Pattern |
|-----------|-------|---------|
| `bwb_id` | `/api/articles/{bwb_id}/...` | `^BWB[RrVv]\d{7}$` |
| `ecli` | `/api/judgments/{ecli}` | `^ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[A-Z0-9._-]+$` |
| `kamerstuknummer` | `/api/dossiers/{kamerstuknummer}/...` | `^\d+(-[A-Z]+)?$` |

Invalid formats return HTTP 422 automatically.

### Hardcoded values

| Location | Hardcoded value | Status |
|----------|----------------|--------|
| ~~`app.py:44-49`~~ | ~~CORS origins~~ | ✅ Fixed — `LAWGRAPH_ALLOWED_ORIGINS` env var |
| `app.py` | API version `"0.4.0"` | 🔴 Open — could be imported from `pyproject.toml` |
| `routes/publications.py:22` | TK resource URL template | ✅ Fixed — derived from `TK_BASE_URL` |
| `schemas.py:727-748` | Party color hex codes | Acceptable (stable reference data) |

---

## 8. Overall Improvement Priorities

### P1 — Fix immediately (correctness/security)

| # | Issue | Status | Effort |
|---|-------|--------|--------|
| 1 | Add API authentication (at minimum: API key middleware) | 🔴 Open | 2h |
| 2 | Move CORS origins to env var | ✅ Fixed | — |
| 3 | Remove 3 stale entry points from pyproject.toml | ✅ Fixed | — |
| 4 | Register 7 missing entry points in pyproject.toml | ✅ Fixed | — |
| 5 | Add exit codes (`sys.exit(1)`) on pipeline errors in CLI | ✅ Fixed | — |
| 6 | Fix pagination in `TKRetrievePipeline` (data loss) | ✅ Fixed | — |
| 7 | Guard stemmingen `Besluit_Id` null (data corruption) | ✅ Fixed | — |
| 8 | Fix dossier nummer collision (data overwrite) | ✅ Fixed | — |

### P2 — Next sprint (completeness)

| # | Issue | Status | Effort |
|---|-------|--------|--------|
| 9 | Add `retrieve-tk-dossiers` + `normalize-tk-dossiers` to `*-all` orchestration | ✅ Fixed | — |
| 10 | Add `lawgraph-semantic-all` to pyproject entry points | ✅ Fixed | — |
| 11 | Define `RELATION_LID_VAN` constant in settings.py | ✅ Fixed | — |
| 12 | Add `/api/health` endpoint checking ArangoDB connectivity | ✅ Fixed | — |
| 13 | Implement HTTP retry with exponential backoff in BaseClient | ✅ Fixed | — |
| 14 | Add stub node creation for TK/EU semantic detector misses | ✅ Fixed | — |
| 15 | Add API tests for dossier/commissie/stemmingen routes | ✅ Fixed | — |

### P3 — Medium term (quality/operations)

| # | Issue | Status | Effort |
|---|-------|--------|--------|
| 16 | Standardize logging to English; replace `print()` with `logger` | ✅ Fixed | — |
| 17 | Add JSON structured logging format option | ✅ Fixed | — |
| 18 | Add request latency logging middleware | ✅ Fixed | — |
| 19 | Add incremental mode to TK, EU, BWB semantic detectors | ✅ Fixed | — |
| 20 | Add startup env var validation | ✅ Fixed | — |
| 21 | Add pagination to `/api/publications` | ✅ Fixed | — |

### P4 — Nice-to-have

| # | Issue | Status | Effort |
|---|-------|--------|--------|
| 22 | Create `Fractie` party nodes; link to stemmingen | ✅ Fixed | — |
| 23 | CommissieZetel date ranges as temporal edge properties | ✅ Fixed | — |
| 24 | Add input format validation (ECLI, CELEX, BWB ID, kamerstuknummer) | ✅ Fixed | — |
| 25 | Rate limiting middleware on API | ✅ Fixed | — |
| 26 | Response caching headers on stable endpoints | ✅ Fixed | — |
