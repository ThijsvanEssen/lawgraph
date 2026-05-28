# Architecture

LawGraph transforms Dutch and EU legal sources into a queryable ArangoDB knowledge graph. It has no UI; the graph is the product.

## Module layout

```
src/lawgraph/
  __main__.py                   # unified CLI entrypoint
  api/
    app.py                      # FastAPI app, middleware, route registration
    routes/                     # one file per domain
    queries/                    # AQL query functions per domain
    schemas.py                  # Pydantic request/response models
    dependencies.py             # get_store() dependency injection
  clients/                      # HTTP clients per source
    base.py                     # BaseClient (retry, session, URL building)
    bwb.py, rechtspraak.py, tk.py, eu.py, staatsblad.py,
    staatscourant.py, eerstekamer.py, verdragenbank.py, echr.py
  commands/                     # high-level orchestration commands
    bootstrap.py                # seed initial graph structure
    expand_graph.py             # expand from stubs
    fill_gaps.py                # fill missing nodes/edges
  config/
    constants.py                # collection names, relation names, source IDs
    settings.py                 # env-var derived runtime config
  core/
    logging.py                  # structured logging setup
    models.py                   # Node, NodeType, PipelineResult, make_node_key
    props.py                    # typed Pydantic props schemas per node type
    time.py                     # time utilities
  db/
    __init__.py                 # re-exports ArangoStore
    store.py                    # ArangoStore (all DB operations)
    schema.py                   # collection/index/view definitions
  pipelines/
    base.py                     # PipelineBase abstract base
    factory.py                  # make_pipeline_cli() — generates CLI main() functions
    list_stats.py               # stats listing pipeline
    orchestration.py            # run_retrieve_all / run_normalize_all / run_semantic_all
    retrieve_cli.py             # retrieve pipeline CLI dispatch functions
    normalize/                  # normalize pipelines per source
    retrieve/                   # retrieve pipelines per source
    semantic/                   # semantic/inference pipelines
  sources/
    registry.py                 # SourceDescriptor registry; drives orchestrators and CLI
```

## Pipeline phases

Every source goes through three phases in order:

```
External APIs → Retrieve → Normalize → Semantic
                (raw_sources)  (nodes/edges)  (inferred edges)
```

**Retrieve** — fetch raw payloads from external APIs and store them verbatim in `raw_sources`, keyed by `SHA-1(source:kind:external_id)`.

**Normalize** — read `raw_sources`, map records to typed `Node` objects, upsert into document collections with deterministic keys, and write structural edges.

**Semantic** — scan normalized text for legal citations and write inferred edges with confidence scores.

## Sources

| Source ID | Display name | What it fetches |
|-----------|-------------|-----------------|
| `tk` | Tweede Kamer (zaken & documenten) | TK Zaak + DocumentVersie |
| `tk_dossiers` | Tweede Kamer (dossiers, stemmingen, commissies) | Kamerstukdossier, Activiteit, Stemming, Toezegging, Commissie, Persoon, Document |
| `rechtspraak` | Rechtspraak (uitspraken) | Judgment XML from Rechtspraak.nl |
| `eurlex` | EUR-Lex (EU-wetgeving) | EU directive/regulation HTML via CELLAR |
| `bwb` | BWB (Nederlandse wetgeving) | Dutch statute XML from wetten.overheid.nl |
| `bwb_history` | BWB (historische toestanden) | Historical BWB versions |
| `staatsblad` | Staatsblad (NvT voor AMvBs) | Staatsblad AMvB XML |
| `staatscourant` | Staatscourant (ministeriele regelingen) | Staatscourant regeling XML |
| `eerstekamer` | Eerste Kamer (kamerstukken & stemmingen) | EK Kamerstukken |
| `echr` | ECHR HUDOC | ECHR judgment JSON |
| `verdragenbank` | Verdragenbank (Nederlandse verdragen) | Dutch treaty records |

## CLI

The unified CLI entrypoint is `lawgraph` (registered in `pyproject.toml`) or `python -m lawgraph`. It dispatches to the source registry in `sources/registry.py`.

```
lawgraph <phase> <source> [options]
lawgraph bootstrap
lawgraph expand-graph
lawgraph fill-gaps
```

The factory module (`pipelines/factory.py`) generates `main(argv)` functions for normalize and semantic pipelines, handling argument parsing, `ArangoStore` construction, `run()` invocation, and `sys.exit(1)` on errors.

## Running the full pipeline

```bash
lawgraph retrieve all    # fetch from all sources
lawgraph normalize all   # build node and edge collections
lawgraph semantic all    # infer semantic edges
```

Or run each phase per-source with `--since 7d` to process only recent data:

```bash
lawgraph normalize bwb --since 7d
```

## Design principles

**Idempotent** — every pipeline can be re-run. Nodes and edges use deterministic `_key` values; all writes go through `insert_or_update`.

**Single edge collection** — all edges (structural and semantic) live in the `edges` collection. The `relation` field distinguishes structural from semantic edges; `confidence` and `status` fields qualify semantic and temporal state.

**Fail gracefully** — errors on individual records are logged and counted; the pipeline continues. Fetch-level failures abort early and surface in the summary.

**Uniform interface** — every pipeline exposes `run(since=None) -> PipelineResult`. `PipelineResult` carries `created`, `updated`, `skipped`, and `errors` counts. Orchestrators log a summary table and exit with code 1 if any step fails.

**Configuration over code** — collection names and relation types are constants in `config/constants.py`. Runtime settings (URLs, credentials, rate limits) are env-var derived in `config/settings.py`. No profile YAMLs; no hardcoded domain strings in business logic.
