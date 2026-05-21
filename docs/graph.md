# Graph model

## Collections

### Document collections

| Collection | Contents |
|-----------|----------|
| `instruments` | Statutes (BWB), EU directives/regulations (CELEX) |
| `instrument_articles` | Individual articles within a statute |
| `judgments` | Court judgments (Rechtspraak.nl) |
| `procedures` | Parliamentary procedures (Tweede Kamer) |
| `publications` | Parliamentary publications (Tweede Kamer) |
| `topics` | Subject tags |
| `raw_sources` | Verbatim API responses, keyed by source + external ID |

### Edge collections

| Collection | Contains |
|-----------|----------|
| `edges_strict` | Structural relationships derived deterministically during normalization |
| `edges_semantic` | Inferred relationships detected by semantic pipelines |

## Edge types

### Structural (`edges_strict`)

| Relation | From → To | Meaning |
|----------|-----------|---------|
| `PART_OF_INSTRUMENT` | `instrument_articles` → `instruments` | Article belongs to statute |
| `PART_OF_PROCEDURE` | `publications` → `procedures` | Publication belongs to parliamentary procedure |
| `RELATED_TOPIC` | any node → `topics` | Node is tagged with a domain topic |

### Semantic (`edges_semantic`)

| Relation | From → To | Meaning | Pipeline |
|----------|-----------|---------|---------|
| `MENTIONS_ARTICLE` | judgments / publications / procedures → `instrument_articles` | Document cites a specific legal article | `semantic-*-articles` |
| `MENTIONS_INSTRUMENT` | judgments / publications / procedures → `instruments` | Document cites an entire statute or EU instrument | `semantic-tk-articles`, `semantic-eu-articles` |
| `REFERS_TO_ARTICLE` | `instrument_articles` → `instrument_articles` | BWB article cross-references another | `semantic-bwb-articles` |
| `CITES_JUDGMENT` | `judgments` → `judgments` | Judgment references another judgment by ECLI | `semantic-judgment-citations` |
| `AMENDS_INSTRUMENT` | `publications` / `procedures` → `instruments` | TK document proposes an amendment to a statute (detected from title) | `semantic-instrument-relations` |
| `IMPLEMENTS_DIRECTIVE` | `instruments` → `instruments` | NL statute references an EU directive in its source text | `semantic-instrument-relations` |

Semantic edges carry:
- `confidence` (0–1): detection reliability
- `source`: which pipeline wrote the edge
- `meta`: raw match text, snippet, or other detection context

## Key generation

All `_key` values are computed deterministically by `make_node_key()` so that re-runs upsert rather than duplicate:

```
instrument_articles  →  <bwb_id>__<article_number>   e.g. BWBR0001854__47
instruments (BWB)    →  <bwb_id>                      e.g. BWBR0001854
instruments (EU)     →  <celex>                       e.g. 32016L0680
judgments            →  <ecli>                        e.g. ECLI_NL_HR_2023_1234
```

Spaces and special characters in inputs are replaced with `_` and uppercased.
