# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set ARANGO_PASSWORD and ARANGO_ROOT_PASSWORD
docker compose up -d arangodb        # the database itself is created on first use
```

## Checks

```bash
pytest tests -q                      # unit suite: fake stores, no database, a few seconds
ruff check src tests
ruff format --check src tests
mypy src
pre-commit run --all-files           # ruff --fix, ruff format, whitespace and YAML checks
```

Pull requests run the same checks in CI. Fix all findings before pushing.

**Integration tests** (`tests/integration/`) run the real code and the real CLI against a
second, deliberately small ArangoDB — the unit suite above never executes a query, so what only
a server shows (a result built in its memory, a cursor that is killed, a run restarted midway)
stays invisible there. They need their own database, never the one `.env` points at:

```bash
docker compose -f docker-compose.test.yml up -d
ALLOW_DB_TESTS=1 pytest tests/integration     # a couple of minutes
docker compose -f docker-compose.test.yml down
```

A different, single file, `tests/test_aql_validity.py`, also needs `ALLOW_DB_TESTS=1` and a
real server, but is collected by `pytest tests` (not `pytest tests/integration`) and, unless you
export `LAWGRAPH_TEST_ARANGO_URL`, defaults to whatever `ARANGO_URL` your `.env` names — normally
your local dev server, not the test one above. It never reads or writes real data either way: it
creates its own scratch database there and asks the server to `explain` every static AQL query in
`src/lawgraph`, so a query the server rejects (an operator it does not know, a misspelt function)
fails here instead of in a real run.

Details, including what `seed.py` can build and at what scale: `docs/operations.md`,
"Tests and CI".

When a real run shows a problem the unit suite could not have caught, reproduce it here first —
as a failing integration test on the small server — before fixing it; small data on a small
server fails the way the real corpus does on the real one. Do not substitute a database-free
benchmark or a sampled measurement for that reproduction.

## Conventions

- Python 3.11+, type annotations on all code.
- Keys come from `make_node_key()` (`lawgraph.core.models`); re-running a pipeline must
  produce the same keys and upsert, never duplicate.
- Collection names, relation names and source ids are constants in
  `src/lawgraph/config/constants.py`, also inside AQL. Only
  `src/lawgraph/config/settings.py` reads the environment; a new variable also goes into
  `.env.example` and `docs/operations.md`.
- A command ends through `run_command` (`pipelines/command.py`) so that exit codes stay uniform;
  the one date option is `--since`, offered only where the pipeline filters on it.
- New relation names go into `src/lawgraph/core/relations.py`; regenerate the tables in
  `docs/data-model.md` with `python -m lawgraph.core.relations`.
- Pipelines follow the naming rule, return a `PipelineResult` from `run()`, write in bulk
  (`NodeWriter`, `EdgeWriter`, `existing_keys`) and are registered in
  `src/lawgraph/sources/registry.py`. Details: `docs/architecture.md`.
- Pure logic (text in, hits out) lives in `core/` or in a detector module without store
  access, and is tested without fakes. `api/` and `pipelines/` never import each other.
- McCabe complexity at most 15 (ruff C901).
- Log with `get_logger(__name__)`; no `print()` in library code.
- Test with small real fixtures where a source has structure (`tests/fixtures/`).

## Branches and pull requests

Work on a feature branch and open a pull request against `develop`. Describe which
pipelines and sources are affected. `main` receives release merges only; do not force-push it.
