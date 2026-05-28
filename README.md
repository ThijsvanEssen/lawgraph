# LawGraph

LawGraph builds a Dutch and EU legal knowledge graph in **ArangoDB**. Pipelines fetch data from Tweede Kamer, Rechtspraak.nl, EUR-Lex, wetten.overheid.nl (BWB), Staatsblad, Staatscourant, Eerste Kamer, Verdragenbank, and ECHR; normalize it into typed nodes; and link nodes with structural and semantic edges. The result is a queryable graph exposed via a FastAPI read API.

## Quick start

Requirements: Python 3.11+, an ArangoDB 3.x/4.x instance.

```bash
git clone <repo-url>
cd lawgraph
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env — at minimum set ARANGO_PASSWORD
```

Start ArangoDB locally:

```bash
docker-compose up -d arangodb
```

Run the full pipeline:

```bash
lawgraph retrieve all       # fetch raw data from all sources
lawgraph normalize all      # build node and edge collections
lawgraph semantic all       # infer semantic citation edges
```

Start the API:

```bash
lawgraph-api
# or: uvicorn lawgraph.api.app:app --reload
```

## Configuration

Copy `.env.example` to `.env`. Required settings:

```env
ARANGO_URL=http://localhost:8529
ARANGO_DB_NAME=lawgraph
ARANGO_USER=root
ARANGO_PASSWORD=changeme
```

All other settings are optional (see `.env.example` for the full list).

Key optional settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LAWGRAPH_ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS allow-list for the API |
| `LAWGRAPH_API_PORT` | `8000` | API listen port |
| `LAWGRAPH_LOG_FORMAT` | _(plain)_ | Set to `json` for structured log output |
| `LAWGRAPH_RATE_LIMIT_CALLS` | `200` | API rate limit per IP per window |
| `LAWGRAPH_RATE_LIMIT_PERIOD` | `60` | Rate limit window in seconds |
| `LAWGRAPH_PROFILE` | _(none)_ | Domain profile name (e.g. `strafrecht`) |

External API base URLs default to the official public endpoints and generally do not need to be changed.

## CLI

The unified CLI entrypoint is `lawgraph` (or `python -m lawgraph`):

```
lawgraph <phase> <source> [options]
```

Phases: `retrieve`, `normalize`, `semantic`. Sources: `tk`, `tk-dossiers`, `rechtspraak`, `eurlex`, `bwb`, `bwb-history`, `staatsblad`, `staatscourant`, `eerstekamer`, `echr`, `verdragenbank`, or `all`.

Special commands:

```
lawgraph bootstrap       # bootstrap database collections and indexes from scratch
lawgraph expand-graph    # iterative expand-graph loop
lawgraph fill-gaps       # diagnose and fill knowledge gaps
```

For source-specific options:

```bash
lawgraph normalize bwb --help
lawgraph retrieve tk-dossiers --help
```

The `lawgraph-api` script starts the API server.

## Development

Run tests:

```bash
pytest tests/
# Network tests (real API calls) — opt in:
ALLOW_NETWORK_TESTS=1 pytest tests/
```

Lint:

```bash
ruff check src tests
```

## Architecture

See `docs/architecture.md` for the pipeline model. See `docs/` for detailed design documents.

## License

MIT — see `LICENSE`.
