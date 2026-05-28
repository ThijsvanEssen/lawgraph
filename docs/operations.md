# Operations

## Environment variables

All configuration is via environment variables loaded from `.env` (see `.env.example`).

### Required

| Variable | Default | Purpose |
|----------|---------|---------|
| `ARANGO_URL` | `http://localhost:8529` | ArangoDB host |
| `ARANGO_DB_NAME` | `lawgraph` | Database name |
| `ARANGO_USER` | `root` | DB user |
| `ARANGO_PASSWORD` | _(empty)_ | DB password |

### API server

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS allow-list (comma-separated) |
| `LAWGRAPH_API_HOST` | `0.0.0.0` | API listen host |
| `LAWGRAPH_API_PORT` | `8000` | API listen port |
| `LAWGRAPH_RATE_LIMIT_CALLS` | `200` | Max requests per window per IP |
| `LAWGRAPH_RATE_LIMIT_PERIOD` | `60` | Rate limit window in seconds |
| `LAWGRAPH_TRUSTED_PROXIES` | _(loopback)_ | IPs allowed to set X-Forwarded-For |

### Collections (optional overrides)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_DOCUMENT_COLLECTIONS` | _(all collections)_ | Comma-separated override |
| `LAWGRAPH_EDGE_COLLECTION` | `edges` | Edge collection name |

### External API URLs (all have working defaults)

| Variable | Default |
|----------|---------|
| `TK_API_BASE` | `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/` |
| `RECHTSPRAAK_BASE` | `https://data.rechtspraak.nl/` |
| `EURLEX_BASE` | `https://eur-lex.europa.eu/` |
| `BWB_BASE` | `https://wetten.overheid.nl/` |
| `BWB_SRU_ENDPOINT` | `https://zoekservice.overheid.nl/sru/Search` |
| `EURLEX_SPARQL_ENDPOINT` | `https://publications.europa.eu/webapi/rdf/sparql` |
| `STAATSBLAD_SRU_ENDPOINT` | `https://sru.officielebekendmakingen.nl/sru/Search` |
| `EERSTEKAMER_BASE` | `https://gegevensmagazijn.eerstekamer.nl/OData/v4/2.0/` |
| `ECHR_HUDOC_BASE` | `https://hudoc.echr.coe.int` |
| `VERDRAGENBANK_SPARQL` | `https://linkeddata.overheid.nl/front/portal/sparql` |

### Semantic confidence overrides

Per-pattern confidence values are overridable via `LAWGRAPH_CONFIDENCE_<PATTERN_NAME_UPPER>`:

```env
LAWGRAPH_CONFIDENCE_BWB_EXPLICIT=0.95
```

### Logging

| Variable | Default | Purpose |
|----------|---------|---------|
| `PIPELINE_LOG_LEVEL` | `INFO` | Log level |
| `LAWGRAPH_LOG_FORMAT` | _(plain)_ | Set to `json` for structured JSON output |
| `NO_COLOR` | _(unset)_ | Set to `1` to disable ANSI colors |

---

## CLI reference

The unified CLI is `lawgraph` (or `python -m lawgraph`).

### Usage

```
lawgraph <phase> <source> [options]
lawgraph bootstrap
lawgraph expand-graph
lawgraph fill-gaps
```

Phases: `retrieve`, `normalize`, `semantic`.

Sources: `tk`, `tk-dossiers`, `rechtspraak`, `eurlex`, `bwb`, `bwb-history`, `staatsblad`, `staatscourant`, `eerstekamer`, `echr`, `verdragenbank`, or `all`.

### Orchestrators

```bash
lawgraph retrieve all [--mode full|incremental] [--since-days N]
lawgraph normalize all [--since DATE]
lawgraph semantic all
```

All orchestrators print a summary table and exit with code 1 if any step fails.

Individual steps can be skipped with env vars of the form `LAWGRAPH_RETRIEVE_SKIP_<SOURCE>=1`, `LAWGRAPH_NORMALIZE_SKIP_<SOURCE>=1`, `LAWGRAPH_SEMANTIC_SKIP_<SOURCE>=1`.

### Retrieve

```bash
lawgraph retrieve tk [--mode full|incremental] [--since-days N]
lawgraph retrieve tk-dossiers [--since DATE] [--skip-personen] [--skip-documents] [--documents-since DATE]
lawgraph retrieve rechtspraak [--mode full|incremental] [--since-days N]
lawgraph retrieve bwb [--mode full]
lawgraph retrieve eurlex [--mode full]
lawgraph retrieve staatsblad
lawgraph retrieve staatscourant [--mode full]
lawgraph retrieve eerstekamer [--mode full]
lawgraph retrieve echr [--mode full]
lawgraph retrieve verdragenbank
lawgraph retrieve bwb-history
lawgraph retrieve tk-content [--soort TEXT] [--dry-run]
```

### Normalize

```bash
lawgraph normalize tk [--since DATE]
lawgraph normalize tk-dossiers [--since DATE]
lawgraph normalize rechtspraak [--since DATE]
lawgraph normalize bwb [--since DATE]
lawgraph normalize bwb-history [--since DATE]
lawgraph normalize eurlex [--since DATE]
lawgraph normalize staatsblad [--since DATE]
lawgraph normalize staatscourant
lawgraph normalize eerstekamer
lawgraph normalize echr
lawgraph normalize verdragenbank
```

### Semantic

```bash
lawgraph semantic tk [--since-days N]
lawgraph semantic rechtspraak [--since-days N]
lawgraph semantic eurlex [--since-days N]
lawgraph semantic bwb [--store-citations]
lawgraph semantic bwb-grondslagen
lawgraph semantic judgment-citations [--since-days N]
lawgraph semantic judgment-appeal
lawgraph semantic instrument-relations
lawgraph semantic amendment-articles [--since-days N]
lawgraph semantic mvt-articles [--since DATE]
lawgraph semantic dossier-law-link
lawgraph semantic version-causes [--window-days N]
lawgraph semantic staatsblad [--since DATE]
lawgraph semantic staatscourant
lawgraph semantic eerstekamer
lawgraph semantic echr
```

---

## Full initial load

```bash
# 1. Retrieve all sources
lawgraph retrieve all --mode full

# 2. Normalize all
lawgraph normalize all

# 3. Run semantic detection
lawgraph semantic all
```

For TK dossiers the full document corpus is large (~400K records). On initial load, either run without `--mode full` and accept the default window, or use the `--documents-since` flag when calling `tk-dossiers` directly:

```bash
lawgraph retrieve tk-dossiers --documents-since 730d
```

## Incremental update (daily/weekly)

```bash
# Retrieve recent changes
lawgraph retrieve all --mode incremental --since-days 7

# Normalize only recent records
lawgraph normalize all --since 7d

# Re-run semantic detection
lawgraph semantic all
```

## Slow operations

| Step | Typical duration | Notes |
|------|-----------------|-------|
| `retrieve tk-dossiers` (full) | ~15 min | Activiteiten: 97K records; Documents: 116K records |
| `normalize tk-dossiers` | ~30 min | 116K documents + 350K+ edges |
| `retrieve tk-content` | Hours | Rate-limited at 0.5 s/request; ~400K publications total |

---

## API

Start the server:

```bash
lawgraph-api
# or with hot reload for development:
uvicorn lawgraph.api.app:app --reload
```

### Health and root

```
GET /                  — {"name": "lawgraph-api", "version": "..."}
GET /api/health        — {"status": "ok", "database": "connected"} or 503
GET /docs              — OpenAPI UI
```

### Key endpoints

```
GET /api/articles/{bwb_id}/{article_number}
GET /api/articles/{bwb_id}/{article_number}/legislative-history
GET /api/articles/{bwb_id}/{article_number}/in-flux

GET /api/judgments/{ecli}

GET /api/instruments
GET /api/instruments/{bwb_id}
GET /api/instruments/{bwb_id}/graph
GET /api/instruments/{bwb_id}/reader
GET /api/instruments/{bwb_id}/procedures
GET /api/instruments/{bwb_id}/publications

GET /api/dossiers/open
GET /api/dossiers/recent
GET /api/dossiers/{kamerstuknummer}
GET /api/dossiers/{kamerstuknummer}/timeline
GET /api/dossiers/{kamerstuknummer}/documents
GET /api/dossiers/{kamerstuknummer}/mutations

GET /api/stemmingen
GET /api/stemmingen/{key}

GET /api/commissies
GET /api/commissies/{slug}
GET /api/leden/{key}
GET /api/leden/{key}/votes

GET /api/publications?q=...&soort=...&limit=50&offset=0
GET /api/publications/{key}

GET /api/nodes/in-flux
GET /api/nodes/heat
GET /api/nodes/{collection}/{key}

GET /api/graph/global
GET /api/graph/instruments
GET /api/graph/judgments

GET /api/search?q=...

GET /api/stats
GET /api/partijen/kleuren

GET /api/watches
POST /api/watches
DELETE /api/watches/{watch_id}

GET /api/parlement/...
GET /api/fracties/...
```

### Middleware

- **Rate limiting**: sliding window per IP; 200 requests/60 s by default. Returns 429 + `Retry-After` when exceeded. First-party CORS origins bypass the limit.
- **Cache-Control**: articles 30 min, judgments 1 h, stats 5 min, all other GET responses 60 s private.
- **Request logging**: every request logs method, path, status, response size, and latency.

### Authentication

There is currently no API authentication. All endpoints are publicly accessible.
