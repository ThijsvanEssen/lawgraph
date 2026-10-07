# Operations

## Environment

All configuration is read in `src/lawgraph/config/settings.py`. Importing it loads `.env`
(searched from the working directory upwards), so every command, the API and any script sees
the same values; a variable already set in the process environment wins over `.env`. Copy
`.env.example` to `.env`.

### Database

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_DB_URL` | `postgresql://lawgraph:<LAWGRAPH_DB_PASSWORD>@localhost:5432` | PostgreSQL server (`postgresql://user:password@host:port`); without it, the server of `docker-compose.yml` with `LAWGRAPH_DB_PASSWORD` |
| `LAWGRAPH_DB_PASSWORD` | none | password of the user `lawgraph`; `docker-compose.yml` gives the server this password |
| `LAWGRAPH_DB_NAME` | `lawgraph` | database; created on first use when it is missing and the user may, together with its tables, indexes and functions (`db/schema.py`). A database whose tables lack a column of the schema, or have one it no longer has, is refused at the start ("schema verouderd: herbouw nodig"): build it again. So is a database that does not sort strings by the ICU collation `und-u-kf-upper` lawgraph makes its databases with (`create_database_sql`): the feed, the dossier and paper kinds and every sort by a name rely on it. The postgres image of `docker-compose.yml` makes its first database with it (`POSTGRES_INITDB_ARGS`); one made otherwise is moved into a database lawgraph makes, by a dump and a restore |
| `LAWGRAPH_ALLOW_COLLATION` | none | the collation of a database let through anyway, as the refusal names it (`libc en_US.utf8`): for the dump and restore that replaces it, never for a running API |
| `LAWGRAPH_DB_POOL_SIZE` | `8` | connections per process, all opened at the start; a query borrows one only while it reads. N API processes open at most N × this many connections. Every connection runs without JIT compilation (`jit = off`): for the statements of the API it costs more than it gains; set it on the server too |
| `LAWGRAPH_DB_BACKGROUND_POOL_SIZE` | `4` | connections per API process for what it computes in the background (the warm-up, the answers it keeps per data version such as the facets of a filtered list, the statistics of the search, the heat), apart from the ones above and opened when first needed: a slow computation never keeps a request waiting for a connection. One for each of the three computations at a time and one for the warm-up |
| `LAWGRAPH_WRITE_TIMEOUT_MS` | `600000` | the longest a statement that writes may run (`statement_timeout`), in milliseconds; a ceiling, never off (0 is refused). A build setting: a full build on a slow disk raises it (the server: `14400000`, four hours). The writes that find their rows across a whole table (`graph-list-stats`, the removals of edges and nodes a step no longer derives) read those rows first and write them 5,000 at a time, so they stay well below it |
| `LAWGRAPH_READ_TIMEOUT_MS` | `10800000` | the longest one statement that reads may run (`statement_timeout`), in milliseconds; a ceiling, never off (0 is refused). A streamed read is a statement per batch of rows, so only a plan that never ends hits it: the step fails with `ReadTimedOut`, naming the setting and the statement, instead of hanging. In the API a request has `LAWGRAPH_API_REQUEST_TIMEOUT_MS` in all as well |
| `LAWGRAPH_API_REQUEST_TIMEOUT_MS` | `30000` | the longest one request to the API may read the database, in milliseconds, in all: every statement of it gets what is left, and past it the request answers 503 with `Retry-After` instead of computing on after its client gave up; never off (0 is refused) |
| `LAWGRAPH_API_WARM_UP` | `true` | the API computes the answers every visitor asks (the facets and totals of the unfiltered lists, `/api/stats`, coverage, the statistics of the search, the pages of the newest cabinets) at its start and, after a change of the data, once the data version has stood still for 90 s (a run of the pipelines raises it with every write), in the background: one warm-up at a time, of the newest data, and one that sees newer data between its parts stops and starts again later, and keeps them until the next change (`db/version_cache.py`); a request waits for one no longer than its deadline (then 503) while it is computed on, and after a change of the data no longer than 2 s before it takes the answer of the version before (the statistics of the search come from a fixed sample of a large table and are kept 6 hours whatever the data does); `false` leaves the first visitor to ask ; `/api/health` says `warm` true once it is done for the current data, so a deploy waits for that |
| `LAWGRAPH_API_HEAT` | `true` | the heat of the whole graph (`/api/nodes/heat` without `ids`), which reads every edge once a day in the background; `false` answers it 503 at once, an emergency switch when the disk cannot bear it (the heat of named nodes stays) |
| `LAWGRAPH_WATCHDOG_MINUTES` | `10` | every this many minutes a running step logs which steps run and for how long, and every statement of its process that has run for over a minute: its state, what it waits on, and its text (for a streamed read the `FETCH` and the read behind it) |
| `LAWGRAPH_PG_MEMORY` | `4g` | memory limit of the server's container (`mem_limit`); `8g` on a 16 GB machine |
| `LAWGRAPH_PG_SHARED_BUFFERS` | `1GB` | `shared_buffers`, the server's own cache; `4GB` on 16 GB |
| `LAWGRAPH_PG_CACHE` | `3GB` | `effective_cache_size`, what the planner may count on the operating system to cache; `6GB` on 16 GB |
| `LAWGRAPH_PG_WORK_MEM` | `32MB` | `work_mem`, per sort or hash of a statement; `64MB` on 16 GB |
| `LAWGRAPH_PG_MAINTENANCE_WORK_MEM` | `512MB` | `maintenance_work_mem`, for an index build and `VACUUM`; `1GB` on 16 GB |
| `ARANGO_URL`, `ARANGO_DB_NAME`, `ARANGO_USER`, `ARANGO_PASSWORD` | | the ArangoDB the parity harness (`tests/parity/`) copies and compares with |
| `LAWGRAPH_DB_SIZE_ALERT_GIB` | `70` | `lawgraph check` fails from this database size on (see Database size) |

### Payload store

The XML and HTML of raw records are kept outside the database (`docs/data-model.md`,
raw_sources): in a directory on this machine, or in an S3 bucket. On the server that is a
bucket of LeafCloud's object storage (Amsterdam, S3-compatible).

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_PAYLOAD_STORE` | `file://~/.local/share/lawgraph/payloads` | `file:///path` or `s3://bucket[/prefix]` |
| `LAWGRAPH_S3_ENDPOINT` | none (AWS) | `https://leafcloud.store` for LeafCloud |
| `LAWGRAPH_S3_REGION` | none | `europe-nl-ams1` for LeafCloud |
| `LAWGRAPH_S3_ACCESS_KEY`, `LAWGRAPH_S3_SECRET_KEY` | none | the EC2 credentials of the project (`openstack ec2 credentials create`) |

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
| `RIJKSOVERHEID_BASE` | `https://www.rijksoverheid.nl` |
| `EERSTEKAMER_SITE` | `https://www.eerstekamer.nl` |
| `EK_ATTRIBUTION` | `Eerste Kamer der Staten-Generaal, www.eerstekamer.nl`: how the API names the source of what it takes over from eerstekamer.nl (`ek_outcome.attribution`), next to the page and the day |
| `TOOI_BASE` | `https://identifier.overheid.nl` |

### Pipelines

| Variable | Default | Purpose |
|----------|---------|---------|
| `BWB_IDS` | empty | comma-separated BWB ids for `retrieve bwb` in incremental mode |
| `LAWGRAPH_CONFIDENCE_<PATTERN_UPPER>` | code default | confidence of one `bwb-relation-types` pattern, for example `LAWGRAPH_CONFIDENCE_SCOPE_LIMITATION_WINDOW=0.7` |
| `LAWGRAPH_<PHASE>_SKIP_<PIPELINE>` | unset | `true` leaves that pipeline out of `<phase> all`: `LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS` (see below) |

### API

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_API_HOST` / `LAWGRAPH_API_PORT` | `127.0.0.1` / `8000` | listen address of `lawgraph-api`; `0.0.0.0` serves other machines |
| `LAWGRAPH_ALLOWED_ORIGINS` | `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:5174`, `http://127.0.0.1:5174` | CORS allow-list (no credentials); a request from these origins counts toward the rate limit like any other |
| `LAWGRAPH_RATE_LIMIT_CALLS` / `LAWGRAPH_RATE_LIMIT_PERIOD` | `200` / `60` | requests per window (seconds) per IP |
| `LAWGRAPH_TRUSTED_PROXIES` | loopback | proxies whose `X-Forwarded-For` is honoured: the rate limit counts the right-most address in it that is no trusted proxy, the one the proxy itself appended (what a client writes into the header at the left does not count) |
| `LAWGRAPH_SEARCH_STATS_DIR` | `~/.local/share/lawgraph/search-stats` | where the API keeps the counts of the terms searched on `/api/search`: per day, term → n, without who asked or when in the day (`core/search_stats.py`); the server: `/srv/lawgraph/stats`. The request log holds the network of a visitor (IPv4 /24, IPv6 /48) and the path without its query string; the full address is only in the memory of the rate limiter |
| `LAWGRAPH_CACHE_TTL` / `LAWGRAPH_CACHE_MAXSIZE` | `60` / `512` | in-process cache of some routes |
| `LAWGRAPH_SITE_URL` | `http://localhost:5173` | Concordans, the front end the Atom feed links its pages and events to |

### Logging and tests

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_LOG_LEVEL` | `INFO` | root log level |
| `LAWGRAPH_LOG_FORMAT` | plain | `json` for one JSON object per line |
| `LAWGRAPH_LOG_FILE` | unset | every log line is also written to this file (plain lines; the terminal keeps its live progress) |
| `NO_COLOR` | unset | disables ANSI colours |
| `ALLOW_NETWORK_TESTS` | unset | `1` runs the tests that call the real APIs; shell only, the test suite ignores it in `.env` |
| `ALLOW_DB_TESTS` | unset | `1` runs everything under `tests/pg/` (among it `test_sql_validity.py`: every static SQL statement planned by a real PostgreSQL in a scratch database) and `tests/integration/`; shell only |
| `LAWGRAPH_TEST_DB_URL` | `postgresql://lawgraph:lawgraph-test@localhost:5433/lawgraph` | server `tests/pg/` and `tests/integration/` talk to (`docker-compose.test.yml`); each test makes a database `lawgraph_it_...` there and drops it; shell only |

## CLI

`lawgraph` or `python -m lawgraph`; `lawgraph <phase> <source> --help` shows the options of
a command. `--since` is the only date option: ISO 8601 (`2024-01-01`) or relative in days (`7d`),
hours (`2h`) or minutes (`90m`). A value in days reaches six hours further back than it says, so
that runs that follow each other overlap: a run that starts late or a source that indexes a
change late leaves no hole, and everything is an upsert. A value in hours or minutes is taken as
it is: a poll chooses it wider than the time between its runs.
Every command exits with code 1 when it raised or its result has errors; a composite command
(`<phase> all`, `bootstrap`, `expand-graph`) continues after a failing pipeline unless `--strict`
and exits 1 when any of them failed.

### retrieve

| Command | Options |
|---------|---------|
| `retrieve all` | `--mode incremental` (default) or `full`, `--since` (default `1d`; `last` for since the last complete run, also on `normalize all` and `semantic all`), `--window DATE` (full mode; default `730d`, `all` for the whole history), `--jobs N` (default: one per server, 8). Incremental passes the mode and `--since` to `tk`, `rechtspraak`, `staatscourant`, `eerstekamer`, `echr`; `--since --skip-members` to `tk-dossiers`; the mode to `bwb` and `bwb-history`. Full passes the mode to `bwb` and `bwb-history` and, for the sources that keep producing (`tk`, `tk-dossiers`, `rechtspraak`, `staatscourant`, `eerstekamer`, `echr`), reads only what changed inside `--window` (as an incremental run since then); `--window all` reads their whole history. The reference sources (`bwb`, `verdragenbank`, `rijksoverheid`, `tooi`, `rechtspraak-instanties`) are always read in full. `tk-content`, `eurlex`, `staatsblad`, `verdragenbank`, `rijksoverheid`, `tooi`, `rechtspraak-instanties` and `staatscourant-posts` take nothing (`eurlex` fetches the acts already in the graph, `tk-content` the papers without stored XML, `staatscourant-posts` the posts of the stored cabinet pages whose function names no ministry). `--jobs` retrieves that many sources at once; sources on one server (`tk` and `tk-dossiers`; `rechtspraak` and `rechtspraak-instanties`; `bwb` and then `bwb-history`; `tk-content`, `staatsblad`, `staatscourant`, `eerstekamer`, `verdragenbank` and `staatscourant-posts`) run one after the other, and `--jobs 1` runs every source in turn. A source that reads what another stored starts when that one has ended, last on its own server so the others do not wait with it: `tk-content` after `tk-dossiers`, `staatsblad` after `bwb` (it reads the stored toestanden), `staatscourant-posts` after `rijksoverheid` (it reads the stored cabinet pages). Three sources choose their work from what a normalize step wrote, which `retrieve all` does not run: `tk-content` the TK documents of `normalize tk-dossiers`, `eerstekamer-bills` the bills named by the EK decisions of `normalize eerstekamer-votes`, and `eurlex` (incremental and `com`) the EU instruments of `normalize eurlex`. On a graph without them the command warns before it runs, and the table at the end notes `no TK documents yet: run normalize tk-dossiers first`; run it again after that normalize. A gaps list longer than 50,000 is cut, and the table notes `50,000 of 93,818 Kamerstukken without XML, again for the rest` |
| `retrieve tk` | `--mode`, `--since` (default `1d`), `--limit N` |
| `retrieve tk-dossiers` | `--since`, `--decisions-since`, `--documents-since` (both override `--since` for one record kind), `--skip-members`, `--skip-decisions`, `--skip-documents`, `--dossier-number N` (only that dossier and its documents, whatever their date: the backfill of an old dossier); `--mode gaps`: every dossier the graph names and lacks (the dossiers of the publications that amended or brought into force a version of an article or a regulation, the first reading a change in the Grondwet in its second reading refers to, and the dossiers the Tweede Kamer papers and cases are part of) or lacks papers of (a number below the highest it has), each fetched with all its documents; a number the Tweede Kamer has no dossier of (`tk-dossier-missing`), or not all papers of (`tk-document-missing`), is remembered for 30 days |
| `retrieve tk-content` | `--mode gaps` (the only mode: the papers of `--kind` of which no XML is stored, less those the repository answered HTTP 404 for not long ago), `--kind` (repeatable; default `toelichting`, `motie`, `amendement`, `voorstel van wet` and `nota van wijziging`; `--kind ""` every paper numbered in a dossier), `--dry-run` |
| `retrieve rechtspraak` | `--court` (repeatable; default `all`, every court of the index; an ECLI court code such as `HR` or a tier such as `gerechtshof` narrows it), `--mode`, `--since` (default `1d`), `--ecli` (repeatable) |
| `retrieve eurlex` | `--mode incremental\|full\|gaps\|nim\|cjeu\|com`, `--celex` (repeatable), `--type directive\|regulation\|decision` (full mode, repeatable), `--lang NL`, `--country NLD` |
| `retrieve eurlex-nim` | `--mode incremental\|full` (full: every measure), `--since` (default `30d`: the measures CELLAR changed since then), `--country NLD` |
| `retrieve bwb` | `--mode incremental\|full\|gaps`, `--bwb-id` (repeatable; default `BWB_IDS`), `--min-stubs N` (gaps mode: a law with at least that many referred articles, default 3) |
| `retrieve bwb-history` | optional BWB ids (default: every regulation of which the current toestand is stored), `--mode incremental` (default: the toestanden not stored yet) or `full` (every one again) |
| `retrieve staatsblad` | `--mode from-graph\|full` |
| `retrieve staatscourant` | `--mode`, `--since`, `--identifiers ...` |
| `retrieve echr` | `--mode`, `--since`, `--respondent`, `--max-records` |
| `retrieve eerstekamer` | `--mode`, `--since`, `--max-records` |
| `retrieve eerstekamer-composition` | none: every run reads the whole composition (about 40 pages) |
| `retrieve eerstekamer-votes` | `--mode` (`full`: the whole list of votes, 106 pages), `--since` (the days of votes from then on; the list of rejected bills is read whole every run) |
| `retrieve verdragenbank` | `--mode full\|gaps`, `--max-records`, `--only-stored` (only the treaties stored already) |

### normalize

`normalize all [--since DATE]` runs every source in registry order (`tk`, `tk-dossiers`,
`tk-content`, `rechtspraak`, `eurlex`, `bwb`, `bwb-history`, `staatsblad`, `staatscourant`,
`eerstekamer`, `echr`, `verdragenbank`). Every `normalize <source>` accepts `--since DATE`: only raw records
fetched since then.

### semantic

`semantic all [--since DATE] [--strict]` runs the pipelines below in this order; `--since` is
passed to the pipelines that accept it and the others run in full.

| Command | Options |
|---------|---------|
| `tk`, `rechtspraak`, `eurlex`, `rechtspraak-citations` | `--since`: sources whose raw record was fetched since then |
| `bwb` | `--since` (as above), `--store-citations` |
| `bwb-grondslagen`, `bwb-amendments`, `bwb-annexes` | none |
| `staatsblad`, `eerstekamer`, `echr` | none |
| `staatscourant` | `--since`: publications dated since then |
| `rechtspraak-appeal` | none |
| `tk-amends` | `--since`: documents dated since then |
| `bwb-implements` | none (every regulation that names or implements an EU act, and every retrieved national implementing measure, on every run) |
| `tk-amendment-articles`, `tk-mvt`, `tk-mvt-articles`, `bwb-relation-types` | none |
| `tk-dossier-outcomes` | `--touched-since` (a poll; `semantic all` never passes it): only the dossiers touched since then; without it every dossier |
| `tk-government` | `--touched-since` (as above): only the commitments and dossiers touched since then; without it all of them |
| `tk-dossier-relations` | none (every dossier and every related case on every run) |
| `graph-list-stats` | `--dry-run`, `--instruments-only`, `--judgments-only`, `--committees-only`, `--articles-only`; backfills the sort and filter fields of the list endpoints |

The order is `tk`, `rechtspraak`, `eurlex`, `bwb`, `bwb-grondslagen`, `bwb-amendments`,
`bwb-annexes`, `staatsblad`, `staatscourant`, `eerstekamer`, `echr`, `rechtspraak-appeal`,
`rechtspraak-conclusions`, `rechtspraak-referrals`, `rechtspraak-duplicates`,
`rechtspraak-citations`, `rechtspraak-series`,
`tk-amends`, `bwb-implements`, `tk-amendment-articles`, `tk-dossier-relations`, `tk-mvt`,
`tk-mvt-articles`, `bwb-relation-types`, `tk-dossier-outcomes`, `tk-government`,
`graph-list-stats`.

### Other commands

| Command | Behaviour |
|---------|-----------|
| `lawgraph bootstrap [--window DATE] [--jobs N] [--max-expand N] [--redo STEP] [--skip-expand] [--skip-retrieve] [--strict] [--plan]` | every step of a build: the retrieves of a full load in `--window` (default `730d`; `all` loads the whole history of the producing sources) in a lane per server, at most `--jobs` at once; every normalize and semantic step one at a time in the write lane, each as soon as what it reads is there; then `expand-graph` (up to `--max-expand` rounds, default 5) and `check`. A step that ends ok is marked (`pipeline_state`, `bootstrap <step>`, with the code it ran on); a run started again skips the marked steps, `--redo STEP` runs one again (repeatable). A failed step leaves out the steps that wait for it, the others go on (`--strict`: nothing starts after it). `--skip-retrieve` and `--skip-expand` count those steps as done. When every step of a phase is marked, the phase is on record for `--since last` from its first start. `--plan` runs nothing and prints the plan of a build: the window, every step in its lane (one per server for the retrieves, one write lane for the rest), what each waits for, which are done (`pipeline_state`, `bootstrap <step>`), and those done on other code than the checkout's (`version (git describe)`) |
| `lawgraph expand-graph [--max-iterations N]` | rounds of `retrieve all --mode gaps`, `normalize all --since <round>` and `semantic all --since <round>` while a round retrieves records (default 10); then one full `semantic all`, for the texts loaded earlier that name a law loaded now |
| `lawgraph poll CHAIN --since WINDOW` | a light chain for one source, between the nightly runs: its retrieves, the normalize of what they fetched and the semantic steps the feed needs of it, every step with the same `--since`, as `--touched-since` to `tk-dossier-outcomes` and `tk-government`. `tk`: `tk` and `tk-dossiers` (without members), `tk-dossier-outcomes`, `tk-government`; `ek`: `eerstekamer-votes`, `tk-dossier-outcomes`; `rechtspraak`: the courts of the feed tiers; `echr`. No mark of its own: choose the window wider than the time between two polls, so they overlap; `--since` is required |
| `lawgraph gaps [--min-stubs N]` | reads only: what `retrieve all --mode gaps` would fetch (laws by number of referred articles, cited judgments, referrals of preliminary rulings, EU acts, treaties, memoranda without text) |
| `lawgraph verify cabinets` | reads only: one row per cabinet (posts, seats, gaps, overlaps, stand-ins, phases) and every rule a cabinet breaks; a broken rule fails it |
| `lawgraph search-stats [--days N] [--top N]` | the terms searched most in the last `--days` (default 7), from the files of `LAWGRAPH_SEARCH_STATS_DIR`. `search-stats prune [--keep-days 7] [--min-count 5]` moves the days older than `--keep-days` into the file of their month, keeping only the terms asked at least `--min-count` times in that day and the days kept after it; `daily.sh` runs it |
| `lawgraph ministries build\|check [--output FILE]` | builds `src/lawgraph/data/ministries.json` from the stored TOOI list and Rijksoverheid pages with the curated keys, order and successions (`data/curated/ministries.json`) and prints what changed and every curated name no source names (`build` writes it, `check` fails on a change); run after `retrieve tooi` and commit the file |
| `lawgraph code-families build\|check [--output FILE]` | builds `src/lawgraph/data/code_families.json` (the codes whose books are regulations of their own: `BW`) from the stored WTI records and prints what changed (`build` writes it, `check` fails on a change); run after `retrieve bwb` and commit the file |
| `lawgraph courts build\|check [--output FILE]` | builds `src/lawgraph/data/courts.json` from the stored Instanties list of the Rechtspraak and prints what changed (`build` writes it, `check` fails on a change); run after `retrieve rechtspraak-instanties`, commit the file, and run `semantic graph-list-stats` when a tier or kind changed |
| `lawgraph retrieve <source> --mode gaps` | fetch the gaps of one source (`bwb`, `rechtspraak`, `eurlex`, `echr`, `verdragenbank`, `tk-dossiers`, `tk-content`); `retrieve all --mode gaps` runs them side by side per host |
| `lawgraph curated list [LIST]`, `check [LIST] [--db]`, `set LIST KEY [JSON] [--after KEY \| --first]`, `remove LIST KEY` | the lists kept by hand in `src/lawgraph/data/curated/` (`core/curated.py`): party colours (the house colour and the colours each Kamer draws a party in, `chambers`), the seating plan of the plenary hall (after the plan of the Tweede Kamer, with its url and date), the phases of a bill (the one order the Kamer does not give, each phase with the exact values of the Kamer that mark it), the names of landmark judgments, the kinds of decision, the courts outside the value list, the ministry keys, order, successions and aliases, the abbreviations of instruments whose source gives none (`instrument-abbreviations`, keyed by BWB id or CELEX number), the BWB treaty of each Protocol to the ECHR that HUDOC names by number (`echr-protocols`, `P1` → `BWBV0001001`). `set` writes a change only when the list stays in order; commit what it changes |
| `lawgraph check [--skip-edges]` | asks the database what no step asks (and checks the curated lists, `lawgraph curated check --db`: also a seated faction the seating plan does not place, and a faction whose number of seats differs from the plan's, and an abbreviated instrument no node of the graph is; a seat that changed after the plan, and a value of a phase no record in the database has, are notes): does every raw kind of the registry hold records, does every source with raw records have nodes (at least 90% of the records that make one: a judgment HUDOC holds in two languages is one, a zaak the Tweede Kamer deleted none), does every edge have both its nodes, does every search view hold what its collection holds, does every BWB regulation carry its `basis` and `celex_refs`, how many BWB treaties have a Verdragenbank record by their `treaty_number` (none carrying one is a problem), do cases name their dossier, how many articles of a Protocol to the ECHR Convention ECHR judgments apply that are not linked (a note), is the retrieved XML of Tweede Kamer papers read into their documents, are the text payloads of a few records of every kind in the payload store, is the database below `LAWGRAPH_DB_SIZE_ALERT_GIB` with its license limit not reached. Read-only, one query each; exits 1 on a problem. Run it after a load: a step can end successfully and leave nothing behind (a source that answers no records for a parameter it does not understand, a normalize step that never ran) |
| `lawgraph-api` | starts the API |

### Skip variables

`LAWGRAPH_<PHASE>_SKIP_<PIPELINE>=true` (case-insensitive `true`; any other value does not skip)
skips one pipeline of `retrieve all`, `normalize all` or `semantic all`. `<PIPELINE>` is the
pipeline name in upper case with underscores (`tk-dossiers` is `TK_DOSSIERS`).

| Phase | Pipelines |
|-------|-----------|
| `RETRIEVE` | `TK`, `TK_DOSSIERS`, `TK_CONTENT`, `RECHTSPRAAK`, `RECHTSPRAAK_INSTANTIES`, `EURLEX`, `EURLEX_NIM`, `BWB`, `BWB_HISTORY`, `STAATSBLAD`, `STAATSCOURANT`, `EERSTEKAMER`, `EERSTEKAMER_VOTES`, `EERSTEKAMER_COMPOSITION`, `EERSTEKAMER_AGENDA`, `EERSTEKAMER_BILLS`, `ECHR`, `VERDRAGENBANK`, `TOOI`, `RIJKSOVERHEID`, `STAATSCOURANT_POSTS` |
| `NORMALIZE` | the same without `TOOI`, `RECHTSPRAAK_INSTANTIES`, `EURLEX_NIM` and `STAATSCOURANT_POSTS` (`lawgraph ministries build`, `lawgraph courts build`, `semantic bwb-implements` and `normalize rijksoverheid` read them) |
| `SEMANTIC` | `TK`, `RECHTSPRAAK`, `EURLEX`, `BWB`, `BWB_GRONDSLAGEN`, `BWB_AMENDMENTS`, `BWB_ANNEXES`, `STAATSBLAD`, `STAATSCOURANT`, `EERSTEKAMER`, `ECHR`, `RECHTSPRAAK_CITATIONS`, `RECHTSPRAAK_APPEAL`, `RECHTSPRAAK_CONCLUSIONS`, `RECHTSPRAAK_REFERRALS`, `RECHTSPRAAK_RELATED`, `RECHTSPRAAK_DUPLICATES`, `RECHTSPRAAK_SERIES`, `TK_AMENDS`, `BWB_IMPLEMENTS`, `VERDRAGENBANK`, `TK_AMENDMENT_ARTICLES`, `TK_MVT`, `TK_MVT_ARTICLES`, `BWB_RELATION_TYPES`, `TK_DOSSIER_OUTCOMES`, `TK_GOVERNMENT`, `TK_DOSSIER_RELATIONS`, `GRAPH_LIST_STATS` |

## Runs

**Full load.**

```bash
lawgraph retrieve all --mode full --window 730d
lawgraph retrieve bwb-history            # optional: every BWB toestand
lawgraph retrieve tk-content             # optional: the XML of MvTs, moties and amendementen; normalize tk-content reads it
lawgraph retrieve rechtspraak --ecli ECLI:NL:HR:2023:1234 ...   # judgment content
lawgraph normalize all
lawgraph semantic all
```

`lawgraph bootstrap` runs the same steps, side by side where they can, and then
`expand-graph` and `check`; `lawgraph bootstrap --plan` shows how. In full mode `retrieve all`
enumerates every BWB regulation and fetches every toestand of each (`bwb-history`), the XML
of the explanatory memoranda (`tk-content`) and the judgments of every court; EU acts come
from `expand-graph`, which fetches the ones the loaded records refer to. The sources that keep producing (Tweede Kamer,
Rechtspraak, Staatscourant, Eerste Kamer, ECHR) load only the last two years, and
`expand-graph` later adds what the loaded records refer to. The whole history for research is
one option away: `--window all` (the Tweede Kamer alone is over 400K documents and hours), or
a date such as `--window 2015-01-01`.

**A code fix during a build.** A running process keeps the code it started with only as long
as nobody changes it: the install is editable and a module is imported when a step first needs
it, so a checkout changed under a running build mixes two versions. A fix goes into a second
checkout, and the build moves to it between steps:

1. The fix is merged and tagged (`build-<version>`).
2. A second checkout beside the running one, with its own venv and the same `.env`:

   ```bash
   git -C /srv/lawgraph/app fetch --tags
   git -C /srv/lawgraph/app worktree add /srv/lawgraph/app-<tag> <tag>
   cd /srv/lawgraph/app-<tag> && uv venv && uv pip install -e . && cp ../app/.env .
   ```

3. Switch between steps, never inside one: the next step starts from the new checkout once the
   running one has ended. A step the fix is about waits for it; one it is not about may end on
   the old code. Ctrl-C stops a step safely: a retrieve stores what it has and its next run
   fetches only what is missing; a normalize or semantic step is run again whole. A build
   with `lawgraph bootstrap` moves by stopping it (Ctrl-C) and starting it again from the new
   checkout: it skips the steps that are marked done, `--plan` shows which ran on which code,
   and `--redo STEP` runs one again on the new code.
4. Never two lawgraph processes that write at once, from either checkout. Every process makes
   sure of the schema when it starts; that takes locks on the tables (it replaces their
   triggers), which wait behind a long write, and every other statement on that table then
   waits behind them.
5. When the build is done, `/srv/lawgraph/app` itself goes to the tag (`git checkout <tag> &&
   uv pip install -e .`), the API and the timers run from there, and the second checkout goes
   (`git -C /srv/lawgraph/app worktree remove /srv/lawgraph/app-<tag>`).

Two more rules for scripts around a build: a script that is running is never changed in place
(`sh` reads it as it goes), a new one is written beside it and moved over it with `mv`; and
`.env` is read by lawgraph itself, not by a shell script that runs it, so a variable a script
needs is set in that script's own environment.

**Incremental.**

```bash
lawgraph retrieve all --since last
lawgraph normalize all --since last
lawgraph semantic all --since last
```

`--since last` goes on where the last complete run of that command began (less the six hours
of overlap every relative `--since` gets), so a day on which nothing ran is caught up by the
next run. A `<phase> all` that ends without a failed or skipped step records when it began,
in `pipeline_state`; a run whose own `--since` lies after that mark leaves a hole and does
not move it (it says so). Before the first complete run `--since last` is refused (exit 2):
`bootstrap`, or a run with a date such as `--since 7d`, puts one on record.

Incremental `retrieve bwb` needs `BWB_IDS` or `--bwb-id`, otherwise it fetches nothing.
Incremental `retrieve bwb-history` reads which toestanden exist (the SRU listing, about 150
pages, once there are 150 regulations or more; else one query per regulation) and downloads
those it has no record of: a new toestand of a known regulation, and every toestand of a
regulation `bwb` stored since. Incremental `retrieve tk-content` fetches the papers of which
no XML is stored; a paper the repository has no XML for yet is asked for again after 3 days
when it is younger than a week (the XML follows the PDF within about two working days), else
after 30.
Law abbreviations (`instruments.props.short_title` and `aliases`, used by the citation
detectors) come from the WTI records that `retrieve bwb` stores and are written by `normalize
bwb`, so run both before `semantic`. A law is only cited once it is loaded: `retrieve bwb
--mode full` enumerates every regulation and treaty of the BWB; an incremental build needs
its ids in `BWB_IDS` (the Wetboek van Strafvordering `BWBR0001903`, Rv `BWBR0001827`, Wet RO
`BWBR0001830`, AWR `BWBR0002320`, Vw 2000 `BWBR0011823`, the EVRM `BWBV0001000`). The laws
judgments cite that are not loaded are in `judgments.props.unresolved_citations`. `normalize bwb --since` still re-evaluates the short title of every
regulation, because an abbreviation claimed by a newly loaded regulation stops being unique.
Incremental `retrieve eurlex` re-fetches the CELEX numbers of the instruments already in the
graph. `verdragenbank` has no date filter and reads all treaties; `staatsblad` reads the stored BWB XML.

**Slow steps.**

| Step | Why |
|------|-----|
| `retrieve tk-content` | one XML per paper (up to several MB), paced at 0.5 s; at most 50,000 papers a run |
| `retrieve rechtspraak` full | every court: 160,718 judgments decided in the two years of the default `--window` (index counts of 2026-09-29; the Hoge Raad, Raad van State and hoven are about 33,000 of them, the rechtbanken most of the rest), one download each at 8 a second: about 5.5 hours. `--window all` is 928,955 judgments, about 32 hours. An incremental run with `--since 1d` reads the index of the last 30 days by decision date (about 3,600 entries) and of the last day by modified date (about 500) and downloads what is new or changed: minutes. A `--since` up to 60 days back also lists by modified date (every court, 60 days: 20,481), which re-downloads what the Rechtspraak republished since it was stored; further back only the decision date is read |
| `retrieve tk-dossiers` full | about 400K documents, fetched 250 at a time |
| `retrieve bwb --mode full`, `retrieve bwb-history` | `bwb`: the SRU listing, then one XML download and one short WTI request (about 1 KB read) per regulation whose current toestand is not the stored one (an unchanged regulation costs nothing; its WTI file is read again after 30 days). `bwb-history`: the SRU listing (or one query per regulation for fewer than 150) and one download per toestand not stored yet; the first run downloads all of them (148,287 toestanden in the SRU on 2026-09-20), side by side at the pace of the repository (0.1 s): at least 4 hours |
| `normalize bwb-history` | streams every stored toestand XML (large documents) in batches of 20 |
| `normalize tk-dossiers` | the largest normalize step (documents, decisions, edges, dossier backfill) |
| `semantic bwb` | scans every article text |

Every retrieve and normalize step is idempotent and safe to interrupt and re-run.

**Pacing.** Every client waits between requests to one host (`HOST_MIN_INTERVAL` in
`config/constants.py`, 0.1 to 0.5 s, 0.2 s for an unlisted host). A host that answers HTTP
429 or 503 makes the interval double, up to 10 s, or follow its `Retry-After`; it shrinks
back while requests succeed (halved after 35 of them), to the base interval or to 15% above
the pace the host last pushed back at (forgotten slowly: halved after 1,400 requests). HTTP 429, 502, 503, 504 and connection errors are retried five
times with a growing pause. `repository.overheid.nl` was measured to throttle from about five
requests per second sustained, so the base interval there is 0.5 s. A `throttling` warning in
the log means the pacer is slowing down; it is not an error. It appears at most once a minute
per host, with the number of HTTP 429/503 answers since the last one; the retries themselves
are logged at `DEBUG`. The pacer is shared inside one process. The first process that reaches a
host holds a lock file for it (in `~/.cache/lawgraph`); a second `lawgraph` process finds
it taken, says so once and paces that host at half speed, so two commands started side by
side stay under the limit together. The lock goes with the use: a process gives it back after
five minutes without a request to that host (a `retrieve all` whose sources on that host are
done), and a process at half speed tries to take it every minute and goes back to full speed
when it can.

**Database volumes.** The data is in a Docker volume that `docker-compose.yml` declares
`external`: compose uses it and cannot remove it. Create it once
(`docker volume create lawgraph_pgdata`), then `docker compose up -d` (PostgreSQL alone: ArangoDB, kept until the rollback window closes, starts only with `--profile arango`, on 127.0.0.1). The server
(service `postgres`, container `lawgraph-postgres`, `127.0.0.1:5432`, user `lawgraph`)
keeps its data in it under `/var/lib/postgresql/18/docker`. `docker compose down -v` removes every volume a project owns,
also with `--profile`, and that is how this database was lost once; the test database is a
compose project of its own for the same reason.

**Database memory.** PostgreSQL takes what it is told: `docker-compose.yml` sets the
container's limit (`LAWGRAPH_PG_MEMORY`) and the server's caches and work memory from the
`LAWGRAPH_PG_*` variables (see Database; the defaults are for a machine of 8 GB, the values
for 16 GB are given next to them), and `shm_size` 1 GB for parallel workers. It runs with
`jit = off` (for these statements a compilation costs more than it gains; the store turns it
off on its own connections too), `random_page_cost` 1.1 and `effective_io_concurrency` 200
(an SSD), `max_wal_size` 4 GB and `wal_compression` zstd (a load writes a lot at once),
`default_toast_compression` lz4 (the large props), and at most 100 connections. The container
restarts when the server stops and reports itself healthy when `pg_isready` answers. A bulk
write is sent again (after 2, 10 and 30 seconds) while the database is unreachable, so a
restart costs a run nothing; when it stays away the step ends there instead of fetching on.

**Interruptions.** A retrieve stores its records while it fetches, a buffer at a time
(`RawSourceWriter`: 500 records, 8 MB of text or 5 seconds, whichever comes first). An
interrupt and a failing source write the buffer before the step ends, so they keep everything
fetched, and a failure in the middle is an error of the step, not a silent stop. A crash of
the process or the machine loses at most that last buffer. A step that downloads one document per record (`staatscourant`, `bwb`, `eurlex`)
skips the records stored in the last 24 hours, so a re-run only does the rest. A refresh
later downloads what the source lists as new or changed: a Staatscourant or Staatsblad
publication stored after its `modified` date, a BWB toestand that is still the stored one and
a judgment not updated since are left alone; a document that answered HTTP 404, or a
redirect that leads nowhere, is asked for again after 30 days (3 when the source listed it
itself, as the SRU does a BWB toestand). The Tweede Kamer pages are read again from the start on a
re-run (upserts, so only time is repeated).

**Scheduled.** `scripts/daily.sh`, `scripts/weekly.sh` and `scripts/poll.sh` are what a
scheduler runs; nothing is installed for you.

| Script | Runs | Why |
|--------|------|-----|
| `daily.sh` | `retrieve all`, `normalize all`, `semantic all`, each `--since last`; `check --skip-edges`; `search-stats prune` | what the sources changed; a day without a run is caught up by the next |
| `weekly.sh` | `semantic all`, `expand-graph`, `check` | a text loaded long ago can name a law loaded this week; what is named and missing is then fetched |
| `poll.sh CHAIN [WINDOW]` | `poll CHAIN --since WINDOW`; the window by default `4h` (`tk`, `ek`), `6h` (`rechtspraak`), `1d` (`echr`) | between the nightly runs, what one source published, up to the feed; the window reaches back past the poll before it, and the first poll of a day past the nightly run |

One run at a time (a lock directory in `$TMPDIR`; a second run exits 75 and says so), a
failing command fails the run and the next command still runs, one log per run in
`~/Library/Logs/lawgraph/` (`LAWGRAPH_LOG_DIR`) and one line per run in `runs.log` there.
A failed run runs `LAWGRAPH_ALERT_COMMAND` (with `sh -c`, the message in
`LAWGRAPH_ALERT_MESSAGE`) when it is set in the environment of the scheduler, for example
`curl -s -d "$LAWGRAPH_ALERT_MESSAGE" https://ntfy.sh/<topic>`; a failing alert command is
noted in `runs.log` and changes nothing else. With cron:

```
30 5 * * *        /path/to/lawgraph/scripts/daily.sh
0  7 * * 0        /path/to/lawgraph/scripts/weekly.sh
0,30 8-19 * * 1-5 /path/to/lawgraph/scripts/poll.sh tk
10 15,18 * * 2    /path/to/lawgraph/scripts/poll.sh ek
15 9-18 * * 1-5   /path/to/lawgraph/scripts/poll.sh rechtspraak
20 11 * * 2,4     /path/to/lawgraph/scripts/poll.sh echr
```

These times follow the sources: the votes of a Tuesday in the Tweede Kamer come out on
Wednesday morning in one batch, and papers all working day; the Eerste Kamer votes on Tuesday;
the Hoge Raad and the Raad van State publish on the day of the decision, on working days; the
ECHR gives its judgments on Tuesday and Thursday mornings. A poll that finds another run holding
the lock exits 75 and leaves it to the next, so the polls start at different minutes; a missed
poll is not caught up, the nightly run covers it. Each chain logs to
`poll-<chain>-<date>.log`.

A poll that finds nothing new writes nothing, and the data version stays as it was. One that
writes a row raises it: the API then drops the answers it keeps and warms up again once the
data has stood still for 90 seconds (`/api/health` says `computing` meanwhile). So a poll can
come no more often than the warm-up takes on the server.

On macOS the scripts run under `caffeinate -i`, which keeps the machine from idle sleep. A
closed lid on battery still sleeps: the run pauses until the next wake and its log shows
gaps of minutes. Keep it on power, or the lid open.

Before the first scheduled run one complete run has to be on record (`bootstrap`, or each
`<phase> all` once with a date), or `--since last` is refused.

**Database size.** `lawgraph check` (daily, in `daily.sh`) logs the size of the database on
disk (`pg_database_size`), the three largest tables (rows, TOAST and indexes together), and
fails from `LAWGRAPH_DB_SIZE_ALERT_GIB` (70 GiB) on. With the alert command set, that failure
reaches you the same morning.

**Backups.** Everything in the database can be built again from the sources, but that takes a
day or more; a backup is back in minutes to hours. `scripts/backup.sh` writes a dump of the
database with `pg_dump` (directory format, four jobs, zstd) to `LAWGRAPH_BACKUP_DIR`
(`./backups`, mounted by `docker-compose.yml` at `/backups` in the container, where the dump
runs), with a `counts` file next to it (`scripts/_counts.sql`: the rows of every table, the
edges per relation, and the columns, indexes, functions and triggers of the schema), and keeps
the newest `LAWGRAPH_BACKUP_KEEP` (7). A dump is written as `<name>.partial`, made readable
to every user (the upload command runs as another user than the container's) and renamed when
it is complete. `LAWGRAPH_BACKUP_UPLOAD_COMMAND` gets each new dump off the machine (`sh -c`, the
path in `LAWGRAPH_BACKUP_PATH`), for example
`rclone copy "$LAWGRAPH_BACKUP_PATH" leafcloud:lawgraph-backups/$(basename "$LAWGRAPH_BACKUP_PATH")`;
let a lifecycle rule of the bucket remove old ones. `scripts/restore-test.sh` restores the
newest dump with `pg_restore` (four jobs) into a scratch database on the test server
(`docker-compose.test.yml`, which mounts the same directory read-only;
`LAWGRAPH_RESTORE_CONTAINER` for another server, which a dump of the full database needs),
made as the schema makes a database (its collation), compares it line by line with `counts`,
and drops it; `runs.log` says how long the restore took. On a laptop a database of 1 GB on
disk dumped to 212 MB in 8 s and restored in 82 s, most of it spent rebuilding the indexes:
plan with about a minute and a half per GB. Both run under the lock of the
scheduled runs, so a dump never reads a database that a load is writing. The dump holds the
metadata of the raw records, not their payloads: those are in the payload store, which is
backed up on its own. A directory store goes with the backups of the machine; in a bucket,
versioning (or a replica in a second bucket) protects against a deleted or overwritten object.

```
0  3 * * *   /path/to/lawgraph/scripts/backup.sh
0  4 * * 6   /path/to/lawgraph/scripts/restore-test.sh
```

## Deploy

A push to the branch `release` deploys that commit (`.github/workflows/deploy.yml`): the unit
suite, then over SSH a checkout of exactly that commit on the server, `uv pip install -e .`
into its venv, and a restart of the API, which has to answer `/api/health` within 30 seconds,
with the `version` of the release.
The deploy takes the lock of the scheduled runs, so it never swaps the code under a running
load; when a run holds it, the job fails and is run again later. Data migrations that a release
needs (a `normalize` or `semantic` step) are not part of it: run them on the server after the
deploy.

The server it expects:

| Path | What |
|------|------|
| `/srv/lawgraph/app` | a clone of this repository with `.venv` (made with `uv`) and `.env` |
| `/srv/lawgraph/tmp` | `TMPDIR` of the scheduled runs, where their lock lives |
| systemd unit `lawgraph-api` | `.venv/bin/lawgraph-api` in `/srv/lawgraph/app`, on 127.0.0.1:8000 behind a reverse proxy |

The user of `DEPLOY_USER` owns `/srv/lawgraph`, has `uv` in `~/.local/bin` and may run
`sudo -n systemctl restart lawgraph-api`. Secrets of the repository: `DEPLOY_SSH_KEY` (a private
key whose public half is in that user's `~/.ssh/authorized_keys`), `DEPLOY_HOST`,
`DEPLOY_USER` and `DEPLOY_KNOWN_HOSTS`. That last one is the known_hosts line of the server's
host key, taken on the server itself and not over the network:
`echo "<DEPLOY_HOST> $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"`. The deploy connects
with `StrictHostKeyChecking=yes`, so a host that answers with another key gets no deploy key and
no code.

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
  at the end, and as each step ends a line under their own label with how far the run is:
  `[retrieve all] 3 of 21 ended: retrieve tk-dossiers ok in 2h 03m, 1,234 created; running:
  retrieve rechtspraak, retrieve bwb.` A node or edge that a run would write as it already is, is not written: it is
  counted as `unchanged`, so `updated` is what really changed.
- Progress (`core/progress.py`, used by every pipeline of every phase; a test enforces it): no
  line per record. In a terminal every running step has one line at the bottom,
  `[retrieve rechtspraak] 12,400 / 34,593 (36%) judgments · 4.9/s · ~1h12m left · 3 skipped ·
  0 errors`, rewritten in place once a second while the other log lines scroll above it. A
  pipe, a file and the JSON mode get that line once a minute instead. The total is there when
  it is cheap to know (an index, a list of ids, the OData `$count`, a count from a database
  index); the speed is that of the last minute. At the end of a step one summary gives the
  duration and the count per outcome and per reason. A reason to skip or fail is logged once,
  with the first record it happened to; a cause of failure is one error of the result
  (`25 x download failed (HTTP 500) (first: ...)`).
- A log file next to the live terminal: `LAWGRAPH_LOG_FILE=run.log lawgraph bootstrap`. Piped
  into `tee`, stderr is no terminal and the live block is off.
- `is throttling` warnings come from the request pacer (see Pacing), not from an error.
- API: each request is logged with id, client, method, path, status, size and latency;
  `GET /api/health` checks the database connection, gives the `version` of the API (after a
  deploy it is the version of the tag that was put live) and shows, from memory, the use of both
  connection pools (`pools`) and what the threads shared by every request run now (`busy`);
  `GET /api/stats` gives counts per collection and relation.
- A request that hangs: `systemctl kill -s USR1 lawgraph-api` writes the stack of every
  thread of the API to its stderr, the journal (`journalctl -u lawgraph-api`). Nothing is
  written without the signal.

## Tests and CI

```bash
pytest tests -q                       # several hundred tests, offline, a few seconds
ALLOW_NETWORK_TESTS=1 pytest tests    # also calls the real APIs
ruff check src tests
ruff format --check src tests
mypy                                  # src, configured in pyproject.toml
```

The suite uses real XML fixtures (`tests/fixtures/`) and replaces the database by patching the
functions of `db/queries/` the code calls (a fake store keeps only the bulk writes and lookups);
no unit test runs or reads a query (`tests/test_conventions.py`), what a query does is tested in
`tests/integration`; `tests/pg/test_sql_validity.py` has a real PostgreSQL plan every static SQL
statement (`ALLOW_DB_TESTS=1`, a scratch database of its own).

What only a server shows under real load is in `tests/integration` and `tests/pg`: the real code and the real
CLI against a second, deliberately small PostgreSQL (`docker-compose.test.yml`, a compose project of its own:
port 5433, 1 GB of memory, a throw-away volume; never the database of `.env`), next to an
S3 server for the payload store in a bucket (versitygw, port 8531, `LAWGRAPH_TEST_S3_URL`;
without it those tests are skipped). Each test has a payload directory of its own.

```bash
docker compose -f docker-compose.test.yml up -d
ALLOW_DB_TESTS=1 pytest tests/integration     # about eight minutes
docker compose -f docker-compose.test.yml down
```

It seeds raw records in the shapes of the sources at any scale (`seed.py`) and checks: a
result larger than the server may hold in memory streams; `normalize all` and `semantic all`
produce every part of the model and a second run changes nothing; `lawgraph check` finds a
source that was never normalized and an edge without its node; a database that restarts in
the middle of a run, and a run that is killed, cost a re-run at most; a stub that is loaded
stops being a stub; an incremental run links to what was loaded earlier; an API route answers
correctly and stays inside the server's memory limit against realistically large or
heavily-cited data. A problem found in a real run gets a test here first: small data on a
small server fails the way the corpus does on the real one.

Each test creates its own database (`lawgraph_it_<uuid>`) on the test server and drops it
afterwards, so tests stay independent of each other and safe to run in parallel; none of them
touches the database of `.env`. `conftest.py` skips the whole directory (rather than erroring)
when `ALLOW_DB_TESTS` is unset or the test server is unreachable, so `pytest tests` without it
stays green. CI (`.github/workflows/tests.yaml`) runs `tests/pg` and `tests/integration` in a job of
their own (`database`, on a pull request and on a push to `develop` or `main`) against a
`postgres:18` service with JIT off, as the test server; it has
no S3 server, so the tests of the payload store in a bucket are skipped there.

Layout: `test_chain`, `test_incremental`, `test_unchanged`, `test_faults`, `test_stubs`,
`test_large_results` and `test_command_line` exercise the pipeline chain itself and its failure
modes; `test_api_articles`, `test_api_documents`, `test_api_queries`, `test_hub_queries`,
`test_node_neighbors`, `test_resolve`, `test_article_parts`, `test_judgment_mentions`,
`test_mvt_articles`, `test_instrument_links` and `test_cited_by_scale` run one API surface, or
one query at a scale that would defeat an unindexed plan, against real data; `test_tk_content`
covers the Kamerstuk XML pipeline specifically; `test_series_end_to_end` seeds one small, real
chain (a law, an amendment, its memorandum, two judgments) and walks every route it touches,
dossier to judgment, once.

The unit suite outside `tests/integration/` is laid out as: `tests/api/` (routes, with the
query functions they call patched), `tests/normalize/` and `tests/semantic/` (one file per source or detector),
`tests/test_*.py` (clients, core helpers, bulk writers, registry, naming, conventions, relation
catalogue, props). CI (`.github/workflows`) runs `mypy` and
`pytest` on Python 3.11 and 3.14 and the pre-commit hooks: ruff `--fix`, ruff format,
end-of-file, trailing whitespace, private-key detection, YAML and merge-conflict checks; it does
not run `tests/integration` (no server available there).
