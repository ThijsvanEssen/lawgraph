# Architecture

LawGraph is a batch system that fills an ArangoDB graph, plus an HTTP API on top of it that
is read-only apart from watches and relationship curation. There is no other user interface.

## Pipeline model

```
external source ──retrieve──▶ raw_sources ──normalize──▶ nodes + structural edges ──semantic──▶ inferred edges
```

| Phase | Input | Output | Rule |
|-------|-------|--------|------|
| retrieve | external API | `raw_sources` documents keyed `SHA-1(source:kind:external_id)`; re-fetching replaces the document and refreshes `fetched_at` | stores the payload verbatim, does not interpret it |
| normalize | `raw_sources` filtered by `source`, `kind`, optional `fetched_at >= since` | nodes in domain collections, structural edges | deterministic keys, props merged on upsert |
| semantic | nodes, raw XML | edges with `confidence`, `source`, `meta` | reads structured data where the source has it, text patterns otherwise |

Contract shared by all pipelines:

- `run(...) -> PipelineResult` with `created`, `updated`, `skipped`, `errors`.
- Errors on one record are logged and counted; the run continues. A failure of the whole step
  is recorded in `errors`, and the CLI exits with code 1 when `errors` is non-empty.
- Normalize pipelines implement `fetch_raw` -> `normalize_nodes` -> `build_edges`
  (`NormalizePipelineBase`). They do not count their writes: the base class hands them a
  `CountingStore` (`db/counting.py`) as `self.store`, which tallies the created/updated
  counts the store returns from `bulk_insert_or_update_nodes`, `bulk_insert_or_update_edges`
  and `insert_or_update`. That covers `NodeWriter`, `EdgeWriter`, direct store calls and
  helpers that only receive `store`. `run` adds the tally (nodes plus edges) to `created`
  and `updated`, also when the step failed halfway, and logs the node/edge breakdown. A
  pipeline only records what the store cannot see: `result.skipped` and `result.add_error`.
  Retrieve pipelines extend `RetrievePipelineBase` (`fetch` returns
  `RetrieveRecord`s that are stored) or override `run`. Semantic pipelines implement `run` on
  `SemanticPipelineBase`.
- Removed upstream records are not deleted from the graph.

## Source registry and CLI dispatch

`sources/registry.py` holds one `SourceDescriptor` per source with its retrieve, normalize and
semantic entry points. It is the only place that defines CLI commands and their order; the
skip variable of a step is derived from its phase and source id:

- `lawgraph <phase> <source>` (`__main__.py`) builds its dispatch table from the registry;
  a source id `tk_dossiers` becomes the command `tk-dossiers`.
- A **command** is a function `(argv) -> PipelineResult` (`pipelines/command.py`): it parses
  its options, does its work and returns what it did. Normalize and semantic commands are made
  from a pipeline class by `PipelineCommand`, which reads from the `run` of the pipeline
  whether the command has `--since`; retrieve commands are written out in
  `pipelines/retrieve_commands.py`; `<phase> all`, `bootstrap`, `expand-graph`, `fill-gaps` and
  `check` are commands too.
- A command is run through `run_command(label, command, argv)` (`pipelines/command.py`), by
  `__main__` for what was typed and by a composite command for its parts. `run_command` is the
  one place that sets the log context, writes one line to start and one to end, measures the
  time and turns an exception or a result with errors into a failed `Outcome`. The label is
  what one types (`normalize bwb`) and is the name of the step everywhere.
- A **step** is one phase of one source (`pipelines/orchestration.py`). The names say what
  they take, each built on the one before: `run_step(step)` runs one (or skips it),
  `run_steps(steps)` a list in registry order (in lanes for retrieve) with a table of how
  each ended, going on after a failure unless `--strict`, and `_run_phase(phase, ...)` the
  steps of a whole phase with the mark of `--since last`; `retrieve_all`, `normalize_all` and
  `semantic_all` are the commands on top. The result of a composite command is the sum of
  its parts, with one error per failed part (`combined_result`).
- A pipeline catches what it can deal with itself: one record of many that cannot be read
  or fetched is left out, counted and named once (`Progress`, `result.skipped`). A query or
  a write that fails is not that: it raises, and `run_command` ends the step as failed with the
  error. No pipeline turns a failed query into a run over half the data.
- Only `__main__` sets up logging and ends the process: exit code 0, 1 when the command
  failed, 2 for a command line that cannot be read. A test keeps `sys.exit` and
  `setup_logging()` out of every other module, so any command can be a part of another.
- There is one date option, `--since` (ISO 8601 or relative, `7d`). A command has it only
  when its pipeline filters on it.
- A step with no `retrieve_argv_builder` (`bwb-history`, `tk-content`) is a manual command
  and is not part of `retrieve all`.
- The order in the registry is the order of `semantic all`; pipelines that read edges written
  by others are placed after them.

Adding a source: write the pipelines, add a `SourceDescriptor`.

## Layering

| Layer | Rule |
|-------|------|
| `config/` | `constants.py`: every name (collections, relations, source ids, raw kinds). `settings.py`: every value from the environment; importing it loads `.env`, and no other module reads the environment |
| `core/` | pure logic and shared definitions, each defined exactly once: node and props models, relation catalogue, BWB XML parsing, citation extraction, dossier stage classification, identifiers, XML and time helpers, batching. Imports only `config` and other `core` modules; no I/O |
| `db/` | `ArangoStore` (all database access), `NodeWriter`, `EdgeWriter`, `CountingStore`, schema |
| `clients/` | HTTP only; one class per source on `BaseClient` |
| `pipelines/` | phases; depend on `config`, `core`, `db`, `clients` |
| `api/` | routes, AQL in `queries/`, DTOs in `schemas/`; depends on `config`, `core`, `db` |
| `commands/` | `bootstrap`, `expand-graph`, `fill-gaps`, maintenance; call pipelines and clients |

`api/` and `pipelines/` never import each other. Logic both need lives in `core/`. No test
enforces this; it holds for the current code.

Semantic pipelines separate pure detectors (text in, hits out, no store; unit-tested without
fakes) from the pipeline that loops over nodes and writes edges (tested with a fake store).

## Writing at scale

The corpus is large (hundreds of thousands of judgments and parliamentary documents,
millions of edges), so cost must not grow with the number of database round-trips. Every
pipeline writes in bulk and looks up by set.

| Need | Use | Not |
|------|-----|-----|
| write edges | `EdgeWriter` (`db/edges.py`): `add(from, to, relation, ...)`, `flush()` or `with` | one insert per edge |
| build an edge document | `make_edge_doc` (the one edge shape: key, `created_at`, confidence check) | hand-built dicts |
| write raw records | `RawSourceWriter` (`db/raw.py`) through `RetrievePipelineBase._store_all`: one request per 500 records, 8 MB or 5 seconds, written on every exit | one insert per record |
| write nodes | `NodeWriter` (`db/nodes.py`) or `NormalizePipelineBase._upsert_nodes` | `insert_or_update` per record |
| does this node exist | `store.existing_keys(collection, keys)`: one primary-index query per 5,000 keys | `get_node` per item |
| resolve targets in a semantic run | `SemanticPipelineBase._prefetch_nodes` (bulk) then `_lookup_node` (cached, hits and misses) | `get_node` per citation |
| look up ids by another property | one `FILTER x IN @values` query per batch | one query per item |
| read raw records | `_iter_raw_sources` streams them (20 at a time for XML, 1000 for small JSON); `RawRecords` for a kind that is walked more than once; write each node as it is read and keep at most the props the edges need (`tk_cases.link_node`) | a list of all records, a dict of all nodes |

Both writers de-duplicate by key inside the buffer (last wins), flush automatically at
500 nodes / 1000 edges, and re-raise a failed batch. Bulk writes do not return the stored
document; keep working from the in-memory node. Node upserts merge `props` (shallow) and
union `labels`. Edge upserts overwrite `confidence`, `source`, `status`, merge `meta`, and
leave `created_at` and all curated fields untouched.

`ArangoStore.query` streams every query that reads (the server would otherwise build the
whole result in its memory first: 44,000 toestanden are 3.5 GB) and closes its cursor when
the reader stops; a query that writes is not streamed and gets `max_runtime=600`. Bulk writes
are sent again (after 2, 10 and 30 s) while the database is unreachable.
`ArangoStore()` creates the database `ARANGO_DB_NAME` when it is missing (and the user may
administer the server), then the missing collections, indexes, analyzers and search views.

## Conventions enforced by tests and lint

| Convention | Enforced by |
|------------|-------------|
| Pipeline class name = CamelCase(module) + Phase + `Pipeline` (acronyms BWB, TK, EU, ECHR in capitals); base classes `<Phase>PipelineBase`; every pipeline inherits `PipelineBase` | `tests/test_pipeline_naming.py` |
| McCabe complexity C901 <= 15 | `ruff` (`pyproject.toml`), CI pre-commit |
| Relation catalogue: names are English `UPPER_SNAKE` verbs, never repeat the target type, every endpoint is a known collection, only instruments and bills amend / introduce / repeal, the `RELATION_*` constants are exactly the catalogue; the generated tables in `docs/data-model.md` are current | `tests/test_relation_catalogue.py` |
| CLI commands and their order come only from the registry; skip variables follow `LAWGRAPH_<PHASE>_SKIP_<SOURCE_ID>`; `list-stats` runs last; manual sources stay out of `retrieve all`; dependencies precede dependents in `semantic all` | `tests/test_source_registry.py` |
| Only `config/settings.py` reads the environment; collection names are spelled out only in `config/constants.py`, also inside AQL; `.env.example` lists only variables that are read | `tests/test_configuration.py` |
| Every command exits 1 when it raised or reported errors; `--since` reaches a pipeline only when the command accepts it | `tests/test_pipeline_cli.py` |
| A relation name is spelled out only in `config/constants.py` and `core/relations.py` — everywhere else, including AQL, it comes from a `RELATION_*` constant | `tests/test_conventions.py` |
| Identifiers, module names and stored property names are English; only `clients/`, `pipelines/retrieve/` and the `RAW_KIND_*` values carry a source's Dutch spelling | `tests/test_conventions.py` |
| Props are validated against a strict Pydantic schema per collection (unknown fields fail) | `core/props.py`, `tests/test_props_validation.py` |
| `PART_OF` always points child (article, annex) to instrument | `tests/test_part_of_instrument_direction.py` |
| Bulk writers batch and de-duplicate; store lookups are bounded | `tests/test_edge_writer.py`, `tests/test_node_writer.py`, `tests/test_raw_source_writer.py`, `tests/test_store_existing_keys.py`, `tests/test_batching.py` |
| Logging via `get_logger(__name__)`, no `print()` in library code | convention (review) |
