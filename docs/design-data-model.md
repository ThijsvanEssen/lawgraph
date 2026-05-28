# Data Model and Database Layer

## 1. Node model

**File:** `src/lawgraph/core/models.py`

```python
@dataclass
class Node:
    collection: str          # Target ArangoDB collection
    type: NodeType           # NodeType enum value
    key: str | None = None   # Deterministic key (set before insert_or_update)
    labels: list[str] = ...  # Domain tags (e.g. ["BWB"], ["TK", "Kamerstuk"])
    props: dict = ...        # Entity-specific fields; validated against core/props.py
```

### Key derivation

`make_node_key(*parts: str | None, fallback="node") -> str` — joins non-None parts with `_`, lowercases, NFKD-normalizes to ASCII, replaces non-alphanumeric characters with `_`, collapses consecutive underscores.

Examples:
- `make_node_key("BWBR0001854")` → `"bwbr0001854"`
- `make_node_key("BWBR0001854", "47")` → `"bwbr0001854_47"`
- `make_node_key("stemming", "dee2ad8f-738b")` → `"stemming_dee2ad8f_738b"`

Edge keys use `SHA-1(from_id:relation:to_id)`.

### NodeType constants

| Value | Used for |
|-------|---------|
| `instrument` | Laws (BWB) and EU instruments (CELEX) |
| `article` | Individual articles within an instrument |
| `judgment` | Court judgments (Rechtspraak.nl, ECHR) |
| `procedure` | TK Zaak — one legislative track |
| `publication` | TK Kamerstukken, Staatsblad, Staatscourant publications |
| `dossier` | Kamerstukdossier — groups one or more Zaak |
| `activiteit` | Debates and hearings |
| `stemming` | Aggregated vote per Besluit |
| `toezegging` | Ministerial commitment |
| `commissie` | Parliamentary committee |
| `lid` | Member of parliament |
| `fractie` | Parliamentary party / political group |
| `instrument_version` | Historical version of an instrument |
| `article_version` | Historical version of an article |
| `topic` | Domain topic node |

### Props validation

`Node.__post_init__` validates `props` against the Pydantic schema for the collection (from `core/props.py`), if one exists. Pass `_skip_validation=True` for internal copies where validation already happened.

---

## 2. Collection catalogue

**File:** `src/lawgraph/config/constants.py` (names), `src/lawgraph/config/settings.py` (list)

| Collection | NodeType | Key scheme |
|-----------|----------|-----------|
| `instruments` | INSTRUMENT | `make_node_key(bwb_id)` or `make_node_key(celex)` |
| `instrument_articles` | ARTICLE | `make_node_key(bwb_id, article_number)` or `make_node_key(celex, article_number)` |
| `instrument_versions` | INSTRUMENT_VERSION | `make_node_key(bwb_id, valid_from)` |
| `instrument_article_versions` | ARTICLE_VERSION | `make_node_key(bwb_id, article_number, valid_from)` |
| `procedures` | PROCEDURE | `make_node_key(external_id)` |
| `publications` | PUBLICATION | `make_node_key(external_id)` |
| `judgments` | JUDGMENT | `make_node_key(ecli)` |
| `topics` | TOPIC | `make_node_key(name)` |
| `kamerstukdossiers` | DOSSIER | `make_node_key(nummer)` or `make_node_key(nummer, toevoeging)` |
| `activiteiten` | ACTIVITEIT | `make_node_key(external_id)` |
| `stemmingen` | STEMMING | `make_node_key("stemming", besluit_id)` |
| `toezeggingen` | TOEZEGGING | `make_node_key(external_id)` |
| `commissies` | COMMISSIE | `make_node_key(external_id)` |
| `leden` | LID | `make_node_key(external_id)` |
| `fracties` | FRACTIE | `make_node_key(external_id)` |
| `raw_sources` | — | `SHA-1(source:kind:external_id)` |
| `watches` | — | `uuid4()` (random) |
| `edge_status_log` | — | `uuid4()` (audit log entries) |

**Edge collection:** `edges` (configurable via `LAWGRAPH_EDGE_COLLECTION`).

---

## 3. Edge model

Stored in the `edges` collection.

```json
{
  "_key": "<SHA-1 of from_id:relation:to_id>",
  "_from": "collection/key",
  "_to": "collection/key",
  "relation": "DEEL_VAN_DOSSIER",
  "source": "tk-dossiers",
  "status": "canoniek",
  "confidence": 0.95,
  "meta": { "raw_match": "...", "snippet": "...", "reason": "..." }
}
```

### Edge status values

| Value | Meaning |
|-------|---------|
| `canoniek` | Current law / confirmed relation |
| `voorgesteld` | Proposed (in legislative procedure) |

`flip_edge_status(edge_key, new_status, reason)` transitions status with an audit entry in `edge_status_log`.

### Relation types

All relation type strings are defined as constants in `src/lawgraph/config/constants.py`. See `docs/graph.md` for the complete edge type table.

---

## 4. Raw sources schema

**Collection:** `raw_sources`

```json
{
  "_key": "<SHA-1 of source:kind:external_id>",
  "source": "tk",
  "kind": "tk-dossier",
  "external_id": "<TK GUID>",
  "fetched_at": "2026-01-01T10:00:00Z",
  "payload_json": { ... },
  "payload_text": null,
  "meta": {}
}
```

Idempotency: same `(source, kind, external_id)` triple → same `_key`; subsequent inserts use `overwrite_mode="replace"`, updating `fetched_at`.

Exception: Rechtspraak index snapshots have `external_id=None` and use a random UUID key — not idempotent.

---

## 5. Index strategy

Indexes are defined in `src/lawgraph/db/schema.py` (`_ensure_indexes`). Key indexes:

| Collection | Fields | Unique | Notes |
|-----------|--------|--------|-------|
| `instruments` | `props.bwb_id` | yes | BWB ID lookup |
| `instruments` | `props.celex` | yes | CELEX lookup |
| `instrument_articles` | `props.bwb_id, props.article_number` | yes | Article lookup |
| `instrument_articles` | `props.celex, props.article_number` | yes | EU article lookup |
| `judgments` | `props.ecli` | yes | ECLI lookup |
| `raw_sources` | `source, kind` | no | Normalize pipeline queries (critical for performance) |
| `edges` | `relation` | no | Edge type filtering |
| `edges` | `_from, relation` | no | Outbound traversal |
| `edges` | `_to, relation` | no | Inbound traversal |
| `edges` | `status` | no | Status filtering |
| `edges` | `confidence` | no | Confidence threshold filtering |
| `edge_status_log` | `timestamp` | no | Audit log time-range queries |
| `edge_status_log` | `edge_key` | no | Audit lookup by edge |

Additional non-sparse indexes on sort-key fields (`instruments.props.article_count`, `judgments.props.date_eff`, etc.) allow the AQL planner to serve list-endpoint queries without collection scans.

### ArangoSearch views

`db/schema.py` also ensures ArangoSearch views for the `/api/search` endpoint:

- `search_articles` — ngram + text_en over `instrument_articles`
- `search_instruments` — ngram + text_en over `instruments`
- `search_judgments` — ngram + text_en over `judgments`
- `search_dossiers` — ngram + text_en over `kamerstukdossiers`
- `search_publications` — ngram + text_en over `publications`
- `search_commissies` — ngram + text_en over `commissies`

Custom analyzers: `lawgraph_ngram_v2` (3–12 char ngrams over lowercased UTF-8) and `lawgraph_norm` (lowercased identity for identifier fields).

---

## 6. ArangoStore API

**File:** `src/lawgraph/db/store.py`

| Method | Description |
|--------|-------------|
| `query(aql, bind_vars, max_runtime=600)` | Execute AQL; returns iterable cursor |
| `insert_raw_source(source, kind, external_id, ...)` | Upsert raw record |
| `insert_or_update(node)` | Upsert: INSERT or UPDATE with props MERGE |
| `update_node(node)` | Update existing node (requires key) |
| `get_node(collection, key)` | Direct collection `.get()` |
| `insert_or_update_edge(from_id, to_id, relation, source, status, confidence, meta)` | Upsert edge by SHA-1 key |
| `flip_edge_status(edge_key, new_status, reason)` | Status transition with audit log |
| `batch_insert_or_update(nodes)` | Batch upsert via AQL UPSERT |
| `batch_insert_or_update_edges(edges)` | Batch edge upsert |

**Connection:** `ArangoClient(hosts=url, request_timeout=620)` — 620 s to cover long-running normalize queries.

**AQL timeout:** `max_runtime=600.0` on all `aql.execute()` calls.

**Schema bootstrap:** `ArangoStore.__init__` calls `ensure_schema(db)` which creates missing collections, indexes, analyzers, and ArangoSearch views.
