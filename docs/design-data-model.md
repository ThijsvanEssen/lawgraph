# LawGraph Data Model & Database Layer — Design Document

## 1. Node Model

**File:** `src/lawgraph/models.py`

```python
@dataclass
class Node:
    collection: str          # Target ArangoDB collection
    type: str                # NodeType constant (e.g., "instrument", "article")
    display_name: str        # Human-readable label
    labels: list[str]        # Domain tags (e.g., ["BWB"], ["TK", "Kamerstuk"])
    props: dict              # All entity-specific fields
    key: str | None = None   # Deterministic key (must be set before insert_or_update)
```

### Key derivation

`make_node_key(*parts: str) -> str` — joins parts with `_`, lowercases, replaces non-alphanumeric with `_`, deduplicates underscores.

Examples:
- `make_node_key("BWBR0001840")` → `"bwbr0001840"`
- `make_node_key("BWBR0001840", "1")` → `"bwbr0001840_1"`
- `make_node_key("stemming", "dee2ad8f-738b-429f-8dc1-f644cfc2953f")` → `"stemming_dee2ad8f_738b_429f_8dc1_f644cfc2953f"`

### NodeType constants

| Constant | Value | Used for |
|----------|-------|---------|
| `INSTRUMENT` | `"instrument"` | Laws (BWB, EU) |
| `ARTICLE` | `"article"` | Articles within instruments |
| `JUDGMENT` | `"judgment"` | Court judgments |
| `PROCEDURE` | `"procedure"` | TK Zaak / legislative cases |
| `PUBLICATION` | `"publication"` | TK Kamerstuk documents, DocumentVersie |
| `DOSSIER` | `"dossier"` | Kamerstukdossier |
| `ACTIVITEIT` | `"activiteit"` | Debates / hearings |
| `STEMMING` | `"stemming"` | Aggregated votes per motion |
| `TOEZEGGING` | `"toezegging"` | Ministerial commitments |
| `COMMISSIE` | `"commissie"` | Parliamentary committees |
| `LID` | `"lid"` | Members of parliament |
| `TOPIC` | `"topic"` | Domain topic nodes (strafrecht) |

### Serialization

- `to_document()` → dict for ArangoDB insert (adds `_key`, `type`, `labels`, `props`)
- `from_document(collection, doc)` → reconstructs Node from stored doc
- `with_key(key)` → returns new Node instance with key set

---

## 2. Collection Catalogue

**Document collections** (defined in `settings.py: DOCUMENT_COLLECTIONS`):

| Collection | NodeType | Key scheme | Purpose |
|-----------|----------|-----------|---------|
| `instruments` | INSTRUMENT | `make_node_key(bwb_id)` or `make_node_key(celex)` | Dutch & EU laws |
| `instrument_articles` | ARTICLE | `make_node_key(bwb_id, article_number)` | Articles within laws |
| `procedures` | PROCEDURE | `make_node_key(external_id)` | TK Zaak (legislative cases) |
| `publications` | PUBLICATION | `make_node_key(external_id)` | TK Kamerstukken + DocumentVersie |
| `judgments` | JUDGMENT | `make_node_key(ecli)` | Court judgments |
| `topics` | TOPIC | `make_node_key(name)` | Domain topic nodes |
| `kamerstukdossiers` | DOSSIER | `make_node_key(nummer)` or `make_node_key(nummer, toevoeging)` | Parliamentary dossiers |
| `activiteiten` | ACTIVITEIT | `make_node_key(external_id)` | Debates and hearings |
| `stemmingen` | STEMMING | `make_node_key("stemming", besluit_id)` | Aggregated votes |
| `toezeggingen` | TOEZEGGING | `make_node_key(external_id)` | Ministerial commitments |
| `commissies` | COMMISSIE | `make_node_key(external_id)` | Parliamentary committees |
| `leden` | LID | `make_node_key(external_id)` | MPs |
| `watches` | — | `uuid4()` (random) | User-defined node watches |
| `raw_sources` | — | `SHA-1(source:kind:external_id)` | Raw API responses (staging) |

**Edge collection:** `lawgraph_edges` (defined in `settings.py: COLLECTION_EDGES`)

---

## 3. Edge Model

**Stored in:** `lawgraph_edges` collection

```json
{
  "_key": "<SHA-1 of from_id:relation:to_id>",
  "_from": "collection/key",
  "_to": "collection/key",
  "relation": "DEEL_VAN_DOSSIER",
  "source": "tk-dossiers",
  "status": "canoniek",
  "confidence": 0.95,
  "meta": { "raw_match": "...", "snippet": "..." }
}
```

### Edge status enum

| Value | Meaning |
|-------|---------|
| `canoniek` | Current law / confirmed relation |
| `voorgesteld` | Proposed (in legislative procedure) |
| `verlopen` | Expired / no longer in force |
| `verworpen` | Rejected |

`flip_edge_status()` transitions status with an audit log entry in `edge_status_log`.

### Relation types

**Structural (strict):**

| Relation | From | To |
|----------|------|----|
| `PART_OF_INSTRUMENT` | article | instrument |
| `PART_OF_PROCEDURE` | publication | procedure |
| `DEEL_VAN_DOSSIER` | activiteit / stemming / publication | kamerstukdossier |
| `BEHANDELD_DOOR` | activiteit | commissie |
| `GEDAAN_IN` | toezegging | activiteit |
| `LID_VAN` | lid | commissie |

**Parliamentary (strict):**

| Relation | From | To |
|----------|------|----|
| `CONTAINS_SECTION` | instrument | instrument_article (section hierarchy) |

**Semantic (detected):**

| Relation | From | To |
|----------|------|----|
| `REFERS_TO_ARTICLE` | article | article |
| `CITES_ARTICLE` | judgment | article |
| `MENTIONS_ARTICLE` | publication / procedure | article |
| `EXPLAINS_ARTICLE` | publication (MvT) | article |
| `MENTIONS_INSTRUMENT` | publication / procedure | instrument |
| `AMENDS_INSTRUMENT` | publication | instrument |
| `DISCUSSES` | procedure | instrument |
| `IMPLEMENTS_DIRECTIVE` | instrument | instrument |
| `CITES_JUDGMENT` | judgment | judgment |
| `RELATED_TOPIC` | any | topic |

---

## 4. Index Strategy

Defined in `ArangoStore._ensure_indexes()` (`db.py:88-150`).

| Collection | Fields | Unique | Purpose |
|-----------|--------|--------|---------|
| `instrument_articles` | `labels[*]` | no | Domain label filtering |
| `publications` | `labels[*]` | no | Domain label filtering |
| `judgments` | `labels[*]` | no | Domain label filtering |
| `procedures` | `labels[*]` | no | Domain label filtering |
| `kamerstukdossiers` | `labels[*]` | no | Domain label filtering |
| `instruments` | `props.bwb_id` | yes | BWB ID lookup |
| `instruments` | `props.celex` | yes | CELEX lookup |
| `instrument_articles` | `props.bwb_id, props.article_number` | yes | Article lookup |
| `instrument_articles` | `props.celex, props.article_number` | yes | EU article lookup |
| `judgments` | `props.ecli` | yes | ECLI lookup |
| `publications` | `props.soort` | no | Type filtering |
| `publications` | `props.datum` | no | Date sorting |
| `publications` | `props.dossier_nummer` | no | Dossier linking |
| `kamerstukdossiers` | `props.nummer` | no | Dossier number lookup |
| `kamerstukdossiers` | `props.afgedaan` | no | Open/closed filtering |
| `kamerstukdossiers` | `props.gesloten_op` | no | Date filtering |
| `activiteiten` | `props.dossier_id` | no | Dossier activity listing |
| `activiteiten` | `props.datum` | no | Date sorting |
| `stemmingen` | `props.dossier_id` | no | Dossier vote listing |
| `stemmingen` | `props.aangenomen` | no | Vote outcome filtering |
| `toezeggingen` | `props.dossier_id` | no | Dossier commitment listing |
| `toezeggingen` | `props.status` | no | Open/closed filtering |
| `watches` | `node_id` | no | Watch lookup |
| `raw_sources` | `source, kind` | no | Normalize pipeline queries |
| `lawgraph_edges` | `relation` | no | Edge type filtering |
| `lawgraph_edges` | `_from, relation` | no | Outbound traversal |
| `lawgraph_edges` | `_to, relation` | no | Inbound traversal |
| `lawgraph_edges` | `status` | no | Status filtering |
| `lawgraph_edges` | `status, relation` | no | Combined status+type filtering |

### Missing indexes (identified gaps)

| Collection | Field | Impact |
|-----------|-------|--------|
| `lawgraph_edges` | `confidence` | Semantic filtering by confidence threshold is a full scan |
| `edge_status_log` | `timestamp` | Audit log time-range queries are full scans |
| `edge_status_log` | `edge_key` | Audit lookups by edge are full scans |

---

## 5. Raw Sources Schema

**Collection:** `raw_sources`

```json
{
  "_key": "<SHA-1 of source:kind:external_id>",
  "source": "tk",
  "kind": "tk-dossier",
  "external_id": "<TK GUID>",
  "fetched_at": "2026-05-09T10:00:00Z",
  "payload_json": { ... },
  "payload_text": null,
  "meta": { "since": "2026-01-01T00:00:00Z" }
}
```

**Idempotency:** Same `(source, kind, external_id)` triple always produces the same `_key`; subsequent inserts use `overwrite_mode="replace"`, updating `fetched_at`.

**Exception:** When `external_id` is `None` (e.g., Rechtspraak index snapshot), a random UUID4 key is used — **not idempotent**. Each run creates a new raw record.

---

## 6. Settings & Constants

**File:** `src/lawgraph/config/settings.py`

### Source constants

| Constant | Value |
|----------|-------|
| `SOURCE_TK` | `"tk"` |
| `SOURCE_BWB` | `"bwb"` |
| `SOURCE_RECHTSPRAAK` | `"rechtspraak"` |
| `SOURCE_EURLEX` | `"eurlex"` |

### Raw kind constants

| Constant | Value | Source |
|----------|-------|--------|
| `RAW_KIND_TK_ZAAK` | `"tk-zaak"` | TK |
| `RAW_KIND_TK_DOCUMENTVERSIE` | `"tk-documentversie"` | TK |
| `RAW_KIND_TK_DOSSIER` | `"tk-dossier"` | TK |
| `RAW_KIND_TK_ACTIVITEIT` | `"tk-activiteit"` | TK |
| `RAW_KIND_TK_STEMMING` | `"tk-stemming"` | TK |
| `RAW_KIND_TK_TOEZEGGING` | `"tk-toezegging"` | TK |
| `RAW_KIND_TK_COMMISSIE` | `"tk-commissie"` | TK |
| `RAW_KIND_TK_PERSOON` | `"tk-persoon"` | TK |
| `RAW_KIND_TK_DOCUMENT` | `"tk-document"` | TK |
| `RAW_KIND_BWB_TOESTAND` | `"bwb-toestand-xml"` | BWB |
| `RAW_KIND_RS_INDEX` | `"rs-index"` | Rechtspraak |
| `RAW_KIND_RS_CONTENT` | `"rs-content"` | Rechtspraak |
| `RAW_KIND_EU_CELEX` | `"eu-celex-html"` | EUR-Lex |

### Base URLs

| Constant | Default |
|----------|---------|
| `TK_BASE_URL` | `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/` |
| `BWB_BASE_URL` | `https://wetten.overheid.nl/` |
| `RECHTSPRAAK_BASE_URL` | `https://data.rechtspraak.nl/` |
| `EU_BASE_URL` | `https://eur-lex.europa.eu/` |

---

## 7. ArangoStore API

**File:** `src/lawgraph/db.py`

| Method | Signature | Description |
|--------|-----------|-------------|
| `query(aql, bind_vars, max_runtime=600)` | `-> Iterable[dict]` | Execute AQL, returns cursor |
| `insert_raw_source(source, kind, external_id, payload_json, payload_text, meta)` | `-> dict` | Upsert raw record |
| `insert_node(node)` | `-> Node` | Insert node (not idempotent — will create duplicates) |
| `insert_or_update(node)` | `-> Node` | Upsert: INSERT or UPDATE with props MERGE |
| `update_node(node)` | `-> Node` | Update existing node (requires key) |
| `get_node(collection, key)` | `-> dict \| None` | Direct collection `.get()` |
| `create_edge(from_id, to_id, relation, source, status, confidence, meta)` | `-> dict` | Insert edge (not idempotent) |
| `insert_or_update_edge(...)` | `-> dict` | Upsert edge by SHA-1 key |
| `flip_edge_status(edge_key, new_status, reason)` | `-> None` | Status transition with audit log |

**Connection:** `ArangoClient(hosts=url, request_timeout=620)` — 620s HTTP timeout to accommodate large normalize queries (default was 60s, causing timeouts on 100K+ record scans).

**AQL timeout:** `max_runtime=600.0` passed to all `aql.execute()` calls.

---

## 8. Gaps & Issues

| # | Severity | Description |
|---|----------|-------------|
| 1 | **HIGH** | `RELATION_LID_VAN` used in normalize code but not defined as a constant in settings.py — hardcoded string |
| 2 | HIGH | `insert_node()` is not idempotent — calling it twice creates duplicate documents |
| 3 | HIGH | `update_node()` overwrites entire document — old props not preserved (use `insert_or_update` instead) |
| 4 | MEDIUM | Missing index on `edges.confidence` — confidence-based filtering requires full scan |
| 5 | MEDIUM | Missing indexes on `edge_status_log.timestamp` and `edge_status_log.edge_key` |
| 6 | MEDIUM | `raw_sources` with `external_id=None` (Rechtspraak index) is non-idempotent — grows unbounded |
| 7 | MEDIUM | `watches` collection has no referential integrity — orphaned watches possible |
| 8 | LOW | `load_dotenv()` called on every `ArangoStore()` and every `BaseClient()` instantiation |
| 9 | LOW | `props` dict has no schema validation — typos in field names silently create wrong data |
| 10 | LOW | `confidence` values are never bounds-checked to `[0.0, 1.0]` |
| 11 | LOW | `RAW_KIND_TK_DOCUMENTVERSIE` — used in TkNormalizePipeline but not in new dossier pipeline; may cause confusion |

---

## 9. Improvement Recommendations

### P1 — Critical
1. Define `RELATION_LID_VAN` constant in `settings.py`
2. Add index on `lawgraph_edges.confidence` (`db.py:_ensure_indexes`)
3. Add indexes on `edge_status_log.timestamp` and `edge_status_log.edge_key`
4. Deprecate `insert_node()` in favor of `insert_or_update()` everywhere
5. Validate edge `_from`/`_to` format on creation (must contain `/`)

### P2 — Data quality
6. Require non-null `external_id` in `insert_raw_source()` (or document the non-idempotent path)
7. Add bounds check for `confidence` in `insert_or_update_edge()`
8. Add watch referential integrity check on creation

### P3 — Documentation
9. Add docstrings to all `ArangoStore` methods
10. Document `props` field contracts per NodeType (what fields are guaranteed)
11. Add `RELATION_LID_VAN` to settings.py and audit other hardcoded relation strings
