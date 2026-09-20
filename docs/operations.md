# Operations

## Environment

All configuration is read in `src/lawgraph/config/settings.py`. Importing it loads `.env`
(searched from the working directory upwards), so every command, the API and any script sees
the same values; a variable already set in the process environment wins over `.env`. Copy
`.env.example` to `.env`.

### Database

| Variable | Default | Purpose |
|----------|---------|---------|
| `ARANGO_URL` | `http://localhost:8529` | server |
| `ARANGO_DB_NAME` | `lawgraph` | database; created on first use when it is missing, together with its collections, indexes and views |
| `ARANGO_USER` | `root` | user |
| `ARANGO_PASSWORD` | empty | password |
| `ARANGO_ROOT_PASSWORD` | none | read by `docker-compose.yml` for the root password of the container; set it equal to `ARANGO_PASSWORD` |

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
| `STAATSBLAD_SRU_ENDPOINT`, `STAATSCOURANT_SRU_ENDPOINT` | `https://repository.overheid.nl/sru` |
| `STAATSBLAD_REPO_BASE`, `STAATSCOURANT_REPO_BASE` | `https://repository.overheid.nl` |
| `KAMERSTUK_REPO_BASE` | `https://repository.overheid.nl` |
| `EERSTEKAMER_SRU` | `https://repository.overheid.nl/sru` |
| `ECHR_HUDOC_BASE` | `https://hudoc.echr.coe.int` |
| `VERDRAGENBANK_SRU` | `https://repository.overheid.nl/sru` |

### Pipelines

| Variable | Default | Purpose |
|----------|---------|---------|
| `BWB_IDS` | empty | comma-separated BWB ids for `retrieve bwb` in incremental mode |
| `EURLEX_MAX_ARTICLE_NUMBER` | `200` | EU articles above this number are not written |
| `LAWGRAPH_CONFIDENCE_<PATTERN_UPPER>` | code default | confidence of one `relation-semantics` pattern, for example `LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION=0.8` |
| `LAWGRAPH_<PHASE>_SKIP_<SOURCE>` | unset | `true` skips that step of `<phase> all` (see below) |

### API

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_API_HOST` / `LAWGRAPH_API_PORT` | `127.0.0.1` / `8000` | listen address of `lawgraph-api`; `0.0.0.0` serves other machines |
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
| `ALLOW_NETWORK_TESTS` | unset | `1` runs the tests that call the real APIs; shell only, the test suite ignores it in `.env` |
| `ALLOW_DB_TESTS` | unset | `1` runs `tests/test_aql_validity.py`: every static AQL query is explained by the real ArangoDB in a scratch database (a query the server rejects, such as one with `??`, fails only there); shell only |

## CLI

`lawgraph` or `python -m lawgraph`; `lawgraph <phase> <source> --help` shows the options of
a command. `--since` is the only date option: ISO 8601 (`2024-01-01`) or relative (`7d`). A relative value
reaches six hours further back than it says, so that runs that follow each other overlap: a
run that starts late or a source that indexes a change late leaves no hole, and everything
is an upsert.
Every command exits with code 1 when it raised or its result has errors; a composite command
(`<phase> all`, `bootstrap`, `expand-graph`) continues after a failing step unless `--strict`
and exits 1 when any step failed.

### retrieve

| Command | Options |
|---------|---------|
| `retrieve all` | `--mode incremental` (default) or `full`, `--since` (default `1d`), `--window DATE` (full mode; default `730d`, `all` for the whole history), `--jobs N` (default: one per server, 6). Incremental passes the mode and `--since` to `tk`, `rechtspraak`, `staatscourant`, `eerstekamer`, `echr`; `--since --skip-members` to `tk-dossiers`; the mode to `bwb`. Full passes the mode to `bwb` and, for the sources that keep producing (`tk`, `tk-dossiers`, `rechtspraak`, `staatscourant`, `eerstekamer`, `echr`), reads only what changed inside `--window` (as an incremental run since then); `--window all` reads their whole history. The reference sources (`bwb`, `verdragenbank`) are always read in full. `eurlex`, `staatsblad` and `verdragenbank` take nothing (`eurlex` fetches the acts already in the graph). `bwb-history` and `tk-content` are not run. `--jobs` retrieves that many sources at once; sources on one server (`tk` and `tk-dossiers`; `staatsblad`, `staatscourant`, `eerstekamer` and `verdragenbank`) run one after the other, and `--jobs 1` runs every source in turn. `staatsblad` reads the stored BWB toestanden, so it starts when `bwb` has ended (and last on its server, so the others do not wait with it) |
| `retrieve tk` | `--mode`, `--since` (default `1d`), `--limit N` |
| `retrieve tk-dossiers` | `--since`, `--decisions-since`, `--documents-since` (both override `--since` for one record kind), `--skip-members`, `--skip-decisions`, `--skip-documents`, `--dossier-number N` |
| `retrieve tk-content` | `--kind` (default `toelichting`), `--dry-run` |
| `retrieve rechtspraak` | `--court` (repeatable; default `hr`, `rvs`, `hoven`), `--mode`, `--since` (default `1d`), `--ecli` (repeatable) |
| `retrieve eurlex` | `--mode incremental\|full\|nim\|cjeu\|com`, `--celex` (repeatable), `--type directive\|regulation\|decision` (full mode, repeatable), `--lang NL`, `--country NLD` |
| `retrieve bwb` | `--mode`, `--bwb-id` (repeatable; default `BWB_IDS`) |
| `retrieve bwb-history` | optional BWB ids (all when omitted) |
| `retrieve staatsblad` | `--mode from-graph\|full` |
| `retrieve staatscourant` | `--mode`, `--since`, `--identifiers ...` |
| `retrieve echr` | `--mode`, `--since`, `--respondent`, `--max-records` |
| `retrieve eerstekamer` | `--mode`, `--since`, `--max-records` |
| `retrieve verdragenbank` | `--max-records` |

### normalize

`normalize all [--since DATE]` runs every source in registry order (`tk`, `tk-dossiers`,
`rechtspraak`, `eurlex`, `bwb`, `bwb-history`, `staatsblad`, `staatscourant`,
`eerstekamer`, `echr`, `verdragenbank`). Every `normalize <source>` accepts `--since DATE`: only raw records
fetched since then.

### semantic

`semantic all [--since DATE] [--strict]` runs the pipelines below in this order; `--since` is
passed to the pipelines that accept it and the others run in full.

| Command | Options |
|---------|---------|
| `tk`, `rechtspraak`, `eurlex` | `--since`: sources whose raw record was fetched since then |
| `bwb` | `--since` (as above), `--store-citations` |
| `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes` | none |
| `staatsblad`, `eerstekamer`, `echr` | none |
| `staatscourant` | `--since`: publications dated since then |
| `judgment-citations`, `judgment-appeal` | none |
| `instrument-relations` | `--since`: documents dated, and BWB records fetched, since then |
| `amendment-articles`, `mvt-articles`, `relation-semantics` | none |
| `list-stats` | `--dry-run`, `--instruments-only`, `--judgments-only`, `--committees-only`, `--articles-only`; backfills the sort and filter fields of the list endpoints |

The order is `tk`, `rechtspraak`, `eurlex`, `bwb`, `bwb-grondslagen`, `bwb-amendments`,
`bwb-annexes`, `staatsblad`, `staatscourant`, `eerstekamer`, `echr`, `judgment-citations`,
`judgment-appeal`, `instrument-relations`, `amendment-articles`, `mvt-articles`,
`relation-semantics`, `list-stats`.

### Other commands

| Command | Behaviour |
|---------|-----------|
| `lawgraph bootstrap [--window DATE] [--jobs N] [--max-expand N] [--skip-expand] [--strict] [--skip-retrieve]` | `retrieve all --mode full --window DATE --jobs N` (default `730d` and one job per server; `all` loads the whole history of the producing sources), `normalize all`, `semantic all`, then `expand-graph` (up to `--max-expand`, default 5) |
| `lawgraph expand-graph [--max-iterations N] [--dry-run]` | repeats `fill-gaps --apply`, `normalize all`, `semantic all` while stub nodes keep disappearing (default 10 iterations); `--dry-run` only prints the `fill-gaps` report |
| `lawgraph fill-gaps [--apply] [--min-stubs N] [--bwb-id ID ...] [--no-mvt] [--no-semantic] [--no-case-law] [--no-eurlex] [--no-echr] [--no-verdragen]` | reports stub laws (referenced by loaded instruments, ranked by reference count; laws with at least `--min-stubs`, default 3, are added), stub judgments, stub EU, ECHR and treaty records and toelichting texts without text; `--apply` retrieves and normalizes them |
| `lawgraph check [--skip-edges]` | asks the database what no step asks: does every raw kind of the registry hold records, does every source with raw records have nodes, does every edge have both its nodes, does every search view hold what its collection holds. Read-only, one query each; exits 1 on a problem. Run it after a load: a step can end successfully and leave nothing behind (a source that answers no records for a parameter it does not understand, a normalize step that never ran) |
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

**Full load.**

```bash
lawgraph retrieve all --mode full --window 730d
lawgraph retrieve bwb-history            # optional: every BWB toestand
lawgraph retrieve tk-content             # optional: MvT text, needed by amendment-articles
lawgraph retrieve rechtspraak --ecli ECLI:NL:HR:2023:1234 ...   # judgment content
lawgraph normalize all
lawgraph semantic all
```

`lawgraph bootstrap` runs the first, fifth and sixth step and then `expand-graph`. In full mode
`retrieve all` enumerates every BWB regulation; EU acts come from `expand-graph`, which fetches
the ones the loaded records refer to. The sources that keep producing (Tweede Kamer,
Rechtspraak, Staatscourant, Eerste Kamer, ECHR) load only the last two years, and
`expand-graph` later adds what the loaded records refer to. The whole history for research is
one option away: `--window all` (the Tweede Kamer alone is over 400K documents and hours), or
a date such as `--window 2015-01-01`.

**Incremental.**

```bash
lawgraph retrieve all --since 7d
lawgraph normalize all --since 7d
lawgraph semantic all --since 7d
```

Incremental `retrieve bwb` needs `BWB_IDS` or `--bwb-id`, otherwise it fetches nothing.
Law abbreviations (`instruments.props.short_title`, used by the citation detectors) come from
the WTI records that `retrieve bwb` stores and are written by `normalize bwb`, so run both
before `semantic`. `normalize bwb --since` still re-evaluates the short title of every
regulation, because an abbreviation claimed by a newly loaded regulation stops being unique.
Incremental `retrieve eurlex` re-fetches the CELEX numbers of the instruments already in the
graph. `verdragenbank` has no date filter and reads all treaties; `staatsblad` reads the stored BWB XML. Scheduling is not wired: run the commands from cron or a
scheduler of your choice.

**Slow steps.**

| Step | Why |
|------|-----|
| `retrieve tk-content` | one XML per paper (up to several MB), paced at 0.5 s |
| `retrieve tk-dossiers` full | about 400K documents, fetched 250 at a time |
| `retrieve bwb --mode full`, `retrieve bwb-history` | `bwb`: the SRU listing, then one XML download and one short WTI request (about 1 KB read) per regulation whose current toestand is not the stored one (an unchanged regulation costs nothing; its WTI file is read again after 30 days). `bwb-history`: one SRU query per regulation and one download per toestand |
| `normalize bwb-history`, `semantic bwb-grondslagen`, `bwb-annexes` | stream every stored toestand XML (large documents) in batches of 20 |
| `normalize tk-dossiers` | the largest normalize step (documents, decisions, edges, dossier backfill) |
| `semantic bwb` | scans every article text |

Every retrieve and normalize step is idempotent and safe to interrupt and re-run.

**Pacing.** Every client waits between requests to one host (`HOST_MIN_INTERVAL` in
`config/constants.py`, 0.1 to 0.5 s, 0.2 s for an unlisted host). A host that answers HTTP
429 or 503 makes the interval double, up to 10 s, or follow its `Retry-After`; it shrinks
back while requests succeed (halved after 35 of them). HTTP 429, 502, 503, 504 and connection errors are retried five
times with a growing pause. `repository.overheid.nl` was measured to throttle from about five
requests per second sustained, so the base interval there is 0.5 s. A `throttling` warning in
the log means the pacer is slowing down; it is not an error. It appears at most once a minute
per host, with the number of HTTP 429/503 answers since the last one; the retries themselves
are logged at `DEBUG`. The pacer is shared inside one process. The first process that reaches a
host holds a lock file for it (in `~/.cache/lawgraph`); a second `lawgraph` process finds
it taken, says so once and paces that host at half speed, so two commands started side by
side stay under the limit together.

**Database volumes.** The data is in two Docker volumes that `docker-compose.yml` declares
`external`: compose uses them and cannot remove them. Create them once
(`docker volume create lawgraph_arango_data && docker volume create lawgraph_arango_apps`),
then `docker compose up -d`. `docker compose down -v` removes every volume a project owns,
also with `--profile`, and that is how this database was lost once; the test database is a
compose project of its own for the same reason.

**Database memory.** ArangoDB sizes its caches from the memory it sees and has no limit of
its own. In Docker that is the whole VM: on an 8 GB VM it grew until the kernel killed it (exit
137, `OOMKilled`) in the middle of a load, which also left a search view out of sync.
`docker-compose.yml` bounds the block cache, the write buffers, the edge cache and the query
memory, sets `mem_limit: 5g` and restarts the server when it stops. A bulk write is sent again
(after 2, 10 and 30 seconds) while the database is unreachable, so a restart costs a run
nothing; when it stays away the step ends there instead of fetching on. A view the server
log reports as `out of sync` is rebuilt by dropping it and starting any command
(`ArangoStore()` creates what is missing).

**Interruptions.** A retrieve stores its records while it fetches, a buffer at a time
(`RawSourceWriter`: 500 records, 8 MB of text or 5 seconds, whichever comes first). An
interrupt and a failing source write the buffer before the step ends, so they keep everything
fetched, and a failure in the middle is an error of the step, not a silent stop. A crash of
the process or the machine loses at most that last buffer. A step that downloads one document per record (`staatscourant`, `bwb`, `eurlex`)
skips the records stored in the last 24 hours, so a re-run only does the rest. A refresh
later downloads what the source lists as new or changed: a Staatscourant or Staatsblad
publication stored after its `modified` date, a BWB toestand that is still the stored one and
a judgment not updated since are left alone; a document that answered HTTP 404 is asked for
again after 30 days. The Tweede Kamer pages are read again from the start on a
re-run (upserts, so only time is repeated).

## Observability

- Logging: `lawgraph.core.logging`; format `time [LEVEL] [step] logger: message`, JSON (with a
  `step` field) with `LAWGRAPH_LOG_FORMAT=json`, level from `LAWGRAPH_LOG_LEVEL`. The step is
  the command a line belongs to (`retrieve staatscourant`, `normalize tk-dossiers`), so lines of
  sources retrieved side by side (`--jobs`) can be told apart; the logger name is shown without
  `lawgraph.`. Lines of the orchestrators carry `retrieve all`, `bootstrap` and so on.
- A step opens with what it does and its options (`starting — Ministerial regulations from the
  Staatscourant. (--mode incremental --since 2024-09-20)`) and closes with how long it took.
  `lawgraph sources` prints what every source and phase does; retrieve commands that are not part
  of `retrieve all` are marked.
- Each pipeline logs `PipelineResult.summary()` (created, updated, skipped, errors) and its
  duration; errors are listed and set exit code 1. Orchestrators print a per-step summary table
  at the end.
- Progress (`core/progress.py`, used by every retrieve): no line per record. Once a minute a
  status line `12,400 / 34,593 (36%) judgments · 4.9/s · ~1h12m left · 3 skipped · 0 errors`
  (the total when the source gives one: an index, a list of ids, the OData `$count`), and at
  the end one summary with the duration and the count per outcome and per reason. A reason to
  skip or fail is logged once, with the first record it happened to; the following ones are
  counted and logged at `DEBUG`. A cause of failure is one error of the result
  (`25 x download failed (HTTP 500) (first: ...)`).
- `is throttling` warnings come from the request pacer (see Pacing), not from an error.
- API: each request is logged with id, client, method, path, status, size and latency;
  `GET /api/health` checks the database connection; `GET /api/stats` gives counts per
  collection and relation.

## Tests and CI

```bash
pytest tests -q                       # several hundred tests, offline, a few seconds
ALLOW_NETWORK_TESTS=1 pytest tests    # also calls the real APIs
ruff check src tests
ruff format --check src tests
```

The suite uses an in-memory fake store and real XML fixtures (`tests/fixtures/`); no unit
test executes AQL, but `ALLOW_DB_TESTS=1` has the server validate every static query.

What only a server shows is in `tests/integration`: the real code and the real CLI against a
second, deliberately small ArangoDB (`docker-compose.test.yml`, a compose project of its own: port 8530, 1 GB
of memory, 256 MiB per query, a throw-away volume; never the database of `.env`).

```bash
docker compose -f docker-compose.test.yml up -d
ALLOW_DB_TESTS=1 pytest tests/integration     # two minutes
docker compose -f docker-compose.test.yml down
```

It seeds raw records in the shapes of the sources at any scale (`seed.py`) and checks: a
result larger than the server may hold in memory streams; `normalize all` and `semantic all`
produce every part of the model and a second run changes nothing; `lawgraph check` finds a
source that was never normalized and an edge without its node; a database that restarts in
the middle of a run, and a run that is killed, cost a re-run at most; a stub that is loaded
stops being a stub; an incremental run links to what was loaded earlier. A problem found in
a real run gets a test here first: small data on a small server fails the way the corpus
does on the real one. Layout: `tests/api/` (routes), `tests/normalize/` and
`tests/semantic/` (one file per source or detector), `tests/test_*.py` (clients, core helpers,
bulk writers, registry, naming, conventions, relation catalogue, props). CI (`.github/workflows`) runs
`pytest` on Python 3.11 and 3.14 and the pre-commit hooks: ruff `--fix`, ruff format, end-of-file,
trailing whitespace, private-key detection, YAML and merge-conflict checks.
