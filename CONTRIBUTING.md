# Contributing

## Setup

As in the README's "Quick start": a `.venv` from `uv sync --extra dev`, a `.env` with
`LAWGRAPH_DB_PASSWORD`, and the development server of `docker-compose.yml`.

## Dependencies

`pyproject.toml` gives the ranges, `uv.lock` the exact versions that CI, the deploy and a local
`uv sync` install (`--frozen`: the lock as it is, never re-resolved). A change to the
dependencies of `pyproject.toml` comes with `uv lock` in the same commit; newer versions come in
a pull request of their own (`uv lock --upgrade`, or `--upgrade-package NAME`), whose CI run is
the test of them. `tests/conventions/test_tool_versions.py` fails when the lock is not the lock
of `pyproject.toml`, and when a workflow sets up another uv than the `uv` of the dev extra.

## Checks

```bash
pytest tests -q -n auto               # unit suite: no database, over the cores
ruff check src tests
ruff format --check src tests
mypy                                 # src strict, tests checked too (pyproject.toml)
pre-commit run --all-files           # the hooks of .pre-commit-config.yaml
```

`pre-commit install` runs the hooks on every commit, and `mypy` (of `.venv`) before a push.

The unit suite never runs a query. What only a server shows (a result built in its memory, a
cursor that is killed, a run restarted halfway) is tested in `tests/pg/` and
`tests/integration/`, against the small test server of `docker-compose.test.yml`, never the
database of `.env`:

```bash
docker compose -f docker-compose.test.yml up -d postgres-test
ALLOW_DB_TESTS=1 pytest tests/pg -n 3 --dist loadgroup
ALLOW_DB_TESTS=1 pytest tests/integration
docker compose -f docker-compose.test.yml down
```

The test server is shared by every worktree, and it has 1 GB of memory. `tests/pg` runs on
at most three workers there; `tests/integration` runs one test at a time, as each starts the
CLI in processes of its own. Only CI spreads both over all cores, with a server per shard.

`tests/pg/test_sql_validity.py` asks the server to plan every static SQL statement in
`src/lawgraph`, so a statement it rejects fails there instead of in a real run. What `seed.py`
can build, and at which scale: `docs/operations.md`, "Tests and CI".

CI runs on every pull request and on a push to `develop` or `main`, not on a push to another
branch: the unit suite and mypy on Python 3.14, and `tests/pg` and `tests/integration`
against PostgreSQL 18. The release pull request (`main-X.Y.Z` into `main`) and its merge to
`main` hold the files of a develop commit that already passed, so they check that run instead
(`.github/scripts/tested-on-develop.sh`). Fix every finding before you push.

When a real run shows a problem the unit suite could not catch, first reproduce it as a failing
integration test on the test server, then fix it. Small data on a small server fails the way the
real corpus does on the real one; a measurement without a database does not replace that test.

## Conventions

- Python 3.14, with type annotations everywhere.
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
