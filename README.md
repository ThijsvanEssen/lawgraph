# LawGraph

LawGraph turns Dutch and EU legal sources into one queryable knowledge graph in ArangoDB:
legislation and its amendment history, case law, and the parliamentary process behind
laws. The graph is the product; a FastAPI service exposes it.

## How it works

Every source passes through the same three phases, each restartable and idempotent
(deterministic keys, upserts):

| Phase | Reads | Writes |
|-------|-------|--------|
| `retrieve` | external APIs | `raw_sources` (payload stored verbatim) |
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

lawgraph bootstrap              # retrieve (Tweede Kamer: last 2 years), normalize, semantic, expand-graph; creates the database
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
| `src/lawgraph/pipelines/` | `retrieve/`, `normalize/`, `semantic/` pipelines, orchestration, CLI factory |
| `src/lawgraph/sources/` | source registry: single definition of CLI commands and their order |
| `src/lawgraph/core/` | pure logic and shared definitions (models, props, relation catalogue, BWB XML, citations) |
| `src/lawgraph/db/` | `ArangoStore`, bulk `NodeWriter` / `EdgeWriter`, schema, indexes, search views |
| `src/lawgraph/api/` | FastAPI app: `routes/`, `queries/`, `schemas/` |
| `src/lawgraph/commands/` | `bootstrap`, `expand-graph`, `fill-gaps` and maintenance commands |
| `src/lawgraph/config/` | `constants.py` (every name), `settings.py` (every environment value; loads `.env`) |
| `tests/` | offline test suite (fake store, real XML fixtures) |

## CLI

```
lawgraph <retrieve|normalize|semantic> <source|all> [options]
lawgraph bootstrap | expand-graph | fill-gaps
lawgraph <phase> <source> --help
```

Sources: `tk`, `tk-dossiers`, `tk-content`, `rechtspraak`, `eurlex`, `bwb`, `bwb-history`,
`staatsblad`, `staatscourant`, `eerstekamer`, `echr`, `verdragenbank`. The semantic phase has
extra commands (`bwb-grondslagen`, `bwb-amendments`, `bwb-annexes`, `judgment-citations`,
`judgment-appeal`, `instrument-relations`, `amendment-articles`, `mvt-articles`,
`relation-semantics`, `list-stats`). `--since` (`2024-01-01` or `7d`) is the one date option.
Every command exits 1 on failure. Full reference in `docs/operations.md`.

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
- Watches and relationship votes can be written without a credential; only curation has a key.
- Rechtspraak structured references are not used: judgment citations are read from the text,
  and judgment content is retrieved only for the ECLIs asked for.
- EUR-Lex implementation data (`eur`) is not evaluated.
- Not covered: CVDR (local regulations) and the Omgevingswet API.
- The Eerste Kamer is loaded as Kamerstukken only, from the KOOP SRU. Votes and their outcome are
  not: they exist only as prose in the Handelingen and as HTML on eerstekamer.nl.
- Scheduling of incremental runs is not wired.
- ArangoSearch view memory at 200K judgments is an open concern.

## License

MIT, see `LICENSE`.
