# Operations

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ARANGO_URL` | `http://localhost:8529` | ArangoDB host |
| `ARANGO_DB_NAME` | `lawgraph` | Database name |
| `ARANGO_USER` | `root` | DB user |
| `ARANGO_PASSWORD` | _(empty)_ | DB password |
| `LAWGRAPH_PROFILE` | _(none)_ | Domain profile name (e.g. `strafrecht`) |
| `LAWGRAPH_API_PORT` | `8000` | API server port |

Startup fails with a clear error if ArangoDB is unreachable.

## Domain profiles

A profile is a YAML file at `src/config/<name>.yml`. It scopes all pipelines to a specific legal domain.

```yaml
topic: strafrecht

# Short aliases → BWB ID mapping (used by semantic pipelines)
code_aliases:
  Sr: BWBR0001854
  Sv: BWBR0001903

# Named instrument aliases for TK/EU semantic detection
instrument_aliases:
  Wetboek van Strafrecht:
    bwb_id: BWBR0001854
  GDPR:
    celex: 32016R0679

# BWB IDs to fetch during retrieve
bwb:
  ids:
    - BWBR0001854
    - BWBR0001903
```

Pass a profile with `--profile <name>` or `LAWGRAPH_PROFILE=<name>`.

## CLI reference

### Orchestrators

```bash
lawgraph-retrieve-all [--since DATE] [--profile NAME]
lawgraph-normalize-all [--since DATE]
lawgraph-semantic-all [--profile NAME]
```

All orchestrators print a summary table and exit with code 1 if any step fails.

### Retrieve

```bash
lawgraph-retrieve-tk --since 2024-01-01 [--limit 200]
lawgraph-retrieve-rechtspraak --since 2024-01-01
lawgraph-retrieve-eurlex CELEX1 CELEX2 ...
lawgraph-retrieve-bwb --profile strafrecht
```

### Normalize

```bash
lawgraph-normalize-tk
lawgraph-normalize-rechtspraak
lawgraph-normalize-eurlex
lawgraph-normalize-bwb
```

### Semantic

```bash
lawgraph-semantic-tk-articles --profile strafrecht
lawgraph-semantic-rechtspraak-articles --profile strafrecht
lawgraph-semantic-eu-articles --profile strafrecht
lawgraph-semantic-bwb-articles --profile strafrecht
lawgraph-semantic-judgment-citations
lawgraph-semantic-instrument-relations --profile strafrecht
```

Skip individual steps in `semantic_all` with env vars:
- `LAWGRAPH_SEMANTIC_SKIP_TK=1`
- `LAWGRAPH_SEMANTIC_SKIP_RECHTSPRAAK=1`
- `LAWGRAPH_SEMANTIC_SKIP_EU=1`
- `LAWGRAPH_SEMANTIC_SKIP_BWB_ARTICLES=1`
- `LAWGRAPH_SEMANTIC_SKIP_JUDGMENT_CITATIONS=1`
- `LAWGRAPH_SEMANTIC_SKIP_INSTRUMENT_RELATIONS=1`

## API

Start the server: `uvicorn lawgraph.api.app:app --port 8000`

### Endpoints

`GET /api/articles/{bwb_id}/{article_number}`
Returns article text, metadata, and outgoing citations.

`GET /api/judgments/{ecli}`
Returns judgment metadata and linked articles.

`GET /api/search?q=<query>[&type=all|articles|judgments|instruments][&limit=20]`
Full-text search across the graph. Returns a list of `SearchResultItem` objects with `id`, `collection`, `result_type`, `display_name`, and `snippet`.

`GET /health`
Returns `{"status": "ok"}` when ArangoDB is reachable.

`GET /docs`
Auto-generated OpenAPI documentation.
