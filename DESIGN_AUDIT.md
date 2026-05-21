# LawGraph Database & Data Model Design Audit

**Project**: LawGraph (Dutch/EU legal knowledge graph on ArangoDB)
**Date**: 2026-05-08
**Auditor**: Claude Code Agent

---

## 1. Node Model

### Overview
The `Node` class is a dataclass representing a graph node (document) in ArangoDB, with deterministic key derivation and type-safe serialization.

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/models.py` (lines 62–129)

### Fields

| Field | Type | Nullable | Purpose |
|-------|------|----------|---------|
| `collection` | `str` | No | ArangoDB collection name (e.g., "instruments", "activiteiten") |
| `type` | `NodeType` | No | Semantic type enum (INSTRUMENT, ARTICLE, PROCEDURE, etc.) |
| `key` | `str \| None` | Yes | Deterministic `_key` for the document; None before insertion |
| `labels` | `list[str]` | No | Domain tags (e.g., ["Strafrecht", "TK"]); mutable list |
| `props` | `dict[str, Any]` | No | Domain-specific metadata; must include `display_name` |

### Serialization

**`to_document() → dict[str, Any]`** (line 85)
- Converts Node to ArangoDB document format
- Always includes: `type` (enum value string), `labels`, `props`
- Only includes `_key` if `node.key is not None`
- Returns a clean dict suitable for `collection.insert()`

**`from_document(collection: str, doc: dict) → Node`** (line 96)
- Parses ArangoDB document back into Node
- Type fallback: unknown types default to `NodeType.TOPIC` (line 102)
- Props resolution (lines 105–111):
  - If `props` field exists and is dict: use it
  - Else: construct props from all non-reserved fields (`_key`, `type`, `labels`)
  - This provides **backward compatibility with legacy unstructured documents**

### Key Derivation

**`make_node_key(*parts: str, fallback: str = "node") → str`** (line 147)
- Deterministic key generation from domain values
- Process:
  1. Join non-empty parts with underscores
  2. Unicode normalization (NFKD)
  3. Strip non-ASCII
  4. Lowercase + trim
  5. Replace non-`[a-z0-9_]` chars with underscores
  6. Collapse `_{2,}` to single underscore
  7. Strip leading/trailing underscores
- If result is empty, use `fallback` (default: "node")
- Example: `make_node_key("Strafrecht", "Algemeen Deel")` → `"strafrecht_algemeen_deel"`

### NodeType Enum

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/models.py` (lines 43–59)

| Variant | Value | Purpose |
|---------|-------|---------|
| `INSTRUMENT` | "instrument" | EU/NL law, directive, regulation, act |
| `ARTICLE` | "article" | Individual article of an instrument |
| `PROCEDURE` | "procedure" | TK Zaak — one legislative track |
| `PUBLICATION` | "publication" | TK document, Staatsblad, OJ publication |
| `JUDGMENT` | "judgment" | Case law (Rechtspraak, Hoge Raad, CJEU) |
| `TOPIC` | "topic" | Semantic topic node |
| `DOSSIER` | "dossier" | Kamerstukdossier — groups one or more Zaak |
| `ACTIVITEIT` | "activiteit" | Debate/hearing in which documents are treated |
| `STEMMING` | "stemming" | Vote on a motion or wetsvoorstel |
| `TOEZEGGING` | "toezegging" | Ministerial commitment made during a debate |
| `COMMISSIE` | "commissie" | Parliamentary committee |
| `LID` | "lid" | Parliamentary member / minister |

### Collection Assignment Logic

Collection is explicitly specified at Node construction:
```python
node = Node(
    collection="instruments",
    type=NodeType.INSTRUMENT,
    key="statutory_key",
    props={...}
)
```

There is **no automatic collection assignment** based on NodeType. Callers are responsible for selecting the correct collection.

---

## 2. Collection Catalogue

### Document Collections (DOCUMENT_COLLECTIONS)

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/config/settings.py` (lines 21–44)

| Collection | NodeType(s) | Purpose | Key Scheme | Typical Fields |
|-----------|-----------|---------|-----------|---|
| **instruments** | INSTRUMENT | EU/NL laws, directives, regulations | `make_node_key(bwb_id)` or `make_node_key(celex)` | `bwb_id`, `celex`, `display_name`, `abstract`, `publication_date` |
| **instrument_articles** | ARTICLE | Individual articles within instruments | `make_node_key(bwb_id, article_number)` | `bwb_id`, `celex`, `article_number`, `text`, `display_name` |
| **procedures** | PROCEDURE | TK legislative procedure (Zaak) | `make_node_key(zaak_nummer)` | `zaak_nummer`, `soort` ("Wetgeving" or similar), `titel`, `display_name` |
| **publications** | PUBLICATION | TK documents, Staatsblad, OJ docs | `make_node_key(datum, identifier)` | `soort` (document type), `datum`, `dossier_nummer`, `display_name`, `text` |
| **judgments** | JUDGMENT | Court decisions (Rechtspraak, CJEU) | `make_node_key(ecli)` | `ecli`, `court`, `date`, `paragraphs` (array), `display_name` |
| **topics** | TOPIC | Semantic topic nodes for grouping | `make_node_key(slug)` or custom | `id`, `slug`, `display_name`, `description` |
| **raw_sources** | N/A (non-node) | Staging area for raw API fetches | SHA-1 of `source:kind:external_id` | `source`, `kind`, `external_id`, `fetched_at`, `payload_json`, `payload_text`, `meta` |
| **kamerstukdossiers** | DOSSIER | Parliamentary dossier grouping zaak | `make_node_key(nummer, toevoeging)` | `nummer`, `kamerstuknummer`, `toevoeging`, `titel`, `afgedaan`, `geopend_op`, `gesloten_op`, `huidige_fase` |
| **activiteiten** | ACTIVITEIT | Debate/hearing where documents treated | `make_node_key(external_id)` | `external_id`, `datum`, `soort`, `dossier_id` (ref), `display_name` |
| **stemmingen** | STEMMING | Vote on motion or wetsvoorstel | `make_node_key(external_id)` | `external_id`, `dossier_id`, `aangenomen` (bool), `display_name` |
| **toezeggingen** | TOEZEGGING | Ministerial commitments | `make_node_key(external_id)` | `external_id`, `dossier_id`, `status`, `display_name` |
| **commissies** | COMMISSIE | Parliamentary committee | `make_node_key(external_id)` | `external_id`, `naam`, `afkorting`, `slug`, `display_name` |
| **leden** | LID | Parliamentary member/minister | `make_node_key(external_id)` | `external_id`, `naam`, `partij`, `actief`, `display_name` |
| **edge_status_log** | N/A (audit) | Immutable log of edge-status mutations | UUID (line 356: `str(uuid4())`) | `edge_key`, `edge_from`, `edge_to`, `relation`, `old_status`, `new_status`, `triggering_stemming_id`, `timestamp` |
| **watches** | N/A (user feature) | User watchlist (persisted server-side) | UUID (auto) | `node_id`, `label` (optional), `collection` (optional), `created_at` |

### Edge Collection

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/config/settings.py` (line 47)

| Collection | Type | Purpose |
|-----------|------|---------|
| **edges** | ArangoDB edge collection | Unified edge storage for all relation types (structural + semantic) |

---

## 3. Edge Model

### Overview
Edges represent directed relationships between nodes. All edges use a deterministic SHA-1 key scheme and carry a `status` field for tracking provisional mutations.

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` (lines 29–374)

### Edge Key Derivation

**`_edge_key(from_id: str, relation: str, to_id: str) → str`** (line 29)
```python
return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()
```
- Deterministic SHA-1 hash of `from_id:relation:to_id`
- Format: hex string (40 characters)
- Guarantees: same (from, relation, to) always produces same key → prevents duplicates

### Edge Document Structure

Created by `create_edge()` (lines 277–308):

| Field | Type | Nullable | Purpose | Indexed |
|-------|------|----------|---------|---------|
| `_key` | `str` | No | SHA-1 hash (deterministic) | Yes (type: persistent) |
| `_from` | `str` | No | Source node ID (e.g., "instruments/bwb-123") | Yes |
| `_to` | `str` | No | Target node ID | Yes |
| `relation` | `str` | No | Relation type (e.g., "PART_OF_INSTRUMENT") | Yes |
| `source` | `str` | Yes | Origin identifier (pipeline, manual edit) | No |
| `status` | `str` | No (defaults to "canoniek") | Edge status enum | Yes |
| `confidence` | `float` | Yes | Semantic link confidence (0.0–1.0) | No ⚠️ |
| `created_at` | `str` | No | ISO 8601 timestamp (UTC, Z suffix) | No |
| `meta` | `dict` | No (empty dict) | Extra metadata | No |

### Edge Status Enum

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/config/settings.py` (lines 134–141)

| Value | Meaning | Use Case |
|-------|---------|----------|
| `EDGE_STATUS_CANONIEK` ("canoniek") | **Current law** — the edge reflects the present state | Structural edges from normalize pipelines; semantic edges |
| `EDGE_STATUS_VOORGESTELD` ("voorgesteld") | **Pending mutation** — proposed change from an open dossier | Document → Article (WIJZIGT/INTRODUCEERT/TREKT_IN); until stemming decides |
| `EDGE_STATUS_VERLOPEN` ("verlopen") | **No longer in force** — edge is historical | Repealed laws, closed dossiers |
| `EDGE_STATUS_VERWORPEN` ("verworpen") | **Rejected** — stemming rejected the proposed mutation | After failed vote on wetsvoorstel |

**Default**: `EDGE_STATUS_CANONIEK` (line 285 in `create_edge()`)

### Edge Status Mutations

**`flip_edge_status(edge_key: str, new_status: str, triggering_stemming_id: str) → dict | None`** (lines 326–374)
- Updates edge status atomically
- Writes immutable audit log entry to `edge_status_log` for every mutation
- Log includes: `edge_key`, `edge_from`, `edge_to`, `relation`, `old_status`, `new_status`, `triggering_stemming_id`, `timestamp`
- Returns updated edge doc, or None if edge not found

---

## 4. Index Strategy

### Defined Indexes

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` (lines 88–153)

#### Array Indexes (Labels)

| Collection | Fields | Unique | Purpose |
|-----------|--------|--------|---------|
| instrument_articles | `labels[*]` | No | Filter by individual label values |
| publications | `labels[*]` | No | e.g., FILTER "Strafrecht" IN doc.labels |
| judgments | `labels[*]` | No | Semantic topic filtering |
| procedures | `labels[*]` | No | Domain tagging |
| kamerstukdossiers | `labels[*]` | No | Parliamentary document filtering |

#### Unique Indexes (Natural Keys)

| Collection | Fields | Unique | Purpose |
|-----------|--------|--------|---------|
| instruments | `props.bwb_id` | Yes | BWB reference uniqueness |
| instruments | `props.celex` | Yes | CELEX reference uniqueness |
| instrument_articles | `[props.bwb_id, props.article_number]` | Yes | Composite: BWB + article number |
| instrument_articles | `[props.celex, props.article_number]` | Yes | Composite: CELEX + article number |
| judgments | `props.ecli` | Yes | ECLI reference uniqueness |

#### Filtered Indexes (Document Props)

| Collection | Fields | Unique | Purpose |
|-----------|--------|--------|---------|
| publications | `props.soort` | No | Filter by document type |
| publications | `props.datum` | No | Range queries on publication date |
| publications | `props.dossier_nummer` | No | Link publications to dossiers |
| kamerstukdossiers | `props.nummer` | No | Dossier number lookup |
| kamerstukdossiers | `props.afgedaan` | No | Filter open vs. closed dossiers |
| kamerstukdossiers | `props.gesloten_op` | No | Filter by closure date |
| activiteiten | `props.dossier_id` | No | Link to parent dossier |
| activiteiten | `props.datum` | No | Chronological queries |
| stemmingen | `props.dossier_id` | No | Link to parent dossier |
| stemmingen | `props.aangenomen` | No | Filter passed/rejected votes |
| toezeggingen | `props.dossier_id` | No | Link to parent dossier |
| toezeggingen | `props.status` | No | Filter by commitment status |
| watches | `node_id` | No | User watchlist lookups |

#### Raw Sources Index

| Collection | Fields | Unique | Purpose |
|-----------|--------|--------|---------|
| raw_sources | `[source, kind]` | No | Critical for normalize pipelines scanning by source+kind |

#### Edge Indexes (Critical for Traversal)

| Collection | Fields | Unique | Purpose |
|-----------|--------|--------|---------|
| edges | `relation` | No | All relations of a type |
| edges | `[_from, relation]` | No | Outbound edges of a specific type |
| edges | `[_to, relation]` | No | Inbound edges of a specific type |
| edges | `status` | No | Filter edges by status (canoniek/voorgesteld/etc.) |
| edges | `[status, relation]` | No | Composite: canonical edges of a type |

### Missing Indexes

⚠️ **Gap**: No index on `edges.confidence`
- Confidence is used in AQL queries (e.g., semantic edge filtering)
- Semantic pipelines create edges with confidence scores
- Currently no way to efficiently filter edges by confidence threshold
- **Recommendation**: Add `("edges", ["confidence"], False)`

⚠️ **Gap**: No index on `edge_status_log.timestamp`
- Audit log queries sort by `timestamp DESC` (api/queries.py)
- Currently does full collection scan
- **Recommendation**: Add `("edge_status_log", ["timestamp"], False)`

⚠️ **Gap**: No index on `edge_status_log.edge_key`
- Lookups by edge_key in audit log may be needed
- **Recommendation**: Add `("edge_status_log", ["edge_key"], False)`

⚠️ **Gap**: No composite index on `[source, kind, external_id]` in raw_sources
- `insert_raw_source()` uses SHA-1 key derived from these three fields
- Current index only covers `[source, kind]`
- Full uniqueness check would require composite index or application-level deduplication

---

## 5. Raw Sources Schema

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` (lines 174–207)

### Purpose
Staging area for raw API fetches. Each record maps to a single external entity (law, case, dossier item). Pipelines consume raw_sources and normalize into domain collections.

### Document Structure

| Field | Type | Nullable | Purpose | Example |
|-------|------|----------|---------|---------|
| `_key` | `str` | No | SHA-1(`source:kind:external_id`) | "a1b2c3d4e5f6..." |
| `source` | `str` | No | Data source identifier | "bwb", "rechtspraak", "eurlex", "tk" |
| `kind` | `str` | No | Record type within source | "bwb-regeling-xml", "rs-content", "tk-zaak" |
| `external_id` | `str \| None` | Yes | Unique ID in source system | "wetten-1992-773", "ECLI:NL:RB:2024:123" |
| `fetched_at` | `str` | No | ISO 8601 UTC timestamp (Z suffix) | "2025-05-08T14:32:17Z" |
| `payload_json` | `dict \| list \| None` | Yes | Structured API response | OData JSON, CELEX metadata |
| `payload_text` | `str \| None` | Yes | Raw text (HTML, XML, plain text) | Rechtspraak HTML, BWB XML |
| `meta` | `dict` | No (empty dict) | Auxiliary metadata | `{"url": "...", "status_code": 200}` |

### Key Derivation

**Deterministic**: `SHA-1(f"{source}:{kind}:{external_id}")`
- Guarantees: same (source, kind, external_id) always maps to same record
- Upsert is safe: `insert(doc, overwrite=True)` at line 206 replaces old if key exists
- If `external_id is None`: fallback to random UUID (line 194) — non-idempotent

### Insert Pattern

**`insert_raw_source(source, kind, external_id, payload_json, payload_text, meta) → dict`** (lines 174–207)
```python
# Timestamp generation (lines 185–187)
fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
if fetched_at.endswith("+00:00"):
    fetched_at = fetched_at.replace("+00:00", "Z")

# Key generation (lines 189–194)
if external_id is not None:
    record_key = hashlib.sha1(f"{source}:{kind}:{external_id}".encode()).hexdigest()
else:
    record_key = str(uuid4())

# Upsert (line 206)
result = self.raw_sources.insert(doc, overwrite=True, overwrite_mode="replace")
```

---

## 6. Settings & Constants

### Source Constants

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/config/settings.py` (lines 78–114)

| Constant | Value | Purpose | Defined | Used |
|----------|-------|---------|---------|------|
| `SOURCE_TK` | "tk" | Dutch Parliament API | Yes | Yes ✓ |
| `SOURCE_RECHTSPRAAK` | "rechtspraak" | Dutch case law portal | Yes | Yes ✓ |
| `SOURCE_EURLEX` | "eurlex" | EU legislation portal | Yes | Yes ✓ |
| `SOURCE_EURLEx` | `SOURCE_EURLEX` | Backwards-compat alias (mixed-case) | Yes | Rarely used |
| `SOURCE_BWB` | "bwb" | Dutch law database | Yes | Yes ✓ |

### Raw Kind Constants

| Constant | Value | Purpose | Source | Defined | Used |
|----------|-------|---------|--------|---------|------|
| `RAW_KIND_TK_ZAAK` | "tk-zaak" | TK legislative procedure | tk | Yes | Yes ✓ |
| `RAW_KIND_TK_DOCUMENTVERSIE` | "tk-documentversie" | TK document version | tk | Yes | ❓ (not clearly used) |
| `RAW_KIND_TK_DOSSIER` | "tk-dossier" | TK dossier grouping | tk | Yes | Yes ✓ |
| `RAW_KIND_TK_ACTIVITEIT` | "tk-activiteit" | TK debate/hearing | tk | Yes | Yes ✓ |
| `RAW_KIND_TK_STEMMING` | "tk-stemming" | TK vote | tk | Yes | Yes ✓ |
| `RAW_KIND_TK_TOEZEGGING` | "tk-toezegging" | TK commitment | tk | Yes | Yes ✓ |
| `RAW_KIND_TK_COMMISSIE` | "tk-commissie" | TK committee | tk | Yes | Yes ✓ |
| `RAW_KIND_TK_PERSOON` | "tk-persoon" | TK person/member | tk | Yes | Yes ✓ |
| `RAW_KIND_TK_DOCUMENT` | "tk-document" | TK document (generic) | tk | Yes | Yes ✓ |
| `RAW_KIND_RS_INDEX` | "rs-index" | Rechtspraak index | rechtspraak | Yes | ✓ |
| `RAW_KIND_RS_CONTENT` | "rs-content" | Rechtspraak full content | rechtspraak | Yes | ✓ |
| `RAW_KIND_EU_CELEX` | "eu-celex-html" | EUR-Lex CELEX document | eurlex | Yes | ✓ |
| `RAW_KIND_BWB_REGELING` | "bwb-regeling-xml" | BWB law (XML) | bwb | Yes | ✓ |
| `RAW_KIND_BWB_TOESTAND` | "bwb-toestand-xml" | BWB snapshot (XML) | bwb | Yes | ✓ |

**Validation**: `RAW_SOURCE_KINDS` dict (lines 99–114) enumerates allowed kind per source.

### Collection Name Constants

All defined and used (lines 118–132). Example: `COLLECTION_KAMERSTUKDOSSIERS = "kamerstukdossiers"`

### Edge Status Constants

All defined and used (lines 134–141).

### Relation Type Constants

**Structural relations** (fully deterministic, written by normalize pipelines):

| Constant | Value | Purpose | Defined | Used |
|----------|-------|---------|---------|------|
| `RELATION_PART_OF_INSTRUMENT` | "PART_OF_INSTRUMENT" | article → instrument | Yes | ✓ |
| `RELATION_PART_OF_PROCEDURE` | "PART_OF_PROCEDURE" | publication → procedure (zaak) | Yes | ✓ |
| `RELATION_DEEL_VAN_DOSSIER` | "DEEL_VAN_DOSSIER" | zaak/pub/activiteit → kamerstukdossier | Yes | ✓ |
| `RELATION_DISCUSSES` | "DISCUSSES" | procedure → instrument | Yes | ✓ |

**Parliamentary structural** (written by dossier normalize pipeline):

| Constant | Value | Purpose | Defined | Used |
|----------|-------|---------|---------|------|
| `RELATION_RAAKT` | "RAAKT" | kamerstukdossier → instrument | Yes | ✓ |
| `RELATION_WIJZIGT` | "WIJZIGT" | document → article (proposes change) | Yes | ✓ |
| `RELATION_INTRODUCEERT` | "INTRODUCEERT" | document → article (new) | Yes | ✓ |
| `RELATION_TREKT_IN` | "TREKT_IN" | document → article (repeal) | Yes | ✓ |
| `RELATION_AMENDEERT` | "AMENDEERT" | amendement → document | Yes | ✓ |
| `RELATION_LICHT_TOE` | "LICHT_TOE" | mvt → article (explains intent) | Yes | ✓ |
| `RELATION_BESLUIT` | "BESLUIT" | stemming → document | Yes | ✓ |
| `RELATION_BETREFT` | "BETREFT" | toezegging → article (optional) | Yes | ✓ |
| `RELATION_BEHANDELD_DOOR` | "BEHANDELD_DOOR" | activiteit → commissie | Yes | ✓ |
| `RELATION_AUTEUR_VAN` | "AUTEUR_VAN" | lid → document | Yes | ✓ |
| `RELATION_GEDAAN_IN` | "GEDAAN_IN" | toezegging → activiteit | Yes | ✓ |
| `RELATION_GESTEMD_IN` | "GESTEMD_IN" | stemming → activiteit | Yes | ✓ |

**Hardcoded relations (not defined as constants)**:

⚠️ **Gap**: `"LID_VAN"` is used in code (tk_dossiers.py, queries.py) but **not defined as a constant**
- Should be: `RELATION_LID_VAN = "LID_VAN"` in settings.py

⚠️ **Gap**: `"RELATED_TOPIC"` is hardcoded in normalize/base.py and strafrecht_seed.py
- Defined as constant at line 192 of settings.py

**Semantic relations** (confidence-weighted, written by semantic pipelines):

| Constant | Value | Purpose | Defined | Used |
|----------|-------|---------|---------|------|
| `RELATION_REFERS_TO_ARTICLE` | "REFERS_TO_ARTICLE" | document mentions article (generic) | Yes (env-configurable) | ✓ |
| `RELATION_EXPLAINS_ARTICLE` | "EXPLAINS_ARTICLE" | document explains article | Yes (env-configurable) | ✓ |
| `RELATION_CITES_ARTICLE` | "CITES_ARTICLE" | judgment cites article | Yes (env-configurable) | ✓ |
| `RELATION_MENTIONS_ARTICLE` | "MENTIONS_ARTICLE" | document mentions article | Yes (env-configurable) | ✓ |
| `RELATION_CITES_JUDGMENT` | "CITES_JUDGMENT" | judgment cites another | Yes (env-configurable) | ✓ |
| `RELATION_MENTIONS_INSTRUMENT` | "MENTIONS_INSTRUMENT" | document mentions law | Yes (env-configurable) | ✓ |
| `RELATION_AMENDS_INSTRUMENT` | "AMENDS_INSTRUMENT" | law amends another law | Yes (env-configurable) | ✓ |
| `RELATION_IMPLEMENTS_DIRECTIVE` | "IMPLEMENTS_DIRECTIVE" | law implements EU directive | Yes (env-configurable) | ✓ |

All semantic relations are **environment-configurable** (can be overridden via `LAWGRAPH_RELATION_*` env vars).

---

## 7. ArangoStore API

**File**: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` (lines 34–375)

### Initialization

**`__init__()`** (lines 37–73)
- Connects to ArangoDB using credentials from settings
- Raises `ConnectionError` if connection fails
- Calls `_ensure_collections()` to create missing collections
- Caches collection references as instance variables

### Query Execution

**`query(aql: str, bind_vars: dict | None = None, *, max_runtime: float = 600.0) → Iterable[dict]`** (lines 156–170)
- Executes AQL query with optional bind variables
- Default max_runtime: 600 seconds
- Returns iterable cursor (lazy evaluation)
- Handles both old and new python-arango versions (checks for `.result()` method)

### Raw Sources API

**`insert_raw_source(*, source, kind, external_id, payload_json, payload_text, meta) → dict`** (lines 174–207)
- Upserts raw source record using deterministic SHA-1 key
- If `external_id is None`: uses random UUID (non-idempotent)
- Always sets `fetched_at` to current UTC time
- Returns inserted document metadata

### Nodes API

**`insert_node(node: Node) → Node`** (lines 211–217)
- Inserts node document
- If node has no key, ArangoDB auto-generates one
- Returns node with resolved key
- ⚠️ **Idempotency**: Not idempotent — multiple calls create duplicates

**`insert_or_update(node: Node) → Node`** (lines 219–255)
- Upserts node using UPSERT AQL statement
- **Requires**: node.key must be non-None
- **On INSERT**: stores full document as-is
- **On UPDATE**:
  - Merges props: `MERGE(OLD.props, @props)` — old fields survive, new fields overwrite
  - Unions labels: `UNIQUE(APPEND(OLD.labels, @labels))` — duplicates removed, order preserved
  - Type updated to new value
- Returns updated node with all fields from database
- **Idempotency**: Fully idempotent (same key + props = same result)

**`update_node(node: Node) → Node`** (lines 257–263)
- Updates existing node (must have key)
- ⚠️ **Warning**: Overwrites entire document structure
- Not idempotent if props are modified

**`get_node(collection: str, key: str) → Node | None`** (lines 265–273)
- Fetches single node by collection and key
- Returns None if not found or collection missing

### Edges API

**`create_edge(*, from_id, to_id, relation, source="", confidence=None, status=EDGE_STATUS_CANONIEK, meta=None) → dict`** (lines 277–308)
- Creates edge with deterministic SHA-1 key
- Default status: "canoniek"
- If edge already exists (same from/to/relation): overwrites via upsert
- Confidence is optional
- Calls `insert_or_update_edge()` internally
- Returns stored edge document

**`insert_or_update_edge(doc: dict) → tuple[dict, bool]`** (lines 310–324)
- Low-level edge upsert
- Edge document **must** have `_key` field
- Returns: (stored_doc, was_created: bool)
- `overwrite=True, return_new=True, return_old=True` — full audit info

**`flip_edge_status(*, edge_key, new_status, triggering_stemming_id, source="stemming-propagation") → dict | None`** (lines 326–374)
- Atomically updates edge status
- Writes immutable audit log entry to `edge_status_log`
- Log includes edge metadata for traceability
- Returns updated edge, or None if not found
- **Use case**: Parliamentary dossier stemming triggers edge flips

### Collection Management

**`_ensure_collections()`** (lines 75–86)
- Creates missing document collections
- Creates edge collection if missing
- Calls `_ensure_indexes()`
- Idempotent — safe to call multiple times

**`_ensure_indexes()`** (lines 88–152)
- Creates all persistent indexes defined in `index_specs` list
- Compares existing vs. desired uniqueness and deletes mismatches
- Logs warnings if index creation fails
- Idempotent — safe to call on every init

---

## 8. Gaps & Issues

### Critical Issues

#### 1. **Hardcoded Relation: LID_VAN**
- **Files**: tk_dossiers.py (line 161 comment, line 363 usage), queries.py (line 363)
- **Issue**: Used in code but not defined as a constant in settings.py
- **Impact**: String typos won't be caught; future refactoring hard
- **Fix**: Add `RELATION_LID_VAN = "LID_VAN"` to settings.py and use everywhere

#### 2. **Missing Index on edges.confidence**
- **File**: db.py (lines 88–124)
- **Issue**: No index on confidence field used for semantic filtering
- **Impact**: Queries filtering by confidence threshold cause full collection scan
- **Fix**: Add `("edges", ["confidence"], False)` to index_specs

#### 3. **insert_node() Not Idempotent**
- **File**: db.py (lines 211–217)
- **Issue**: Multiple calls with same node key create duplicates or errors
- **Usage**: Only in strafrecht_seed.py (legacy)
- **Impact**: Data duplication if called twice; inconsistent with insert_or_update
- **Fix**: Deprecate in favor of insert_or_update; document in comments

#### 4. **Props Merge Semantics in insert_or_update()**
- **File**: db.py (line 240)
- **Issue**: `MERGE(OLD.props, @props)` — new props overwrite old, but unspecified fields are lost
- **Example**:
  - Old doc: `props: {external_id: "123", name: "Foo", status: "active"}`
  - New node: `props: {external_id: "123", name: "Bar"}` (no status)
  - Result: `props: {external_id: "123", name: "Bar", status: "active"}` — **status survives**
  - But if old had 10 fields and new has 5, the 5 old fields not in new survive
  - **Expectation mismatch**: Caller may expect "replace" semantics
- **Fix**: Document explicitly that old props are preserved unless overwritten; consider adding replace mode

#### 5. **Raw Source Key Non-Idempotency**
- **File**: db.py (lines 189–194)
- **Issue**: If `external_id is None`, a random UUID is used instead of deterministic key
- **Impact**: Same raw entity fetched twice without external_id creates two records
- **Fix**: Require external_id, or use (source, kind, timestamp) tuple as backup

#### 6. **Update Node Overwrites Full Document**
- **File**: db.py (line 262)
- **Code**: `collection.update(node.to_document())`
- **Issue**: Overwrites entire document; old fields in ArangoDB not in node are lost
- **Example**: If document has extra fields added by another pipeline, update_node() deletes them
- **Impact**: Data loss if two pipelines touch the same node
- **Fix**: Use AQL MERGE in update_node() like insert_or_update() does

#### 7. **No Validation of Edge from_id / to_id Format**
- **File**: db.py (lines 277–308)
- **Issue**: create_edge() doesn't validate that from_id and to_id are valid node references
- **Impact**: Can create edges to non-existent nodes; no referential integrity
- **Fix**: Add optional validation check in create_edge()

### Data Model Gaps

#### 8. **missing Dossier Phase Completion Logic**
- **File**: tk_dossiers.py (lines 265–270)
- **Issue**: `huidige_fase` is initially set to "afgehandeld" or None, later enriched in `_enrich_dossier_fasen()`
- **Problem**: If enrichment fails, phase stays NULL; no fallback
- **Impact**: Incomplete dossier phase data; unclear query semantics
- **Fix**: Always populate huidige_fase with a computed value; document the enum

#### 9. **No Schema Validation for Props**
- **File**: models.py
- **Issue**: Node.props is `dict[str, Any]` — no schema enforcement
- **Impact**: Callers can set invalid/unexpected fields; no early error detection
- **Example**: `props = {"dispaliy_name": "..."}` (typo) silently succeeds
- **Fix**: Add Pydantic schemas per NodeType (optional but recommended for large projects)

#### 10. **Edge Confidence Not Indexed or Validated**
- **File**: db.py (line 305)
- **Issue**: Confidence accepted as any float; no bounds check or range validation
- **Impact**: Confidence scores not guaranteed to be [0.0, 1.0]
- **Fix**: Validate `0.0 <= confidence <= 1.0` in create_edge()

#### 11. **edge_status_log No Unique Constraint**
- **File**: db.py (line 366)
- **Issue**: Log entries use random UUIDs as keys; theoretically non-unique (hash collision)
- **Impact**: Extremely low probability, but audit trail could lose entries
- **Fix**: Use deterministic key: `sha1(edge_key + timestamp + new_status)` or accept UUID risk

### Schema Inconsistencies

#### 12. **Timestamp Format Inconsistency**
- **File**: db.py (lines 185–187, 350–352)
- **Issue**: Manual ISO 8601 formatting with Z suffix
- **Pattern**: `"2025-05-08T14:32:17Z"` (hardcoded Z replacement)
- **Impact**: If timezone-aware datetime differs, format may be wrong
- **Fix**: Use `datetime.fromisoformat()` and document expected format

#### 13. **Labels Array Mutability**
- **File**: models.py (line 76)
- **Issue**: labels is default_factory=list; each Node gets own list
- **Impact**: If default list used as mutable shared state, could cause bugs
- **Best practice**: Use tuple or frozen list for immutable labels
- **Current code**: Safe (list is copied on Node construction), but confusing

### Usage Patterns

#### 14. **insert_node() Used in Legacy Code Only**
- **File**: strafrecht_seed.py (several uses)
- **Issue**: insert_node() is non-idempotent but strafrecht_seed assumes idempotency
- **Impact**: Data duplication if pipeline re-run
- **Fix**: Migrate strafrecht_seed to use insert_or_update()

#### 15. **Watches Collection No Referential Integrity**
- **File**: queries.py, api/routes/watches.py
- **Issue**: Watches store `node_id` as string; no check that node exists
- **Impact**: Can create watch for non-existent node; dangling references
- **Fix**: Add foreign key validation in create_watch() (optional; acceptable for user feature)

#### 16. **Edge Status Log Queries Lack Index**
- **File**: api/queries.py (sort by timestamp)
- **Issue**: `SORT entry.timestamp DESC LIMIT 200` without index
- **Impact**: O(n) scan on entire audit trail
- **Fix**: Add index on edge_status_log.timestamp

### Constants & Configuration

#### 17. **RAW_KIND_TK_DOCUMENTVERSIE Unused**
- **File**: settings.py (line 85)
- **Issue**: Defined but not found in any pipeline
- **Impact**: Dead constant; unclear purpose
- **Investigation**: May be for future use or legacy
- **Fix**: Document purpose in comment, or remove if truly unused

#### 18. **SOURCE_EURLEx Backwards-Compat Alias**
- **File**: settings.py (line 81)
- **Issue**: Alias for SOURCE_EURLEX with different capitalization
- **Impact**: Confusing; may cause bugs if mixed
- **Fix**: Deprecate in favor of SOURCE_EURLEX; add migration script if used in raw_sources

---

## 9. Improvement Recommendations

### Priority 1: Correctness & Safety (Do First)

1. **Define RELATION_LID_VAN constant** (Issue #1)
   - Add to settings.py
   - Update all usages
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/config/settings.py`
   - Effort: 5 minutes

2. **Add missing index on edges.confidence** (Issue #2)
   - Append to index_specs in _ensure_indexes()
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 124
   - Effort: 2 minutes

3. **Add index on edge_status_log.timestamp** (Issue #16)
   - Append to index_specs
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 124
   - Effort: 2 minutes

4. **Fix update_node() to preserve old props** (Issue #6)
   - Replace collection.update() with AQL MERGE
   - Match logic in insert_or_update()
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` lines 257–263
   - Effort: 15 minutes

5. **Validate edge from_id / to_id format** (Issue #7)
   - Add check in create_edge(): `assert "/" in from_id and "/" in to_id`
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 293
   - Effort: 5 minutes

### Priority 2: Data Quality (Next Sprint)

6. **Migrate strafrecht_seed to insert_or_update()** (Issue #14)
   - Replace insert_node() calls
   - Add deterministic key derivation
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/pipelines/strafrecht_seed.py`
   - Effort: 1 hour

7. **Validate confidence in [0.0, 1.0]** (Issue #10)
   - Add check in create_edge()
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 305
   - Effort: 5 minutes

8. **Require external_id in insert_raw_source()** (Issue #5)
   - Make external_id non-optional parameter
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 179
   - Effort: 30 minutes (includes updating all call sites)

### Priority 3: Documentation & Maintainability (Polish)

9. **Document props merge semantics in insert_or_update()** (Issue #4)
   - Add docstring explaining MERGE behavior
   - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 219
   - Effort: 10 minutes

10. **Add deprecation warning to insert_node()** (Issue #3)
    - Mark as deprecated in docstring
    - Suggest insert_or_update() alternative
    - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 211
    - Effort: 5 minutes

11. **Document timestamp format** (Issue #12)
    - Add comment explaining ISO 8601 + Z convention
    - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 185
    - Effort: 5 minutes

12. **Clarify dossier huidige_fase enum** (Issue #8)
    - Document possible values: None, "afgehandeld", "wetsvoorstel", etc.
    - File: `/Users/thijs/Development/lawgraph/src/lawgraph/pipelines/normalize/tk_dossiers.py` line 265
    - Effort: 10 minutes

13. **Investigate RAW_KIND_TK_DOCUMENTVERSIE usage** (Issue #17)
    - Search codebase for references
    - Add comment documenting purpose or remove if unused
    - File: `/Users/thijs/Development/lawgraph/src/lawgraph/config/settings.py` line 85
    - Effort: 15 minutes

### Priority 4: Nice-to-Have (Future)

14. **Add Pydantic validation schemas per NodeType**
    - Enforce required props per type (e.g., INSTRUMENT must have display_name)
    - File: New `/src/lawgraph/schemas.py` or extend models.py
    - Effort: 2–4 hours

15. **Implement referential integrity check for watches**
    - Validate node_id exists before creating watch
    - File: `/Users/thijs/Development/lawgraph/src/lawgraph/api/queries.py` (create_watch)
    - Effort: 20 minutes

16. **Use deterministic UUID for edge_status_log**
    - Replace random UUIDs with SHA-1(edge_key + timestamp)
    - File: `/Users/thijs/Development/lawgraph/src/lawgraph/db.py` line 355
    - Effort: 15 minutes

---

## Summary

The LawGraph data model is well-structured with:
- **Strengths**: Deterministic key derivation, edge status tracking, immutable audit logs, comprehensive indexing
- **Weaknesses**: Missing constant definitions, some indices missing, non-idempotent operations, props merge confusion

**Immediate actions**: Define LID_VAN constant, add confidence/timestamp indexes, fix update_node() to preserve props. These are low-effort, high-impact fixes.

**Long-term**: Migrate to Pydantic schemas for props validation and deprecate non-idempotent insert_node().
