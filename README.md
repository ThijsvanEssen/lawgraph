# LawGraph

LawGraph turns Dutch and EU legal sources into one knowledge graph in PostgreSQL: legislation
and its history, case law, and the parliamentary process behind laws. A FastAPI service serves
the graph.

## How it works

Every source passes through three phases. Each can be run again: keys are deterministic and
writes are upserts.

| Phase | Reads | Writes |
|-------|-------|--------|
| `retrieve` | the sources' APIs and sites | `raw_sources`, with the XML and HTML verbatim in the payload store (a directory or an S3 bucket) |
| `normalize` | `raw_sources` | typed nodes and the edges their records state |
| `semantic` | nodes and raw text | edges inferred from structure or text, each with a `confidence` |

A relation a source states (amendments, legal basis and references in the BWB XML) is read,
not guessed. `docs/architecture.md` explains how the phases, the API and the scheduled runs fit
together.

## Quick start

Requires Python 3.11+ and PostgreSQL 18 (`docker-compose.yml` starts one).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # set LAWGRAPH_DB_PASSWORD
```

The store creates its database, with tables, indexes and functions, on first use.

**Development server** (`docker-compose.yml`, port 5432, this machine only). Its data lives in
an external volume. It is sized for 8 GB; `LAWGRAPH_PG_*` in `.env` gives it more.

```bash
docker volume create lawgraph_pgdata      # once
docker compose up -d postgres
lawgraph-api                              # http://localhost:8000/docs
```

**Test server** (`docker-compose.test.yml`, port 5433). A small server (1 GB) in a compose
project of its own, so it never touches the volume above; its data goes with the container. It
backs `tests/pg/` and `tests/integration/`, and it gives an empty API to try in seconds:

```bash
docker compose -f docker-compose.test.yml up -d postgres-test
LAWGRAPH_DB_URL=postgresql://lawgraph:lawgraph-test@localhost:5433 lawgraph-api
docker compose -f docker-compose.test.yml down
```

**A small database with every feature.** `scripts/test-database.sh` builds `lawgraph_small` on
the development server from real sources: a few laws with their history and dossiers, two weeks
of case law and parliament, and a little of every other source. Every relation of the model
occurs in it. It takes about twenty minutes and a few hundred MB.

```bash
scripts/test-database.sh
LAWGRAPH_DB_NAME=lawgraph_small lawgraph-api
```

## Loading data

`lawgraph bootstrap` fills an empty database. It retrieves every source and normalizes each one
as soon as it is in, then derives the semantic edges, fetches what the loaded records refer to
(`expand-graph`) and checks the result. The sources that keep producing load the last two
years; `--window all` loads their whole history. `lawgraph bootstrap --plan` shows the steps
and which are done.

```bash
lawgraph bootstrap
```

Afterwards each phase goes on from where its last complete run began. `scripts/daily.sh` runs:

```bash
lawgraph retrieve all --since last
lawgraph normalize all --since last
lawgraph semantic all --since last
```

## CLI

```
lawgraph <retrieve|normalize|semantic> <pipeline|all> [options]
lawgraph <bootstrap|check|code-families|courts|curated|expand-graph|gaps|ministries|verify> [options]
lawgraph sources                 # every pipeline under its source, and what it does
lawgraph <command> --help
```

A command exits 1 when it failed and 2 for a command line it cannot read. The commands, their
options and the environment variables are in `docs/operations.md`.

## Repository map

| Path | Contents |
|------|----------|
| `src/lawgraph/clients/` | one HTTP client per source |
| `src/lawgraph/pipelines/` | the `retrieve/`, `normalize/` and `semantic/` pipelines, how a command runs (`command.py`) and the `<phase> all` commands (`orchestration.py`) |
| `src/lawgraph/sources/` | the registry: every pipeline, its order and what it waits for |
| `src/lawgraph/core/` | logic without network or database: models, props, the relation catalogue, BWB XML, citations |
| `src/lawgraph/db/` | the PostgreSQL store (`GraphStore`), `NodeWriter` and `EdgeWriter`, the schema, and every query (`queries/`) |
| `src/lawgraph/api/` | the FastAPI app: `routes/` and `schemas/` |
| `src/lawgraph/commands/` | what is no pipeline: `bootstrap` and `expand-graph`, the reports `check`, `gaps` and `verify`, the tables built from official sources (`ministries`, `courts`, `code-families`) and the curated lists (`curated`) |
| `src/lawgraph/data/` | the tables those commands build, committed; `curated/` holds what no source gives (`lawgraph curated list`) |
| `src/lawgraph/config/` | `constants.py` (every name) and `settings.py` (every environment value; reads `.env`) |
| `tests/` | the unit tests; `tests/pg/` and `tests/integration/` run against the test server |

## Configuration

`config/settings.py` reads the environment and `.env`. To start you need:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_DB_PASSWORD` | none | password of the server of `docker-compose.yml` |
| `LAWGRAPH_DB_URL` | `postgresql://lawgraph:<password>@localhost:5432` | database server |
| `LAWGRAPH_DB_NAME` | `lawgraph` | database; created when missing |

The other variables are in `docs/operations.md`.

## Documents

| File | Topic |
|------|-------|
| `docs/architecture.md` | how the parts fit together: phases, registry, layering, writing at scale, conventions |
| `docs/data-model.md` | nodes, edges, keys, props, tables, indexes and the relation catalogue |
| `docs/pipelines.md` | per source: what is retrieved, normalized and derived, and in which order |
| `docs/api.md` | endpoints and response conventions |
| `docs/operations.md` | environment, commands, runs, deploy, observability, tests |

## Status

Loaded, normalized and linked:
- the Tweede Kamer: cases, dossiers, papers with their text, votes, commitments, members and
  committees;
- the Eerste Kamer: papers, votes, bills, agendas, factions and committees;
- the BWB: every regulation, with its history and the WTI abbreviations;
- Staatsblad, Staatscourant and treaties (Verdragenbank);
- EUR-Lex: acts, and the Dutch measures that implement them;
- Rechtspraak: every court, and ECHR judgments against the Netherlands;
- cabinets (Rijksoverheid) and ministries (TOOI).

Not covered:
- of the WTI files, only the general information is read; the amendment log and
  `grondslag-voor` are not;
- citations between judgments come from the text and from `dcterms:relation` and
  `isReplacedBy`; LiDO is not used;
- an older judgment arrives only when a loaded record cites it (`expand-graph`);
- CVDR (local regulations) and the Omgevingswet API.

## License

MIT, see `LICENSE`.
