# Contributing

## Setup

As in the README's "Quick start": a virtualenv with `pip install -e ".[dev]"`, a `.env` with
`LAWGRAPH_DB_PASSWORD`, and the development server of `docker-compose.yml`.

## Checks

```bash
pytest tests -q                      # unit suite: no database, a few seconds
ruff check src tests
ruff format --check src tests
mypy src
pre-commit run --all-files           # the hooks of .pre-commit-config.yaml
```

The unit suite never runs a query. What only a server shows (a result built in its memory, a
cursor that is killed, a run restarted halfway) is tested in `tests/pg/` and
`tests/integration/`, against the small test server of `docker-compose.test.yml`, never the
database of `.env`:

```bash
docker compose -f docker-compose.test.yml up -d postgres-test
ALLOW_DB_TESTS=1 pytest tests/pg tests/integration   # some minutes
docker compose -f docker-compose.test.yml down
```

`tests/pg/test_sql_validity.py` asks the server to plan every static SQL statement in
`src/lawgraph`, so a statement it rejects fails there instead of in a real run. What `seed.py`
can build, and at which scale: `docs/operations.md`, "Tests and CI".

CI runs on every pull request and on a push to `develop` or `main`, not on a push to another
branch: the unit suite and mypy on Python 3.11 and 3.14, and `tests/pg` and `tests/integration`
against PostgreSQL 18. The release pull request (`main-X.Y.Z` into `main`) and its merge to
`main` hold the files of a develop commit that already passed, so they check that run instead
(`.github/scripts/tested-on-develop.sh`). Fix every finding before you push.

When a real run shows a problem the unit suite could not catch, first reproduce it as a failing
integration test on the test server, then fix it. Small data on a small server fails the way the
real corpus does on the real one; a measurement without a database does not replace that test.

## Conventions

- Python 3.11+, with type annotations everywhere.
- Keys come from `make_node_key()` (`lawgraph.core.models`). Running a pipeline again gives the
  same keys and upserts; it never duplicates.
- Collection names, relation names and source ids are constants in
  `src/lawgraph/config/constants.py`. Only `src/lawgraph/config/settings.py` reads the
  environment; a new variable also goes into `.env.example` and `docs/operations.md`.
- SQL lives in `src/lawgraph/db/` only.
- A command runs through `run_command` (`pipelines/command.py`), so exit codes are the same
  everywhere. A pipeline offers `--since` only where it filters on it.
- A new relation goes into `src/lawgraph/core/relations.py`; `python -m lawgraph.core.relations`
  regenerates its tables in `docs/data-model.md`.
- A pipeline follows the naming rule, returns a `PipelineResult` from `run()`, writes in bulk
  (`NodeWriter`, `EdgeWriter`, `existing_keys`) and is registered in
  `src/lawgraph/sources/registry.py` (`docs/architecture.md`).
- Logic without I/O (text in, hits out) lives in `core/` or in a detector module without store
  access, and is tested without fakes. `api/` and `pipelines/` never import each other.
- McCabe complexity at most 15 (ruff C901).
- Log with `get_logger(__name__)`; no `print()` in library code.
- Where a source has structure, test with small real fixtures (`tests/fixtures/`).

## Branches and pull requests

Work on a feature branch and open a pull request against `develop`; say which sources and
pipelines it touches. `main` receives release merges only. A push to `release` deploys to the
server (`docs/operations.md`, "Deploy"): never push there by hand, and never force-push `main`.
