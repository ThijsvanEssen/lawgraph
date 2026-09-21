# API

A FastAPI service over the graph (`lawgraph.api.app:app`), read-only except for watches and
semantic-relationship curation. Start it with
`lawgraph-api` (uvicorn, `LAWGRAPH_API_HOST`:`LAWGRAPH_API_PORT`, default `127.0.0.1:8000`; set the host to `0.0.0.0` to serve other machines) or
`uvicorn lawgraph.api.app:app --reload`. The interactive schema is at `/docs`, the machine
schema at `/openapi.json`: every route has a summary, a tag and a typed answer, and a route
that writes names its key (`tests/api/test_openapi_schema.py` holds the schema to that), so
a client can generate its types from it. The write endpoints are `POST` and `DELETE` on `/api/watches` and
the two `POST` endpoints under `/api/relationships`.

## Endpoints

Paths are relative to the host. `bwb_id` is a BWB id (`BWBR0001854`); a dossier `number`
matches `^\d+(-[A-Za-z]+)?$` (`29684`, `29684-I`), otherwise 422. List parameters `limit` and
`offset` have the bounds shown in `/docs`.

### Service

| Method | Path | Response |
|--------|------|----------|
| GET | `/` | `{"name": "lawgraph-api", "version": ...}` |
| GET | `/api/health` | `{"status": "ok", "database": "connected"}`, 503 when the database is unreachable |
| GET | `/api/stats` | document count per collection and edge count per relation |

### Articles

| Path | Returns |
|------|---------|
| `/api/articles/{bwb_id}/{article_number}` | the article, its instrument, citing judgments and citations |
| `.../history` | every version of the article, oldest first: validity period, text, `effect`, normalized `change` (`introduces`, `amends`, `repeals`), amending publication (`amended_by`) and commencement publication, each with its dossiers. The article is identified by `stam_id`, so renumbering does not break history; 404 for an unknown article |
| `.../legislative-history` | dossiers and documents that introduced, amended or propose to amend the article, including `voorgesteld`; empty list, never 404 |
| `.../in-flux` | whether an open bill targets the article: `{in_flux, open_dossier_count}`; never 404 |
| `.../relationships` | outgoing and incoming references with `semantic_type`, explanation, badge, community votes, and annex scopes |

### Instruments and annexes

| Path | Returns |
|------|---------|
| `GET /api/instruments` | paged list; `q`, `jurisdiction` (`nl`, `eu`), `kind`, `article_count_min`, `sort` (default `title`) |
| `/api/instruments/{bwb_id}/articles` | articles in natural order (`24` before `24c` before `25`); `include_stubs`, `text_preview_chars`, `limit` (max 2000), `offset` |
| `.../articles/at/{at_date}` | article versions valid on `YYYY-MM-DD` (`valid_from <= date < valid_until`) |
| `.../versions` | every toestand, newest first, `current` flagged |
| `.../amended-by` | amending publications (Staatsblad, Tractatenblad, ...) with edge counts per kind, articles affected, first effective date and dossiers; `limit`, `offset` |
| `.../dossiers` | dossiers through `LEGISLATED_IN` from the regulation itself (`via: instrument`) and from its amending publications (`via: amending_publication`, `publication` = newest) |
| `.../citations` | all edges touching the regulation's articles in one call; `relations` whitelist, `include_part_of` (default false), `max_edges` (default 20,000) |
| `.../judgments` | citing judgments with the cited articles |
| `.../related-instruments` | per related instrument, inbound and outbound article-level `REFERS_TO` counts |
| `.../cross-law-dependencies` | article references to other laws, with semantic type |
| `.../shared-annexes` | annexes shared with other laws |
| `GET /api/annexes` | annexes; `bwb_id`, `shared_across_laws` |
| `/api/annexes/{key}` and `.../referenced-by` | one annex with entries; the articles that scope by it |

### Judgments

| Path | Returns |
|------|---------|
| `GET /api/judgments` | paged list; `q`, `court` (ECLI code), `tier` (`hoge_raad`, `gerechtshof`, `rechtbank`, `bijzonder`), `source`, `from`, `to`, `cited_by_min`, `sort` (`date_desc`, `date_asc`, `citation_count`) |
| `/api/judgments/{ecli}` | the judgment with the articles its `REFERS_TO` edges point at, each with its parent instrument |

### Parliament

| Path | Returns |
|------|---------|
| `GET /api/dossiers/open` | dossiers not yet closed; `committee` (slug), `subject`, `stage`, `has_stage` (all listed stages), `limit`, `offset` |
| `/api/dossiers/recent` | dossiers with activity in `days` (default 30) |
| `/api/dossiers/{number}` | header, current stage, counts of documents, activities, decisions, commitments |
| `.../timeline` | documents, activities, decisions and commitments; `order` (`desc`, `asc`), `kind` (comma-separated), `limit` |
| `.../documents` | documents linked directly or through a case, newest first, with `total` |
| `.../mutations` | the subgraph of `voorgesteld` edges, in graph shape |
| `/api/dossiers/documents/bulk?numbers=a,b` | top `per_dossier_limit` (default 8) documents per dossier |
| `GET /api/decisions`, `/{key}`, `/{key}/document` | decisions (`passed`, `party`, `chamber` `TK`/`EK`; the Eerste Kamer has papers but no votes) with every vote cast — per member on a roll-call, per faction otherwise; the decided motion, amendment or bill with text |
| `GET /api/committees`, `/with-members`, `/{slug}` | committees; detail lists current members (`current_only=true`, the default) and the dossiers it leads |
| `GET /api/members`, `/{key}`, `/{key}/votes`, `/{key}/touched-instruments` | members (filter `party`, `active`, `q`; ministers only with `include_all`); a member's votes, a faction vote counted only for the period they belonged to it; laws the member proposed changes to |
| `GET /api/factions`, `/{key}`, `/{key}/touched-instruments` | factions with member counts; the same aggregate per faction |
| `GET /api/parliament/seats` | seated factions with seat counts in plenary-hall order |
| `GET /api/parties/colors` | party abbreviation to hex colour |
| `GET /api/documents`, `/{key}` | documents across sources, metadata only (`q`, `kind`, `chamber`, `source`, `limit` up to 1000); one with its extracted text (null when `normalize tk-content` has not reached it) |

### Graph, search, nodes

| Path | Returns |
|------|---------|
| `GET /api/graph/global` | instruments, articles, judgments and edges; `include_judgments`, `max_judgments` |
| `/api/graph/instruments` | instruments as nodes, edges aggregated from article-level `REFERS_TO` plus the direct `IMPLEMENTS` and `AMENDS` edges |
| `/api/graph/judgments` | judgments and their edges; `max_judgments`, `include_stubs` |
| `/api/nodes/{collection}/{key}` | a node with all neighbours, direction and confidence; `neighbor_limit` |
| `.../neighborhood` | nodes and edges within `depth` (1-4) hops, capped by `cap` |
| `/api/nodes/in-flux`, `/api/nodes/heat` | node id to count of open proposed mutations; node id to incoming edges created in the last `months` (default 6), `min_count`. Both answer a plain map (`{"articles/bwbr0001854_287": 3}`), not validated through a response model |
| `GET /api/search?q=` | text search over `types` (`articles`, `committees`, `documents`, `dossiers`, `factions`, `instruments`, `judgments`, `members`; all by default), `kind`, `limit`; every hit has `score` 1.0 (no ranking) |

### Semantic relationships and watches

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/relationships/types` | the seven semantic types and four sources |
| GET | `/api/relationships/search` | classified article relations; `type`, `law` (`bwb_id` of the source article) |
| POST | `/api/relationships/tag` | creates or updates a `REFERS_TO` edge with `semantic_type`; body `source_article`, `target_article` (`BWBR0001854/287`), `semantic_type`, `explanation`, `semantic_source`, `expert_badge`, `created_by`; needs `X-Curation-Key` |
| POST | `/api/relationships/{edge_id}/vote` | body `{"vote": "upvote" or "downvote"}`; increments the community counter |
| GET, POST, DELETE | `/api/watches`, `/api/watches/{watch_id}` | saved node watches: list (newest first), create (201; 400 when `node_id` is malformed or the node does not exist), delete (204, 404) |

## Response conventions

- Every DTO forbids unknown fields (`extra="forbid"`).
- Node references use `id` (`collection/key`) and `key`; edges use `from` and `to`.
- List responses carry `items` and `total`, the absolute number of matches independent of
  `limit`. Some carry a domain name instead of `items` (`entries` for timelines, `versions`,
  `votes`, `relationships`).
- Errors: 401 missing or wrong key, 404 unknown resource, 422 invalid parameter, 429 rate
  limited, 503 database unreachable or writing not configured.
- Responses of the route handlers carry an `X-Request-ID` header.

## Layout

| Path | Contents |
|------|----------|
| `api/app.py` | app, middleware, router registration, `lawgraph-api` entry point |
| `api/routes/` | one module per domain (`articles`, `instruments`, `judgments`, `dossiers` (also `parties`), `committees` (also `members` and `factions`), `decisions`, `documents`, `graph`, `nodes`, `search`, `stats`, `watches`, `relationships`, `annexes`, `parliament`) |
| `api/queries/` | AQL per domain; user input only through bind variables |
| `api/schemas/` | Pydantic DTOs, one module per route module; shared ones in `common.py` |
| `api/dependencies.py` | `get_store()`: one shared `ArangoStore`; the two keys and `refuse_open_writes` |
| `api/cache.py` | `TTLCache`: in-process LRU with TTL (`LAWGRAPH_CACHE_TTL` 60 s, `LAWGRAPH_CACHE_MAXSIZE` 512) used by several routes |

## Middleware

| Middleware | Behaviour |
|------------|-----------|
| CORS | origins from `LAWGRAPH_ALLOWED_ORIGINS` (default `localhost:5173`, `5174`, `127.0.0.1` variants); credentials allowed |
| Rate limit | sliding window per client IP: `LAWGRAPH_RATE_LIMIT_CALLS` (200) per `LAWGRAPH_RATE_LIMIT_PERIOD` seconds (60); 429 with `Retry-After`. Requests whose `Origin` is in the CORS allow-list are exempt. `X-Forwarded-For` is honoured only from loopback or `LAWGRAPH_TRUSTED_PROXIES`. State is per process, so N workers allow N times the limit |
| Cache-Control | on 2xx GET: `/api/articles/` 30 min public, `/api/judgments/` 1 h public, `/api/stats` 5 min public, everything else `private, max-age=60` |
| Request log | `[id] client METHOD path -> status size latency`; sets `X-Request-ID` |

## Authentication

Reads are public. Every route that writes asks for a shared key, compared in constant time:

| Header | Variable | Routes |
|--------|----------|--------|
| `X-Write-Key` | `LAWGRAPH_WRITE_API_KEY` | `POST` and `DELETE` on `/api/watches`, `POST /api/relationships/{edge_id}/vote` |
| `X-Curation-Key` | `LAWGRAPH_CURATION_API_KEY` | `POST /api/relationships/tag` |

The schema declares both as API keys, so `/docs` has an Authorize button. Without the
variable the routes answer 503 (an API nobody configured writes nothing), with a
missing or wrong key 401. `refuse_open_writes` (`api/dependencies.py`) runs when the app is
built and stops it when a route that writes asks for neither key.

The keys are for a server to send. A browser app cannot keep one: it calls a route of its own
server, which holds the key and passes the request on. There are no users or roles, so a vote
is not tied to a person and a watch list is one list for the deployment.
