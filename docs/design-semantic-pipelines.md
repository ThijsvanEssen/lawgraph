# LawGraph Semantic & Citation Detection Pipelines — Design Document

## 1. Architecture Overview

All semantic pipelines inherit from `SemanticPipelineBase` (`pipelines/semantic/base.py`):

- **Domain config loading**: `_load_domain_config()` — loads BWB IDs, code aliases, instrument aliases from `config/<profile>.yml`
- **Code alias resolution**: e.g. `"Sr"` → `"BWBR0001854"` (Wetboek van Strafrecht)
- **Instrument alias resolution**: e.g. `"Wetboek van Strafrecht"` → `(bwb_id, None)`
- **Edge key generation**: `SHA-1(from_id:relation:to_id)` — deterministic and idempotent (`base.py:18-20`)
- **Result aggregation**: `PipelineResult` with created/updated/skipped/error counts

### Citation detection workflow

1. Load domain profile config
2. Scan source collection via AQL
3. Extract text (strip XML/HTML tags for Rechtspraak raw_xml)
4. Run regex detector → yield `CitationHit` or `ArticleCitationHit` objects
5. Resolve each hit to a target node (exact key lookup; optionally create stubs)
6. Emit semantic edge with confidence + metadata (raw_match, snippet, span offsets)

---

## 2. Detection Strategies

### 2.1 BWB Article Detector

**Files:** `pipelines/semantic/bwb_detect.py`, `pipelines/semantic/bwb_articles.py`

**Source collection:** `instrument_articles` filtered by `bwb_id IN config.bwb.ids`

**Text field:** `props.text`

**Patterns:**

| Pattern | Regex (simplified) | Confidence | Example |
|---------|-------------------|-----------|---------|
| Cross-law code | `art\. \d+ [A-Z][A-Za-z]{1,4}` | 0.90 | `art. 126aa Sv` |
| Cross-law "van de/het" | `art\. \d+ van de/het <law name>` | 0.90 | `art. 3 van de Wegenverkeerswet` |
| Within-document single | `art\. \d+` (same law) | 0.95 | `artikel 51` |
| Within-document range | `art\. \d+ tot \d+` | 0.80 | `art. 100 tot 105` |

**Range expansion:** Generates intermediate hits for all integers between bounds. Max range span: 200; max article number: 1999 (prevents false positives on fines/years).

**Target resolution:** `make_node_key(bwb_id, article_number)` — exact lookup in `instrument_articles`

**Edge type:** `REFERS_TO_ARTICLE`

**Optional:** `--store-citations` flag stores detected hits as `props.citations` array on source node.

---

### 2.2 Rechtspraak Article Detector

**File:** `pipelines/semantic/rechtspraak_articles.py`

**Source collection:** `judgments`, optionally filtered by `raw_sources.fetched_at >= @since`

**Text fields:** `props.raw_xml` (preferred, XML-stripped) → `props.text`

**Patterns:**

| Pattern | Confidence | Example |
|---------|-----------|---------|
| `art. \d+ Sr` / `artikel \d+ Sv` | 0.95 | `art. 10 Sv` |
| Bare `artikel \d+` (no law code) | 0.35 | `artikel 10` |

**Target resolution:**
- Dutch (BWBR): exact key lookup
- EU: exact key lookup by `(celex, article_number)`
- Not found AND confidence ≥ 0.9 → create **stub node** in `instrument_articles`
- Not found AND confidence < 0.9 → **silently skip**

**Edge type:** `CITES_ARTICLE`

---

### 2.3 TK Article Detector

**File:** `pipelines/semantic/tk_articles.py`

**Source collections:** `publications` + `procedures` (label: "TK")

**Text fields:** Multi-source aggregation up to 200KB per document — `title`, `summary`, `body`, `text`, `raw` (recursive dict/list flattening)

**Patterns:**

| Pattern | Confidence | Kind | Example |
|---------|-----------|------|---------|
| Named instrument alias | 0.60 | instrument | `Wetboek van Strafrecht` |
| Direct BWBR | 0.75 | instrument | `BWBR0001940` |
| Article with code | 0.95 | article | `art. 10 Sv` |
| Article + EU directive | 0.88 | article | `artikel 3 van Richtlijn 2010/64` |
| Direct CELEX | 0.90 | instrument | `CELEX:32010L0064` |
| Whole directive/regulation | 0.65 | instrument | `Richtlijn 2010/64` |

**Target resolution:** Exact lookup only — **no stub creation** (silent miss if node not found)

**Edge types:**
- `EXPLAINS_ARTICLE` — if publication soort contains "toelichting" (MvT)
- `MENTIONS_ARTICLE` — all other articles
- `MENTIONS_INSTRUMENT` — whole-instrument references

---

### 2.4 EU Article Detector

**File:** `pipelines/semantic/eu_articles.py`

**Source collection:** `instrument_articles` (EU, `props.celex != null`)

**Text field:** `props.text` → `props.display_name`

**Patterns:** Mirrors TK detector for EU-context text (directive/regulation patterns, BWB code aliases, CELEX, BWBR). Confidence range: 0.70–0.95.

**Target resolution:** Exact lookup only — no stub creation.

**Edge types:** `MENTIONS_ARTICLE`, `MENTIONS_INSTRUMENT`

---

### 2.5 Instrument Relations Detector

**File:** `pipelines/semantic/instrument_relations.py`

Three sub-pipelines:

**A. AMENDS_INSTRUMENT**
- Source: TK publications/procedures
- Signal: title contains "wijziging van"
- Target: instrument matched via alias
- Confidence: 0.85
- Edge: `AMENDS_INSTRUMENT`

**B. IMPLEMENTS_DIRECTIVE** (two passes)
- Pass 1: Auto-detect CELEX in BWB raw_sources text (`3\d{4}[LRD]\d{4}`)
  - Confidence: 0.75
- Pass 2: Explicit mappings from `config.implements[]`
  - Confidence: 1.0 (manually curated)
- Edge: `IMPLEMENTS_DIRECTIVE`

**C. DISCUSSES**
- Source: TK procedures
- Signal: procedure title matches instrument alias
- Confidence: 0.70
- Edge: `DISCUSSES`

---

### 2.6 Judgment Citations Detector

**File:** `pipelines/semantic/judgment_citations.py`

**Source collection:** `judgments`

**Text fields:** `props.raw_xml` → `props.text` → `props.body`

**Pattern:** ECLI format `\bECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:\d+\b`

- Confidence: 0.95 (structured format is highly reliable)
- Deduplicates via `seen` set
- Skips self-references

**Target resolution:**
1. Exact key lookup `make_node_key(ecli)`
2. Secondary query on `props.ecli` (legacy non-deterministic keys)
3. Not found → create **stub node** in `judgments`

**Edge type:** `CITES_JUDGMENT`

---

## 3. Edge Types Summary

| Source Type | Detector | Relation | Target Type | Confidence | Stubs? |
|-------------|----------|----------|-------------|-----------|--------|
| instrument_article | BWB | REFERS_TO_ARTICLE | instrument_article | 0.80–0.95 | No |
| judgment | Rechtspraak | CITES_ARTICLE | instrument_article | 0.35–0.95 | Yes (≥0.9) |
| publication | TK | EXPLAINS_ARTICLE | instrument_article | 0.60–0.95 | No |
| publication | TK | MENTIONS_ARTICLE | instrument_article | 0.60–0.95 | No |
| publication / procedure | TK | MENTIONS_INSTRUMENT | instrument | 0.60–0.95 | No |
| instrument_article | EU | MENTIONS_ARTICLE | instrument_article | 0.70–0.95 | No |
| instrument_article | EU | MENTIONS_INSTRUMENT | instrument | 0.70–0.95 | No |
| publication | Instrument Rels | AMENDS_INSTRUMENT | instrument | 0.85 | No |
| procedure | Instrument Rels | DISCUSSES | instrument | 0.70 | No |
| instrument | Instrument Rels | IMPLEMENTS_DIRECTIVE | instrument | 0.75–1.0 | No |
| judgment | Judgment Citations | CITES_JUDGMENT | judgment | 0.95 | Yes |

All edges store: `raw_match`, `snippet` (300-char window), optional span offsets.

---

## 4. CLI Interface

| Command | File | Incremental | Notes |
|---------|------|-------------|-------|
| `lawgraph-semantic-bwb-articles` | `cli/semantic_bwb_articles.py` | No | Full scan; `--store-citations` |
| `lawgraph-semantic-rechtspraak-articles` | `cli/semantic_rechtspraak_articles.py` | Yes (`--since-days`) | |
| `lawgraph-semantic-tk-articles` | `cli/semantic_tk_articles.py` | No | `--since-days` accepted but unused |
| `lawgraph-semantic-eu-articles` | `cli/semantic_eu_articles.py` | No | Same |
| `lawgraph-semantic-instrument-relations` | `cli/semantic_instrument_relations.py` | No | Runs all 3 sub-pipelines |
| `lawgraph-semantic-judgment-citations` | `cli/semantic_judgment_citations.py` | No | `--since-days` accepted but unused |
| `lawgraph-semantic-all` | `cli/semantic_all.py` | Partial | Orchestrates all 6; skippable via env vars |

**`semantic-all` env var skips:**
`LAWGRAPH_SEMANTIC_SKIP_TK`, `LAWGRAPH_SEMANTIC_SKIP_RECHTSPRAAK`, `LAWGRAPH_SEMANTIC_SKIP_EU`, `LAWGRAPH_SEMANTIC_SKIP_BWB`, `LAWGRAPH_SEMANTIC_SKIP_JUDGMENT_CITATIONS`, `LAWGRAPH_SEMANTIC_SKIP_INSTRUMENT_RELATIONS`

---

## 5. Gaps & Missing Detectors

| Gap | Status | Impact |
|-----|--------|--------|
| ~~TK / EU detectors never create stub nodes~~ | ✅ Fixed — stubs created at confidence ≥ 0.85 | — |
| ~~No legislative amendment text scanner~~ | ✅ Fixed — `amendment_articles.py` detects `WIJZIGT`/`INTRODUCEERT`/`TREKT_IN` edges | — |
| No treaty article patterns | 🔴 Open | EVRM "artikel 8 van het Europees Verdrag..." not matched |
| No detector for parliamentary question→article links | 🔴 Open | Schriftelijke vragen referencing laws not linked |
| ~~Rechtspraak index (`rs-index`) never parsed~~ | ✅ Fixed — ECLI stub nodes created from index records | — |
| ~~`props.summary` on judgments never mined for ECLIs~~ | ✅ Fixed — `_extract_judgment_text` now joins `raw_xml`, `text`, and `summary` | — |
| ~~EU C-category directives not matched~~ | ✅ Fixed — `_ARTICLE_BESLUIT_PATTERN` (→ `C`) and `_ARTICLE_KADERBESLUIT_PATTERN` (→ `D`) added to `tk_articles.py` | — |
| ~~All detectors lack true incremental mode~~ | ✅ Fixed — TK, EU, BWB filter by `raw_sources.fetched_at` | — |

---

## 6. Bugs & Issues

| # | Severity | File | Status | Description |
|---|----------|------|--------|-------------|
| 1 | HIGH | `tk_articles.py`, `eu_articles.py` | ✅ Fixed | Stub nodes now created for high-confidence (≥ 0.85) misses in both TK and EU detectors |
| 2 | MEDIUM | `tk_articles.py` | ✅ Fixed | `_ARTICLE_BESLUIT_PATTERN` (→ CELEX `C`) and `_ARTICLE_KADERBESLUIT_PATTERN` (→ CELEX `D`) added; `format_celex` in `citation_detect.py` updated to handle all four kinds |
| 3 | MEDIUM | `bwb_detect.py` | 🔴 Open | Range detection assumes "tot" always means contiguous range — edge case false positives |
| 4 | LOW | `tk_articles.py` | ✅ Fixed | Debug log emitted when document text is truncated at `_MAX_TEXT_LENGTH` (200 000 chars) |
| 5 | LOW | `instrument_relations.py` | ✅ Fixed | CELEX pattern updated to `3\d{4}[CLRDF]\d{4}` — C, F, and D types now matched |
| 6 | LOW | `rechtspraak_articles.py` | ✅ Fixed | Inline comment added: confidence 0.35 is intentionally below the 0.85 stub threshold — bare numbers without law context are too ambiguous |
| 7 | LOW | All detectors | ✅ Fixed | All four detectors emit `logger.debug(...)` when a target node is not found; `meta.reason` field added to every edge (e.g. `"bwb_article"`, `"celex_instrument"`) |

---

## 7. Improvement Recommendations

### P1 — Critical
1. ✅ Fixed — Stub nodes created in TK and EU detectors for confidence ≥ 0.85 misses
2. ✅ Fixed — EU C-category (`Besluit` → `C`) and D-category (`Kaderbesluit` → `D`) CELEX patterns added to `tk_articles.py`
3. ✅ Fixed — All detectors emit `logger.debug(...)` when a target node is not found

### P2 — High
4. ✅ Fixed — Incremental mode added to TK, EU, and BWB detectors (filter by `raw_sources.fetched_at`)
5. ✅ Fixed — `amendment_articles.py` pipeline detects five Dutch amendment patterns; creates `WIJZIGT`, `INTRODUCEERT`, and `TREKT_IN` edges; registered as `lawgraph-semantic-amendment-articles` CLI and included in `semantic-all`
6. ✅ Fixed — `get_confidence_override(pattern_name, default)` added to `settings.py`; reads `LAWGRAPH_CONFIDENCE_<PATTERN_NAME>` env vars; detectors can adopt incrementally

### P3 — Medium
7. 🔴 Open — **Unify `CitationHit` and `ArticleCitationHit`** into single dataclass
8. ✅ Fixed — `tests/semantic/test_regex_patterns.py` added with 51 tests covering all amendment patterns and `format_celex` for all four CELEX kinds
9. ✅ Fixed — `meta.reason` field added to all edges in TK, EU, and Rechtspraak detectors (values: `"bwb_article"`, `"celex_article"`, `"bwb_instrument"`, `"celex_instrument"`)
10. 🔴 Open — **Add citation audit report** (`--audit` flag) logging detection stats per confidence bucket
