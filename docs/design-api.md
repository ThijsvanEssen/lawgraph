# LawGraph API Layer — Design Document

## 1. Architecture Overview

The LawGraph API is built on **FastAPI** with the following structure:

- **Framework**: FastAPI, async route handlers
- **Dependency injection**: `get_store()` in `dependencies.py` — returns a shared `ArangoStore` instance via `@lru_cache`
- **Database**: ArangoDB via `ArangoStore` singleton
- **CORS**: Configurable via `LAWGRAPH_ALLOWED_ORIGINS` env var (comma-separated). Default: `http://localhost:5173,http://localhost:5174` for local dev.
- **Entry point**: `src/lawgraph/api/app.py`

### Router prefix map

| Prefix | File |
|--------|------|
| `/api/articles` | `routes/articles.py` |
| `/api/judgments` | `routes/judgments.py` |
| `/api/nodes` | `routes/nodes.py` |
| `/api/dossiers` | `routes/dossiers.py` |
| `/api/commissies` | `routes/commissies.py` |
| `/api/leden` | `routes/commissies.py` |
| `/api/partijen` | `routes/dossiers.py` |
| `/api/graph` | `routes/graph.py` |
| `/api/publications` | `routes/publications.py` |
| `/api/search` | `routes/search.py` |
| `/api/stats` | `routes/stats.py` |
| `/api/watches` | `routes/watches.py` |
| `/api/stemmingen` | `routes/stemmingen.py` |

---

## 2. Endpoint Inventory

### Articles

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/articles/{bwb_id}/{article_number}` | path | `ArticleDetailResponse` |
| GET | `/api/articles/{bwb_id}/{article_number}/legislative-history` | path | `ArticleLegislativeHistoryResponse` |
| GET | `/api/articles/{bwb_id}/{article_number}/in-flux` | path | `ArticleInFluxResponse` |

### Judgments

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/judgments/{ecli}` | path | `JudgmentDetailResponse` |

### Instruments

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/instruments` | — | `InstrumentIndexResponse` |
| GET | `/api/instruments/{bwb_id}` | path | `InstrumentSummaryDTO` |
| GET | `/api/instruments/{bwb_id}/graph` | path | `InstrumentGraphResponse` |
| GET | `/api/instruments/{bwb_id}/reader` | path | `InstrumentReaderResponse` |
| GET | `/api/instruments/{bwb_id}/procedures` | path | `InstrumentProceduresResponse` |
| GET | `/api/instruments/{bwb_id}/publications` | path, `?relation` | `InstrumentPublicationsResponse` |

### Dossiers

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/dossiers/open` | `?commissie`, `?onderwerp`, `?fase`, `?limit` | `list[DossierSummaryDTO]` |
| GET | `/api/dossiers/recent` | `?days=30`, `?limit=50` | `list[DossierSummaryDTO]` |
| GET | `/api/dossiers/{kamerstuknummer}` | path | `DossierDetailResponse` |
| GET | `/api/dossiers/{kamerstuknummer}/timeline` | path, `?order`, `?soort`, `?limit` | `DossierTimelineResponse` |
| GET | `/api/dossiers/{kamerstuknummer}/documents` | path, `?limit`, `?offset` | `{total, items[]}` |
| GET | `/api/dossiers/{kamerstuknummer}/mutations` | path | `DossierMutationsResponse` |

### Stemmingen (Votes)

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/stemmingen` | `?aangenomen`, `?partij`, `?limit`, `?offset` | `{total, items[]}` |
| GET | `/api/stemmingen/{key}` | path | `{id, key, datum, onderwerp, dossier_nummers, aangenomen, besluit_id, voor, tegen, onthouding}` |

### Commissies & Leden

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/commissies` | — | `list[CommissieDTO]` |
| GET | `/api/commissies/{slug}` | path | `CommissieDetailDTO` |
| GET | `/api/leden/{key}` | path | `LidDTO` |
| GET | `/api/leden/{key}/votes` | path, `?limit` | `{lid_id, votes, total}` |

### Publications

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/publications` | `?q`, `?soort`, `?limit` (1–500, default 50), `?offset` (default 0) | `PublicationListResponse` |
| GET | `/api/publications/{key}` | path | `PublicationTextResponse` |

### Graph

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/graph/global` | `?include_judgments`, `?max_judgments` | `GlobalGraphResponse` |
| GET | `/api/graph/instruments` | — | `InstrumentLayerGraphResponse` |
| GET | `/api/graph/judgments` | `?max_judgments`, `?include_stubs` | `JudgmentLayerGraphResponse` |

### Nodes, Stats, Watches

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/api/nodes/in-flux` | — | `dict[node_id, count]` |
| GET | `/api/nodes/heat` | `?months=6` | `dict[node_id, activity_count]` |
| GET | `/api/nodes/{collection}/{key}` | path | `NodeGraphResponse` |
| GET | `/api/stats` | — | `StatsResponse` |
| GET | `/api/partijen/kleuren` | — | `PartyColorsResponse` |
| GET | `/api/watches` | — | `list[WatchOut]` |
| POST | `/api/watches` | body: `WatchIn` | `WatchOut` (201) |
| DELETE | `/api/watches/{watch_id}` | path | 204 / 404 |
| GET | `/` | — | `{name, version}` |

---

## 3. Schema Catalogue

All DTOs in `src/lawgraph/api/schemas.py`.

### Core

- **`BaseNodeDTO`** — `id, key, collection, type, display_name, labels, props` (drops `raw_xml`)
- **`NeighborDTO`** — extends BaseNodeDTO + `relation, direction, confidence`
- **`NodeNeighborsDTO`** — `all, strict, semantic: list[NeighborDTO]` (all point to same list)
- **`NodeGraphResponse`** — `node: BaseNodeDTO, neighbors: NodeNeighborsDTO`

### Articles

- **`ArticleSummaryDTO`** — `id, key, bwb_id, article_number, display_name, text`
- **`ArticleCitationSpan`** — `start, end, text, target: ArticleCitationTarget, kind, confidence`
- **`ArticleDetailResponse`** — `article, instrument, judgments, citations, metadata`
  - `metadata` currently contains only `{"judgment_count": N}` — no BibTeX or citation format data
  - `citation_formats` field has been **removed** from this response. The front-end (`graph-store.ts`) has a dead fallback to `metadata.bibtex` that will never populate since `metadata` does not include bibtex.
- **`ArticleLegislativeHistoryResponse`** — `article_id, entries: list[LegislativeHistoryEntry], total`
- **`ArticleInFluxResponse`** — `article_id, in_flux: bool, open_dossier_count: int`

### Judgments

- **`JudgmentDTO`** — extends BaseNodeDTO + `ecli, summary, paragraphs: list[JudgmentParagraph]`
- **`JudgmentDetailResponse`** — `judgment, articles, cited_judgments, metadata`

### Instruments

- **`InstrumentSummaryDTO`** — `id, key, display_name, article_count, judgment_count, inbound_citation_count, outbound_citation_count`
- **`InstrumentLayerInstrumentDTO`** — `id, key, bwb_id, display_name, citation_title, title, shorthand, jurisdiction, stub, citation_count`

### Dossiers

- **`DossierSummaryDTO`** — `id, key, kamerstuknummer, titel, huidige_fase, afgedaan, geopend_op, gesloten_op`
- **`DossierDetailResponse`** — extends summary + `document_count, activiteit_count, stemming_count, toezegging_count`
- **`TimelineEntryDTO`** — `datum, soort, titel, node_id, node_type, tk_url, body: dict`
- **`DossierTimelineResponse`** — `kamerstuknummer, total, order, entries`

### Parliamentary

- **`CommissieDTO`** — `id, key, naam, afkorting, slug, active_dossier_count`
- **`CommissieDetailDTO`** — extends CommissieDTO + `leden, dossiers`
- **`LidDTO`** — `id, key, naam, partij, actief`
- **`ActiviteitDTO`** — `id, key, datum, agenda_titel, soort, commissie_id, video_url`
- **`ToezeggingDTO`** — `id, key, tekst, minister_naam, minister_functie, gedaan_op, verwachte_afhandeling, status`

### Publications / Search / Graph

- **`PublicationSummaryDTO`** — `id, key, datum, soort, titel, external_id`
- **`SearchResultItem`** — `id, key, collection, type, display_name, snippet, score (always 1.0), extra`
- **`GraphEdgeDTO`** — `from_id, to_id, relation_type, start, end, text, confidence`
- **`WatchIn/WatchOut`** — `node_id, label, collection, created_at`

---

## 4. AQL Query Patterns

All queries in `src/lawgraph/api/queries.py`.

- **Pagination**: `LIMIT @offset, @limit` with a separate `LENGTH(...)` subquery for `total`
- **Edge traversal**: Direct `FOR e IN edges FILTER e._from/e._to == @id AND e.relation == @rel`
- **Graph aggregation**: `COLLECT` with `WITH COUNT INTO cnt` for citation weights
- **Safe bind vars**: All user input passed via bind variables, never string-interpolated
- **Multi-collection merge**: `UNIQUE(APPEND(direct, via_procedure))` for publication lookup chains
- **Confidence extraction**: `_extract_confidence()` checks `edge.confidence` then `edge.meta.confidence`

---

## 5. Gaps & Missing Endpoints

| Gap | Status | Description |
|-----|--------|-------------|
| No write endpoints | 🔴 Open | Only watches support creation/deletion; all domain entities are read-only |
| No date-range filter on stemmingen | 🔴 Open | Can only filter by `aangenomen` and `partij` |
| No pagination on publications | ✅ Fixed | `?limit` (1–500) and `?offset` added |
| No batch endpoints | 🔴 Open | Clients must loop N times for N entities |
| No dossier→dossier related endpoint | 🔴 Open | No way to find related dossiers |
| No article→article references endpoint | 🔴 Open | Must traverse global graph |
| Instruments list has no search/filter | 🔴 Open | Returns all instruments |
| No activity stream / webhooks | 🔴 Open | No real-time updates |
| No `/api/health` endpoint | ✅ Fixed | `GET /api/health` returns `{status, database}` and 503 if DB unreachable |
| `citation_formats` removed with no replacement | 🔴 Open | Front-end has dead fallback to `metadata.bibtex`; neither exists in current API |

---

## 6. Bugs & Inconsistencies

| # | Severity | File | Status | Description |
|---|----------|------|--------|-------------|
| 1 | HIGH | `app.py` | ✅ Fixed | CORS origins moved to `LAWGRAPH_ALLOWED_ORIGINS` env var |
| 2 | HIGH | `routes/watches.py` | ✅ Fixed | Watch creation now validates `node_id` format, collection existence, and document existence |
| 3 | MEDIUM | `routes/dossiers.py` | ✅ Fixed | `order` param accepted any string; now `Literal["asc", "desc"]` with 422 on invalid value |
| 4 | LOW | all routes | ✅ Fixed | Mixed Dutch/English 404 messages; standardised to English |
| 5 | MEDIUM | `schemas.py` | 🔴 Open | `metadata` in `ArticleDetailResponse` only contains `judgment_count`; front-end `metadata.bibtex` fallback is dead code |
| 3 | MEDIUM | `schemas.py` | 938 | `PublicationSummary` uses `title`; `PublicationSummaryDTO` uses `titel` — inconsistent |
| 4 | MEDIUM | `schemas.py` | 494 | `kamerstuknummer` fallback returns `""` (empty string) instead of `null` |
| 5 | MEDIUM | `routes/search.py` | 70 | `score` hardcoded to `1.0` — no relevance ranking |
| 6 | MEDIUM | `routes/publications.py` | 35 | No LIMIT on publications query — returns all records |
| 7 | MEDIUM | `routes/dossiers.py` | 164 | `order` param not validated against `{"asc","desc"}` — invalid values silently default |
| 8 | LOW | `routes/dossiers.py` | 50 | 404 messages in Dutch, API otherwise English |
| 9 | LOW | `schemas.py` | 185 | JudgmentDTO summary falls back to `strafrecht_profile` without warning |
| 10 | LOW | `schemas.py` | 717 | `active_dossier_count` recomputed locally from dossier list vs. pre-computed value |
| 11 | LOW | `schemas.py` | 836 | Instrument `shorthand` falls back to `short_title` — no normalization |
| 12 | LOW | `routes/nodes.py` | 85 | Mixed 400/404 without OpenAPI distinction |

---

## 7. Improvement Recommendations

### P1 — Critical
1. Move CORS origins to env var (`LAWGRAPH_ALLOWED_ORIGINS`)
2. Validate `node_id` existence before creating a watch (return 400 if not found)
3. Standardize error messages to English

### P2 — High
4. Add pagination to `/api/publications` (default limit 50)
5. Add date-range filter to `/api/stemmingen` (`start_date`, `end_date`)
6. Add missing filter params: instrument search, commissie active-only
7. Normalize `titel` vs `title` across all DTOs

### P3 — Medium
8. Implement batch endpoints (`POST /api/dossiers/batch`, etc.)
9. Add cursor-based pagination for large result sets
10. Add `min_confidence` query param to graph endpoints
11. Add response caching headers (stable endpoints: 1 hour)
12. Add rate limiting middleware

### P4 — Nice-to-have
13. RDF/LinkedData export
14. Webhook subscriptions for dossier updates
15. Analytics/metrics endpoints
