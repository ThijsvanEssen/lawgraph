# Architecture

Lawgraph transforms Dutch and EU legal sources into a queryable ArangoDB knowledge graph. It has no UI; the graph is the product.

## Pipeline phases

Every source goes through three phases in order:

```
External APIs → Retrieve → Normalize → Semantic
                (raw_sources)  (nodes/edges)  (inferred edges)
```

**Retrieve** — fetch raw payloads from external APIs and store them verbatim in `raw_sources`.

| CLI | Source |
|-----|--------|
| `lawgraph-retrieve-tk` | Tweede Kamer OData (publications, procedures) |
| `lawgraph-retrieve-rechtspraak` | Rechtspraak.nl (judgment index + full text) |
| `lawgraph-retrieve-eurlex` | EUR-Lex / CELEX (EU instruments) |
| `lawgraph-retrieve-bwb` | wetten.overheid.nl (statutes + articles) |

**Normalize** — read `raw_sources`, map to typed `Node` objects, write to document collections with deterministic keys, and build structural edges in `edges_strict`.

**Semantic** — scan normalized text for legal citations and write inferred edges to `edges_semantic`.

| CLI | What it detects | Edge type |
|-----|----------------|-----------|
| `lawgraph-semantic-tk-articles` | Article references in TK documents | `MENTIONS_ARTICLE` |
| `lawgraph-semantic-rechtspraak-articles` | Article references in judgments | `MENTIONS_ARTICLE` |
| `lawgraph-semantic-eu-articles` | Article references in EU instruments | `MENTIONS_ARTICLE` |
| `lawgraph-semantic-bwb-articles` | Cross-references between BWB articles | `REFERS_TO_ARTICLE` |
| `lawgraph-semantic-judgment-citations` | ECLI cross-references between judgments | `CITES_JUDGMENT` |

## Design principles

**Idempotent** — every pipeline can be re-run. Nodes and edges use deterministic `_key` values; all writes go through `insert_or_update`.

**Profile-driven** — a domain profile YAML (`src/config/*.yml`) controls which instruments to load, code aliases, and filters. Pass `--profile strafrecht` or set `LAWGRAPH_PROFILE`.

**Fail gracefully** — errors on individual records are logged and counted; the pipeline continues. Fetch-level failures abort early and surface in the summary.

**Uniform interface** — every pipeline exposes `run(since=None) → PipelineResult`. `PipelineResult` carries `created`, `updated`, `skipped`, and `errors` counts. The `_all` orchestrators log a summary table and exit with code 1 if any step fails.

## Running the full pipeline

```bash
lawgraph-retrieve-all    # fetch from all sources
lawgraph-normalize-all   # build node and edge collections
lawgraph-semantic-all    # infer semantic edges
```

Or run each phase individually with `--since 2024-01-01` to process only recent data.
