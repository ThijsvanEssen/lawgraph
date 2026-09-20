# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set ARANGO_PASSWORD and ARANGO_ROOT_PASSWORD
docker-compose up -d arangodb        # then create the database named in ARANGO_DB_NAME
```

The test suite needs no database.

## Checks

```bash
pytest tests -q
ruff check src tests
pre-commit run --all-files           # black, ruff --fix, isort, whitespace and YAML checks
```

Pull requests run the same checks in CI. Fix all findings before pushing.

## Conventions

- Python 3.11+, type annotations on all code.
- Keys come from `make_node_key()` (`lawgraph.core.models`); re-running a pipeline must
  produce the same keys and upsert, never duplicate.
- Collection names, relation names and source ids are constants in
  `src/lawgraph/config/constants.py`; runtime configuration is read in
  `src/lawgraph/config/settings.py`. No hardcoded strings.
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
