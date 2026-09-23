# LawGraph

LawGraph turns Dutch and EU legal sources into one queryable knowledge graph in ArangoDB:
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

Requires Python 3.11+ and ArangoDB 3.12 (a `docker-compose.yml` is included).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # set ARANGO_PASSWORD and ARANGO_ROOT_PASSWORD
docker compose up -d arangodb

lawgraph bootstrap              # retrieve (last 2 years of what keeps producing; --window all for history), normalize, semantic, expand-graph
lawgraph-api                    # http://localhost:8000/docs
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
| `src/lawgraph/db/` | `ArangoStore`, bulk `NodeWriter` / `EdgeWriter`, schema, indexes, search views |
| `src/lawgraph/api/` | FastAPI app: `routes/`, `queries/`, `schemas/` |
| `src/lawgraph/commands/` | sequences of phases (`bootstrap`, `expand-graph`) and reports (`check`, `gaps`) |
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
| `ARANGO_URL` | `http://localhost:8529` | database host |
| `ARANGO_DB_NAME` | `lawgraph` | database name; created when missing |
| `ARANGO_USER` / `ARANGO_PASSWORD` | `root` / empty | credentials |
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
- Writing needs a shared key (`X-Write-Key`, `X-Curation-Key`); there are no users or roles,
  so a vote is not tied to a person and the watch list is one list for the deployment.
- Rechtspraak is loaded for the chosen courts (default: Hoge Raad, Raad van State, the hoven)
  inside the window; a judgment of another court arrives only when a loaded record cites it
  (`expand-graph`). Citations between judgments are read from the text; of the structured
  metadata only `dcterms:relation` is used (for `APPEAL_OF`), LiDO is not.
- EUR-Lex implementation data (`eur`) is not evaluated.
- Not covered: CVDR (local regulations) and the Omgevingswet API.
- The Eerste Kamer is loaded as Kamerstukken only, from the KOOP SRU. Votes and their outcome are
  not: they exist only as prose in the Handelingen and as HTML on eerstekamer.nl.
- Nothing installs a schedule: `scripts/daily.sh` and `scripts/weekly.sh` are there for cron
  or launchd (`docs/operations.md`).

## License

MIT, see `LICENSE`.
