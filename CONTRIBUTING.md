# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set ARANGO_PASSWORD and ARANGO_ROOT_PASSWORD
docker compose up -d arangodb        # the database itself is created on first use
```

The test suite needs no database.

## Checks

```bash
pytest tests -q
ruff check src tests
ruff format --check src tests
pre-commit run --all-files           # ruff --fix, ruff format, whitespace and YAML checks
```

Pull requests run the same checks in CI. Fix all findings before pushing.

## Conventions

- Python 3.11+, type annotations on all code.
- Keys come from `make_node_key()` (`lawgraph.core.models`); re-running a pipeline must
  produce the same keys and upsert, never duplicate.
- Collection names, relation names and source ids are constants in
  `src/lawgraph/config/constants.py`, also inside AQL. Only
  `src/lawgraph/config/settings.py` reads the environment; a new variable also goes into
  `.env.example` and `docs/operations.md`.
- A command ends through `run_step` (`pipelines/factory.py`) so that exit codes stay uniform;
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
