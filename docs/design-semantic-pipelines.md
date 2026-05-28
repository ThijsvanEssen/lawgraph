# Semantic and Citation Detection Pipelines

## 1. Architecture

All semantic pipelines inherit from `SemanticPipelineBase` (`pipelines/semantic/base.py`):

- **Code alias resolution**: e.g. `"Sr"` → `"BWBR0001854"` (Wetboek van Strafrecht)
- **Instrument alias resolution**: e.g. `"Wetboek van Strafrecht"` → `(bwb_id, None)`
- **Edge key generation**: `SHA-1(from_id:relation:to_id)` — deterministic and idempotent
- **Result aggregation**: `PipelineResult` with created/updated/skipped/error counts
- **Confidence overrides**: per-pattern confidence values overridable via `LAWGRAPH_CONFIDENCE_<PATTERN_NAME>` env vars

### Detection workflow

1. Scan source collection via AQL
2. Extract text (strip XML/HTML tags where needed)
3. Run regex detector → yield `CitationHit` objects
4. Resolve each hit to a target node (exact key lookup; optionally create stubs)
5. Emit semantic edge with `confidence`, `source`, `meta.reason`, and `meta.snippet`

All detectors emit `meta.reason` on edges (e.g. `"bwb_article"`, `"celex_instrument"`) for graph traversal clarity.

---

## 2. Detection strategies

### 2.1 BWB article detector

**Files:** `pipelines/semantic/bwb_detect.py`, `pipelines/semantic/bwb_articles.py`

**Source collection:** `instrument_articles` filtered by loaded BWB IDs

**Text field:** `props.text`

| Pattern | Confidence | Example |
|---------|-----------|---------|
| Cross-law code | 0.90 | `art. 126aa Sv` |
| Cross-law "van de/het" | 0.90 | `art. 3 van de Wegenverkeerswet` |
| Within-document single | 0.95 | `artikel 51` |
| Within-document range | 0.80 | `art. 100 tot 105` |

Range expansion: generates intermediate hits for all integers between bounds. Max range span: 200; max article number: 1999.

**Edge type:** `REFERS_TO_ARTICLE`

Optional: `--store-citations` stores detected hits as `props.citations` on source node.

### 2.2 Rechtspraak article detector

**File:** `pipelines/semantic/rechtspraak_articles.py`

**Source collection:** `judgments`, filterable by `--since-days`

**Text fields:** `props.raw_xml` (stripped) → `props.text` → `props.summary` (all joined before detection)

| Pattern | Confidence |
|---------|-----------|
| `art. \d+ Sr` / `artikel \d+ Sv` | 0.95 |
| Bare `artikel \d+` (no law code) | 0.35 |

Target resolution:
- Exact key lookup by `(bwb_id, article_number)` or `(celex, article_number)`
- Not found AND confidence ≥ 0.9 → create stub node in `instrument_articles`
- Not found AND confidence < 0.9 → skip silently

Note: the 0.35 confidence for bare `artikel \d+` is intentionally below the 0.85 stub creation threshold — bare numbers without law context are too ambiguous for stub creation.

**Edge type:** `CITES_ARTICLE`

### 2.3 TK article detector

**File:** `pipelines/semantic/tk_articles.py`

**Source collections:** `publications` + `procedures` (label: "TK")

**Text fields:** Multi-source aggregation up to 200 KB per document — `title`, `summary`, `body`, `text`, `raw` (recursive dict/list flattening). Debug log emitted when truncated at `_MAX_TEXT_LENGTH`.

| Pattern | Confidence | Kind |
|---------|-----------|------|
| Named instrument alias | 0.60 | instrument |
| Direct BWBR | 0.75 | instrument |
| Article with code | 0.95 | article |
| Article + EU directive | 0.88 | article |
| Direct CELEX | 0.90 | instrument |
| Whole directive/regulation | 0.65 | instrument |
| EU Besluit (C-type CELEX) | 0.88 | article |
| EU Kaderbesluit (D-type CELEX) | 0.88 | article |

Target resolution: exact lookup only — no stubs created. High-confidence (≥ 0.85) misses create stub nodes.

**Edge types:**
- `EXPLAINS_ARTICLE` — publication `soort` contains "toelichting" (MvT)
- `MENTIONS_ARTICLE` — all other article references
- `MENTIONS_INSTRUMENT` — whole-instrument references

### 2.4 EU article detector

**File:** `pipelines/semantic/eu_articles.py`

**Source collection:** `instrument_articles` (EU, `props.celex != null`)

**Text fields:** `props.text` → `props.display_name`

Mirrors TK detector patterns for EU-context text. Confidence range: 0.70–0.95.

**Edge types:** `MENTIONS_ARTICLE`, `MENTIONS_INSTRUMENT`

### 2.5 Instrument relations detector

**File:** `pipelines/semantic/instrument_relations.py`

Three sub-pipelines:

**AMENDS_INSTRUMENT:** TK publications/procedures where title contains "wijziging van". Confidence: 0.85.

**IMPLEMENTS_DIRECTIVE:**
- Pass 1: auto-detect CELEX pattern `3\d{4}[CLRDF]\d{4}` in BWB raw source text. Confidence: 0.75.
- Pass 2: explicit mappings from domain config `implements[]`. Confidence: 1.0.

**DISCUSSES:** TK procedures where title matches instrument alias. Confidence: 0.70.

### 2.6 Judgment citations detector

**File:** `pipelines/semantic/judgment_citations.py`

**Source collection:** `judgments`, filterable by `--since-days`

**Text fields:** `props.raw_xml` → `props.text` → `props.body`

**Pattern:** `\bECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:\d+\b`. Confidence: 0.95.

Target resolution:
1. Exact key lookup `make_node_key(ecli)`
2. Secondary query on `props.ecli` (legacy keys)
3. Not found → create stub node in `judgments`

**Edge type:** `CITES_JUDGMENT`

### 2.7 Amendment articles detector

**File:** `pipelines/semantic/amendment_articles.py`

Detects five Dutch amendment patterns in TK publications. Creates `WIJZIGT`, `INTRODUCEERT`, and `TREKT_IN` edges. Accepts `--since-days`.

### 2.8 MvT articles detector

**File:** `pipelines/semantic/mvt_articles.py`

Links MvT/NvT publications to instrument articles via `LICHT_TOE` edges. Accepts `--since`.

### 2.9 BWB grondslagen detector

**File:** `pipelines/semantic/bwb_grondslagen.py`

Creates `DELEGATED_BY` edges from BWB AMvB articles to their grondslag articles.

### 2.10 Judgment appeal detector

**File:** `pipelines/semantic/judgment_appeal.py`

Creates `APPEAL_OF` edges between judgments based on appellate chain metadata from Rechtspraak.nl.

### 2.11 Dossier law link detector

**File:** `pipelines/semantic/dossier_law_link.py`

Creates `RESULTED_IN` edges from `kamerstukdossiers` to `instruments` (enacted laws).

### 2.12 Version causes detector

**File:** `pipelines/semantic/version_causes.py`

Creates `CAUSED_VERSION` edges from publications to `instrument_article_versions`. Accepts `--window-days` (default: 365).

### 2.13 Staatsblad NvT detector

**File:** `pipelines/semantic/staatsblad_nvt.py`

Links Staatsblad NvT publications to BWB instruments.

### 2.14 Staatscourant regeling detector

**File:** `pipelines/semantic/staatscourant_regeling.py`

Creates `EXPLAINS_INSTRUMENT` edges from Staatscourant regelingen.

### 2.15 Eerste Kamer dossier link

**File:** `pipelines/semantic/eerstekamer_dossier_link.py`

Creates `DEEL_VAN_DOSSIER` edges from EK stukken to TK kamerstukdossiers.

### 2.16 ECHR citations detector

**File:** `pipelines/semantic/echr_citations.py`

Creates `CITES_ARTICLE` and `MENTIONS_INSTRUMENT` edges from ECHR judgments.

---

## 3. Edge types summary

| Source type | Detector | Relation | Target type | Stubs? |
|-------------|----------|----------|-------------|--------|
| instrument_articles | BWB | REFERS_TO_ARTICLE | instrument_articles | No |
| judgments | Rechtspraak | CITES_ARTICLE | instrument_articles | Yes (≥ 0.9) |
| publications | TK | EXPLAINS_ARTICLE | instrument_articles | Yes (≥ 0.85) |
| publications | TK | MENTIONS_ARTICLE | instrument_articles | Yes (≥ 0.85) |
| publications / procedures | TK | MENTIONS_INSTRUMENT | instruments | No |
| instrument_articles | EU | MENTIONS_ARTICLE | instrument_articles | No |
| publications | Instrument Rels | AMENDS_INSTRUMENT | instruments | No |
| instruments | Instrument Rels | IMPLEMENTS_DIRECTIVE | instruments | No |
| procedures | Instrument Rels | DISCUSSES | instruments | No |
| judgments | Judgment Citations | CITES_JUDGMENT | judgments | Yes |
| publications | Amendment | WIJZIGT / INTRODUCEERT / TREKT_IN | instrument_articles | No |
| publications (MvT) | MvT Articles | LICHT_TOE | instrument_articles | No |
| instruments (AMvB) | BWB Grondslagen | DELEGATED_BY | instrument_articles | No |
| judgments | Judgment Appeal | APPEAL_OF | judgments | No |
| kamerstukdossiers | Dossier Law Link | RESULTED_IN | instruments | No |
| publications | Version Causes | CAUSED_VERSION | instrument_article_versions | No |
| judgments (ECHR) | ECHR Citations | CITES_ARTICLE | instrument_articles | No |

All semantic edges store: `confidence`, `source`, `meta.reason`, `meta.snippet` (300-char window), and optional span offsets.

---

## 4. CLI dispatch

All semantic pipelines are registered in the source registry (`sources/registry.py`) and invoked via the unified CLI:

```bash
lawgraph semantic <source> [options]
lawgraph semantic all
```

Skip individual detectors in `semantic all`:

```bash
LAWGRAPH_SEMANTIC_SKIP_TK=1 lawgraph semantic all
LAWGRAPH_SEMANTIC_SKIP_RECHTSPRAAK=1 lawgraph semantic all
LAWGRAPH_SEMANTIC_SKIP_BWB=1 lawgraph semantic all
LAWGRAPH_SEMANTIC_SKIP_JUDGMENT_CITATIONS=1 lawgraph semantic all
LAWGRAPH_SEMANTIC_SKIP_INSTRUMENT_RELATIONS=1 lawgraph semantic all
LAWGRAPH_SEMANTIC_SKIP_AMENDMENT_ARTICLES=1 lawgraph semantic all
```

---

## 5. Known gaps

| Gap | Status |
|-----|--------|
| No treaty article patterns (EVRM `art. 8 EVRM`) | Open |
| No detector for parliamentary question → article links | Open |
| `CitationHit` and `ArticleCitationHit` are two separate dataclasses | Open (minor) |
| No per-detector `--audit` flag for confidence distribution stats | Open |
| BWB range detection: `"tot"` always assumed contiguous — rare false positives | Open |
