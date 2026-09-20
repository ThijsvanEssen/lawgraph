# Operations

## Environment

Variables are read from the process environment; `lawgraph`, `lawgraph-api` and the commands
load `.env` first (`python-dotenv`). Copy `.env.example` to `.env`. `.env.example` also lists
`PIPELINE_LOG_LEVEL` and `LAWGRAPH_PROFILE`; nothing reads them.

### Database

| Variable | Default | Purpose |
|----------|---------|---------|
| `ARANGO_URL` | `http://localhost:8529` | server |
| `ARANGO_DB_NAME` | `lawgraph` | database; it must exist, the application creates collections, indexes and views inside it |
| `ARANGO_USER` | `root` | user |
| `ARANGO_PASSWORD` | empty | password |
| `ARANGO_ROOT_PASSWORD` | none | read by `docker-compose.yml` for the root password of the container; set it equal to `ARANGO_PASSWORD` |
| `LAWGRAPH_EDGE_COLLECTION` | `edges` | edge collection name |
| `LAWGRAPH_DOCUMENT_COLLECTIONS` | all collections | comma-separated override; must list every collection the code uses |

### External sources

All default to the public endpoints; no key is required.

| Variable | Default |
|----------|---------|
| `TK_API_BASE` | `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/` |
| `RECHTSPRAAK_BASE` | `https://data.rechtspraak.nl/` |
| `EURLEX_BASE` | `https://eur-lex.europa.eu/` |
| `EURLEX_SPARQL_ENDPOINT` | `https://publications.europa.eu/webapi/rdf/sparql` |
| `BWB_BASE` | `https://wetten.overheid.nl/` |
| `BWB_SRU_ENDPOINT` | `https://zoekservice.overheid.nl/sru/Search` |
| `STAATSBLAD_SRU_ENDPOINT`, `STAATSCOURANT_SRU_ENDPOINT` | `https://sru.officielebekendmakingen.nl/sru/Search` |
| `STAATSBLAD_REPO_BASE`, `STAATSCOURANT_REPO_BASE` | `https://repository.overheid.nl` |
| `EERSTEKAMER_BASE` | `https://gegevensmagazijn.eerstekamer.nl/OData/v4/2.0/` |
| `ECHR_HUDOC_BASE` | `https://hudoc.echr.coe.int` |
| `VERDRAGENBANK_SPARQL` | `https://linkeddata.overheid.nl/front/portal/sparql` |

### Pipelines

| Variable | Default | Purpose |
|----------|---------|---------|
| `BWB_IDS` | empty | comma-separated BWB ids for `retrieve bwb` in incremental mode |
| `EURLEX_MAX_ARTICLE_NUMBER` | `200` | EU articles above this number are not written (read at import) |
| `LAWGRAPH_CONFIDENCE_<PATTERN_UPPER>` | code default | confidence of one `relation-semantics` pattern, for example `LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION=0.8` |
| `LAWGRAPH_<PHASE>_SKIP_<SOURCE>` | unset | `true` skips that step of `<phase> all` (see below) |

### API

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_API_HOST` / `LAWGRAPH_API_PORT` | `0.0.0.0` / `8000` | listen address of `lawgraph-api` |
| `LAWGRAPH_ALLOWED_ORIGINS` | `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:5174`, `http://127.0.0.1:5174` | CORS allow-list; these origins also bypass the rate limit |
| `LAWGRAPH_RATE_LIMIT_CALLS` / `LAWGRAPH_RATE_LIMIT_PERIOD` | `200` / `60` | requests per window (seconds) per IP |
| `LAWGRAPH_TRUSTED_PROXIES` | loopback | proxies whose `X-Forwarded-For` is honoured |
| `LAWGRAPH_CACHE_TTL` / `LAWGRAPH_CACHE_MAXSIZE` | `60` / `512` | in-process cache of some routes |
| `LAWGRAPH_CURATION_API_KEY` | unset | enables `POST /api/relationships/tag` |

### Logging and tests

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_LOG_LEVEL` | `INFO` | root log level |
| `LAWGRAPH_LOG_FORMAT` | plain | `json` for one JSON object per line |
| `NO_COLOR` | unset | disables ANSI colours |
| `ALLOW_NETWORK_TESTS` | unset | `1` runs the tests that call the real APIs |

## CLI

`lawgraph` or `python -m lawgraph`; `lawgraph <phase> <source> --help` shows the options of
a command. Dates (`--since`) are ISO 8601 (`2024-01-01`) or relative (`7d`). Every step
exits with code 1 when its result has errors.

### retrieve

| Command | Options |
|---------|---------|
| `retrieve all` | `--mode incremental` (default) or `full`, `--since-days N` (default 1). Passes to each source: `tk` and `rechtspraak` mode and days; `tk-dossiers` nothing in full mode, `--since Nd --skip-members --decisions-since Nd --documents-since Nd` in incremental mode; `eurlex`, `bwb`, `staatscourant`, `eerstekamer`, `echr` the mode; `staatsblad`, `verdragenbank` nothing. `bwb-history` and `tk-content` are not run |
| `retrieve tk` | `--mode`, `--since-days`, `--limit N` |
| `retrieve tk-dossiers` | `--since`, `--skip-members`, `--skip-decisions`, `--decisions-since`, `--skip-documents`, `--documents-since`, `--dossier-number N` |
| `retrieve tk-content` | `--kind` (default `toelichting`), `--dry-run` |
| `retrieve rechtspraak` | `--mode`, `--since-days`, `--ecli` (repeatable) |
| `retrieve eurlex` | `--mode incremental\|full\|nim\|cjeu\|com`, `--celex` (repeatable), `--lang NL`, `--country NLD` |
| `retrieve bwb` | `--mode`, `--bwb-id` (repeatable) |
| `retrieve bwb-history` | optional BWB ids (all when omitted) |
| `retrieve staatsblad` | `--mode from-graph\|full` |
| `retrieve staatscourant` | `--mode`, `--since`, `--identifiers ...` |
| `retrieve eerstekamer` | `--mode`, `--since`, `--max-records` |
| `retrieve echr` | `--mode`, `--respondent`, `--since`, `--max-records` |
| `retrieve verdragenbank` | `--max-records` |

### normalize

`normalize all` takes no options and runs every source in registry order (`tk`, `tk-dossiers`,
`rechtspraak`, `eurlex`, `bwb`, `bwb-history`, `staatsblad`, `staatscourant`, `eerstekamer`,
`echr`, `verdragenbank`). `normalize <source> --since DATE` (only records fetched since) is
accepted by `tk`, `tk-dossiers`, `rechtspraak`, `eurlex`, `bwb`, `bwb-history` and `staatsblad`;
the others take no options.

### semantic

`semantic all [--strict]` runs the pipelines below in this order, then the `list_stats`
backfill; `--strict` aborts at the first failure.

| Command | Options |
|---------|---------|
| `tk`, `rechtspraak`, `eurlex` | `--since-days N` (0 = everything); resolved against `raw_sources.fetched_at` |
| `bwb` | `--store-citations`; `--since-days` is not exposed |
| `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes` | none |
| `staatscourant`, `eerstekamer`, `echr` | none |
| `staatsblad` | `--since DATE`, which the pipeline ignores |
| `judgment-citations`, `amendment-articles` | `--since-days N`, and `mvt-articles` `--since DATE`; all three filter on `props.fetched_at`, which no pipeline writes, so a value other than the default processes nothing |
| `judgment-appeal`, `instrument-relations`, `relation-semantics` | none |

The order is `tk`, `rechtspraak`, `eurlex`, `bwb`, `bwb-grondslagen`, `bwb-amendments`,
`bwb-annexes`, `staatsblad`, `staatscourant`, `eerstekamer`, `echr`, `judgment-citations`,
`judgment-appeal`, `instrument-relations`, `amendment-articles`, `mvt-articles`,
`relation-semantics`.

### Other commands

| Command | Behaviour |
|---------|-----------|
| `lawgraph bootstrap [--max-expand N] [--skip-expand] [--strict] [--skip-retrieve]` | `retrieve all --mode full`, `normalize all`, `semantic all`, then `expand-graph` (up to `--max-expand`, default 5) |
| `lawgraph expand-graph [--max-iterations N] [--dry-run]` | repeats `fill-gaps --apply`, `normalize all`, `semantic all` while stub nodes keep disappearing (default 10 iterations) |
| `lawgraph fill-gaps [--apply] [--min-stubs N] [--bwb-id ID ...] [--no-mvt] [--no-semantic] [--no-case-law] [--no-eurlex] [--no-echr] [--no-verdragen]` | reports stub laws (referenced by loaded instruments, ranked by reference count; laws with at least `--min-stubs`, default 3, are added), stub judgments, stub EU, ECHR and treaty records and toelichting texts without text; `--apply` retrieves and normalizes them |
| `python -m lawgraph.pipelines.list_stats [--dry-run] [--instruments-only\|--judgments-only\|--committees-only\|--articles-only]` | backfills sort and filter fields for the list endpoints |
| `lawgraph-api` | starts the API |

### Skip variables

`LAWGRAPH_<PHASE>_SKIP_<SOURCE>=true` (case-insensitive `true`; any other value does not skip)
skips one step of `retrieve all`, `normalize all` or `semantic all`. `<SOURCE>` is the source id
in upper case with underscores.

| Phase | Sources |
|-------|---------|
| `RETRIEVE` | `TK`, `TK_DOSSIERS`, `RECHTSPRAAK`, `EURLEX`, `BWB`, `STAATSBLAD`, `STAATSCOURANT`, `EERSTEKAMER`, `ECHR`, `VERDRAGENBANK` |
| `NORMALIZE` | the same plus `BWB_HISTORY` |
| `SEMANTIC` | `TK`, `RECHTSPRAAK`, `EURLEX`, `BWB`, `BWB_GRONDSLAGEN`, `BWB_AMENDMENTS`, `BWB_ANNEXES`, `STAATSBLAD`, `STAATSCOURANT`, `EERSTEKAMER`, `ECHR`, `JUDGMENT_CITATIONS`, `JUDGMENT_APPEAL`, `INSTRUMENT_RELATIONS`, `AMENDMENT_ARTICLES`, `MVT_ARTICLES`, `RELATION_SEMANTICS`, `LIST_STATS` |

## Runs

**Full load.** Create the database first (`ARANGO_DB_NAME`, for example in the web UI at
`http://localhost:8529`).

```bash
lawgraph retrieve all --mode full
lawgraph retrieve bwb-history            # optional: every BWB toestand
lawgraph retrieve tk-content             # optional: MvT text, needed by amendment-articles
lawgraph retrieve rechtspraak --ecli ECLI:NL:HR:2023:1234 ...   # judgment content
lawgraph normalize all
lawgraph semantic all
```

`lawgraph bootstrap` runs the first, fifth and sixth step and then `expand-graph`. In full mode
`retrieve all` enumerates every BWB regulation and every EUR-Lex act; `tk-dossiers` fetches
everything unless run directly with `--documents-since 730d`.

**Incremental.**

```bash
lawgraph retrieve all --mode incremental --since-days 7
lawgraph normalize all                   # no --since here; use per-source --since to limit work
lawgraph semantic all
```

Incremental `retrieve bwb` needs `BWB_IDS` or `--bwb-id`, otherwise it fetches nothing.
Incremental `retrieve eurlex` re-fetches the CELEX numbers of the instruments already in the
graph. Incremental `staatscourant`, `eerstekamer`, `echr` and `verdragenbank` read all
records up to their record caps. Scheduling is not wired: run the commands from cron or a
scheduler of your choice.

**Slow steps.**

| Step | Why |
|------|-----|
| `retrieve tk-content` | one PDF per document, 0.5 s between requests |
| `retrieve tk-dossiers` full | about 400K documents, fetched 250 at a time |
| `retrieve bwb --mode full`, `retrieve bwb-history` | one SRU query and one XML download per regulation or toestand |
| `normalize bwb-history`, `semantic bwb-grondslagen`, `bwb-annexes` | stream every stored toestand XML (large documents) in batches of 20 |
| `normalize tk-dossiers` | the largest normalize step (documents, decisions, edges, dossier backfill) |
| `semantic bwb` | scans every article text |

Every retrieve and normalize step is idempotent and safe to interrupt and re-run.

## Observability

- Logging: `lawgraph.core.logging`; format `time [LEVEL] logger: message`, JSON with
  `LAWGRAPH_LOG_FORMAT=json`, level from `LAWGRAPH_LOG_LEVEL`.
- Each pipeline logs `PipelineResult.summary()` (created, updated, skipped, errors); errors are
  listed and set exit code 1. Orchestrators print a per-step summary table at the end.
- API: each request is logged with id, client, method, path, status, size and latency;
  `GET /api/health` checks the database connection; `GET /api/stats` gives counts per
  collection and relation.

## Tests and CI

```bash
pytest tests -q                       # several hundred tests, offline, a few seconds
ALLOW_NETWORK_TESTS=1 pytest tests    # also calls the real APIs
ruff check src tests
```

The suite uses an in-memory fake store and real XML fixtures (`tests/fixtures/`); no test
executes AQL against a database. Layout: `tests/api/` (routes), `tests/normalize/` and
`tests/semantic/` (one file per source or detector), `tests/test_*.py` (clients, core helpers,
bulk writers, registry, naming, conventions, relation catalogue, props). CI (`.github/workflows`) runs
`pytest` on Python 3.11 and the pre-commit hooks: black, ruff `--fix`, isort, end-of-file,
trailing whitespace, private-key detection, YAML and merge-conflict checks.
