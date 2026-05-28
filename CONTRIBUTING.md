# Contributing to LawGraph

LawGraph builds a Dutch and EU legal knowledge graph in ArangoDB. Pipelines are deterministic: re-running any pipeline produces the same `_key` values and idempotent upserts.

## Local setup

1. Clone and create a virtual environment:

   ```bash
   git clone <repo-url>
   cd lawgraph
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

2. Copy `.env.example` to `.env` and fill in the ArangoDB connection:

   ```env
   ARANGO_URL=http://localhost:8529
   ARANGO_DB_NAME=lawgraph
   ARANGO_USER=root
   ARANGO_PASSWORD=changeme
   ```

3. Start ArangoDB:

   ```bash
   docker-compose up -d arangodb
   ```

## Running pipelines

The unified CLI is `lawgraph` (or `python -m lawgraph`):

```bash
# Retrieve raw data
lawgraph retrieve all

# Normalize into graph nodes and edges
lawgraph normalize all

# Infer semantic citation edges
lawgraph semantic all
```

Run individual sources:

```bash
lawgraph retrieve bwb --mode full
lawgraph normalize bwb --since 7d
lawgraph semantic bwb
```

Pass `--help` after a source name to see all flags.

## Coding conventions

- Python 3.11+; type annotations are required throughout.
- Use `make_node_key()` from `lawgraph.core.models` for all `_key` derivation. Multiple runs must produce identical keys.
- Collection names and relation types are defined as constants in `src/lawgraph/config/constants.py`. Do not hardcode strings.
- Runtime configuration (URLs, credentials, feature flags) belongs in `.env` via `src/lawgraph/config/settings.py`.
- All pipeline classes must return a `PipelineResult` from `run()`.
- Complexity limit: McCabe complexity C901 <= 15 (enforced by ruff).
- Log using `get_logger(__name__)` from `lawgraph.core.logging`; do not use `print()`.

## Tests

```bash
pytest tests/
# Opt in to real network calls:
ALLOW_NETWORK_TESTS=1 pytest tests/
```

## Linting

```bash
ruff check src tests
```

Fix all issues before pushing.

## Branches, commits, and pull requests

- Work on feature branches under `feature/<description>`.
- Commit messages should be descriptive and reference the changed component, e.g. `fix: deterministic keys for stemmingen` or `feat: staatsblad normalize pipeline`.
- Open pull requests against `develop`. Describe which pipelines and sources were tested.
- PRs targeting `main` are reserved for release merges.
- Do not force-push to `main`.

Thank you for contributing.
