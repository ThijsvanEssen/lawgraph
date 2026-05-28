# API Layer

## 1. Architecture

**File:** `src/lawgraph/api/app.py`

- **Framework**: FastAPI, async route handlers
- **Dependency injection**: `get_store()` in `api/dependencies.py` — returns a shared `ArangoStore` instance via `@lru_cache`
- **Database**: ArangoDB via `ArangoStore` singleton
- **CORS**: Configurable via `LAWGRAPH_ALLOWED_ORIGINS` env var (comma-separated). Default: `http://localhost:5173,http://localhost:5174` for local dev.
- **Startup**: `lifespan` context manager warns on missing `ARANGO_URL`, `ARANGO_PASSWORD`, `LAWGRAPH_ALLOWED_ORIGINS`.

### Middleware

1. **`_RateLimitMiddleware`** — sliding-window per-IP rate limiter. Default: 200 requests/60 s. First-party origins (matching CORS allow-list) bypass the limit. Returns 429 + `Retry-After`. State is in-process; with multiple workers the effective limit is N_workers × limit.

2. **`_CacheControlMiddleware`** — injects `Cache-Control` headers on successful GET responses:
   - `/api/articles/` → `public, max-age=1800` (30 min)
   - `/api/judgments/` → `public, max-age=3600` (1 h)
   - `/api/stats` → `public, max-age=300` (5 min)
   - Everything else → `private, max-age=60`

3. **Request logging middleware** — logs `[request_id] client METHOD path status size latency_ms` for every request. Adds `X-Request-ID` header to responses.

### Route registration

| Prefix | Router file |
|--------|-------------|
| `/api/articles` | `routes/articles.py` |
| `/api/judgments` | `routes/judgments.py` |
| `/api/instruments` | `routes/instruments.py` |
| `/api/nodes` | `routes/nodes.py` |
| `/api/dossiers` | `routes/dossiers.py` |
| `/api/commissies` | `routes/commissies.py` |
| `/api/leden` | `routes/commissies.py` |
| `/api/fracties` | `routes/commissies.py` |
| `/api/partijen` | `routes/dossiers.py` |
| `/api/graph` | `routes/graph.py` |
| `/api/publications` | `routes/publications.py` |
| `/api/search` | `routes/search.py` |
| `/api/stats` | `routes/stats.py` |
| `/api/watches` | `routes/watches.py` |
| `/api/stemmingen` | `routes/stemmingen.py` |
| `/api/parlement` | `routes/parlement.py` |

---

## 2. Endpoint inventory

### Root and health

| Method | Path | Response |
|--------|------|----------|
| GET | `/` | `{"name": "lawgraph-api", "version": "..."}` |
| GET | `/api/health` | `{"status": "ok", "database": "connected"}` or 503 |

### Articles

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/articles/{bwb_id}/{article_number}` | `ArticleDetailResponse` |
| GET | `/api/articles/{bwb_id}/{article_number}/legislative-history` | `ArticleLegislativeHistoryResponse` |
| GET | `/api/articles/{bwb_id}/{article_number}/in-flux` | `ArticleInFluxResponse` |

Path param validation: `bwb_id` matches `^BWB[RrVv]\d{7}$`; returns 422 on invalid format.

### Judgments

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/judgments/{ecli}` | `JudgmentDetailResponse` |

Path param validation: `ecli` matches `^ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[A-Z0-9._-]+$`.

### Instruments

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/instruments` | — | `InstrumentIndexResponse` |
| GET | `/api/instruments/{bwb_id}` | — | `InstrumentSummaryDTO` |
| GET | `/api/instruments/{bwb_id}/graph` | — | `InstrumentGraphResponse` |
| GET | `/api/instruments/{bwb_id}/reader` | — | `InstrumentReaderResponse` |
| GET | `/api/instruments/{bwb_id}/procedures` | — | `InstrumentProceduresResponse` |
| GET | `/api/instruments/{bwb_id}/publications` | `?relation` | `InstrumentPublicationsResponse` |

### Dossiers

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/dossiers/open` | `?commissie`, `?onderwerp`, `?fase`, `?limit` | `list[DossierSummaryDTO]` |
| GET | `/api/dossiers/recent` | `?days=30`, `?limit=50` | `list[DossierSummaryDTO]` |
| GET | `/api/dossiers/{kamerstuknummer}` | — | `DossierDetailResponse` |
| GET | `/api/dossiers/{kamerstuknummer}/timeline` | `?order`, `?soort`, `?limit` | `DossierTimelineResponse` |
| GET | `/api/dossiers/{kamerstuknummer}/documents` | `?limit`, `?offset` | `{total, items[]}` |
| GET | `/api/dossiers/{kamerstuknummer}/mutations` | — | `DossierMutationsResponse` |

Path param validation: `kamerstuknummer` matches `^\d+(-[A-Z]+)?$`.

### Stemmingen (votes)

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/stemmingen` | `?aangenomen`, `?partij`, `?limit`, `?offset` | `{total, items[]}` |
| GET | `/api/stemmingen/{key}` | — | stemming detail |

### Commissies and leden

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/commissies` | `list[CommissieDTO]` |
| GET | `/api/commissies/{slug}` | `CommissieDetailDTO` |
| GET | `/api/leden/{key}` | `LidDTO` |
| GET | `/api/leden/{key}/votes` | `{lid_id, votes, total}` |

### Publications

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/publications` | `?q`, `?soort`, `?limit` (1–500, default 50), `?offset` | `PublicationListResponse` |
| GET | `/api/publications/{key}` | — | `PublicationTextResponse` |

### Graph

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/graph/global` | `?include_judgments`, `?max_judgments` | `GlobalGraphResponse` |
| GET | `/api/graph/instruments` | — | `InstrumentLayerGraphResponse` |
| GET | `/api/graph/judgments` | `?max_judgments`, `?include_stubs` | `JudgmentLayerGraphResponse` |

### Nodes, stats, watches, partijen

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/nodes/in-flux` | `dict[node_id, count]` |
| GET | `/api/nodes/heat` | `dict[node_id, activity_count]` (`?months=6`) |
| GET | `/api/nodes/{collection}/{key}` | `NodeGraphResponse` |
| GET | `/api/stats` | `StatsResponse` |
| GET | `/api/partijen/kleuren` | `PartyColorsResponse` |
| GET | `/api/watches` | `list[WatchOut]` |
| POST | `/api/watches` | `WatchOut` (201) |
| DELETE | `/api/watches/{watch_id}` | 204 / 404 |

Watch creation validates `node_id` format, collection existence, and document existence before inserting.

---

## 3. Schema catalogue

All DTOs in `src/lawgraph/api/schemas.py`. AQL queries in `src/lawgraph/api/queries/`.

### Core

- **`BaseNodeDTO`** — `id, key, collection, type, display_name, labels, props` (drops `raw_xml`)
- **`NeighborDTO`** — extends BaseNodeDTO + `relation, direction, confidence`
- **`NodeGraphResponse`** — `node: BaseNodeDTO, neighbors: NodeNeighborsDTO`

### Articles

- **`ArticleDetailResponse`** — `article, instrument, judgments, citations, metadata`
  - `metadata` contains `{"judgment_count": N}` only
- **`ArticleLegislativeHistoryResponse`** — `article_id, entries, total`
- **`ArticleInFluxResponse`** — `article_id, in_flux, open_dossier_count`

### Judgments

- **`JudgmentDTO`** — extends BaseNodeDTO + `ecli, summary, paragraphs`
- **`JudgmentDetailResponse`** — `judgment, articles, cited_judgments, metadata`

### Instruments

- **`InstrumentSummaryDTO`** — `id, key, display_name, article_count, judgment_count, inbound_citation_count, outbound_citation_count`

### Dossiers

- **`DossierSummaryDTO`** — `id, key, kamerstuknummer, titel, huidige_fase, afgedaan, geopend_op, gesloten_op`
- **`DossierDetailResponse`** — extends summary + `document_count, activiteit_count, stemming_count, toezegging_count`
- **`DossierTimelineResponse`** — `kamerstuknummer, total, order, entries`

### Parliamentary

- **`CommissieDTO`** — `id, key, naam, afkorting, slug, active_dossier_count`
- **`CommissieDetailDTO`** — extends CommissieDTO + `leden, dossiers`
- **`LidDTO`** — `id, key, naam, partij, actief`

### Publications, search, graph

- **`PublicationSummaryDTO`** — `id, key, datum, soort, titel, external_id`
- **`SearchResultItem`** — `id, key, collection, type, display_name, snippet, score, extra`
- **`GraphEdgeDTO`** — `from_id, to_id, relation_type, start, end, text, confidence`
- **`WatchIn/WatchOut`** — `node_id, label, collection, created_at`

---

## 4. AQL query patterns

All queries in `src/lawgraph/api/queries/`.

- **Pagination**: `LIMIT @offset, @limit` with a separate `LENGTH(...)` subquery for `total`
- **Edge traversal**: `FOR e IN edges FILTER e._from/e._to == @id AND e.relation == @rel`
- **Safe bind vars**: all user input passed via bind variables, never string-interpolated
- **Confidence extraction**: checks `edge.confidence` then `edge.meta.confidence`

---

## 5. Known gaps

| Gap | Description |
|-----|-------------|
| No API authentication | All endpoints are fully public |
| No date-range filter on stemmingen | Can only filter by `aangenomen` and `partij` |
| No batch endpoints | Clients must loop N times for N entities |
| No dossier→dossier related endpoint | No way to find related dossiers |
| Instruments list has no search/filter | Returns all instruments |
| `score` hardcoded to `1.0` on search results | No relevance ranking |
