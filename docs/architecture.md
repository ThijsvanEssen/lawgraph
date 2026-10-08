# Architecture

LawGraph is a batch system that fills a graph in PostgreSQL, plus an HTTP API that only reads
it. The user interface is Concordans, a SvelteKit front end in a repository of its own that
reads this API; this repository has none.

## Pipeline model

```
source ──retrieve──▶ raw_sources ──normalize──▶ nodes + stated edges ──semantic──▶ inferred edges ──▶ API
```

| Phase | Input | Output | Rule |
|-------|-------|--------|------|
| retrieve | a source's API or site | `raw_sources` records (keys: `docs/data-model.md`), their XML or HTML in the payload store; fetching again replaces both | stores the payload verbatim, does not interpret it |
| normalize | `raw_sources` of its source and kinds, optionally fetched since a date | nodes, and the edges their records state | deterministic keys, props merged on upsert |
| semantic | nodes and raw text | edges with `confidence`, `source` and `meta` | reads structure where the source has it, text patterns otherwise |

What every pipeline shares:

- `run(...)` returns a `PipelineResult` (`core/models.py`): `created`, `updated`,
  `unchanged`, `skipped`, `errors` and `notes`.
- A record that cannot be read or fetched is left out, counted and named once (`Progress`,
  `result.skipped`); the run goes on. A query or a write that fails raises: `run_command`
  records the pipeline as failed and the command exits 1. No pipeline turns a failed query into
  a run over half the data.
- A normalize pipeline implements `fetch_raw` → `normalize_nodes` → `build_edges`
  (`NormalizePipelineBase`). It does not count its writes: its `self.store` is a
  `CountingStore` (`db/counting.py`) that tallies what every write of the store reports, through
  `NodeWriter`, `EdgeWriter` or a direct call. `run` adds that tally to the result; a pipeline
  only records `skipped` and errors. When the pipeline fails, it logs what was written and
  raises.
- A retrieve pipeline extends `RetrievePipelineBase`: `fetch` yields `RetrieveRecord`s, which
  are stored (`_store_all`). A semantic pipeline implements `run` on `SemanticPipelineBase`.
- A record removed at the source stays in the graph, with two exceptions: the Tweede Kamer
  marks deleted records (`Verwijderd`), and normalize removes those; a semantic step removes the
  edges it no longer derives.

## Phases, sources, pipelines and their address

A **phase** is `retrieve`, `normalize` or `semantic`. A **source** is where records come from
(`SOURCES` in `sources/registry.py`; `graph` is what works on the whole graph). A **pipeline**
is one unit of work in one phase for one source, and it has an address:

```
<phase> <source>[-<part>]                 normalize tk-dossiers
lawgraph normalize tk-dossiers            what one types
[normalize tk-dossiers]                   the label of its log lines, its row in the table
pipelines/normalize/tk_dossiers.py        its module (retrieve: retrieve_tk_dossiers in retrieve_commands.py)
TKDossiersNormalizePipeline               its class
LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS       its skip variable
```

The main pipeline of a source has no part (`normalize bwb`). A pipeline that links two sources
belongs to the one its edges start at, the text that is read (`semantic tk-mvt`, `semantic
bwb-implements`). A module of a phase package that is no pipeline starts with an underscore.

The address is written nowhere: the registry reads it from the module of the class, or for
retrieve from the name of the command function, and refuses at import a class whose name does
not follow. The registry lists the pipelines of each phase in the order `<phase> all` runs
them, and says what each waits for:

- `after`: pipelines of the same phase that must have ended first (a retrieve that reads what
  another stored; a normalize that reads nodes another one wrote);
- `reads`: of a retrieve, the normalized nodes it chooses its work from (`retrieve tk-content`
  fetches the XML of the documents of `normalize tk-dossiers`);
- `fed_by`: of a normalize, the retrieves whose raw records it reads besides its own;
- `lane`: the server a retrieve talks to, so one server never gets two request streams;
- `fills_gaps`: the retrieve has `--mode gaps`.

`lawgraph sources` prints every pipeline under its source. Adding a pipeline: write the module
under its address and add one `_pipeline(...)` line to the list of its phase; a new source goes
into `SOURCES` first.

A retrieve pipeline chooses what to fetch in one of three ways (`--mode`): what changed since a
date (`incremental`), everything inside the window (`full`), or what loaded records refer to and
the graph holds only a stub of (`gaps`, from the queries of `pipelines/retrieve/_gaps.py`).
Filling gaps is retrieve, not a phase of its own.

## Commands

A command is a function `(argv) -> PipelineResult`: it parses its options, does its work and
returns what it did. `run_command(label, command, argv)` (`pipelines/command.py`) runs it: it
sets the label of the log lines (the address, or the command's name), logs the start and the
end with the time, and turns an exception or a result with errors into a failed `Outcome`. Only
the entry points (`__main__`, `api/app.py`) set up logging, and only `__main__` ends the
process: 0, 1 when the command failed, 2 for a command line it cannot read. So any command can
be a part of another. The module docstring of `pipelines/command.py` names each layer.

`<phase> all` (`pipelines/orchestration.py`) runs every pipeline of a phase: retrieve in lanes,
one per server; normalize and semantic in registry order. It logs a line as each pipeline ends
and a table at the end. When every pipeline ended `ok`, it records in `pipeline_state` when the
run began; `--since last` starts there the next time (`pipelines/watermark.py`). A gaps run
records nothing. After normalize and semantic it runs `VACUUM (ANALYZE)`.

| Command | What it is |
|---------|------------|
| `bootstrap` | a build of an empty database (below) |
| `expand-graph` | rounds of `retrieve all --mode gaps` with `normalize all` and `semantic all` of what came in, then one full `semantic all` |
| `poll` | one source between the nightly runs: its retrieves over a window back, their normalize and the semantic steps the feed needs (`commands/poll.py`) |
| `check`, `gaps`, `verify` | reports that only read: is the graph what the pipelines should have made, what a gaps run would fetch, does every cabinet meet the rules of its seats and phases |
| `courts`, `ministries`, `code-families` | build a table from an official source and commit it (`data/courts.json`, `ministries.json`, `code_families.json`) |
| `curated` | lists, checks and sets what a person decides (`data/curated/`) |

What no official source gives and a person decides (a party colour, the name of a landmark
judgment, our key of a ministry) is data in `data/curated/`, which only `lawgraph curated`
changes. How a source writes (month names, name particles, ECLI country codes) is parser
vocabulary and stays in code.

## From an empty database to a running API

**Bootstrap.** `lawgraph bootstrap` (`commands/bootstrap.py`, `bootstrap_plan.py`) runs every
step of a build in one process. Each server has a lane for its retrieves, and one write lane
runs every normalize and semantic step one at a time, each as soon as what it waits for has
ended. So the other sources are normalized while Rechtspraak is still being retrieved. Then
come `analyze` (`VACUUM (ANALYZE)`), the semantic steps in registry order, `expand-graph` and
`check`. A retrieve that chooses from what its own normalize makes of it (`retrieve eurlex`) is
left out: `expand-graph` fetches those acts. A step that ends `ok` is marked in
`pipeline_state` with the code it ran on, and a build started again skips the marked steps;
`--plan` prints the plan and what is done.

**Scheduled runs.** `scripts/daily.sh` runs each phase `--since last`, then `check
--skip-edges`; `scripts/weekly.sh` runs a full `semantic all`, `expand-graph` and `check`;
`scripts/backup.sh` dumps the database. They share one lock (`scripts/_run.sh`), so two never
write at once. Schedules, logs and alerts: `docs/operations.md`, "Runs".

**Release.** A push to the branch `release` deploys that commit: CI runs mypy and the tests,
then on the server checks it out, installs it and restarts the API, under the lock of the
scheduled runs (`docs/operations.md`, "Deploy").

**The API** (`api/`) reads only. A route calls functions of `db/queries/` and answers with the
DTOs of `api/schemas/`. Every write to a table of the graph bumps its row in
`lg_data_version`, and the API's `ETag` follows that version, so a migration shows without a
restart (`docs/api.md`). An answer kept per table is kept while its tables stand still
(`db/version_cache.py`; `tests/pg/test_cached_tables.py` checks the tables each one names
against the plans of its statements).

## Layering

| Layer | Rule |
|-------|------|
| `config/` | `constants.py`: every name (collections, relations, source ids, raw kinds). `settings.py`: every value from the environment; importing it loads `.env` |
| `core/` | logic and shared definitions, each defined once: node and props models, the relation catalogue, BWB XML, citation extraction, dossier stages, identifiers, XML and time helpers, batching, the TTL cache. Imports only `config` and `core`; no network or database, but it reads (and the build commands write) the data files of `data/` |
| `db/` | all database access: `GraphStore`, `NodeWriter`, `EdgeWriter`, `CountingStore`, the schema, the payload store (`payloads.py`), and every query in `queries/` as a function in the terms of its caller (`get_dossier_hub(store, number)`) |
| `clients/` | HTTP only; one class per source on `BaseClient`, paced per host |
| `pipelines/` | the phases; depend on `config`, `core`, `db`, `clients` |
| `api/` | routes and DTOs; depends on `config`, `core`, `db` |
| `commands/` | what is no pipeline (above) |

`api/` and `pipelines/` never import each other; what both need lives in `core/`.

A semantic pipeline keeps its detectors (text in, hits out, no store) apart from the pipeline
that loops over nodes and writes edges. Detectors are tested without fakes; the pipeline's unit
tests fake the query functions of `db/queries/`, and what a query does is tested against a real
server (`tests/pg/`, `tests/integration/`).

## Writing at scale

The corpus is large (hundreds of thousands of judgments and parliamentary documents, millions
of edges), so cost must not grow with the number of round trips. Every pipeline writes in bulk
and looks up by set.

| Need | Use | Not |
|------|-----|-----|
| write edges | `EdgeWriter` (`db/edges.py`): `add(from, to, relation, ...)`, then `flush()` or `with` | one insert per edge |
| build an edge document | `make_edge_doc` (the one edge shape: key, `created_at`, confidence check) | a hand-built dict |
| write raw records | `RawSourceWriter` (`db/raw.py`) through `RetrievePipelineBase._store_all`: one request per 500 records, 8 MB or 5 seconds, written on every exit | one insert per record |
| write nodes | `NodeWriter` (`db/nodes.py`) or `NormalizePipelineBase._upsert_nodes` | `insert_or_update` per record |
| does this node exist | `store.existing_keys(collection, keys)`: one query per 5,000 keys | `get_node` per item |
| resolve targets in a semantic run | `SemanticPipelineBase._prefetch_nodes` (bulk), then `_lookup_node` (cached, hits and misses) | `get_node` per citation |
| look up ids by another property | one query per batch, `= ANY(%(values)s)` | one query per item |
| read raw records | `_iter_raw_sources`: a stream, 20 at a time for XML and 1,000 for small JSON, each with its text from the payload store (`store.with_payloads`, 16 objects side by side); `RawRecords` for a kind that is walked more than once | a list of all records |

Write each node as it is read, and keep at most the props its edges need
(`_tk_cases.link_node`): never a dict of all nodes.

Both writers de-duplicate by key inside their buffer (the last wins), flush at 500 nodes or
16 MB and at 1,000 edges, and re-raise a failed batch. A bulk write returns no document: keep
working from the node in memory. A row that would be written as it is, is left alone and
counted as `unchanged`. A node upsert merges `props` (shallow) and unions `labels`. An edge
upsert overwrites `confidence`, `source` and `status`, merges `meta`, and leaves `created_at`
and every curated field alone. An update writes the keys of `props` and `meta` in alphabetical
order (`lg_update`). The API therefore serves them in one order, whichever step wrote them.

`GraphStore.query` streams every read on a server-side cursor, a batch of rows at a time, and
gives its connection back to the pool when the reader stops. Each statement has a ceiling:
`LAWGRAPH_READ_TIMEOUT_MS` for a batch of a read, `LAWGRAPH_WRITE_TIMEOUT_MS` for a write
(`docs/operations.md`). A statement that would find its rows across a whole table reads them
first and writes them in chunks (`db/queries/_chunks.py`). A write is sent again (after 2, 10
and 30 s) while the database cannot be reached; a statement cancelled for running too long is
not. Every connection carries the name of its process (`application_name`), so the watchdog of
a running step (`pipelines/watchdog.py`) logs the long statements of its own process, a
streamed read with the query behind its `FETCH`.

`GraphStore()` creates the database `LAWGRAPH_DB_NAME` when it is missing (and the user may),
with the collation the queries rely on, then whatever is missing of the schema of
`db/schema.py`: tables, indexes, functions and triggers. It refuses a database that sorts
strings by another collation, and one whose tables differ from the schema; both are built
again.

## Conventions enforced by tests and lint

Where possible a convention is derived (the address) or typed (`Phase`, `Store`, a required
`EdgeWriter(what=...)`; mypy runs in CI); lint and tests cover the rest.

| Convention | Enforced by |
|------------|-------------|
| Pipeline class name = CamelCase(module) + Phase + `Pipeline` (`TK`, `BWB`, `ECHR` in capitals); base classes `<Phase>PipelineBase`; every pipeline inherits `PipelineBase` | the registry at import; `tests/test_pipeline_naming.py` |
| A module of a phase package is a pipeline or starts with `_` | `tests/test_source_registry.py` |
| The CLI and its order come from the registry; a skip variable is `LAWGRAPH_<PHASE>_SKIP_<SOURCE>[_<PART>]`; `graph-list-stats` runs last; every retrieve is part of `retrieve all`; `after` names an earlier pipeline of its phase; the Ordering table of `docs/pipelines.md` is the normalize `after` | `tests/test_source_registry.py` |
| `sys.exit` and `setup_logging` only in an entry point | ruff `TID251` (`pyproject.toml`) |
| McCabe complexity at most 15 | ruff `C901` |
| A command exits 1 when it raised or reported errors; `--since` reaches a pipeline only when its `run` takes it | `tests/test_pipeline_cli.py` |
| Only `config/settings.py` reads the environment; `.env.example` lists only variables that are read | `tests/test_configuration.py` |
| SQL lives in `db/` only, and no other layer touches the driver; no `jsonb_build_object` or `jsonb_agg`; every `ORDER BY` says where its nulls go | `tests/test_sql_conventions.py`, `tests/test_conventions.py` |
| A relation name is spelled out only in `config/constants.py` and `core/relations.py`; elsewhere, SQL included, it comes from a `RELATION_*` constant | `tests/test_conventions.py` |
| No identifier, module name or props field contains a Dutch stem of the list in the test; only `clients/`, `pipelines/retrieve/` and the `RAW_KIND_*` values carry a source's spelling | `tests/test_conventions.py` |
| A join on a sparse index excludes null; a semantic pipeline does not have whole documents sent over | `tests/test_conventions.py` |
| Unit tests fake query functions, not the database; every pipeline reports `Progress`; a semantic pipeline writes its edges through `EdgeWriter` | `tests/test_conventions.py` |
| Relation names are English `UPPER_SNAKE` verbs, never repeat the target type, every endpoint is a known collection, only instruments and bills amend, introduce or repeal; the `RELATION_*` constants are the catalogue; the generated tables of `docs/data-model.md` are current | `tests/test_relation_catalogue.py` |
| A node built as a `Node` is validated against the strict Pydantic schema of its collection (unknown fields fail) | `core/props.py`, `tests/test_props_validation.py` |
| `PART_OF` points from the child (article, annex) to the instrument | `tests/test_part_of_direction.py` |
| The writers batch and de-duplicate; `existing_keys` is bounded | `tests/test_edge_writer.py`, `tests/test_node_writer.py`, `tests/test_raw_source_writer.py`, `tests/test_store_existing_keys.py` |
| Logging through `get_logger(__name__)`, no `print()` in library code | review |
