# LawGraph

LawGraph turns Dutch and EU legal sources into one queryable knowledge graph in PostgreSQL:
legislation and its amendment history, case law, and the parliamentary process behind
laws. The graph is the product; a FastAPI service exposes it.

## How it works

Every source passes through the same three phases, each restartable and idempotent
(deterministic keys, upserts):

| Phase | Reads | Writes |
|-------|-------|--------|
| `retrieve` | external APIs | `raw_sources`, the XML and HTML verbatim in the payload store (a directory, or an S3 bucket) |
| `normalize` | `raw_sources` | typed nodes and structural edges |
| `semantic` | nodes and raw XML | edges inferred from structure or text, with `confidence` |

Where a source states a relation (BWB XML: amendments, legal basis, references), it is
read, not guessed.

## Quick start

Requires Python 3.11+ and PostgreSQL 18 (a `docker-compose.yml` is included).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # set LAWGRAPH_DB_PASSWORD
```

### Database: development or test

Either server works with the same `.venv`; the store creates the database and its schema
(tables, indexes, functions) on first use, so nothing more is needed to start the API against
an empty one.

**Development** (`docker-compose.yml`, port 5432 on this machine only): keeps its data in an
external volume across restarts, sized for 8 GB (`LAWGRAPH_PG_*` in `.env` for more). This is
the one `LAWGRAPH_DB_URL` points at by default, and the one `lawgraph
bootstrap`/`retrieve`/`normalize`/`semantic` load real data into.

```bash
docker volume create lawgraph_pgdata      # once
docker compose up -d postgres
lawgraph-api                              # http://localhost:8000/docs
```

**Test** (`docker-compose.test.yml`, port 5433): a second, deliberately small server (1 GB) in
its own compose project, so it can never reach the volume above; its data is thrown away with
the container. It backs `tests/pg/` and `tests/integration/` (see `docs/operations.md`, "Tests
and CI"), and doubles as a fast way to click against a running API without waiting for a real
retrieve:

```bash
docker compose -f docker-compose.test.yml up -d
LAWGRAPH_DB_URL=postgresql://lawgraph:lawgraph-test@localhost:5433 lawgraph-api   # empty database
docker compose -f docker-compose.test.yml down   # discards it
```

### A small database with every feature

For the API and the front end on a laptop: `scripts/test-database.sh` builds `lawgraph_small` on
the development server, next to the database of `.env`, from real sources (a few laws with their
history and dossiers, two weeks of case law and parliament, a little of every other source), in
about half an hour and a few hundred MB. Every relation of the model occurs in it.

```bash
docker compose up -d postgres
scripts/test-database.sh
LAWGRAPH_DB_NAME=lawgraph_small lawgraph-api
```

### Loading data

```bash
lawgraph bootstrap              # retrieve (last 2 years of what keeps producing; --window all for history), normalize, semantic, expand-graph
```

Keeping it current afterwards:

```bash
lawgraph retrieve all --since 7d
lawgraph normalize all --since 7d
lawgraph semantic all --since 7d
```

## Repository map

| Path | Contents |
|------|----------|
| `src/lawgraph/clients/` | one HTTP client per external source |
| `src/lawgraph/pipelines/` | `retrieve/`, `normalize/`, `semantic/` pipelines, the command layer (`command.py`), orchestration |
| `src/lawgraph/sources/` | source registry: single definition of CLI commands and their order |
| `src/lawgraph/core/` | pure logic and shared definitions (models, props, relation catalogue, BWB XML, citations) |
| `src/lawgraph/db/` | the PostgreSQL store (`ArangoStore`), bulk `NodeWriter` / `EdgeWriter`, schema, queries |
| `src/lawgraph/api/` | FastAPI app: `routes/`, `queries/`, `schemas/` |
| `src/lawgraph/commands/` | sequences of phases (`bootstrap`, `expand-graph`), reports (`check`, `gaps`, `verify`) `ministries`, `courts` and `code-families` (build the ministry, court and code tables) and `curated` (the lists kept by hand) |
| `src/lawgraph/data/` | tables built from official sources and committed (`ministries.json`, `courts.json`, `code_families.json`); `curated/` what no source gives, kept with `lawgraph curated` (party colours, the seating plan, judgment names, decision kinds, courts outside the value list, ministry keys, order, successions and aliases) |
| `src/lawgraph/config/` | `constants.py` (every name), `settings.py` (every environment value; loads `.env`) |
| `tests/` | offline test suite (fake store, real XML fixtures) |

## CLI

```
lawgraph <retrieve|normalize|semantic> <pipeline|all> [options]
lawgraph bootstrap | expand-graph | check | gaps
lawgraph <phase> <pipeline> --help
lawgraph sources                 # every pipeline under its source, and what it does
```

A pipeline has one address, `<phase> <source>[-<part>]`: `normalize tk-dossiers`, `semantic
rechtspraak-citations`. It is what one types, the label of its log lines, its module and its
class. Sources: `tk`, `rechtspraak`, `eurlex`, `bwb`, `staatsblad`, `staatscourant`,
`eerstekamer`, `echr`, `verdragenbank`, and `graph` for what works on the whole graph.
`--since` (`2024-01-01`, `7d`, or `last` on `<phase> all`) is the one date option. A command
exits 1 when it failed and 2 for a command line it cannot read. Full reference in
`docs/operations.md`.

## Configuration

Environment variables, loaded from `.env` by `config/settings.py`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_DB_PASSWORD` | none | password of the server of `docker-compose.yml` |
| `LAWGRAPH_DB_URL` | `postgresql://lawgraph:<password>@localhost:5432` | database server |
| `LAWGRAPH_DB_NAME` | `lawgraph` | database name; created when missing |
| `LAWGRAPH_ALLOWED_ORIGINS` | localhost:5173/5174 | CORS allow-list of the API |

External base URLs default to the public endpoints. All variables are listed in
`docs/operations.md`.

## Documents

| File | Topic |
|------|-------|
| `docs/architecture.md` | pipeline model, source registry, layering, writing at scale, enforced conventions |
| `docs/data-model.md` | nodes, edges, keys, versioning, parliament model, indexes, relation catalogue |
| `docs/pipelines.md` | per source: retrieval, normalization, semantic detection, ordering |
| `docs/api.md` | endpoints, response conventions, middleware, auth |
| `docs/operations.md` | environment variables, CLI, runs, observability, tests |

## Status

Implemented: retrieve, normalize and semantic phases for Tweede Kamer (cases, dossiers),
Rechtspraak, EUR-Lex, BWB (current text plus full history from the XML), Staatsblad,
Staatscourant, Eerste Kamer (Kamerstukken) and ECHR; Verdragenbank (retrieve and normalize); the API.

Open:

- Of the BWB WTI files only the official abbreviations are ingested (as
  `instruments.props.short_title`); the amendment log and `grondslag-voor` are not.
- Rechtspraak is loaded for every court inside the window (`--court` narrows it); an older
  judgment arrives only when a loaded record cites it (`expand-graph`). Citations between judgments are read from the text; of the structured
  metadata only `dcterms:relation` is used (for `APPEAL_OF`), LiDO is not.
- EUR-Lex implementation data (`eur`) is not evaluated.
- Not covered: CVDR (local regulations) and the Omgevingswet API.
- The Eerste Kamer is loaded as Kamerstukken only, from the KOOP SRU. Votes and their outcome are
  not: they exist only as prose in the Handelingen and as HTML on eerstekamer.nl.
- Nothing installs a schedule: `scripts/daily.sh` and `scripts/weekly.sh` are there for cron
  or launchd (`docs/operations.md`).

## License

MIT, see `LICENSE`.
